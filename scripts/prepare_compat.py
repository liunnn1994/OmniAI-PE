"""从匹配的 amd64 Windows 介质提取用于补充 WinPE 功能的构建输入。"""

import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

if __package__:
    from . import pe
else:
    import pe


DRIVER_ROOT = "windows/system32/driverstore/filerepository/"
SYSTEM32 = "windows/system32/"
SYSTEM_FOLDERS = {"en-us", "zh-cn", "wbem", "inputmethod", "winmetadata", "winevt",
                  "speech", "speech_onecore"}
EXPLORER = {"windows/explorer.exe", "windows/zh-cn/explorer.exe.mui",
            "windows/en-us/explorer.exe.mui"}
INK = "program files/common files/microsoft shared/ink/"
SMB1 = f"{SYSTEM32}drivers/mrxsmb10.sys"
LEGACY_RUNTIMES = {
    "devbasedll.dll", "devbasedlld.dll", "mfc140u.dll", "mscomctl.ocx", "msvcp100.dll",
    "msvcp120.dll", "msvcp140.dll", "msvcp140_1.dll", "msvcr100.dll", "msvcr110.dll",
    "msvcr120.dll", "vcomp100.dll", "vcomp140.dll", "vcruntime140.dll", "vcruntime140_1.dll",
}
WMIC_COMPAT_FILES = {
    SYSTEM32 + "wbem/" + name for name in (
        "cli.mof", "cliegaliases.mof", "rawxml.xsl", "texttable.xsl", "textvaluelist.xsl",
        "wmic.exe", "xsl-mappings.xml", "zh-cn/cli.mfl", "zh-cn/cliegaliases.mfl", "zh-cn/wmic.exe.mui",
    )
}


def wim_paths(path):
    result = subprocess.run([pe.tool("SEVENZIP", "7z.exe"), "l", "-slt", "-sccUTF-8", str(path)],
                            check=True, capture_output=True, encoding="utf-8")
    header, separator, body = result.stdout.partition("\n----------\n")
    pe.require(separator, f"Missing WIM inventory: {path}")
    comment = re.search(r"^Comment = (<WIM>.*</WIM>)$", header, re.MULTILINE)
    pe.require(comment, f"Missing WIM XML: {path}")
    images = ET.fromstring(comment[1]).findall("IMAGE")
    pe.require(len(images) == 1, f"Export one WIM index before preparing components: {path}")
    windows = images[0].find("WINDOWS")
    pe.require(windows is not None and windows.findtext("ARCH") == "9", f"Expected amd64 WIM: {path}")
    build = windows.findtext("VERSION/BUILD")
    paths = {}
    for record in re.split(r"\n\s*\n", body):
        fields = dict(line.split(" = ", 1) for line in record.splitlines() if " = " in line)
        if fields.get("Folder") == "-" and not fields.get("Link") and fields.get("Alternate Stream") != "+":
            name = fields["Path"].replace("\\", "/")
            pe.relative(name)
            key = name.casefold()
            pe.require(key not in paths, f"Case-insensitive WIM path collision: {name}")
            paths[key] = name
    return build, paths


def feature_path(name):
    if name.startswith(pe.EXTRA_FEATURE_ROOTS) or name in pe.EXTRA_FEATURE_FILES:
        return True
    if name.startswith(("windows/syswow64/", "windows/systemapps/", "windows/systemresources/", INK)) or name in EXPLORER:
        return True
    if not name.startswith(SYSTEM32):
        return False
    first, separator, rest = name[len(SYSTEM32):].partition("/")
    if separator:
        if first == "drivers":
            return Path(rest).suffix in {".sys", ".dll", ".mui", ".dls"}
        return first in SYSTEM_FOLDERS and not rest.endswith(".evtx")
    # 完整 Windows 的 DWM 初始化组件会使这个 WinPE 在登录前卡住。
    return first not in {"dwminit.dll", "pecmd.exe"} and Path(first).suffix in {
        ".dll", ".exe", ".com", ".cpl", ".nls", ".ocx", ".ax", ".msc", ".tlb", ".mui", ".drv", ".acm",
    }


def driver_id(path):
    if path.startswith(DRIVER_ROOT):
        directory, child, _ = path[len(DRIVER_ROOT):].partition("/")
        inf, separator, _ = directory.partition("_amd64_")
        if separator and child:
            return inf
    return None


def driver_directory(path):
    return path[len(DRIVER_ROOT):].split("/", 1)[0]


def runtime_versions(paths):
    assemblies = defaultdict(lambda: defaultdict(set))
    for name in paths:
        match = pe.RUNTIME_ASSEMBLY.fullmatch(name)
        if match:
            version = tuple(map(int, match[2].split(".")))
            identity = (match[1], version[:2], match[3])
            assemblies[identity][version].add(name)
    return assemblies


