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


class MESHSYNC_OT_auto_sync_toggle(bpy.types.Operator):
    bl_idname = "meshsync.auto_sync_toggle"
    bl_label = "Toggle Auto Sync"

    _timer = None
    _running = False

    @classmethod
    def poll(cls, context):
        return context.scene is not None

    def modal(self, context, event):
        if event.type == "TIMER":
            if not context.scene.meshsync_auto_sync:
                self.cancel(context)
                return {"CANCELLED"}
            from .operators import MESHSYNC_OT_sync
            # Fire sync (debounce handled by interval). Reuse the operator logic via
            # invoke-less direct call is complex; simplest: call operator's execute
            # through a new operator instance is not possible without context op;
            # instead we re-run the manual operator logic here.
            try:
                op = MESHSYNC_OT_sync()
                res = op.execute(context)
                context.scene.meshsync_last_status = (
                    "auto-sync ok" if res == {"FINISHED"} else "auto-sync skipped")
            except Exception as e:  # noqa: BLE001
                context.scene.meshsync_last_status = f"auto-sync error: {e}"
        return {"PASS_THROUGH"}

    def execute(self, context):
        if self._running:
            return {"CANCELLED"}
        self._running = True
        wm = context.window_manager
        self._timer = wm.event_timer_add(context.scene.meshsync_interval,
                                         window=context.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def cancel(self, context):
        if self._timer:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        self._running = False
        return {"CANCELLED"}


def register():
    from bpy.props import BoolProperty, FloatProperty, IntProperty, StringProperty

    from .meshsync.client import DEFAULT_PORT

    bpy.types.Scene.meshsync_host = StringProperty(
        name="Host", default="127.0.0.1")
    bpy.types.Scene.meshsync_port = IntProperty(
        name="Port", default=DEFAULT_PORT, min=1, max=65535)
    bpy.types.Scene.meshsync_auto_sync = BoolProperty(name="Auto Sync", default=False)
    bpy.types.Scene.meshsync_interval = FloatProperty(
        name="Interval (s)", default=1.0, min=0.1, max=60.0)
    bpy.types.Scene.meshsync_sync_meshes = BoolProperty(name="Meshes", default=True)
    bpy.types.Scene.meshsync_sync_cameras = BoolProperty(name="Cameras", default=True)
    bpy.types.Scene.meshsync_sync_lights = BoolProperty(name="Lights", default=True)
    bpy.types.Scene.meshsync_sync_empties = BoolProperty(name="Empties", default=True)
    bpy.types.Scene.meshsync_last_status = StringProperty(name="Last Sync", default="")

    bpy.utils.register_class(MESHSYNC_PT_panel)
    bpy.utils.register_class(MESHSYNC_OT_auto_sync_toggle)


def unregister():
    bpy.utils.unregister_class(MESHSYNC_OT_auto_sync_toggle)
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
