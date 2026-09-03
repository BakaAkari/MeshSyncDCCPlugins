# Unity Mesh Sync — pure-Python Blender Live Link (MeshSync protocol v124)
#
# Sends the Blender scene to a running Unity MeshSyncServer over HTTP.
# Package layout (this directory is the installable addon root):
#   unity_mesh_sync/           — Blender addon package (this package)
#   unity_mesh_sync/meshsync/  — pure-python wire protocol + client (no bpy imports)

bl_info = {
    "name": "Unity Mesh Sync",
    "author": "Baka Akari (fork of unity3d-jp MeshSync; pure-Python rewrite)",
    "version": (0, 2, 2),
    "blender": (5, 2, 0),
    "location": "View3D > Sidebar > MeshSync",
    "description": "Live-sync Blender meshes/transforms/cameras/lights to Unity MeshSyncServer",
    "category": "Import-Export",
}

# NOTE: operators/ui are imported lazily inside register() so that the pure-Python
# subpackage (unity_mesh_sync.meshsync) stays importable without bpy — the wire
# tests and headless export chain rely on this. bl_info must stay top-level.


def register():
    from . import operators, ui
    operators.register()
    ui.register()


def unregister():
    from . import operators, ui
    ui.unregister()
    operators.unregister()
