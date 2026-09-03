"""Blender sidebar panel: MeshSync connection + manual sync + auto-sync toggle."""

import bpy


class MESHSYNC_PT_panel(bpy.types.Panel):
    bl_label = "Unity Mesh Sync"
    bl_idname = "MESHSYNC_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MeshSync"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        box = layout.box()
        box.label(text="Server", icon="WORLD_DATA")
        row = box.row()
        row.prop(scene, "meshsync_host", text="Host")
        row = box.row()
        row.prop(scene, "meshsync_port", text="Port")
        box.operator("meshsync.test_connection", icon="WORLD")

        box = layout.box()
        box.label(text="Sync", icon="MESH_DATA")
        box.operator("meshsync.sync", icon="PLAY")
        if getattr(scene, "meshsync_auto_sync", False):
            box.operator("meshsync.auto_sync", icon="PAUSE", text="Stop Auto Sync")
            box.prop(scene, "meshsync_interval", text="Interval (s)")
        else:
            box.operator("meshsync.auto_sync", icon="PLAY", text="Start Auto Sync")

        box = layout.box()
        box.label(text="Options", icon="PREFERENCES")
        col = box.column()
        col.prop(scene, "meshsync_sync_meshes")
        col.prop(scene, "meshsync_sync_cameras")
        col.prop(scene, "meshsync_sync_lights")
        col.prop(scene, "meshsync_sync_empties")

        if getattr(scene, "meshsync_last_status", ""):
            box = layout.box()
            box.label(text="Last sync", icon="INFO")
            box.label(text=scene.meshsync_last_status)


def register():
    from bpy.props import BoolProperty, FloatProperty, IntProperty, StringProperty

    from .meshsync.client import DEFAULT_PORT

    bpy.types.Scene.meshsync_host = StringProperty(
        name="Host", default="127.0.0.1")
    bpy.types.Scene.meshsync_port = IntProperty(
        name="Port", default=DEFAULT_PORT, min=1, max=65535)
    bpy.types.Scene.meshsync_auto_sync = BoolProperty(name="Auto Sync", default=False)
    bpy.types.Scene.meshsync_interval = FloatProperty(
        name="Interval (s)", default=0.25, min=0.02, max=60.0,
        description="Auto-sync period. Blender-side send costs ~1ms for small "
                    "scenes (~33ms for 100 objects/10k verts); Unity applies "
                    "messages per editor tick and coalesces bursts, so ~0.05s "
                    "(20Hz) is a practical floor for live-viewport use.")
    bpy.types.Scene.meshsync_sync_meshes = BoolProperty(name="Meshes", default=True)
    bpy.types.Scene.meshsync_sync_cameras = BoolProperty(name="Cameras", default=True)
    bpy.types.Scene.meshsync_sync_lights = BoolProperty(name="Lights", default=True)
    bpy.types.Scene.meshsync_sync_empties = BoolProperty(name="Empties", default=True)
    bpy.types.Scene.meshsync_last_status = StringProperty(name="Last Sync", default="")

    bpy.utils.register_class(MESHSYNC_PT_panel)


def unregister():
    # Kill any running auto-sync timer first — a live timer callback referencing
    # unregistered Scene properties would error every tick after disable/reload.
    from .operators import MESHSYNC_OT_auto_sync
    MESHSYNC_OT_auto_sync._stop()

    bpy.utils.unregister_class(MESHSYNC_PT_panel)

    del bpy.types.Scene.meshsync_host
    del bpy.types.Scene.meshsync_port
    del bpy.types.Scene.meshsync_auto_sync
    del bpy.types.Scene.meshsync_interval
    del bpy.types.Scene.meshsync_sync_meshes
    del bpy.types.Scene.meshsync_sync_cameras
    del bpy.types.Scene.meshsync_sync_lights
    del bpy.types.Scene.meshsync_sync_empties
    del bpy.types.Scene.meshsync_last_status
