"""Blender addon operators: manual sync, connection test, auto-sync timer.

Sync logic lives in sync_scene(context) so the manual operator and the auto-sync
timer share one code path.
"""

import bpy

from .meshsync import protocol as P
from .meshsync.client import DEFAULT_PORT, MeshSyncClient, MeshSyncClientError

from .blender_exporter import export_scene, scan_paths

# Session id is generated ONCE per addon lifetime and reused by every sync —
# matching the upstream C++ DCC clients (AsyncSceneSender keeps one session_id
# for the whole process). Unity's CheckForNewSession pops a "A new session
# started" dialog whenever the id changes; generating a fresh id per sync
# made auto-sync spam that dialog every tick.
_session_id = P.new_session_id()

# Paths successfully synced to the server since addon load. Diffed against each
# export to detect Blender-side deletions and push DeleteMessages — the C++
# client does the same via depsgraph dirty tracking + its ObjectRecord table.
_synced_paths: set = set()

# Incremental-sync dirty set: hierarchy paths marked changed by the depsgraph
# handler. Auto-sync drains this set each tick (full serialization only for
# dirty objects + their ancestors); manual Sync always sends the full scene.
# None = "everything dirty" (initial state / fallback), matching the C++
# client's dirty_all behaviour.
_dirty_paths = None  # None | set[str]


def _mark_dirty(paths) -> None:
    global _dirty_paths
    if _dirty_paths is None:
        return  # already all-dirty; nothing to add
    _dirty_paths.update(paths)


def _depsgraph_post(scene, depsgraph=None):
    """bpy.app.handlers.depsgraph_update_post — collect changed objects.
    Same trigger the C++ client uses (onDepsgraphUpdatedPost)."""
    if depsgraph is None:
        return
    from .blender_exporter import _hierarchy_path
    paths = []
    for upd in depsgraph.updates:
        obj = getattr(upd.id, "original", None) or upd.id
        if isinstance(obj, bpy.types.Object):
            paths.append(_hierarchy_path(obj))
    if paths:
        _mark_dirty(paths)


def _bake_modifiers(context) -> bool:
    return bool(getattr(context.scene, "meshsync_bake_modifiers", False))


def get_server(context) -> "tuple[str, int]":
    scene = context.scene
    host = getattr(scene, "meshsync_host", "127.0.0.1") or "127.0.0.1"
    port = int(getattr(scene, "meshsync_port", DEFAULT_PORT) or DEFAULT_PORT)
    return host, port


def sync_scene(context, host: str = "", port: int = 0, incremental: bool = False) -> str:
    """Run one sync pass. Returns a human-readable status string (no bpy.report).

    incremental=True (auto-sync): serialize only depsgraph-dirty objects (plus
    their ancestors) and drain the dirty set. Deletions are still caught every
    pass via a cheap full-scene path scan. Falls back to a full sync when the
    dirty set is in the all-dirty (None) state — first tick, handler gaps, or
    structural changes.
    """
    global _dirty_paths
    if not host:
        host, port = get_server(context)
    bake = _bake_modifiers(context)

    only = None
    if incremental and _dirty_paths is not None:
        # new objects (present now, never synced) must go out even if the
        # depsgraph handler missed them
        current_all = scan_paths(context)
        new_paths = current_all - _synced_paths
        only = set(_dirty_paths) | new_paths
        if not only and not (_synced_paths - current_all):
            return "no changes"
    else:
        current_all = scan_paths(context)

    scene = export_scene(context, bake_modifiers=bake, only_paths=only)
    deleted = sorted(_synced_paths - current_all)
    if not scene.entities and not deleted:
        if not _synced_paths:
            return "no supported objects to sync"
        return "no changes"
    client = MeshSyncClient(host, port)
    session = _session_id
    # Mirror AsyncSceneSender::send(): SceneBegin fence -> SetMessage(s) ->
    # SceneEnd fence, all sharing one session_id. Without the fences the
    # server's session gate (msServer.cpp processMessages) silently skips
    # every SetMessage — HTTP 200 but nothing applied.
    client.send_fence(P.FenceMessage(
        P.FenceMessage.FENCE_BEGIN, session_id=session,
        dcc_tool_name="Blender").serialize())
    if scene.entities:
        client.send_set(P.SetMessage(scene, session_id=session).serialize())
    # Blender-side deletions: paths we synced before that are gone now.
    if deleted:
        client.send_delete(P.DeleteMessage(paths=deleted, session_id=session).serialize())
    client.send_fence(P.FenceMessage(
        P.FenceMessage.FENCE_END, session_id=session).serialize())
    _synced_paths.clear()
    _synced_paths.update(current_all)
    if incremental:
        _dirty_paths = set()
    tag = " (incremental)" if only is not None else ""
    suffix = f", deleted {len(deleted)}" if deleted else ""
    return f"synced {len(scene.entities)} objects to {host}:{port}{tag}{suffix}"


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
    """Toggle auto-sync on/off. ON state is a bpy.app.timers callback (survives
    the operator returning, so Blender can close normally); OFF unregisters it."""

    bl_idname = "meshsync.auto_sync"
    bl_label = "Toggle Auto Sync"
    bl_description = "Continuously sync the scene on a timer while enabled"

    _tick_fn = None  # registered bpy.app.timers callback while running

    @classmethod
    def _is_running(cls) -> bool:
        return cls._tick_fn is not None

    @classmethod
    def _stop(cls) -> None:
        if cls._tick_fn is not None:
            try:
                bpy.app.timers.unregister(cls._tick_fn)
            except Exception:  # noqa: BLE001 — already unregistered
                pass
            cls._tick_fn = None

    @classmethod
    def _tick(cls):
        """Timer callback. Returning None unregisters; float = seconds to next."""
        try:
            context = bpy.context
            scene = getattr(context, "scene", None)
            if scene is None or not getattr(scene, "meshsync_auto_sync", False):
                cls._tick_fn = None
                return None
            try:
                scene.meshsync_last_status = sync_scene(context, incremental=True)
            except Exception as e:  # noqa: BLE001
                scene.meshsync_last_status = f"auto-sync error: {e}"
            return max(0.1, float(getattr(scene, "meshsync_interval", 1.0)))
        except Exception:  # noqa: BLE001 — never leak exceptions into the timer loop
            cls._tick_fn = None
            return None

    def execute(self, context):
        scene = context.scene
        if self._is_running():
            # toggle OFF
            self._stop()
            scene.meshsync_auto_sync = False
            scene.meshsync_last_status = "auto-sync stopped"
            return {"FINISHED"}
        # toggle ON
        scene.meshsync_auto_sync = True
        interval = max(0.1, float(getattr(scene, "meshsync_interval", 1.0)))
        self.__class__._tick_fn = self.__class__._tick
        bpy.app.timers.register(self.__class__._tick_fn, first_interval=interval)
        return {"FINISHED"}

    def cancel(self, context):
        # Blender is shutting down / operator cancelled: make sure the timer dies.
        self._stop()
        if getattr(context, "scene", None) is not None:
            context.scene.meshsync_auto_sync = False


_OPERATORS = (MESHSYNC_OT_sync, MESHSYNC_OT_test, MESHSYNC_OT_auto_sync)


def register():
    for op in _OPERATORS:
        bpy.utils.register_class(op)
    if _depsgraph_post not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_depsgraph_post)


def unregister():
    MESHSYNC_OT_auto_sync._stop()
    if _depsgraph_post in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_depsgraph_post)
    for op in reversed(_OPERATORS):
        bpy.utils.unregister_class(op)
