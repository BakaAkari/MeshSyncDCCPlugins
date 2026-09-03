#!/usr/bin/env python3
"""Build the installable Blender addon zip from unity_mesh_sync/.

Output: dist/UnityMeshSync-Blender-<version>.zip
  zip root: unity_mesh_sync/   (Blender installs a zip whose root dir contains __init__.py)
Version is read from bl_info in unity_mesh_sync/__init__.py (single source of truth).

Usage: python3 tools/build_addon_zip.py
"""

import ast
import zipfile
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parent.parent
ADDON_DIR = PKG_ROOT / "unity_mesh_sync"
DIST = PKG_ROOT / "dist"


def read_version() -> str:
    tree = ast.parse((ADDON_DIR / "__init__.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "bl_info" for t in node.targets
        ):
            info = ast.literal_eval(node.value)
            return ".".join(str(x) for x in info["version"])
    raise SystemExit("bl_info not found in unity_mesh_sync/__init__.py")


def main() -> None:
    version = read_version()
    DIST.mkdir(exist_ok=True)
    out = DIST / f"UnityMeshSync-Blender-{version}.zip"
    if out.exists():
        out.unlink()

    files = sorted(
        p for p in ADDON_DIR.rglob("*.py")
        if "__pycache__" not in p.parts
    )
    if not any(p.name == "__init__.py" and p.parent == ADDON_DIR for p in files):
        raise SystemExit("addon root __init__.py missing — aborting")

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            zf.write(p, p.relative_to(PKG_ROOT))
    print(f"built {out} ({len(files)} files, version {version})")
    for p in files:
        print(f"  {p.relative_to(PKG_ROOT)}")


if __name__ == "__main__":
    main()
