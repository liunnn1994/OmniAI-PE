import copy
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from scripts import pe, prepare_compat, prepare_upstream


class BundleTest(unittest.TestCase):
    def test_range_download_resumes_at_first_missing_byte(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "kernel.wim"
            first = BytesIO(b"ab")
            first.status, first.headers = 206, {"Content-Range": "bytes 10-13/100"}
            second = BytesIO(b"cd")
            second.status, second.headers = 206, {"Content-Range": "bytes 12-13/100"}
            with patch.object(prepare_upstream, "build_opener") as opener:
                request = opener.return_value.open
                request.side_effect = [first, second]
                prepare_upstream.download_range("https://example.test/iso", output, 10, 4)
            self.assertEqual(output.read_bytes(), b"abcd")
            self.assertEqual([call.args[0].get_header("Range") for call in request.call_args_list],
                             ["bytes=10-13", "bytes=12-13"])

    def test_publish_rejects_unverified_upstream_payload(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.cab"
            source.write_bytes(b"unverified")
            destination = root / "inputs" / "update.cab"
            record = {"source": "update.cab", "sha256": "0" * 64}
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                prepare_upstream.publish(source, destination,
                                         lambda path: prepare_upstream.verify_payload(path, record))
            self.assertFalse(destination.exists())

    def test_bundle_preserves_referenced_inputs_and_empty_directories(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = root / "inputs"
            files = {
                "original.iso", "wims/base.wim", "packages/tool/配置.txt",
                "updates/feature.cab", "drivers/driver.inf", "files/runtime.dll",
                "registry/SOFTWARE",
            }
            for name in files | {"updates/unused.msu"}:
                path = inputs / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(name.encode())
            (inputs / "packages/tool/empty").mkdir()
            project = {"wims": {"boot": {"replacement": {"source": "wims/base.wim"}}}}
            lock = {"iso": {"file": "original.iso"}}
            scopes = {"boot/1": {
                "packages": {"tools": {"source": "packages/tool"}},
                "windows_packages": [{"source": "updates/feature.cab"}],
                "windows_drivers": {"source": "drivers"},
                "windows_files": {"source": "files"},
                "registry": {"SOFTWARE": {"source": "registry/SOFTWARE"}},
            }}
            bundle = root / "bundles/inputs.zip"
            pe.bundle_inputs(inputs, project, lock, scopes, bundle)
            with self.assertRaises(FileExistsError):
                pe.bundle_inputs(inputs, project, lock, scopes, bundle)
            with ZipFile(bundle) as archive:
                self.assertEqual({name for name in archive.namelist() if not name.endswith("/")}, files)
            with (patch.dict("os.environ", {"OMNIAI_INPUTS_ARCHIVE": str(bundle)}, clear=True),
                  patch.object(pe, "load_plan") as validate):
                pe.fetch_inputs(root / "extracted", "project.json", None)
                validate.assert_called_once()
            self.assertTrue((root / "extracted/packages/tool/empty").is_dir())
            for folder in ("packages/tool", "files", "drivers"):
                self.assertEqual(pe.package_hash(inputs / folder), pe.package_hash(root / "extracted" / folder))

    def test_fetch_requires_an_input_source(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(ValueError, "缺少完整的私有构建输入 ZIP"):
                pe.fetch_inputs(Path("未创建的构建输入目录"), "project.json", None)

    def test_fetch_rejects_archive_traversal_before_publishing_inputs(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / "inputs.zip"
            with ZipFile(bundle, "w") as archive:
                archive.writestr("../escape", "data")
            inputs = root / "inputs"
            with self.assertRaisesRegex(ValueError, "Invalid relative path"):
                pe.fetch_inputs(inputs, "project.json", bundle)
            self.assertEqual(list(root.iterdir()), [bundle])


class PathsTest(unittest.TestCase):
    def test_setup_paths_relocate_only_installed_folders_on_the_pe_drive(self):
        cases = {
            r'@"X:\$WINDOWS.~BT\Windows\System32\foo.dll",-6': r'@"X:\Windows\System32\foo.dll",-6',
            r"x:\$windows.~bt\Program Files (x86)": r"x:\Program Files (x86)",
            r"X:\$windows.~bt\ProgramData\Microsoft": r"X:\ProgramData\Microsoft",
            r"X:\$windows.~bt\Users\Default": r"X:\Users\Default",
            "X:\\$windows.~bt\\": "X:\\",
            r"X:\$windows.~bt\pagefile.sys": r"X:\$windows.~bt\pagefile.sys",
            r"C:\$windows.~bt\Windows": r"C:\$windows.~bt\Windows",
            r"X:\$windows.~bt\Windows.old": r"X:\$windows.~bt\Windows.old",
        }
        for before, after in cases.items():
            with self.subTest(before=before):
                self.assertEqual(pe.relocate_setup_path(before), after)

    def test_feature_driver_paths_exclude_store_sidecars_and_event_logs(self):
        root = prepare_compat.DRIVER_ROOT
        self.assertEqual(prepare_compat.driver_id(root + "example.inf_amd64_abcd/example.inf"), "example.inf")
        self.assertIsNone(prepare_compat.driver_id(root + "example.inf_amd64_abcd.ini"))
        self.assertTrue(prepare_compat.feature_path("windows/system32/drivers/nwifi.sys"))
        self.assertFalse(prepare_compat.feature_path("windows/system32/winevt/logs/system.evtx"))

    def test_legacy_windows_multimedia_files_are_selected(self):
        for name in ("wdmaud.drv", "msacm32.drv", "l3codeca.acm"):
            with self.subTest(name=name):
                self.assertTrue(prepare_compat.feature_path(f"windows/system32/{name}"))
        self.assertFalse(prepare_compat.feature_path("windows/system32/dwminit.dll"))
        self.assertTrue(prepare_compat.feature_path("windows/system32/dcomp.dll"))

    def test_side_by_side_assemblies_group_versions_without_importing_servicing_files(self):
        directory = "x86_microsoft.windows.common-controls_6595b64144ccf1df_6.0.26100"
        files = [f"windows/winsxs/{directory}.{revision}_none_a1/comctl32.dll" for revision in (1, 9974)]
        files += ["windows/winsxs/amd64_microsoft-windows-servicingstack_a1_10.0.26100.9971_none_a1/wcp.dll"]
        groups = prepare_compat.runtime_versions(files)
        self.assertEqual(len(groups), 1)
        versions = next(iter(groups.values()))
        self.assertEqual(versions[max(versions)], {files[1]})

    def test_windows_path_boundaries(self):
        self.assertEqual(pe.relative("HotProgMods/test [PreInstall].HPM"),
                         "HotProgMods/test [PreInstall].HPM")
        for name in ("", "/", "../x", "./x", "a//b", "a\\b", "A:", "a:stream", "nul.ini", "a."):
            with self.subTest(name=name), self.assertRaises(ValueError):
                pe.relative(name)

    def test_manifest_rejects_overlapping_and_reserved_targets(self):
        baseline = pe.read_json("project.json")
        lock = pe.read_json("upstream.lock.json")
        recipe = pe.read_json(baseline["wims"]["boot"]["replacement"]["recipe"])
        cases = [
            ("media_remove", ["HotProgMods", "hotprogmods/a.hpm"], "Overlapping"),
            ("media_remove", ["HotPE"], "Reserved"),
            ("wim_remove", {"boot": ["2/a"]}, "Unknown WIM index"),
            ("wim_remove", {"boot": ["1/Windows/System32/ntoskrnl.exe"]}, "Reserved"),
        ]
        for field, value, message in cases:
            with self.subTest(value=value):
                project = copy.deepcopy(baseline)
                project[field] = value
                with patch.object(pe, "read_json", side_effect=[project, lock, recipe]):
                    with self.assertRaisesRegex(ValueError, message):
                        pe.load_plan(Path("inputs"), False)


class OverlayTest(unittest.TestCase):
    def test_boot_descriptions_update_both_stores_without_shipping_registry_logs(self):
        with TemporaryDirectory() as directory:
            media = Path(directory) / "media"
            stores = {kind: media / name for kind, name in pe.BCD_STORES.items()}
            for store in stores.values():
                store.parent.mkdir(parents=True)
                store.write_bytes(b"original")

            project = pe.read_json("project.json")
            descriptions = project["boot_descriptions"]
            default = project["uefi_default_entry"]
            expected = [(kind, entry, name) for kind, entries in descriptions.items()
                        for entry, name in entries.items()]
            applied = []
            defaults_applied = []
            display_applied = []

            def edit(command, store_option, path, set_option, entry, element=None, name=None):
                if set_option == "/default":
                    self.assertEqual(path.name, stores["uefi"].name)
                    self.assertEqual(applied, expected)
                    defaults_applied.append(entry)
                    return
                if element in {"highestmode", "loadoptions"}:
                    self.assertEqual(path.name, stores["uefi"].name)
                    self.assertEqual(entry, default)
                    display_applied.append((element, name))
                    return
                self.assertEqual((command, store_option, set_option, element),
                                 ("bcdedit.exe", "/store", "/set", "description"))
                kind = next(kind for kind, store in stores.items() if store.name == path.name)
                self.assertEqual(path.parent.parent, media.parent)
                path.with_suffix(".LOG1").touch()
                with path.open("ab") as handle:
                    handle.write(name.encode())
                applied.append((kind, entry, name))

            with patch.object(pe, "run", side_effect=edit):
                pe.apply_boot_descriptions(media, descriptions, default, prefer_1080p=project["uefi_prefer_1080p"])
            self.assertEqual(applied, expected)
            self.assertEqual(display_applied, [("highestmode", "off"), ("loadoptions", "OMNIAI_DISPLAY_1080P")])
            self.assertEqual(defaults_applied, [default])
            self.assertEqual({path for path in media.rglob("*") if path.is_file()}, set(stores.values()))
            for kind, store in stores.items():
                self.assertEqual(store.read_bytes(), b"original" + b"".join(
                    name.encode() for name in descriptions[kind].values()))

    def test_windows_feature_files_preserve_base_files_and_reject_kernel(self):
        with TemporaryDirectory() as directory:
            work = Path(directory)
            image = work / "image"
            payload = work / "inputs" / "compat"
            system = "Windows/System32"
            for root in (image, payload):
                (root / system).mkdir(parents=True)
            (image / system / "existing.dll").write_bytes(b"updated")
            (payload / system / "existing.dll").write_bytes(b"donor")
            (payload / system / "service.dll").write_bytes(b"feature")
            (payload / system / "policymanager.dll").write_bytes(b"policy")
            additions = ("Windows/L2Schemas/WLAN_profile_v1.xsd",
                         "Windows/OCR/zh-CN/MsOcrRes.orp",
                         "Program Files (x86)/Common Files/System/ado/msado15.dll",
                         "Windows/apppatch/sysmain.sdb", "Windows/System32/wbem/WMIC.exe")
            for name in additions:
                self.assertTrue(prepare_compat.feature_path(name.casefold()))
                path = payload / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"dependency")
            marker = {"source": "compat", "sha256": pe.package_hash(payload)}
            plan = {"windows_files": marker}
            pe.add_windows_files(image, plan, work / "inputs")
            self.assertEqual((image / system / "existing.dll").read_bytes(), b"updated")
            self.assertEqual((image / system / "service.dll").read_bytes(), b"feature")
            for name in additions:
                self.assertEqual((image / name).read_bytes(), b"dependency")
            self.assertFalse((image / system / "policymanager.dll").exists())
            self.assertEqual((image / "Program Files/OmniAI Startup/policymanager.dll").read_bytes(), b"policy")
            (payload / pe.KERNEL).touch()
            marker["sha256"] = pe.package_hash(payload)
            with self.assertRaisesRegex(ValueError, "Reserved Windows feature file"):
                pe.add_windows_files(image, plan, work / "inputs")

    def test_archive_package_checks_extracted_files(self):
        with TemporaryDirectory() as directory:
            work = Path(directory)
            archive = work / "tool.7z"
            archive.write_bytes(b"archive input")
            expected = work / "expected"
            expected.mkdir()
            (expected / "Tool.exe").write_bytes(b"expected content")
            media = work / "media"
            package = {"source": archive.name, "sha256": pe.sha256(archive),
                       "unpacked_sha256": pe.package_hash(expected)}
            plan = {"remove": [], "overlay": {}, "packages": {"Apps/Tool": package}}

            def extract(_exe, _command, _yes, output, source):
                self.assertEqual(source, archive)
                target = Path(output.removeprefix("-o"))
                target.mkdir()
                (target / "Tool.exe").write_bytes(b"wrong content")

            with patch.object(pe, "tool", return_value="7z.exe"), patch.object(pe, "run", side_effect=extract):
                with self.assertRaisesRegex(ValueError, "Staged payload hash mismatch"):
                    pe.apply_plan(media, plan, work)

    def test_replace_directory_then_apply_overlay_and_remove_file(self):
        with TemporaryDirectory() as directory:
            work = Path(directory)
            inputs = work / "inputs"
            media = work / "media"
            payload = inputs / "payload"
            (payload / "empty").mkdir(parents=True)
            (payload / "base.ini").write_bytes(b"package data")
            (media / "tools").mkdir(parents=True)
            (media / "tools/stale.txt").touch()
            (media / "remove.hpm").touch()
            overlay = work / "edit.ini"
            overlay.write_bytes(b"\xef\xbb\xbfproject edit\r\n")
            digest = pe.package_hash(payload)
            plan = {
                "packages": {"tools": {"source": "payload", "sha256": digest}},
                "overlay": {"tools/base.ini": overlay},
                "remove": ["remove.hpm"],
            }
            pe.apply_plan(media, plan, inputs)
            self.assertEqual((media / "tools/base.ini").read_bytes(), overlay.read_bytes())
            self.assertTrue((media / "tools/empty").is_dir())
            self.assertFalse((media / "tools/stale.txt").exists())
            self.assertFalse((media / "remove.hpm").exists())
            (payload / "empty").rmdir()
            self.assertNotEqual(pe.package_hash(payload), digest)


class ImageTest(unittest.TestCase):
    def test_boot_media_copies_bios_and_uefi_resources_without_replacing_bcd(self):
        with TemporaryDirectory() as directory:
            stage = Path(directory)
            media = stage / "media"
            for name in pe.BCD_STORES.values():
                bcd = media / name
                bcd.parent.mkdir(parents=True)
                bcd.write_bytes(b"existing BCD")

            def extract(*args):
                output = Path(args[3][2:])
                for filename in args[5:]:
                    path = output / filename
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(filename, encoding="ascii")

            with patch.object(pe, "tool", return_value="7z.exe"), patch.object(pe, "run", side_effect=extract):
                pe.apply_windows_boot_media(stage, stage / "boot.wim")

            self.assertEqual((media / "bootmgr").read_text(), "Windows/Boot/PCAT/bootmgr")
            self.assertEqual((media / "bootmgr.efi").read_text(), "Windows/Boot/EFI/bootmgr.efi")
            for name in pe.BCD_STORES.values():
                self.assertEqual((media / name).read_bytes(), b"existing BCD")

    def test_build_iso_checks_replacement_uefi_image_and_upstream_bios(self):
        with TemporaryDirectory() as directory:
            stage = Path(directory)
            project = pe.read_json("project.json")
            lock = pe.read_json("upstream.lock.json")
            original_uefi = dict(lock["boot"]["uefi"])
            pending = stage / "building.iso"

            with (patch.object(pe, "tool", return_value="oscdimg.exe"),
                  patch.object(pe, "run", side_effect=lambda *args: pending.write_bytes(b"iso")),
                  patch.object(pe, "boot_images") as verify):
                iso = pe.build_iso(project, lock, stage, stage)

            verify.assert_called_once_with(pending, {
                "bios": lock["boot"]["bios"], "uefi": project["uefi_boot"],
            })
            self.assertEqual(lock["boot"]["uefi"], original_uefi)
            self.assertEqual(iso.read_bytes(), b"iso")

    def test_base_updates_commit_in_order_before_publishing(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = root / "inputs"
            (inputs / "wims").mkdir(parents=True)
            source = inputs / "wims/base.wim"
            header = bytearray(124)
            header[:8] = b"MSWIM\0\0\0"
            header[44] = header[120] = 1
            source.write_bytes(header)
            packages = []
            for name in ("checkpoint.msu", "rollup.msu"):
                path = inputs / name
                path.write_bytes(name.encode())
                packages.append({"source": name, "sha256": pe.sha256(path)})
            recipe = {"kernel_version": "10.0.26100.9974",
                      "base": {"source": "wims/base.wim", "sha256": pe.sha256(source)},
                      "updates": packages}
            output = inputs / "wims/Microsoft-WinPE-26100.9974-amd64.wim"
            with (patch.object(pe, "ROOT", root),
                  patch.object(pe, "service_wim") as service,
                  patch.object(pe, "tool", return_value="mock"),
                  patch.object(pe, "run"),
                  patch.object(pe.subprocess, "run") as version):
                version.return_value.stdout = "10.0.26100.9974\n"
                pe.prepare_base(inputs, recipe)

            self.assertEqual([args[3]["windows_packages"] for args, _ in service.call_args_list],
                             [[packages[0]], [packages[1]]])
            self.assertEqual([args[0].name for args, _ in service.call_args_list], ["1", "2"])
            self.assertEqual(output.read_bytes(), source.read_bytes())

    def test_base_exports_selected_setup_index_as_bootable_single_image(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = root / "inputs"
            (inputs / "wims").mkdir(parents=True)
            source = inputs / "wims/setup.wim"
            header = bytearray(124)
            header[:8] = b"MSWIM\0\0\0"
            header[44] = header[120] = 2
            source.write_bytes(header)
            package = inputs / "rollup.msu"
            package.write_bytes(b"rollup")
            output_name = "setup-pe-26100.9974.wim"
            recipe = {
                "kernel_version": "10.0.26100.9974",
                "base": {"source": "wims/setup.wim", "sha256": pe.sha256(source),
                         "image_count": 2, "boot_index": 2, "index": 1},
                "output": output_name,
                "updates": [{"source": package.name, "sha256": pe.sha256(package)}],
            }
            exported = root / ".work/base" / Path(output_name).stem / output_name
            single_image = bytearray(header)
            single_image[44] = single_image[120] = 1

            def run(*args):
                if "/Export-Image" in args:
                    self.assertIn(f"/SourceImageFile:{source}", args)
                    self.assertIn("/SourceIndex:1", args)
                    self.assertIn(f"/DestinationImageFile:{exported}", args)
                    self.assertIn("/Bootable", args)
                    exported.write_bytes(single_image)

            with (patch.object(pe, "ROOT", root),
                  patch.object(pe, "service_wim") as service,
                  patch.object(pe, "tool", return_value="mock"),
                  patch.object(pe, "run", side_effect=run),
                  patch.object(pe.subprocess, "run") as version):
                version.return_value.stdout = "10.0.26100.9974\n"
                pe.prepare_base(inputs, recipe)

            self.assertEqual(service.call_args.args[1:3], (exported, 1))
            self.assertEqual((inputs / "wims" / output_name).read_bytes(), single_image)
            self.assertEqual(source.read_bytes(), header)

    def test_replacement_configs_are_selected_without_legacy_overlays(self):
        project = pe.read_json("project.json")
        lock = pe.read_json("upstream.lock.json")
        project["wims"]["boot"].pop("replacement")
        project.pop("uefi_boot")
        project.pop("media_source", None)
        project["wim_remove"] = {}
        project["packages"] = []
        with patch.object(pe, "read_json", side_effect=[project, lock]):
            _, _, legacy = pe.load_plan(Path("inputs"), False)
        startup = "Windows/System32/startnet.cmd"
        self.assertNotIn(startup, legacy["boot/1"]["overlay"])
        project["wims"]["boot"]["replacement"] = {
            "source": "wims/new.wim",
            "sha256": "a" * 64,
            "kernel_version": "10.0.26100.9974",
            "configs": {"1": [startup]},
            "windows_features": {"1": {"locale": "zh-CN"}},
            "windows_packages": {"1": [
                {"source": "updates/checkpoint.msu", "sha256": "b" * 64},
                {"source": "updates/update.msu", "sha256": "c" * 64},
            ]},
        }
        with patch.object(pe, "read_json", side_effect=[project, lock]):
            _, _, scopes = pe.load_plan(Path("inputs"), False, "candidate.json")
        plan = scopes["boot/1"]
        self.assertEqual(plan["windows_locale"], "zh-CN")
        self.assertEqual(list(plan["overlay"]), [startup])
        self.assertEqual([entry["source"] for entry in plan["windows_packages"]],
                         ["updates/checkpoint.msu", "updates/update.msu"])
        project["wims"]["boot"]["replacement"]["kernel_version"] = "26100.9974"
        with (patch.object(pe, "read_json", side_effect=[project, lock]),
              self.assertRaisesRegex(ValueError, "Invalid expected boot kernel version")):
            pe.load_plan(Path("inputs"), False, "candidate.json")

    def test_boot_kernel_version_uses_boot_index_and_rejects_mismatch(self):
        wim = Path("replacement.wim")
        destination = Path("verify")
        slot = {"image_count": 5, "boot_index": 5}
        with (patch.object(pe, "tool", side_effect=lambda _, default: default),
              patch.object(pe, "run") as extract,
              patch.object(pe.subprocess, "run") as metadata):
            metadata.return_value.stdout = "10.0.26100.1742\n"
            with self.assertRaisesRegex(ValueError, "Expected kernel 10.0.26100.9974, found 10.0.26100.1742"):
                pe.verify_wim_kernel(wim, slot, "10.0.26100.9974", destination)
        entry = f"5/{pe.KERNEL}"
        extract.assert_called_once_with("7z.exe", "x", f"-o{destination}", wim, entry)
        self.assertEqual(metadata.call_args.kwargs["env"]["OMNIAI_VERSION_FILE"], str(destination / entry))

    def test_replacement_must_match_hash_and_slot(self):
        with TemporaryDirectory() as directory:
            inputs = Path(directory)
            path = inputs / "new.wim"
            header = bytearray(124)
            header[:8] = b"MSWIM\0\0\0"
            header[44] = header[120] = 1
            path.write_bytes(header)
            slot = {
                "image_count": 1,
                "boot_index": 1,
                "replacement": {"source": path.name, "sha256": pe.sha256(path)},
            }
            self.assertEqual(pe.replacement_wim(inputs, slot), path)
            slot["boot_index"] = 2
            with self.assertRaisesRegex(ValueError, "boot index changed"):
                pe.replacement_wim(inputs, slot)
            path.write_bytes(header + b"changed")
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                pe.replacement_wim(inputs, slot)

    def test_rejects_wim_with_changed_boot_index(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "test.wim"
            header = bytearray(124)
            header[:8] = b"MSWIM\0\0\0"
            header[44] = 5
            header[120] = 5
            path.write_bytes(header)
            pe.check_wim(path, {"image_count": 5, "boot_index": 5})
            with self.assertRaisesRegex(ValueError, "boot index changed"):
                pe.check_wim(path, {"image_count": 5, "boot_index": 1})
