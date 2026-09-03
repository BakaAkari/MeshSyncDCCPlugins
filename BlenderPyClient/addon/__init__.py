# Unity Mesh Sync — pure-Python Blender Live Link (MeshSync protocol v124)
#
# Sends the Blender scene to a running Unity MeshSyncServer over HTTP.
# Package layout:
#   addon/  — Blender addon (this package); imports the engine-agnostic meshsync/.
#   meshsync/ — pure-python wire protocol + client (no bpy imports).

import sys
from pathlib import Path

bl_info = {
    "name": "Unity Mesh Sync",
    "author": "Baka Akari (fork of unity3d-jp MeshSync; pure-Python rewrite)",
    "version": (0, 1, 0),
    "blender": (5, 2, 0),
    "location": "View3D > Sidebar > MeshSync",
    "description": "Live-sync Blender meshes/transforms/cameras/lights to Unity MeshSyncServer",
    "category": "Import-Export",
}

# Expose the engine-agnostic meshsync package to this addon's imports. The package
# lives in the addon root next to addon/, so add the parent of addon/ to sys.path.
_ADDON_DIR = Path(__file__).resolve().parent          # .../BlenderPyClient/addon
_PKG_ROOT = _ADDON_DIR.parent                         # .../BlenderPyClient
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from . import operators, ui  # noqa: E402


def register():
    operators.register()
    ui.register()


def unregister():
    ui.unregister()
    operators.unregister()
