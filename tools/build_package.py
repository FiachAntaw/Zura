"""Build dist/ZortraxM-<version>.curapackage for drag-and-drop install into Cura.

Run: python3 tools/build_package.py
Drag the file onto Cura's window (or open it from File > Open), accept, and restart Cura.
"""
import json
import os
import zipfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PLUGIN = os.path.join(ROOT, "plugins", "ZortraxM")
SKIP_DIRS = {"__pycache__"}


def main():
    with open(os.path.join(PLUGIN, "plugin.json")) as f:
        meta = json.load(f)
    version = meta["version"]
    package = {
        "package_id": "ZortraxM",
        "package_type": "plugin",
        "display_name": "Zortrax M-series (Zura)",
        "description": meta["description"],
        "package_version": version,
        "sdk_version": meta["supported_sdk_versions"][-1],
        "sdk_version_semver": meta["supported_sdk_versions"][-1],
        "author": {"author_id": "Zura", "display_name": meta["author"]},
        "tags": ["printer", "Zortrax"],
        "website": "",
    }
    out_dir = os.path.join(ROOT, "dist")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"ZortraxM-{version}.curapackage")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("package.json", json.dumps(package, indent=4))
        for dirpath, dirnames, filenames in os.walk(PLUGIN):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
            for name in sorted(filenames):
                if name.endswith((".pyc", ".DS_Store")):
                    continue
                path = os.path.join(dirpath, name)
                rel = os.path.relpath(path, PLUGIN)
                z.write(path, os.path.join("files", "plugins", "ZortraxM", rel))
    print(f"{out}: {os.path.getsize(out) / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
