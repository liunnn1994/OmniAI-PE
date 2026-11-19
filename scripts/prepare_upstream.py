"""下载并校验上游介质，恢复可直接从发布包制备的构建输入。"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPException
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from urllib.request import Request, build_opener

if __package__:
    from . import pe
else:
    import pe


SETUP_RECIPE = "base-setup-26100.9974.json"
HOTPE_EXCLUSIONS = {
    "Program Files/Icons": ("picture.ico", "picture2.ico", "picture3.ico", "Theme.ico", "Wallpapers.ico"),
    "Program Files/PETools": ("RandomWall.bat",),
    "Program Files/StartAllBack": ("DarkMagicLoaderX64.exe", "DarkMagicX64.dll", "Ribbon", "UpdateCheck.exe"),
}
X86_DRIVER_PATH = "Windows/System32/DriverStore/FileRepository"
X86_DRIVERS = ("ntprint.inf_x86_ee71fa42a4ee4f00", "prnms003.inf_x86_d6fba059ec824b4a")
HOTPE_PACKAGE_PREFIXES = ("packages/hotpe-2.8-no-theme/", "packages/hotpe-2.8-shell-tools/")


def publish(source, target, verify):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        verify(target)
        return
    with TemporaryDirectory(prefix=".omniai-inputs-", dir=target.parent) as directory:
        pending = Path(directory) / target.name
        if source.is_dir():
            shutil.copytree(source, pending)
        else:
            shutil.copyfile(source, pending)
        verify(pending)
        pending.rename(target)


def verify_payload(path, record):
    pe.require(pe.package_hash(path) == record["sha256"], f"构建输入的 SHA-256 不匹配：{record['source']}")


def extract(archive, output, filenames):
    pe.run(pe.tool("SEVENZIP", "7z.exe"), "x", "-y", "-spd", "-scsUTF-8", f"-o{output}", archive, *filenames)


def prepare_hotpe(inputs, project, lock, hotpe_iso, work):
    iso = pe.safe_path(inputs, lock["iso"]["file"])
    if hotpe_iso is None and not iso.exists():
        hotpe_iso = work / iso.name
        pe.download_https(lock["iso"]["url"], hotpe_iso, "原版 HotPE ISO")
    if hotpe_iso is not None:
        pe.check_file(hotpe_iso, lock["iso"])
        publish(hotpe_iso, iso, lambda path: pe.check_file(path, lock["iso"]))
    pe.check_file(iso, lock["iso"])

    boot = lock["wims"]["boot"]["path"]
    extract(iso, work / "hotpe", [boot])
    wim = pe.safe_path(work / "hotpe", boot)
    pe.check_file(wim, lock["media"][boot])
    sources = [record for record in project["packages"]
               if record["source"].startswith(HOTPE_PACKAGE_PREFIXES)]
    members = [record["target"] for record in sources]
    members.extend(f"{X86_DRIVER_PATH}/{driver}" for driver in X86_DRIVERS)
    hotpe_system = project["wims"]["boot"]["replacement"]["windows_features"]["1"]["registry"]["SYSTEM"]
    system_path = "Windows/System32/config/system"
    members.append(system_path)
    raw = work / "payload"
    extract(wim, raw, members)

    for folder, names in HOTPE_EXCLUSIONS.items():
        if folder not in members:
            continue
        for name in names:
            path = pe.safe_path(raw, f"{folder}/{name}")
            if path.is_dir():
                pe.require(path.resolve().is_relative_to(raw.resolve()), f"目录超出临时解包目录：{path}")
                pe.tree(path)
                shutil.rmtree(path)
            else:
                path.unlink()
    if "Program Files/PETools" in members:
        appearance = "Program Files/PETools/PlainAppearance.reg"
        shutil.copyfile(pe.safe_path(pe.ROOT, f"src/wim/boot/1/{appearance}"), pe.safe_path(raw, appearance))

    sources_by_path = [(record, pe.safe_path(raw, record["target"])) for record in sources]
    sources_by_path.extend((record, pe.safe_path(raw, X86_DRIVER_PATH)) for record in project["packages"]
                           if record["source"] == "packages/hotpe-2.8-x86-driver-packages")
    unresolved = []
    for record, source in sources_by_path:
        target = pe.safe_path(inputs, record["source"])
        if not target.exists() and pe.package_hash(source) != record["sha256"]:
            unresolved.append(record["source"])
            continue
        publish(source, target, lambda path: verify_payload(path, record))
    print(f"已校验并准备 {len(sources_by_path) - len(unresolved)} 项 HotPE 软件和驱动包")
    registry_source = pe.safe_path(raw, system_path)
    registry_target = pe.safe_path(inputs, hotpe_system["source"])
    if registry_target.exists() or pe.sha256(registry_source) == hotpe_system["sha256"]:
        publish(registry_source, registry_target, lambda path: verify_payload(path, hotpe_system))
    else:
        unresolved.append(hotpe_system["source"])
    return unresolved


def prepare_microsoft(inputs, project, recipe, windows_iso, winpe_ocs, work):
    packages = project["wims"]["boot"]["replacement"]["windows_packages"]["1"]
    for record in packages:
        name = Path(record["source"]).name
        path = pe.safe_path(inputs, record["source"])
        if not path.exists():
            pe.require(winpe_ocs.is_dir(), "请安装 26100 版 WinPE 加载项，或用 --winpe-ocs 指定组件目录")
        source = winpe_ocs / "zh-cn" / name if name.endswith("_zh-cn.cab") else winpe_ocs / name
        publish(source, path, lambda candidate: verify_payload(candidate, record))
    prepare_kernel_sources(inputs, recipe, windows_iso, work)
    print("微软安装介质底座、离线更新和 WinPE 可选组件已通过校验")


def prepare_kernel_sources(inputs, recipe, windows_iso, work):
    base = recipe["base"]
    base_path = pe.safe_path(inputs, base["source"])
    if not base_path.exists():
        if windows_iso is None:
            raw = work / "boot.wim"
            iso = base["iso"]
            download_range(iso["url"], raw, iso["wim_offset"], iso["wim_size"])
        else:
            extract(windows_iso, work / "windows", ["sources/boot.wim"])
            raw = work / "windows/sources/boot.wim"
        publish(raw, base_path, lambda candidate: verify_payload(candidate, base))
        raw.unlink()
    verify_payload(base_path, base)

    for record in recipe["updates"]:
        path = pe.safe_path(inputs, record["source"])
        if not path.exists():
            download = work / path.name
            download_range(record["url"], download, 0, record["size"])
            publish(download, path, lambda candidate: verify_payload(candidate, record))
            download.unlink()
        verify_payload(path, record)


def download_range(url, destination, start, size):
    pe.require(url.startswith("https://"), "微软底座下载必须使用 HTTPS")
    chunk_size = 16 * 1024 * 1024

    def fetch(offset):
        length = min(chunk_size, size - offset)
        part = destination.with_name(f"{destination.name}.{offset}.part")
        end = start + offset + length - 1
        for _ in range(4):
            count = part.stat().st_size if part.exists() else 0
            if count == length:
                return part
            first = start + offset + count
            request = Request(url, headers={"Range": f"bytes={first}-{end}"})
            try:
                with build_opener(pe.HttpsRedirectHandler()).open(request, timeout=60) as response:
                    pe.require(response.status == 206
                               and response.headers.get("Content-Range", "").startswith(f"bytes {first}-{end}/"),
                               f"微软下载端点未返回预期区段：{destination.name}")
                    with part.open("ab") as target:
                        remaining = length - count
                        while remaining and (data := response.read(min(remaining, 64 * 1024))):
                            target.write(data)
                            remaining -= len(data)
                    if remaining == 0:
                        return part
            except (OSError, HTTPException):
                continue
        raise ValueError(f"微软底座下载中断：{destination.name}（偏移 {offset}）")

    print(f"正在下载微软底座资源 {destination.name}（{size:,} 字节）", flush=True)
    with ThreadPoolExecutor(max_workers=8) as pool, destination.open("xb") as output:
        for part in pool.map(fetch, range(0, size, chunk_size)):
            with part.open("rb") as source:
                shutil.copyfileobj(source, output)
            part.unlink()


def init_kernel(inputs, replacement, windows_iso, work):
    slot = {"image_count": 1, "boot_index": 1, "replacement": replacement}
    cache = pe.kernel_cache(replacement["recipe"])
    legacy = pe.safe_path(inputs, replacement["source"])
    if cache.exists() or (legacy.is_file() and pe.sha256(legacy) == replacement["sha256"]):
        print(f"已校验 WinPE 底座 {pe.replacement_wim(inputs, slot)}")
        return
    work.mkdir()
    recipe = pe.read_json(replacement["recipe"])
    prepare_kernel_sources(inputs, recipe, windows_iso, work)
    prepared = work / "prepared"
    prepared.mkdir()
    digest = pe.prepare_base(inputs, recipe, output_dir=prepared, stage=work / "service")
    (prepared / "sha256").write_text(f"{digest}\n", encoding="ascii")
    cache.parent.mkdir(parents=True, exist_ok=True)
    if not cache.exists():
        try:
            prepared.rename(cache)
        except FileExistsError:
            pass
    print(f"已校验 WinPE 底座 {pe.replacement_wim(inputs, slot)}")
    (work / "service" / recipe["output"]).unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hotpe-iso", type=Path, help="使用已有的 HotPE ISO")
    parser.add_argument("--windows-iso", type=Path, help="使用已有的微软安装 ISO")
    parser.add_argument("--winpe-ocs", type=Path, help="微软 ADK 中 amd64/WinPE_OCs 目录")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--hotpe-only", action="store_true", help="只恢复可直接从 HotPE ISO 制备的输入")
    mode.add_argument("--kernel-only", action="store_true", help="只下载并制备微软 WinPE 底座")
    args = parser.parse_args()
    if not args.hotpe_only and not args.kernel_only and args.winpe_ocs is None:
        args.winpe_ocs = Path(os.environ["ProgramFiles(x86)"]) / (
            "Windows Kits/10/Assessment and Deployment Kit/Windows Preinstallation Environment/amd64/WinPE_OCs"
        )
    inputs = Path(os.environ.get("OMNIAI_INPUTS", pe.ROOT / "inputs")).absolute()
    project = pe.read_json("project.json")
    lock = pe.read_json("upstream.lock.json")
    work_parent = pe.safe_path(pe.ROOT, ".work")
    work_parent.mkdir(exist_ok=True)
    if args.kernel_only:
        project, _, _ = pe.load_plan(inputs, True, with_kernel=False)
        # DISM 提交失败时保留日志和挂载目录。
        work = work_parent / f"init-{pe.uuid.uuid4().hex}"
        init_kernel(inputs, project["wims"]["boot"]["replacement"], args.windows_iso, work)
        return
    with TemporaryDirectory(prefix="upstream-", dir=work_parent) as directory:
        work = Path(directory)
        unresolved = prepare_hotpe(inputs, project, lock, args.hotpe_iso, work)
        if not args.hotpe_only:
            prepare_microsoft(inputs, project, pe.read_json(SETUP_RECIPE), args.windows_iso, args.winpe_ocs, work)
    for source in unresolved:
        print(f"仍需补齐旧构建的派生输入：{source}", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        sys.exit(f"错误：{error}")
