#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Preserve experiment outputs and ABI evidence without touching releases."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile


def command(*args):
    return subprocess.check_output(args, text=True,
                                   env=dict(os.environ, LC_ALL="C")).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    if output == source or source in output.parents or output in source.parents:
        parser.error("output must be outside, and not an ancestor of, the OpenWrt source tree")
    for name in ("metadata", "firmware", "packages", "SHA256SUMS"):
        if (output / name).exists() or (output / name).is_symlink():
            parser.error(f"output already contains {name}; refusing to overwrite or mix builds")
    output.mkdir(parents=True, exist_ok=True)
    metadata = output / "metadata"
    metadata.mkdir(exist_ok=True)
    missing = []
    inspection_issues = []

    def preserve(path):
        if not path.exists():
            missing.append(str(path.relative_to(source)))
            return
        dest = metadata / path.relative_to(source)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if path.is_dir():
            shutil.copytree(path, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(path, dest)

    def inspect(*args):
        try:
            return command(*args)
        except (OSError, subprocess.CalledProcessError) as error:
            inspection_issues.append(f"Inspection failed ({args[0]}): {error}")
            return ""

    # Capture available evidence even when the firmware build failed.
    for name in (".config", "feeds.conf", "feeds.conf.default",
                 "target/linux/generic/kernel-6.18",
                 "tmp/.packageinfo", "tmp/.packagedeps",
                 "package/qca-nss/qca-nss-drv", "package/qca-nss/qca-nss-ecm",
                 "package/qca-nss/nss-firmware"):
        preserve(source / name)
    if (source / ".config").exists():
        try:
            result = subprocess.run([str(source / "scripts/diffconfig.sh")],
                                    cwd=source, text=True, capture_output=True)
            (metadata / "config.diff").write_text(result.stdout + result.stderr)
            if result.returncode:
                inspection_issues.append("diffconfig failed; see config.diff")
        except OSError as error:
            inspection_issues.append(f"diffconfig unavailable: {error}")

    feeds = []
    for feed in sorted((source / "feeds").glob("*")):
        if feed.is_dir() and (feed / ".git").exists():
            feeds.append({"name": feed.name,
                          "url": inspect("git", "-C", str(feed), "remote", "get-url", "origin"),
                          "commit": inspect("git", "-C", str(feed), "rev-parse", "HEAD")})
    (metadata / "feeds.lock.json").write_text(json.dumps(feeds, indent=2) + "\n")
    # ^commit is the src-git revision syntax understood by scripts/feeds.
    (metadata / "feeds.conf.lock").write_text("".join(
        f"src-git {feed['name']} {feed['url']}^{feed['commit']}\n" for feed in feeds))

    build_roots = sorted(source.glob("build_dir/target-*/linux-qualcommax_ipq60xx"))
    modules = []
    kernel_releases = []
    for build_root in build_roots:
        preserve(build_root / "symvers/qca-nss-drv.symvers")
        for kernel in sorted(build_root.glob("linux-[0-9]*")):
            if not kernel.is_dir():
                continue
            for name in (".config", ".vermagic", "Module.symvers", "include/config/kernel.release"):
                preserve(kernel / name)
            release = kernel / "include/config/kernel.release"
            if release.exists():
                kernel_releases.append(release.read_text().strip())
            headers = [kernel / "include/config", kernel / "include/generated"]
            archive = metadata / f"{kernel.name}-generated-headers.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                for directory in headers:
                    if directory.exists():
                        tar.add(directory, arcname=str(directory.relative_to(kernel)))
        modules.extend(sorted(build_root.glob("nss-usbnet-*/nss_usbnet.ko")))
        for package in sorted(build_root.glob("nss-usbnet-*")):
            # Only the probe's installation staging, never other packages.
            for name in ("modules.d", "modules-boot.d"):
                for directory in package.rglob(name):
                    if directory.is_dir() and any(directory.iterdir()):
                        inspection_issues.append(f"Unexpected probe autoload files: {directory}")
    for include in source.glob("staging_dir/target-*/usr/include/qca-nss-drv"):
        preserve(include)

    target = source / "bin/targets/qualcommax/ipq60xx"
    if target.is_dir():
        shutil.copytree(target, output / "firmware", dirs_exist_ok=True)
    packages = sorted(p for p in (source / "bin").rglob("*nss-usbnet*")
                      if p.is_file() and p.suffix in (".apk", ".ipk"))
    for package in packages:
        dest = output / "packages" / package.relative_to(source / "bin")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(package, dest)

    module_info = []
    for module in modules:
        preserve(module)
        symbols = inspect("nm", "-u", str(module))
        info = inspect("modinfo", str(module))
        elf = inspect("readelf", "-h", str(module))
        (metadata / f"{module.name}.undefined-symbols.txt").write_text(symbols + "\n")
        (metadata / f"{module.name}.modinfo.txt").write_text(info + "\n")
        (metadata / f"{module.name}.elf-header.txt").write_text(elf + "\n")
        imports = {line.split()[-1] for line in symbols.splitlines() if line.split()}
        nss_imports = {symbol for symbol in imports if symbol.startswith("nss_")}
        if nss_imports != {"nss_cmn_get_interface_number_by_dev"}:
            inspection_issues.append(f"Unexpected NSS imports: {sorted(nss_imports)}")
        vermagic = inspect("modinfo", "-F", "vermagic", str(module))
        dependencies = inspect("modinfo", "-F", "depends", str(module))
        machine = next((line.split(":", 1)[1].strip() for line in elf.splitlines()
                        if line.strip().startswith("Machine:")), "unknown")
        module_info.append({"vermagic": vermagic, "machine": machine,
                            "dependencies": dependencies,
                            "nss_imports": sorted(nss_imports)})

    record = {
        "source_commit": inspect("git", "-C", str(source), "rev-parse", "HEAD"),
        "ci_commit": os.environ.get("GITHUB_SHA", "local-unrecorded"),
        "build_result": os.environ.get("NSS_USBNET_BUILD_RESULT", "unverified"),
        "validation_result": "pending" if args.verify else "not_requested",
        "installed_router_abi": "UNVERIFIED: original config, feeds and symvers unavailable",
        "kernel_releases": kernel_releases,
        "packages": [str(p.relative_to(source)) for p in packages],
        "modules": module_info,
        "missing_evidence": missing,
        "inspection_issues": inspection_issues,
        "excluded_feed_sources": ["squeezelite"],
    }
    (metadata / "build.json").write_text(json.dumps(record, indent=2) + "\n")
    # Include the actual experiment sources, including private hooks.
    workspace = Path(os.environ.get("GITHUB_WORKSPACE", Path(__file__).resolve().parents[1]))
    with tarfile.open(metadata / "experiment-inputs.tar.gz", "w:gz") as tar:
        for name in ("Packages/nss-usbnet", "Scripts/PRIVATE.sh",
                     "Scripts/NSS-Usbnet-Artifacts.py", "Config/PRIVATE.txt",
                     "Config/IPQ60XX-NSS-USBNET.txt", "Config/NSS-USBNET-feeds.conf",
                     ".github/workflows/NSS-USBNET.yml"):
            tar.add(workspace / name, arcname=name)

    def verify_outputs():
        if inspection_issues:
            raise RuntimeError("; ".join(inspection_issues))
        if record["source_commit"] != "0fb9b10cb9df51fb076470e1dd93d1c30dd89d83":
            raise RuntimeError("Source commit does not match the reviewed v0.1 baseline")
        expected_feeds = []
        for line in (workspace / "Config/NSS-USBNET-feeds.conf").read_text().splitlines():
            if line.startswith("src-git "):
                _, name, location = line.split()
                url, commit = location.rsplit("^", 1)
                expected_feeds.append({"name": name, "url": url, "commit": commit})
        if sorted(feeds, key=lambda feed: feed["name"]) != sorted(expected_feeds, key=lambda feed: feed["name"]):
            raise RuntimeError("Actual feeds differ from the reviewed v0.1 lock")
        config = (source / ".config").read_text().splitlines()
        expected = ("CONFIG_TARGET_qualcommax_ipq60xx=y",
                    "CONFIG_TARGET_qualcommax_ipq60xx_DEVICE_jdcloud_re-ss-01=y",
                    "CONFIG_PACKAGE_nss-firmware=y",
                    "CONFIG_PACKAGE_kmod-nss-usbnet=m", "CONFIG_KERNEL_DEBUG_FS=y")
        if any(line not in config for line in expected):
            raise RuntimeError("Experiment configuration did not survive defconfig")
        firmware_recipe = (metadata / "package/qca-nss/nss-firmware/Makefile").read_text()
        firmware_settings = {line.strip() for line in firmware_recipe.splitlines()}
        if not {"override NSS_MAJOR=12", "override NSS_MINOR=5", "override NSS_REL=210"} <= firmware_settings:
            raise RuntimeError("NSS firmware recipe differs from the reviewed 12.5.210 baseline")
        if (source / "package/feeds/packages/squeezelite").is_symlink():
            raise RuntimeError("The known upstream Kconfig cycle was not excluded")
        if not packages or len(modules) != 1 or kernel_releases != ["6.18.52"]:
            raise RuntimeError("Missing or ambiguous probe package/module/kernel output")
        package_suffix = ".apk" if "CONFIG_USE_APK=y" in config else ".ipk"
        if any(package.suffix != package_suffix for package in packages):
            raise RuntimeError("Probe package format does not match this build's package manager")
        vermagic_fields = module_info[0]["vermagic"].split()
        if not vermagic_fields or vermagic_fields[0] != kernel_releases[0]:
            raise RuntimeError("Probe vermagic does not match this build's kernel release")
        if module_info[0]["machine"] != "AArch64":
            raise RuntimeError("Probe module was not built for AArch64")
        dependencies = module_info[0]["dependencies"].replace("-", "_").split(",")
        if "qca_nss_drv" not in dependencies:
            raise RuntimeError("Probe module is missing its real NSS driver dependency")
        includes = list((metadata / "staging_dir").glob("target-*/usr/include/qca-nss-drv"))
        if len(includes) != 1 or any(not (includes[0] / name).is_file()
                                     for name in ("nss_arch.h", "nss_def.h", "nss_cmn.h")):
            raise RuntimeError("Missing staged NSS API headers")
        for build_root in build_roots:
            for kernel in build_root.glob("linux-[0-9]*"):
                if kernel.is_dir():
                    for name in (".config", "Module.symvers", ".vermagic"):
                        if not (kernel / name).is_file() or not (kernel / name).stat().st_size:
                            raise RuntimeError(f"Missing kernel ABI evidence: {kernel / name}")
        if not any((output / "firmware").glob("*jdcloud_re-ss-01*sysupgrade*")):
            raise RuntimeError("Missing paired JDCloud sysupgrade image")
        symvers = list((metadata / "build_dir").glob("target-*/linux-qualcommax_ipq60xx/symvers/qca-nss-drv.symvers"))
        if len(symvers) != 1:
            raise RuntimeError("Missing matching NSS Module.symvers evidence")
        exports = [line.split() for line in symvers[0].read_text().splitlines()]
        if not any(len(fields) >= 4 and fields[1] == "nss_cmn_get_interface_number_by_dev"
                   and fields[3] in ("EXPORT_SYMBOL", "EXPORT_SYMBOL_GPL") for fields in exports):
            raise RuntimeError("Recorded NSS symvers does not export the required lookup API")

    verification_error = None
    if args.verify:
        try:
            verify_outputs()
            record["validation_result"] = "passed"
        except (OSError, RuntimeError) as error:
            verification_error = error
            record["validation_result"] = "failed"
            record["validation_error"] = str(error)
        (metadata / "build.json").write_text(json.dumps(record, indent=2) + "\n")

    with (output / "SHA256SUMS").open("w") as sums:
        for path in sorted(output.rglob("*")):
            if path.is_file() and path != output / "SHA256SUMS":
                with path.open("rb") as stream:
                    digest = hashlib.sha256()
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(block)
                sums.write(f"{digest.hexdigest()}  {path.relative_to(output)}\n")
    if verification_error:
        raise verification_error
    print(f"Saved {len(packages)} probe package(s); installed-router ABI remains unverified: {output}")


if __name__ == "__main__":
    main()
