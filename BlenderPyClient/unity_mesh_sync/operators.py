"""Blender addon operators: manual sync, connection test, auto-sync timer.

Sync logic lives in sync_scene(context) so the manual operator and the auto-sync
timer share one code path.
"""

import bpy

from .meshsync import protocol as P
from .meshsync.client import DEFAULT_PORT, MeshSyncClient, MeshSyncClientError

from .blender_exporter import export_scene


def get_server(context) -> "tuple[str, int]":
    scene = context.scene
    host = getattr(scene, "meshsync_host", "127.0.0.1") or "127.0.0.1"
    port = int(getattr(scene, "meshsync_port", DEFAULT_PORT) or DEFAULT_PORT)
    return host, port


def sync_scene(context, host: str = "", port: int = 0) -> str:
    """Run one sync pass. Returns a human-readable status string (no bpy.report)."""
    if not host:
        host, port = get_server(context)
    scene = export_scene(context)
    if not scene.entities:
        return "no supported objects to sync"
    client = MeshSyncClient(host, port)
    session = P.new_session_id()
    msg = P.SetMessage(scene, session_id=session)
    client.send_set(msg.serialize())
    return f"synced {len(scene.entities)} objects to {host}:{port}"


def test_connection(context) -> str:
    host, port = get_server(context)
    client = MeshSyncClient(host, port)
    version = client.query_protocol_version()
    return f"MeshSync server OK (protocol {version}) at {host}:{port}"


class MESHSYNC_OT_sync(bpy.types.Operator):
    bl_idname = "meshsync.sync"
    bl_label = "Sync Scene to Unity"
    bl_description = "Send the current Blender scene to the Unity MeshSyncServer"

    def execute(self, context):
        try:
            status = sync_scene(context)
        except MeshSyncClientError as e:
            self.report({"ERROR"}, f"MeshSync: {e}")
            return {"CANCELLED"}
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            self.report({"ERROR"}, f"MeshSync error: {e}")
            return {"CANCELLED"}
        if status.startswith("no"):
            self.report({"WARNING"}, "MeshSync: " + status)
            return {"CANCELLED"}
        context.scene.meshsync_last_status = status
        self.report({"INFO"}, "MeshSync: " + status)
        return {"FINISHED"}


class MESHSYNC_OT_test(bpy.types.Operator):
    bl_idname = "meshsync.test_connection"
    bl_label = "Test Connection"

    def execute(self, context):
        try:
            status = test_connection(context)
        except MeshSyncClientError as e:
            self.report({"ERROR"}, f"MeshSync connection failed: {e}")
            return {"CANCELLED"}
        except Exception as e:  # noqa: BLE001
            self.report({"ERROR"}, f"MeshSync connection failed: {e}")
            return {"CANCELLED"}
        context.scene.meshsync_last_status = status
        self.report({"INFO"}, "MeshSync: " + status)
        return {"FINISHED"}


class MESHSYNC_OT_auto_sync(bpy.types.Operator):
    bl_idname = "meshsync.auto_sync"
    bl_label = "Toggle Auto Sync"
    bl_description = "Continuously sync the scene on a timer while enabled"

    _timer = None

    def modal(self, context, event):
        if event.type == "TIMER":
            if not context.scene.meshsync_auto_sync:
                self.cancel(context)
                return {"CANCELLED"}
            try:
                status = sync_scene(context)
                context.scene.meshsync_last_status = status
            except Exception as e:  # noqa: BLE001
                context.scene.meshsync_last_status = f"auto-sync error: {e}"
        return {"PASS_THROUGH"}

    def execute(self, context):
        wm = context.window_manager
        if self._timer is not None:
            return {"CANCELLED"}
        interval = max(0.1, float(getattr(context.scene, "meshsync_interval", 1.0)))
        self._timer = wm.event_timer_add(interval, window=context.window)
        wm.modal_handler_add(self)
        context.scene.meshsync_auto_sync = True
        return {"RUNNING_MODAL"}

    def cancel(self, context):
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        context.scene.meshsync_auto_sync = False


_OPERATORS = (MESHSYNC_OT_sync, MESHSYNC_OT_test, MESHSYNC_OT_auto_sync)


def register():
    for op in _OPERATORS:
        bpy.utils.register_class(op)


def unregister():
    for op in reversed(_OPERATORS):
        bpy.utils.unregister_class(op)
