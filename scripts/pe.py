"""使用锁定版本的 HotPE 和本地构建输入装配 OmniAI PE。"""

import argparse
from contextlib import contextmanager, nullcontext
import hashlib
from http.client import HTTPException
import json
import ntpath
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import uuid
from urllib.request import HTTPRedirectHandler, build_opener
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
SECTOR = 2048
BOOT_PLATFORMS = {0: "bios", 0xEF: "uefi"}
BCD_STORES = {"bios": "Boot/bcd", "uefi": "EFI/MICROSOFT/BOOT/BCD"}
KERNEL = "Windows/System32/ntoskrnl.exe"
KERNEL_VERSION = re.compile(r"10\.0\.[0-9]+\.[0-9]+")
REGISTRY_HIVES = {"SYSTEM", "SOFTWARE", "DEFAULT"}
SETUP_FILE_PATH = re.compile(
    r"(x:\\)\$windows\.~bt\\(?=(?:windows|program files(?: \(x86\))?|programdata|users)(?:\\|$)|$)",
    re.IGNORECASE,
)
RUNTIME_ASSEMBLY = re.compile(
    r"windows/winsxs/(?:manifests/)?"
    r"((?:amd64|x86)_(?:microsoft\.windows\.(?:common-controls|c\.\.-controls\.resources|gdiplus|"
    r"i\.\.utomation\.proxystub|isolationautomation|systemcompatible)|"
    r"(?:policy\.[89]\.0\.)?microsoft\.vc[89]0\.crt)_[0-9a-f]+)"
    r"_([0-9.]+)_([a-z-]+)_[0-9a-f]+(?:\.manifest|/[^/]+)$"
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(name):
    return json.loads(safe_path(ROOT, f"manifests/{name}").read_text(encoding="utf-8"))


def relative(name):
    require(isinstance(name, str), f"Expected a relative path: {name!r}")
    for part in name.split("/"):
        require(
            part and part not in {".", ".."} and not ntpath.isreserved(part)
            and not any(char in part for char in ":\\"),
            f"Invalid relative path: {name!r}",
        )
    return name


def safe_path(root, name):
    path = root
    for part in ["", *relative(name).split("/")]:
        path = path / part
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        require(
            not stat.S_ISLNK(info.st_mode)
            and not getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT,
            f"Link or junction is not supported: {path}",
        )
    return path


def sha256(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def tree(root):
    entries = {}
    if root.exists():
        require(root.is_dir(), f"Expected a directory: {root}")
        pending = [root]
        while pending:
            for child in pending.pop().iterdir():
                name = child.relative_to(root).as_posix()
                path = safe_path(root, name)
                key = name.casefold()
                require(key not in entries, f"Case-insensitive path collision: {path}")
                require(path.is_dir() or path.is_file(), f"Unsupported file type: {path}")
                entries[key] = (name, path)
                if path.is_dir():
                    pending.append(path)
    return sorted(entries.values())


def package_hash(path):
    if path.is_file():
        return sha256(path)
    require(path.is_dir(), f"Missing payload: {path}")
    rows = [(name, None if entry.is_dir() else sha256(entry)) for name, entry in tree(path)]
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode("utf-8")).hexdigest()


def overlaps(left, right):
    left, right = left.casefold(), right.casefold()
    return left == right or left.startswith(right + "/") or right.startswith(left + "/")


def check_hash(value):
    require(isinstance(value, str) and re.fullmatch("[a-f0-9]{64}", value), f"Invalid SHA-256: {value}")


def check_file(path, record):
    require(path.is_file(), f"Missing input: {path}")
    require(path.stat().st_size == record["size"] and sha256(path) == record["sha256"],
            f"File differs from the upstream lock: {path}")


def boot_images(iso, expected):
    """读取 BIOS 和 EFI 的无仿真启动条目，校验对应的启动镜像。"""
    images = {}
    with iso.open("rb") as handle:
        for sector in range(16, 32):
            handle.seek(sector * SECTOR)
            descriptor = handle.read(SECTOR)
            if descriptor.startswith(b"\0CD001\x01EL TORITO SPECIFICATION"):
                handle.seek(struct.unpack_from("<I", descriptor, 71)[0] * SECTOR)
                catalog = handle.read(SECTOR)
                break
        else:
            raise ValueError(f"Missing El Torito boot record: {iso}")
        require(len(catalog) == SECTOR and catalog[0] == 1 and catalog[30:32] == b"\x55\xaa"
                and sum(struct.unpack_from("<16H", catalog)) % 65536 == 0,
                f"Invalid El Torito catalog: {iso}")
        position = 32
        platform, remaining = catalog[1], 1
        while remaining:
            entry = catalog[position:position + 32]
            kind = BOOT_PLATFORMS.get(platform)
            require(kind in expected and kind not in images and entry[:2] == b"\x88\0",
                    f"Unsupported El Torito entry: {iso}")
            start = struct.unpack_from("<I", entry, 8)[0] * SECTOR
            handle.seek(start)
            data = handle.read(expected[kind]["size"])
            require(hashlib.sha256(data).hexdigest() == expected[kind]["sha256"],
                    f"Boot image differs from the upstream lock: {kind} in {iso}")
            images[kind] = data
            remaining -= 1
            position += 32
            if not remaining and catalog[position] in (0x90, 0x91):
                platform = catalog[position + 1]
                remaining = struct.unpack_from("<H", catalog, position + 2)[0]
                require(0 < remaining <= (SECTOR - position - 32) // 32,
                        f"Invalid El Torito section: {iso}")
                position += 32
        require(images.keys() == expected.keys(), f"Missing boot image: {iso}")
    return images


def check_wim(path, slot):
    with path.open("rb") as handle:
        header = handle.read(124)
    require(len(header) == 124 and header.startswith(b"MSWIM\0\0\0"), f"Invalid WIM: {path}")
    require(struct.unpack_from("<I", header, 44)[0] == slot["image_count"]
            and struct.unpack_from("<I", header, 120)[0] == slot["boot_index"],
            f"WIM image count or boot index changed: {path}")


def replacement_wim(inputs, slot):
    replacement = slot["replacement"]
    source = safe_path(inputs, replacement["source"])
    if source.is_file() and sha256(source) == replacement["sha256"]:
        check_wim(source, slot)
        return source
    if recipe := replacement.get("recipe"):
        cache = kernel_cache(recipe)
        source = safe_path(cache, Path(replacement["source"]).name)
        stamp = safe_path(cache, "sha256")
        require(source.is_file() and stamp.is_file(),
                "请先运行 mise run init 制备微软 WinPE 底座")
        expected = stamp.read_text(encoding="ascii").strip()
        check_hash(expected)
    else:
        expected = replacement["sha256"]
    require(source.is_file() and sha256(source) == expected,
            f"Replacement WIM missing or SHA-256 mismatch: {source}")
    check_wim(source, slot)
    return source


def kernel_cache(recipe):
    require("/" not in relative(recipe) and recipe.endswith(".json"), "底座配方必须是 JSON 文件名")
    config = safe_path(ROOT, f"manifests/{recipe}")
    return safe_path(ROOT, f".work/kernel/{sha256(config)}")


def media_path(name, project):
    renames = project.get("media_renames", {})
    return "/".join(renames.get(part, part) for part in name.split("/"))


def check_fixed_media(media, project, lock):
    generated = {slot["path"] for slot in lock["wims"].values()}
    expected = {media_path(name, project): record for name, record in lock["media"].items()
                if name not in generated}
    actual = {name for name, path in tree(media) if path.is_file()}
    require(actual == expected.keys(), f"固定媒体文件清单与上游锁不一致：{media}")
    for name, record in expected.items():
        check_file(safe_path(media, name), record)


def fixed_media(inputs, project, lock):
    media = safe_path(inputs, project["media_source"])
    check_fixed_media(media, project, lock)
    for kind, record in lock["boot"].items():
        check_file(safe_path(inputs, f"boot/{kind}.bin"), record)
    return media


def verify_wim_kernel(wim, slot, expected, destination):
    entry = KERNEL if slot["image_count"] == 1 else f"{slot['boot_index']}/{KERNEL}"
    run(tool("SEVENZIP", "7z.exe"), "x", f"-o{destination}", wim, entry)
    kernel = safe_path(destination, entry)
    result = subprocess.run([tool("POWERSHELL", "powershell.exe"), "-NoProfile", "-Command",
                             "(Get-Item -LiteralPath $env:OMNIAI_VERSION_FILE -ErrorAction Stop)"
                             ".VersionInfo.ProductVersion"],
                            check=True, capture_output=True, text=True,
                            env={**os.environ, "OMNIAI_VERSION_FILE": str(kernel)})
    actual = result.stdout.strip()
    require(actual == expected, f"Expected kernel {expected}, found {actual} in {wim}")
    print(f"Verified boot image kernel {actual} in {wim}", flush=True)


def load_plan(inputs, with_inputs, manifest="project.json", *, with_kernel=True):
    require("/" not in relative(manifest) and manifest.endswith(".json"), "Expected a manifest filename")
    project = read_json(manifest)
    lock = read_json("upstream.lock.json")
    require(re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", project["version"]), "Version must be x.y.z")
    require(re.fullmatch("[A-Z0-9_]{1,32}", project["volume_label"]), "Invalid ISO volume label")
    if uefi := project.get("uefi_boot"):
        slot = project["wims"]["boot"]
        require(slot["image_count"] == 1 and "replacement" in slot,
                "UEFI media requires a single-image replacement boot WIM")
        relative(uefi["source"])
        cabinet = uefi["cabinet"]
        require("/" not in relative(cabinet["member"]) and cabinet["url"].startswith("https://"),
                "Invalid ADK cabinet input")
        for record in (uefi, cabinet):
            check_hash(record["sha256"])
            require(isinstance(record["size"], int) and record["size"] > 0, "Invalid UEFI input size")
        if with_inputs and with_kernel:
            check_file(safe_path(inputs, uefi["source"]), uefi)
    for kind, descriptions in project.get("boot_descriptions", {}).items():
        require(kind in BCD_STORES and BCD_STORES[kind] in lock["media"],
                f"未知的启动配置：{kind}")
        for entry, description in descriptions.items():
            require(re.fullmatch(r"\{(?:default|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})\}", entry)
                    and isinstance(description, str) and description.strip() and "\0" not in description,
                    f"无效的启动项名称：{kind}/{entry}")
    if "uefi_default_entry" in project:
        entry = project["uefi_default_entry"]
        require(isinstance(entry, str) and entry != "{default}"
                and entry in project.get("boot_descriptions", {}).get("uefi", {}),
                "UEFI 默认启动项必须引用 boot_descriptions 中的启动项 GUID")
    if "uefi_prefer_1080p" in project:
        require(isinstance(project["uefi_prefer_1080p"], bool)
                and (not project["uefi_prefer_1080p"] or "uefi_default_entry" in project),
                "UEFI 1080p 首选项需要指定默认启动项")
    renames = project.get("media_renames", {})
    require(isinstance(renames, dict), "Expected media renames by path component")
    for old, new in renames.items():
        require("/" not in relative(old) and "/" not in relative(new), "Expected media path components")
    renamed_media = {media_path(name, project).casefold() for name in lock["media"]}
    require(len(renamed_media) == len(lock["media"]), "Media rename causes a path collision")
    boot_files = [*BCD_STORES.values(), "Boot/boot.sdi", "bootmgr", "bootmgr.efi"]
    require(all(media_path(name, project) == name for name in boot_files),
            "Boot manager, BCD and SDI paths cannot be renamed")
    layouts = {name: {key: value for key, value in slot.items() if key != "replacement"}
               for name, slot in project["wims"].items()}
    locked_layouts = {name: dict(slot, path=media_path(slot["path"], project))
                      for name, slot in lock["wims"].items()}
    require(layouts == locked_layouts, "WIM paths, image counts and boot indexes must match the lock")
    if layouts["boot"]["path"] != lock["wims"]["boot"]["path"]:
        require(all(project.get("boot_descriptions", {}).get(kind) for kind in BCD_STORES),
                "Renaming the boot WIM requires boot entries in both BCD stores")
    if "media_source" in project:
        relative(project["media_source"])
        require(all("replacement" in slot for slot in project["wims"].values()),
                "固定媒体目录需要为每个 WIM 提供替换映像")
    scopes = {"media": {"root": "media", "protected": ["Boot", "EFI", "bootmgr", "bootmgr.efi"]}}
    for name, slot in project["wims"].items():
        relative(name)
        if "replacement" in slot:
            replacement = slot["replacement"]
            require(relative(replacement["source"]).lower().endswith(".wim"),
                    f"Expected a complete replacement WIM: {name}")
            check_hash(replacement["sha256"])
            if recipe_name := replacement.get("recipe"):
                kernel_cache(recipe_name)
                recipe = read_json(recipe_name)
                require(recipe["output"] == Path(replacement["source"]).name
                        and recipe["kernel_version"] == replacement.get("kernel_version"),
                        f"底座配方与项目配置不匹配：{recipe_name}")
            if "kernel_version" in replacement:
                version = replacement["kernel_version"]
                require(isinstance(version, str) and KERNEL_VERSION.fullmatch(version)
                        and 1 <= slot["boot_index"] <= slot["image_count"],
                        f"Invalid expected boot kernel version: {name}")
            if with_inputs and (with_kernel or "media_source" not in project):
                replacement_wim(inputs, slot)
        scopes["media"]["protected"].append(relative(slot["path"]))
        for index in range(1, slot["image_count"] + 1):
            scopes[f"{name}/{index}"] = {"root": f"wim/{name}/{index}", "protected": [KERNEL]}
    for scope, plan in scopes.items():
        source = safe_path(ROOT, f"src/{plan['root']}")
        baseline = {}
        for name, digest in lock["configs"].get(scope, {}).items():
            if scope == "media":
                name = media_path(name, project)
            baseline[name.casefold()] = (name, digest)
        files = {name.casefold(): (name, path) for name, path in tree(source)
                 if path.is_file() and not name.casefold().startswith(".replacement/")}
        require(baseline.keys() <= files.keys(), f"Use an explicit removal for upstream files in {source}")
        plan["overlay"] = {}
        for key, (name, path) in files.items():
            if key in baseline:
                original, digest = baseline[key]
                require(name == original, f"Preserve capitalization of upstream path: {path}")
                if sha256(path) == digest:
                    continue
            plan["overlay"][name] = path
        plan["packages"] = {}
        plan["remove"] = []
        plan["windows_packages"] = []
        plan["windows_locale"] = None
        plan["windows_files"] = None
        plan["windows_drivers"] = None
        plan["registry"] = {}
        plan["relocate_setup_paths"] = False
    for slot, settings in project["wims"].items():
        replacement = settings.get("replacement", {})
        for index, paths in replacement.get("configs", {}).items():
            scope = f"{slot}/{index}"
            require(scope in scopes, f"Unknown replacement WIM index: {scope}")
            require(isinstance(paths, list), f"Expected a list of replacement configs: {scope}")
            plan = scopes[scope]
            source = safe_path(ROOT, f"src/{plan['root']}/.replacement")
            entries = {}
            for name in paths:
                relative(name)
                require(name.casefold() not in entries, f"Duplicate replacement config: {scope}/{name}")
                path = safe_path(source, name)
                require(path.is_file(), f"Missing replacement config: {path}")
                entries[name.casefold()] = (name, path)
            plan["overlay"] = dict(entries.values())
        for index, packages in replacement.get("windows_packages", {}).items():
            scope = f"{slot}/{index}"
            require(scope in scopes, f"Unknown servicing WIM index: {scope}")
            require(isinstance(packages, list), f"Expected a list of Windows packages: {scope}")
            seen = set()
            for package in packages:
                name = relative(package["source"])
                require(Path(name).suffix.lower() in {".cab", ".msu"}, f"Expected CAB or MSU: {name}")
                require(name.casefold() not in seen, f"Duplicate Windows package: {name}")
                seen.add(name.casefold())
                check_hash(package["sha256"])
                if with_inputs:
                    path = safe_path(inputs, name)
                    require(path.is_file() and sha256(path) == package["sha256"],
                            f"Windows package missing or SHA-256 mismatch: {path}")
                scopes[scope]["windows_packages"].append(package)
        for index, feature in replacement.get("windows_features", {}).items():
            scope = f"{slot}/{index}"
            require(scope in scopes, f"Unknown feature WIM index: {scope}")
            plan = scopes[scope]
            relocation = feature.get("relocate_setup_paths", False)
            require(isinstance(relocation, bool), f"Expected a Setup path relocation flag for {scope}")
            plan["relocate_setup_paths"] = relocation
            if "locale" in feature:
                locale = feature["locale"]
                require(isinstance(locale, str) and re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", locale),
                        f"Expected a Windows language tag for {scope}: {locale}")
                plan["windows_locale"] = locale
            for kind, field in (("files", "windows_files"), ("drivers", "windows_drivers")):
                package = feature.get(kind)
                if not package:
                    continue
                relative(package["source"])
                check_hash(package["sha256"])
                if with_inputs:
                    payload = safe_path(inputs, package["source"])
                    require(payload.is_dir() and package_hash(payload) == package["sha256"],
                            f"Windows feature tree missing or SHA-256 mismatch: {payload}")
                plan[field] = package
            for hive, rules in feature.get("registry", {}).items():
                require(hive in REGISTRY_HIVES, f"Unsupported registry hive: {hive}")
                relative(rules["source"])
                check_hash(rules["sha256"])
                for key in [*rules.get("keys", []), *rules.get("multi_strings", {})]:
                    relative(key)
                for values in rules.get("multi_strings", {}).values():
                    for additions in values.values():
                        require(isinstance(additions, list)
                                and all(isinstance(item, str) for item in additions),
                                "Expected a list of registry strings")
                if with_inputs:
                    path = safe_path(inputs, rules["source"])
                    require(path.is_file() and sha256(path) == rules["sha256"],
                            f"Registry input missing or SHA-256 mismatch: {path}")
                plan["registry"][hive] = rules
    require(isinstance(project["media_remove"], list), "Expected a list of media removals")
    scopes["media"]["remove"] = [relative(name) for name in project["media_remove"]]
    for slot, paths in project["wim_remove"].items():
        require(slot in project["wims"], f"Unknown WIM: {slot}")
        require(isinstance(paths, list), f"Expected a list of removals: {slot}")
        for path in paths:
            index, _, name = relative(path).partition("/")
            scope = f"{slot}/{index}"
            require(scope in scopes, f"Unknown WIM index in removal: {slot}/{path}")
            scopes[scope]["remove"].append(relative(name))
    for package in project["packages"]:
        scope = package["scope"]
        require(scope in scopes, f"Unknown package scope: {scope}")
        target = relative(package["target"])
        check_hash(package["sha256"])
        plan = scopes[scope]
        require(target not in plan["packages"], f"Duplicate package target: {scope}/{target}")
        source = relative(package["source"])
        if "unpacked_sha256" in package:
            check_hash(package["unpacked_sha256"])
            require(scope == "media" and source.lower().endswith((".7z", ".zip")),
                    f"Expected a media package sourced from a .7z or .zip archive: {source}")
        if with_inputs:
            payload = safe_path(inputs, source)
            if "unpacked_sha256" in package:
                require(payload.is_file(), f"Missing archive payload: {payload}")
            require(package_hash(payload) == package["sha256"], f"Payload hash mismatch: {payload}")
        plan["packages"][target] = package
    for scope, plan in scopes.items():
        targets = [*plan["remove"], *plan["packages"]]
        for position, target in enumerate(targets):
            require(not any(overlaps(target, other) for other in targets[:position]),
                    f"Overlapping removal or package: {scope}/{target}")
        for target in [*targets, *plan["overlay"]]:
            require(not any(overlaps(target, protected) for protected in plan["protected"]),
                    f"Reserved path: {scope}/{target}")
        for target in plan["remove"]:
            require(not any(overlaps(target, name) for name in plan["overlay"]),
                    f"Removal overlaps a changed configuration: {scope}/{target}")
    if with_inputs:
        if "media_source" in project:
            fixed_media(inputs, project, lock)
        else:
            iso = safe_path(inputs, lock["iso"]["file"])
            check_file(iso, lock["iso"])
            boot_images(iso, lock["boot"])
    return project, lock, scopes


def apply_plan(root, plan, inputs):
    def remove(path):
        if path.is_dir():
            tree(path)  # 删除目录前检查其中是否存在符号链接或目录联接。
            shutil.rmtree(path)
        else:
            path.unlink()

    for name in plan["remove"]:
        remove(safe_path(root, name))
    for name, package in plan["packages"].items():
        target = safe_path(root, name)
        source = safe_path(inputs, package["source"])
        unpacked_digest = package.get("unpacked_sha256")
        if unpacked_digest:
            require(source.is_file() and sha256(source) == package["sha256"],
                    f"Archive payload hash mismatch: {source}")
        if target.exists():
            remove(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        if unpacked_digest:
            run(tool("SEVENZIP", "7z.exe"), "x", "-y", f"-o{target}", source)
        elif source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
        digest = unpacked_digest or package["sha256"]
        require(package_hash(target) == digest, f"Staged payload hash mismatch: {target}")
    for name, source in plan["overlay"].items():
        target = safe_path(root, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def tool(env, default):
    name = os.environ.get(env, default)
    path = shutil.which(name)
    if not path and env == "OSCDIMG" and env not in os.environ:
        kits = Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
        path = shutil.which(str(kits / "Windows Kits/10/Assessment and Deployment Kit"
                                / "Deployment Tools/amd64/Oscdimg/oscdimg.exe"))
    require(path, f"Missing {name}. Set {env} to its executable path.")
    return path


def run(*args):
    args = [str(arg) for arg in args]
    print(subprocess.list2cmdline(args), flush=True)
    subprocess.run(args, check=True)


def prepare_service_directory(path, with_windows_packages):
    path.mkdir()
    if with_windows_packages:
        # DISM 打开部分映像文件时使用的大小写与实际文件名不同。
        probe = path / ".case-check"
        probe.touch()
        case_sensitive = not probe.with_name(".CASE-CHECK").exists()
        probe.unlink()
        if case_sensitive:
            run(tool("FSUTIL", "fsutil.exe"), "file", "setCaseSensitiveInfo", path, "disable")
    (path / "scratch").mkdir()


EXTRA_FEATURE_ROOTS = (
    "windows/l2schemas/", "windows/ocr/",
    "program files (x86)/common files/system/ado/",
    "program files (x86)/common files/system/ole db/",
)
EXTRA_FEATURE_FILES = {
    "windows/apppatch/msimain.sdb", "windows/apppatch/sysmain.sdb",
    "windows/system32/bthprops/@bthpropsnotificationlogo.png",
    "windows/system32/noise.dat", "windows/wmsyspr9.prx",
}


def add_windows_files(root, plan, inputs):
    files = plan["windows_files"]
    if not files:
        return
    source = safe_path(inputs, files["source"])
    require(package_hash(source) == files["sha256"], f"Windows feature file tree changed: {source}")
    for name, entry in tree(source):
        if entry.is_dir():
            continue
        normalized = name.casefold()
        require(normalized.startswith(("windows/system32/", "windows/syswow64/",
                                       "windows/systemapps/", "windows/systemresources/",
                                       "program files/common files/microsoft shared/ink/"))
                or RUNTIME_ASSEMBLY.fullmatch(normalized)
                or normalized.startswith(EXTRA_FEATURE_ROOTS)
                or normalized in EXTRA_FEATURE_FILES
                or normalized in {"windows/explorer.exe", "windows/zh-cn/explorer.exe.mui",
                                  "windows/en-us/explorer.exe.mui"},
                f"Unexpected Windows feature path: {name}")
        require(not any(overlaps(name, reserved) for reserved in [
            KERNEL, "Windows/System32/config", "Windows/System32/boot",
            "Windows/System32/CatRoot", "Windows/System32/CatRoot2", "Windows/System32/DriverStore",
            "Windows/System32/Dism", "Windows/System32/CodeIntegrity",
            "Windows/System32/ntdll.dll", "Windows/System32/hal.dll", "Windows/System32/dwminit.dll",
        ]), f"Reserved Windows feature file: {name}")
        target = safe_path(root, name)
        if target.exists():
            require(target.is_file(), f"Windows feature file collides with a directory: {target}")
            continue
        if normalized == "windows/system32/policymanager.dll":
            # 等 WinPE 完成防火墙初始化后再放入 Windows 策略 DLL。
            target = safe_path(root, "Program Files/OmniAI Startup/policymanager.dll")
            require(not target.exists(), f"Startup file already exists: {target}")
        if RUNTIME_ASSEMBLY.fullmatch(normalized):
            # 保留离线 WinSxS 组件存储原有的 NTFS 权限。
            args = [tool("ROBOCOPY", "robocopy.exe"), str(entry.parent), str(target.parent), entry.name,
                    "/B", "/COPY:DAT", "/XC", "/XN", "/XO", "/R:0", "/W:0", "/NFL", "/NDL", "/NJH", "/NJS"]
            result = subprocess.run(args, check=False)
            require(result.returncode < 8 and target.is_file() and sha256(target) == sha256(entry),
                    f"Could not copy offline runtime assembly: {name} (robocopy {result.returncode})")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(entry, target)


@contextmanager
def offline_hive(path):
    import winreg

    name = f"OmniAI_{uuid.uuid4().hex}"
    reg = tool("REG", "reg.exe")
    alias = f"HKLM\\{name}"
    run(reg, "load", alias, path)
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, name) as key:
            yield key
    finally:
        run(reg, "unload", alias)


def copy_registry_key(source, destination, path):
    import winreg

    try:
        target = winreg.OpenKey(destination, path)
    except FileNotFoundError:
        target = winreg.CreateKeyEx(destination, path, access=winreg.KEY_READ)
    with target:
        children, values, _ = winreg.QueryInfoKey(source)
        for index in range(values):
            name, value, kind = winreg.EnumValue(source, index)
            try:
                winreg.QueryValueEx(target, name)
            except FileNotFoundError:
                with winreg.OpenKey(destination, path, access=winreg.KEY_SET_VALUE) as writable:
                    winreg.SetValueEx(writable, name, 0, kind, value)
    for index in range(children):
        name = winreg.EnumKey(source, index)
        if name.casefold() == "enum":
            # PnP 会在目标计算机上重新创建设备实例。
            continue
        try:
            with winreg.OpenKey(source, name) as src:
                copy_registry_key(src, destination, f"{path}\\{name}")
        except PermissionError as error:
            raise PermissionError(f"Cannot merge {path}\\{name}: {error}") from error


def apply_registry(mount, stage, inputs, rules_by_hive):
    import winreg

    def prefix(key, hive):
        if hive != "SYSTEM":
            return ""
        with winreg.OpenKey(key, "Select") as selected:
            index, _ = winreg.QueryValueEx(selected, "Default")
        return f"ControlSet{index:03d}\\"

    config = safe_path(mount, "Windows/System32/config")
    for hive, rules in rules_by_hive.items():
        source = safe_path(inputs, rules["source"])
        copy = stage / f"registry-reference-{mount.name}-{hive}"
        shutil.copyfile(source, copy)
        require(sha256(copy) == rules["sha256"], f"Registry input changed: {source}")
        path = safe_path(config, hive)
        require(path.is_file(), f"Missing offline hive: {path}")
        with offline_hive(copy) as old, offline_hive(path) as new:
            old_prefix, new_prefix = prefix(old, hive), prefix(new, hive)
            for name in rules.get("keys", []):
                name = name.replace("/", "\\")
                try:
                    with winreg.OpenKey(old, old_prefix + name) as src:
                        copy_registry_key(src, new, new_prefix + name)
                except PermissionError as error:
                    raise PermissionError(f"Cannot merge offline {hive}\\{new_prefix}{name}: {error}") from error
            for name, values in rules.get("multi_strings", {}).items():
                with winreg.CreateKeyEx(new, new_prefix + name.replace("/", "\\"),
                                        access=winreg.KEY_READ | winreg.KEY_WRITE) as dst:
                    for entry, additions in values.items():
                        try:
                            before, kind = winreg.QueryValueEx(dst, entry)
                            require(kind == winreg.REG_MULTI_SZ, f"Expected REG_MULTI_SZ: {name}/{entry}")
                        except FileNotFoundError:
                            before = []
                        already = {item.casefold() for item in before}
                        after = list(before)
                        for item in additions:
                            if item.casefold() not in already:
                                after.append(item)
                                already.add(item.casefold())
                        if after != before:
                            winreg.SetValueEx(dst, entry, 0, winreg.REG_MULTI_SZ, after)


def relocate_setup_path(value):
    return SETUP_FILE_PATH.sub(r"\1", value)


@contextmanager
def offline_registry_writer():
    import ctypes
    from ctypes import wintypes
    import winreg

    class TokenPrivilege(ctypes.Structure):
        _fields_ = [("count", wintypes.DWORD), ("luid_low", wintypes.DWORD),
                    ("luid_high", wintypes.LONG), ("attributes", wintypes.DWORD)]

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(wintypes.HANDLE(kernel.GetCurrentProcess()), 0x28, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        desired = TokenPrivilege(count=1, attributes=2)
        previous = TokenPrivilege()
        previous_size = wintypes.DWORD()
        if not advapi.LookupPrivilegeValueW(None, "SeRestorePrivilege",
                                           ctypes.byref(desired, TokenPrivilege.luid_low.offset)):
            raise ctypes.WinError(ctypes.get_last_error())
        enabled = advapi.AdjustTokenPrivileges(token, False, ctypes.byref(desired), ctypes.sizeof(previous),
                                               ctypes.byref(previous), ctypes.byref(previous_size))
        if not enabled or ctypes.get_last_error():
            raise ctypes.WinError(ctypes.get_last_error())

        def write(key, name, kind, value):
            writable = wintypes.HKEY()
            # REG_OPTION_BACKUP_RESTORE 以还原权限打开现有的离线注册表项。
            status = advapi.RegCreateKeyExW(wintypes.HKEY(int(key)), "", 0, None, 4, 0, None,
                                           ctypes.byref(writable), None)
            if status:
                raise ctypes.WinError(status)
            try:
                winreg.SetValueEx(writable.value, name, 0, kind, value)
            finally:
                winreg.CloseKey(writable.value)

        try:
            yield write
        finally:
            advapi.AdjustTokenPrivileges(token, False, ctypes.byref(previous), 0, None, None)
    finally:
        kernel.CloseHandle(token)


def apply_setup_path_relocation(mount):
    import winreg

    software_skip = {
        "microsoft\\windows\\currentversion\\component based servicing",
        "microsoft\\windows\\currentversion\\sidebyside",
    }

    def relocate(write, key, path="", children=True):
        subkeys, values, _ = winreg.QueryInfoKey(key)
        changes = 0
        for index in range(values):
            name, value, kind = winreg.EnumValue(key, index)
            if kind in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
                relocated = relocate_setup_path(value)
            elif kind == winreg.REG_MULTI_SZ:
                relocated = [relocate_setup_path(item) for item in value]
            else:
                continue
            if relocated != value:
                write(key, name, kind, relocated)
                changes += 1
        if children:
            for index in range(subkeys):
                name = winreg.EnumKey(key, index)
                child = f"{path}\\{name}" if path else name
                if child.casefold() not in software_skip:
                    with winreg.OpenKey(key, name) as branch:
                        changes += relocate(write, branch, child)
        return changes

    config = safe_path(mount, "Windows/System32/config")
    with (offline_hive(safe_path(config, "SOFTWARE")) as software,
          offline_registry_writer() as write):
        print(f"Relocated Setup paths in {relocate(write, software)} SOFTWARE values")
    with (offline_hive(safe_path(config, "SYSTEM")) as system,
          offline_registry_writer() as write):
        with winreg.OpenKey(system, "Select") as selected:
            index, _ = winreg.QueryValueEx(selected, "Default")
        # 遍历时跳过驱动注册和设备实例数据。
        sections = (
            "Control\\CMF", "Control\\FeatureManagement", "Control\\NetTrace",
            "Control\\Session Manager\\Environment",
            "Services\\EventLog", "Services\\LSM", "Services\\RemoteAccess", "Services\\SharedAccess",
            "Services\\WinSock2",
        )
        changes = 0
        for section in sections:
            try:
                branch = winreg.OpenKey(system, f"ControlSet{index:03d}\\{section}")
            except FileNotFoundError:
                continue
            with branch:
                changes += relocate(write, branch, section)
        with winreg.OpenKey(system, "DriverDatabase") as drivers:
            changes += relocate(write, drivers, "DriverDatabase", children=False)
        print(f"Relocated Setup paths in {changes} SYSTEM values")


def service_wim(stage, path, index, plan, inputs):
    dism = tool("DISM", "dism.exe")
    service = stage
    if plan["windows_packages"] or (plan["windows_drivers"] and not Path(str(stage).lower()).exists()):
        # 累积更新展开后路径很深，驱动提供程序还会将挂载路径转成小写。
        service = Path(tempfile.mkdtemp(prefix="pe-"))
        require(Path(str(service).lower()).exists(), f"DISM needs a case-insensitive temp path: {service}")
        (service / "scratch").mkdir()
    mount = service / f"mount-{index}"
    mount.mkdir()
    options = ["/English", f"/LogPath:{stage / 'dism.log'}", f"/ScratchDir:{service / 'scratch'}"]

    def remove_empty_temp():
        if service != stage:
            for directory in (mount, service / "scratch", service):
                if directory.is_dir() and not any(directory.iterdir()):
                    directory.rmdir()

    run(dism, *options, "/Mount-Image", f"/ImageFile:{path}", f"/Index:{index}", f"/MountDir:{mount}")
    try:
        for package in plan["windows_packages"]:
            source = safe_path(inputs, package["source"])
            require(sha256(source) == package["sha256"], f"Windows package hash mismatch: {source}")
            run(dism, *options, f"/Image:{mount}", "/Add-Package", f"/PackagePath:{source}")
        if locale := plan.get("windows_locale"):
            run(dism, *options, f"/Image:{mount}", f"/Set-AllIntl:{locale}")
        if drivers := plan["windows_drivers"]:
            source = safe_path(inputs, drivers["source"])
            require(package_hash(source) == drivers["sha256"], f"Windows driver tree changed: {source}")
            # 厂商 INF 引用的文件也需要按大小写不敏感的方式查找。
            staging = (tempfile.TemporaryDirectory(prefix="drivers-", dir=service)
                       if service != stage else nullcontext())
            try:
                with staging as directory:
                    if directory is not None:
                        destination = Path(directory) / "payload"
                        shutil.copytree(source, destination)
                        require(package_hash(destination) == drivers["sha256"],
                                f"Copied Windows driver tree changed: {destination}")
                        source = destination
                    run(dism, *options, f"/Image:{mount}", "/Add-Driver", f"/Driver:{source}", "/Recurse")
            except subprocess.CalledProcessError:
                setup_log = mount / "Windows/INF/setupapi.offline.log"
                if setup_log.is_file():
                    shutil.copyfile(setup_log, stage / "setupapi.offline.log")
                raise
        add_windows_files(mount, plan, inputs)
        if plan["registry"]:
            apply_registry(mount, stage, inputs, plan["registry"])
        if plan.get("relocate_setup_paths"):
            apply_setup_path_relocation(mount)
        apply_plan(mount, plan, inputs)
    except BaseException:
        try:
            run(dism, *options, "/Unmount-Image", f"/MountDir:{mount}", "/Discard")
        except subprocess.CalledProcessError:
            print(f"DISM discard failed. Inspect the mount at {mount}", file=sys.stderr)
        else:
            remove_empty_temp()
        raise
    try:
        run(dism, *options, "/Unmount-Image", f"/MountDir:{mount}", "/Commit")
    except BaseException:
        print(f"DISM commit did not complete. Inspect the mount at {mount}", file=sys.stderr)
        raise
    remove_empty_temp()


def prepare_base(inputs, recipe, *, output_dir=None, stage=None):
    version = recipe["kernel_version"]
    require(isinstance(version, str) and KERNEL_VERSION.fullmatch(version), "Invalid target kernel version")
    layout = {"image_count": 1, "boot_index": 1}
    base = recipe["base"]
    source_layout = {key: base.get(key, value) for key, value in layout.items()}
    index = base.get("index", 1)
    require(type(index) is int and 1 <= index <= source_layout["image_count"], "Invalid source WIM index")
    source = replacement_wim(inputs, {**source_layout, "replacement": base})
    packages = recipe["updates"]
    require(packages, "Specify at least one ordered WinPE update")
    for package in packages:
        check_hash(package["sha256"])
        path = safe_path(inputs, package["source"])
        require(path.suffix.casefold() == ".msu" and path.is_file(), f"Expected WinPE MSU: {path}")
        require(sha256(path) == package["sha256"], f"Windows package hash mismatch: {path}")
    output_name = recipe.get("output", f"Microsoft-WinPE-{version.removeprefix('10.0.')}-amd64.wim")
    require("/" not in relative(output_name) and output_name.lower().endswith(".wim"), "Expected a WIM output filename")
    output = safe_path(inputs / "wims" if output_dir is None else output_dir, output_name)
    require(not output.exists(), f"Base already exists: {output}")
    stage_name = output.stem if "output" in recipe else version
    if stage is None:
        stage = safe_path(ROOT, f".work/base/{stage_name}")
    stage.parent.mkdir(parents=True, exist_ok=True)
    prepare_service_directory(stage, True)
    wim = stage / output.name
    if source_layout == layout:
        shutil.copyfile(source, wim)
        require(sha256(wim) == base["sha256"], f"Copied base hash mismatch: {wim}")
    else:
        run(tool("DISM", "dism.exe"), "/English", "/Export-Image", f"/SourceImageFile:{source}",
            f"/SourceIndex:{index}", f"/DestinationImageFile:{wim}", "/Compress:max", "/Bootable", "/CheckIntegrity")
    check_wim(wim, layout)
    plan = dict(windows_drivers=None, windows_files=None, registry={}, remove=[], packages={}, overlay={})
    for number, package in enumerate(packages, 1):
        # 每个检查点更新都先提交，再挂载映像以应用下一份 MSU。
        pass_dir = stage / str(number)
        prepare_service_directory(pass_dir, False)
        service_wim(pass_dir, wim, 1, {**plan, "windows_packages": [package]}, inputs)
        check_wim(wim, layout)
    verify_wim_kernel(wim, layout, version, stage / "verify")
    pending = output.with_suffix(".wim.partial")
    with pending.open("xb") as target, wim.open("rb") as image:
        shutil.copyfileobj(image, target)
    digest = sha256(wim)
    require(sha256(pending) == digest, f"Copied base hash mismatch: {pending}")
    pending.rename(output)
    print(f"{digest}  {output}")
    return digest


def apply_boot_descriptions(media, descriptions, uefi_default=None, *, prefer_1080p=False, ramdisks=None):
    for kind, entries in descriptions.items():
        store = safe_path(media, BCD_STORES[kind])
        # BCDEdit 会产生注册表日志，只将修改后的 BCD 放回媒体目录。
        with tempfile.TemporaryDirectory(dir=media.parent) as directory:
            editable = Path(directory) / store.name
            shutil.copyfile(store, editable)
            for entry, description in entries.items():
                run("bcdedit.exe", "/store", editable, "/set", entry, "description", description)
                if ramdisks:
                    for element in ("device", "osdevice"):
                        run("bcdedit.exe", "/store", editable, "/set", entry, element, ramdisks[kind])
            if kind == "uefi" and uefi_default is not None:
                if prefer_1080p:
                    # BCDEdit 的 graphicsresolution 不接受 1080p。保留固件模式并在 PE 内请求 1080p。
                    run("bcdedit.exe", "/store", editable, "/set", uefi_default, "highestmode", "off")
                    run("bcdedit.exe", "/store", editable, "/set", uefi_default, "loadoptions", "OMNIAI_DISPLAY_1080P")
                run("bcdedit.exe", "/store", editable, "/default", uefi_default)
            shutil.copyfile(editable, store)


def apply_windows_boot_media(stage, wim):
    files = {
        "bootmgr": "PCAT/bootmgr",
        "Boot/zh-cn/bootmgr.exe.mui": "PCAT/zh-CN/bootmgr.exe.mui",
        "bootmgr.efi": "EFI/bootmgr.efi",
        "EFI/BOOT/bootx64.efi": "EFI/bootmgfw.efi",
        "EFI/BOOT/zh-cn/bootx64.efi.mui": "EFI/zh-CN/bootmgfw.efi.mui",
        "EFI/MICROSOFT/BOOT/zh-cn/bootmgr.efi.mui": "EFI/zh-CN/bootmgr.efi.mui",
    }
    for folder in ("Boot", "EFI/MICROSOFT/BOOT"):
        for name in ("Resources/bootres.dll", "Resources/zh-CN/bootres.dll.mui",
                     "Fonts/chs_boot.ttf", "Fonts/wgl4_boot.ttf", "Fonts/msyh_boot.ttf"):
            files[f"{folder}/{name.lower()}"] = name
    with tempfile.TemporaryDirectory(dir=stage) as directory:
        sources = Path(directory)
        run(tool("SEVENZIP", "7z.exe"), "x", "-spd", f"-o{sources}", wim,
            *(f"Windows/Boot/{name}" for name in dict.fromkeys(files.values())))
        for destination, name in files.items():
            target = safe_path(stage / "media", destination)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(safe_path(sources, f"Windows/Boot/{name}"), target)


def stage_media(project, lock, scopes, inputs):
    stage = safe_path(ROOT, f".work/stage/{project['version']}")
    stage.mkdir(parents=True)
    media = stage / "media"
    if "media_source" in project:
        shutil.copytree(fixed_media(inputs, project, lock), media)
        check_fixed_media(media, project, lock)
        for kind, record in lock["boot"].items():
            target = stage / f"{kind}.bin"
            shutil.copyfile(safe_path(inputs, f"boot/{kind}.bin"), target)
            check_file(target, record)
    else:
        source = safe_path(inputs, lock["iso"]["file"])
        for kind, data in boot_images(source, lock["boot"]).items():
            (stage / f"{kind}.bin").write_bytes(data)
        run(tool("SEVENZIP", "7z.exe"), "x", "-y", f"-o{media}", source)
        actual = {name for name, path in tree(media) if path.is_file()}
        require(actual == lock["media"].keys(), "Extracted media file list differs from the upstream lock")
        for path, record in lock["media"].items():
            check_file(safe_path(media, path), record)
        for name, path in reversed(tree(media)):
            renamed = media_path(path.name, project)
            if renamed != path.name:
                path.rename(safe_path(media, Path(name).with_name(renamed).as_posix()))
    uefi = project.get("uefi_boot")
    if uefi:
        target = stage / "uefi.bin"
        shutil.copyfile(safe_path(inputs, uefi["source"]), target)
        check_file(target, uefi)
    apply_plan(media, scopes["media"], inputs)
    ramdisks = None
    boot_path = project["wims"]["boot"]["path"]
    if boot_path != lock["wims"]["boot"]["path"]:
        windows_path = "\\" + boot_path.replace("/", "\\")
        ramdisks = {kind: f"ramdisk=[boot]{windows_path},{options}"
                    for kind, options in lock["bcd_ramdisk_options"].items()}
    apply_boot_descriptions(media, project.get("boot_descriptions", {}), project.get("uefi_default_entry"),
                            prefer_1080p=project.get("uefi_prefer_1080p", False), ramdisks=ramdisks)
    for slug, slot in project["wims"].items():
        wim = safe_path(media, slot["path"])
        if "replacement" in slot:
            source = replacement_wim(inputs, slot)
            shutil.copyfile(source, wim)
            require(sha256(wim) == sha256(source),
                    f"Copied replacement WIM hash mismatch: {wim}")
            if uefi and slug == "boot":
                apply_windows_boot_media(stage, source)
        check_wim(wim, slot)
        plans = [scopes[f"{slug}/{index}"] for index in range(1, slot["image_count"] + 1)]
        service = stage / f"service-{slug}"
        for index, plan in enumerate(plans, 1):
            if any(plan[key] for key in
                   ("remove", "overlay", "packages", "windows_packages", "windows_locale", "windows_files",
                    "windows_drivers", "registry", "relocate_setup_paths")):
                if not service.exists():
                    prepare_service_directory(service, any(
                        item["windows_packages"] or item["windows_locale"] or item["registry"]
                        or item["windows_files"]
                        or item["windows_drivers"] or item["relocate_setup_paths"] for item in plans))
                service_wim(service, wim, index, plan, inputs)
        check_wim(wim, slot)
        if version := slot.get("replacement", {}).get("kernel_version"):
            verify_wim_kernel(wim, slot, version, stage / f"verify-{slug}")
    return stage


def build_iso(project, lock, stage, dist):
    pending = dist / "building.iso"
    iso = dist / f"OmniAI-PE-{project['version']}.iso"
    boot = f"-bootdata:2#p0,e,b{stage / 'bios.bin'}#pEF,e,b{stage / 'uefi.bin'}"
    run(tool("OSCDIMG", "oscdimg.exe"), "-m", "-h", "-u2", "-udfver102",
        f"-l{project['volume_label']}", boot, stage / "media", pending)
    expected_boot = dict(lock["boot"])
    if uefi := project.get("uefi_boot"):
        expected_boot["uefi"] = uefi
    boot_images(pending, expected_boot)
    digest = sha256(pending)
    pending.rename(iso)
    (dist / f"{iso.name}.sha256").write_text(f"{digest}  {iso.name}\n", encoding="utf-8")
    return iso


def bundle_inputs(inputs, project, lock, scopes, destination):
    if media := project.get("media_source"):
        sources = {media, *(f"boot/{kind}.bin" for kind in lock["boot"])}
    else:
        sources = {lock["iso"]["file"]}
        for slot in project["wims"].values():
            if "replacement" in slot:
                sources.add(slot["replacement"]["source"])
    for plan in scopes.values():
        packages = [*plan["packages"].values(), *plan["windows_packages"], *plan["registry"].values()]
        packages.extend(plan[kind] for kind in ("windows_files", "windows_drivers") if plan[kind])
        sources.update(package["source"] for package in packages)

    entries = set()
    for name in sorted(sources):
        path = safe_path(inputs, name)
        entries.add(path)
        if path.is_dir():
            entries.update(entry for _, entry in tree(path))

    destination.parent.mkdir(parents=True, exist_ok=True)
    output = destination.open("xb")
    try:
        with output, ZipFile(output, "w", ZIP_DEFLATED, compresslevel=1) as archive:
            for path in sorted(entries):
                archive.write(path, path.relative_to(inputs).as_posix())
    except BaseException:
        destination.unlink()
        raise


class HttpsRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        require(newurl.startswith("https://"), "构建输入下载只允许重定向到 HTTPS 地址")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_https(url, destination, label):
    require(url.startswith("https://"), f"{label}必须使用 HTTPS")
    try:
        opener = build_opener(HttpsRedirectHandler())
        with opener.open(url, timeout=120) as response, destination.open("xb") as archive:
            shutil.copyfileobj(response, archive)
    except (HTTPException, OSError, ValueError):
        raise ValueError(f"{label}下载失败") from None


def fetch_inputs(inputs, manifest, archive_path):
    safe_path(inputs.parent, inputs.name)
    require(not inputs.exists(), f"构建输入目录已存在：{inputs}")
    url = os.environ.get("OMNIAI_INPUTS_URL", "").strip()
    if archive_path is None and not url:
        local_archive = os.environ.get("OMNIAI_INPUTS_ARCHIVE", "").strip()
        if local_archive:
            archive_path = Path(local_archive).expanduser()
    if archive_path is not None:
        require(archive_path.is_file(), f"找不到构建输入 ZIP：{archive_path}")
    elif url:
        require(url.startswith("https://"), "OMNIAI_INPUTS_URL 必须是私有 ZIP 的 HTTPS 下载地址")
    else:
        raise ValueError("缺少完整的私有构建输入 ZIP。请设置 OMNIAI_INPUTS_URL 或 OMNIAI_INPUTS_ARCHIVE，"
                         "也可运行 mise run fetch-inputs -- --archive <ZIP 路径>")

    inputs.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".omniai-inputs-", dir=inputs.parent) as directory:
        work = Path(directory)
        if archive_path is None:
            archive_path = work / "inputs.zip"
            download_https(url, archive_path, "私有构建输入")

        unpacked = work / "inputs"
        unpacked.mkdir()
        project = read_json(manifest)
        with ZipFile(archive_path) as archive:
            for entry in archive.infolist():
                name = relative(entry.filename.removesuffix("/"))
                folder, separator, remainder = name.partition("/")
                if folder == project.get("media_source") and separator:
                    name = f"{folder}/{media_path(remainder, project)}"
                elif project.get("media_renames") and folder in {"packages", "registry"}:
                    package, tail, member = remainder.partition("/")
                    if package in {"hotpe-2.8-no-theme", "hotpe-2.8-shell-tools",
                                   "hotpe-2.8-x86-driver-packages", "hotpe-2.8"}:
                        name = f"{folder}/OmniAIPE{package.removeprefix('hotpe')}{tail}{member}"
                path = safe_path(unpacked, name)
                if entry.is_dir():
                    path.mkdir(parents=True, exist_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(entry) as source, path.open("xb") as output:
                        shutil.copyfileobj(source, output)

        load_plan(unpacked, True, manifest, with_kernel=False)
        unpacked.rename(inputs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="project.json", help="manifests/ 下的构建配置文件名")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check").add_argument("--without-inputs", action="store_true", help="跳过私有构建输入的校验")
    sub.add_parser("stage")
    sub.add_parser("build")
    sub.add_parser("bundle-inputs")
    sub.add_parser("fetch-inputs").add_argument("--archive", type=Path, help="从本地 ZIP 恢复构建输入")
    sub.add_parser("hash").add_argument("source", help="相对于输入目录的文件或目录路径")
    sub.add_parser("prepare-base").add_argument("recipe", help="manifests/ 下的底座配方文件名")
    args = parser.parse_args()
    inputs = Path(os.environ.get("OMNIAI_INPUTS", ROOT / "inputs")).absolute()
    if args.command == "fetch-inputs":
        fetch_inputs(inputs, args.manifest, args.archive)
        print(f"构建输入已校验并恢复到 {inputs}")
        return
    if args.command == "hash":
        print(package_hash(safe_path(inputs, args.source)))
        return
    if args.command == "prepare-base":
        require("/" not in relative(args.recipe) and args.recipe.endswith(".json"),
                "Expected a recipe filename")
        prepare_base(inputs, read_json(args.recipe))
        return
    with_inputs = not getattr(args, "without_inputs", False)
    project, lock, scopes = load_plan(inputs, with_inputs, args.manifest,
                                      with_kernel=args.command != "bundle-inputs")
    if args.command == "check":
        print("Checks passed" if with_inputs else "Manifest and overlay checks passed (private inputs skipped)")
        return
    if args.command == "bundle-inputs":
        destination = safe_path(ROOT, f".work/bundles/{Path(args.manifest).stem}-{project['version']}.zip")
        bundle_inputs(inputs, project, lock, scopes, destination)
        print(destination)
        return
    stage = safe_path(ROOT, f".work/stage/{project['version']}")
    require(not stage.exists(), f"Stage already exists: {stage}")
    if args.command == "build":
        dist = safe_path(ROOT, f"dist/{project['version']}")
        require(not dist.exists(), f"Output already exists: {dist}")
        tool("OSCDIMG", "oscdimg.exe")
    tool("SEVENZIP", "7z.exe")
    stage = stage_media(project, lock, scopes, inputs)
    if args.command == "build":
        dist.mkdir(parents=True)
        print(build_iso(project, lock, stage, dist))
    else:
        print(stage)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, BadZipFile, subprocess.CalledProcessError) as error:
        sys.exit(f"Error: {error}")