def prepare(reference, base, donor, payload, work):
    reference_build, original = wim_paths(reference)
    base_build, present = wim_paths(base)
    donor_build, available = wim_paths(donor)
    pe.require(reference_build == base_build == donor_build, "WIM build branches differ")
    expected = {name for name in original.keys() - present.keys() if feature_path(name)}
    if SMB1 in expected and SMB1 not in available:
        versions = {}
        for name, stored in available.items():
            component = re.fullmatch(
                r"windows/winsxs/amd64_microsoft-windows-smb10-minirdr_[^_]+_(10\.0\.\d+\.\d+)_none_[^/]+/mrxsmb10\.sys",
                name,
            )
            if component:
                versions[tuple(map(int, component[1].split(".")))] = stored
        if versions:
            available[SMB1] = versions[max(versions)]
    selected = expected & available.keys()
    old_assemblies = runtime_versions(original)
    base_assemblies = runtime_versions(present)
    donor_assemblies = runtime_versions(available)
    missing_assemblies = old_assemblies.keys() - base_assemblies.keys()
    for version_set in (donor_assemblies[identity] for identity in missing_assemblies & donor_assemblies.keys()):
        selected.update(version_set[max(version_set)])
    legacy_assemblies = {name for identity in missing_assemblies - donor_assemblies.keys()
                         if "microsoft.vc" in identity[0]
                         for name in old_assemblies[identity][max(old_assemblies[identity])]}
    runtimes = {name for name in expected - selected if
                name.rsplit("/", 1)[0] in {"windows/system32", "windows/syswow64"}
                and name.rsplit("/", 1)[-1] in LEGACY_RUNTIMES}
    runtimes.update(legacy_assemblies | ((expected - selected) & WMIC_COMPAT_FILES))
    old_drivers = {driver_id(name) for name in original}
    base_drivers = {driver_id(name) for name in present}
    missing_drivers = old_drivers - base_drivers - {None}
    driver_files = {name for name in available if driver_id(name) in missing_drivers}
    driver_coverage = {driver_id(name) for name in driver_files}
    installed_packages = {driver_directory(name) for name in present.keys() | available.keys()
                          if driver_id(name)}
    legacy_packages = {driver_directory(name) for name in original
                       if driver_id(name) and name.endswith(".cat")} - installed_packages
    legacy_drivers = {name for name in original if driver_id(name)
                      and driver_directory(name) in legacy_packages}
    pe.require(selected, "No Windows feature files matched the donor")
    work.mkdir(parents=True)
    payload.mkdir(parents=True)
    (payload / "files").mkdir()
    (payload / "drivers").mkdir()
    for role, image, paths, feature_set, driver_set in (
        ("donor", donor, available, selected, driver_files),
        ("hotpe", reference, original, runtimes, legacy_drivers),
    ):
        names = feature_set | driver_set
        if not names:
            continue
        requests = work / f"{role}-paths.txt"
        requests.write_text("\n".join(paths[name] for name in sorted(names)) + "\n", encoding="utf-8")
        extracted = work / role
        pe.run(pe.tool("SEVENZIP", "7z.exe"), "x", "-y", "-spd", "-scsUTF-8",
               f"-o{extracted}", image, f"@{requests}")
        for name in sorted(names):
            source = pe.safe_path(extracted, paths[name])
            if name in driver_set:
                destination = pe.safe_path(payload / "drivers", paths[name].split("/", 4)[4])
            else:
                destination = pe.safe_path(payload / "files", original.get(name, paths[name]))
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
    legacy_driver_coverage = {driver_id(name) for name in legacy_drivers}
    evidence = {
        "build": donor_build,
        "source_wims": {role: pe.sha256(path) for role, path in
                         (("hotpe", reference), ("base", base), ("donor", donor))},
        "files": len(selected | runtimes),
        "driver_packages": len(driver_coverage | legacy_driver_coverage),
        "hotpe_runtime_files": sorted(original[name] for name in runtimes),
        "hotpe_driver_packages": sorted(legacy_driver_coverage),
        "unmatched_files": sorted(original[name] for name in expected - selected - runtimes),
        "unmatched_drivers": sorted(missing_drivers - driver_coverage - legacy_driver_coverage),
        "payload_sha256": {kind: pe.package_hash(payload / kind) for kind in ("files", "drivers")},
    }
    (work / "coverage.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n",
                                      encoding="utf-8")
    print(f"Prepared {evidence['files']} feature files and {evidence['driver_packages']} driver families in {payload}")
    print(f"Coverage: {work / 'coverage.json'}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path, help="作为参照的 HotPE WIM")
    parser.add_argument("base", type=Path, help="已安装 Windows 组件包的官方 WinPE WIM")
    parser.add_argument("donor", type=Path, help="导出为单索引的微软 Windows 安装 WIM")
    parser.add_argument("name", help="inputs/packages/ 下的新目录名")
    args = parser.parse_args()
    pe.require("/" not in pe.relative(args.name), "Expected one payload directory name")
    prepare(args.reference.resolve(), args.base.resolve(), args.donor.resolve(),
            pe.safe_path(pe.ROOT, f"inputs/packages/{args.name}"),
            pe.safe_path(pe.ROOT, f".work/compat/{args.name}"))


if __name__ == "__main__":
    main()
