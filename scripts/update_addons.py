#!/usr/bin/env python3
"""Package newer versions of the public GitHub add-ons in addon-sources.json."""

import argparse
import hashlib
import io
import json
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


def version_key(version):
    # These repositories publish stable, dotted numeric Kodi versions.
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", version):
        raise ValueError("Use a stable numeric version, such as 1.2.3: " + version)
    parts = [int(part) for part in version.split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def load_sources(root):
    sources = json.loads((root / "addon-sources.json").read_text(encoding="utf-8"))
    seen = set()
    for source in sources:
        addon_id = source["id"]
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", addon_id) or addon_id in seen:
            raise ValueError("Invalid or duplicate add-on ID: " + addon_id)
        seen.add(addon_id)
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", source["repository"]):
            raise ValueError("Expected a GitHub owner/repository")
        path = PurePosixPath(source["path"])
        if path.is_absolute() or ".." in path.parts or "\\" in source["path"]:
            raise ValueError("Add-on path must stay inside its source repository")
        if not source["branch"] or source["branch"].startswith("-"):
            raise ValueError("Invalid source branch")
    return sources


def checkout_source(source, destination):
    subprocess.run(
        [
            "git",
            "clone",
            "--quiet",
            "--depth",
            "1",
            "--single-branch",
            "--branch",
            source["branch"],
            "--",
            "https://github.com/" + source["repository"] + ".git",
            str(destination),
        ],
        check=True,
        timeout=180,
    )
    return destination


def read_addon(source_root, source):
    addon_dir = (source_root / source["path"]).resolve()
    if not addon_dir.is_relative_to(source_root.resolve()):
        raise ValueError("Add-on directory escapes its source repository")
    manifest = ET.fromstring((addon_dir / "addon.xml").read_bytes())
    if manifest.tag != "addon" or manifest.get("id") != source["id"]:
        raise ValueError("Source addon.xml ID does not match " + source["id"])
    version_key(manifest.attrib["version"])
    return addon_dir, manifest


def package_addon(source_root, addon_dir, addon_id):
    # Include only tracked files inside the add-on, never local settings or tools.
    output = subprocess.check_output(
        [
            "git",
            "-C",
            str(source_root),
            "ls-files",
            "-z",
            "--",
            addon_dir.relative_to(source_root.resolve()).as_posix(),
        ],
        timeout=30,
    )
    archive = io.BytesIO()
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as bundle:
        for name in sorted(output.decode("utf-8").split("\0")):
            if not name:
                continue
            path = source_root / name
            if path.is_symlink() or not path.resolve().is_relative_to(addon_dir):
                raise ValueError("Refusing to package a symlink: " + name)
            relative = path.relative_to(addon_dir)
            if "__pycache__" in relative.parts or path.suffix in (".pyc", ".pyo"):
                continue
            # Fixed timestamps and permissions make repeat builds reproducible.
            info = ZipInfo(addon_id + "/" + relative.as_posix(), (1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            bundle.writestr(info, path.read_bytes())
    with ZipFile(archive) as bundle:
        if addon_id + "/addon.xml" not in bundle.namelist():
            raise ValueError("addon.xml must be tracked in Git")
        if bundle.testzip() is not None:
            raise ValueError("Invalid generated ZIP")
    return archive.getvalue()


def update_repository(root, local_sources=None):
    root = Path(root).resolve()
    local_sources = local_sources or {}
    original = (root / "addons.xml").read_bytes()
    expected_hash = (root / "addons.xml.sha256").read_text().strip().lower()
    if hashlib.sha256(original).hexdigest() != expected_hash:
        raise ValueError("Existing addons.xml.sha256 does not match addons.xml")
    catalog = ET.fromstring(original)
    if catalog.tag != "addons":
        raise ValueError("Expected an <addons> catalog")
    entries = {addon.attrib["id"]: addon for addon in catalog}
    if len(entries) != len(catalog):
        raise ValueError("Duplicate add-on IDs in addons.xml")
    updates = []
    packages = []
    with tempfile.TemporaryDirectory(prefix="kodi-addons-") as temporary:
        for source in load_sources(root):
            addon_id = source["id"]
            if addon_id in local_sources:
                source_root = Path(local_sources[addon_id]).resolve()
            else:
                source_root = checkout_source(source, Path(temporary) / addon_id)
            addon_dir, manifest = read_addon(source_root, source)
            previous = entries.get(addon_id)
            version = manifest.attrib["version"]
            if previous is not None and version_key(version) <= version_key(
                previous.attrib["version"]
            ):
                print(addon_id + ": no newer version (source " + version + ")")
                continue
            archive = package_addon(source_root, addon_dir, addon_id)
            target = root / addon_id / (addon_id + "-" + version + ".zip")
            if target.exists():
                raise ValueError(
                    "Refusing to overwrite a published package: " + str(target)
                )
            packages.append((target, archive))
            if previous is not None:
                position = list(catalog).index(previous)
                catalog.remove(previous)
                catalog.insert(position, manifest)
            else:
                catalog.append(manifest)
            updates.append(addon_id + " " + version)

    # Finish every download and package before changing the published files.
    if updates:
        ET.indent(catalog, space="    ")
        content = ET.tostring(catalog, encoding="utf-8", xml_declaration=True) + b"\n"
        for target, archive in packages:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive)
        (root / "addons.xml").write_bytes(content)
        (root / "addons.xml.sha256").write_text(
            hashlib.sha256(content).hexdigest(), encoding="ascii"
        )
        for update in updates:
            print("Updated " + update)
    else:
        print("All add-ons are up to date; no files changed.")
    return updates


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        metavar="ID=PATH",
        help="Use a local source checkout instead of downloading it",
    )
    args = parser.parse_args()
    sources = dict(value.split("=", 1) for value in args.source)
    try:
        update_repository(args.root, sources)
    except (
        ValueError,
        OSError,
        KeyError,
        ET.ParseError,
        subprocess.SubprocessError,
    ) as error:
        parser.exit(1, "Update failed: " + str(error) + "\n")


if __name__ == "__main__":
    main()
