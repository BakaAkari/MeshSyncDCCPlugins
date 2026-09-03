"""Headless smoke: run inside Blender 5.2 to export the default scene and serialize
a SetMessage. Prints protocol header, entity summary and byte counts.

Usage:
  /Applications/Blender.app/Contents/MacOS/Blender --background --python smoke_headless.py
"""

import struct
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent  # BlenderPyClient root
sys.path.insert(0, str(PKG))
sys.path.insert(0, str(PKG / "unity_mesh_sync"))

import bpy  # noqa: E402


def main():
    # Reset to a known scene with a mesh + camera + light
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 0))
    bpy.ops.object.camera_add(location=(5, -5, 5))
    bpy.ops.object.light_add(type="POINT", location=(3, 3, 3))

    from unity_mesh_sync.blender_exporter import export_scene
    from unity_mesh_sync.meshsync import protocol as P

    scene = export_scene(bpy.context)
    print(f"[smoke] exported {len(scene.entities)} entities:")
    for e in scene.entities:
        cls = type(e).__name__
        extra = ""
        if isinstance(e, P.Mesh):
            extra = (f" pts={len(e.points)} idx={len(e.indices)} "
                     f"counts={len(e.counts)} normals={len(e.normals)} uv0={len(e.uv0)}")
        print(f"  - {cls} path={e.path} pos={tuple(round(x,3) for x in e.position)}{extra}")

    msg = P.SetMessage(scene)
    data = msg.serialize()
    print(f"[smoke] SetMessage bytes={len(data)}")
    off = 0
    print(f"  protocol_version = {struct.unpack_from('<i', data, off)[0]}"); off += 4
    print(f"  session_id       = {struct.unpack_from('<i', data, off)[0]}"); off += 4
    print(f"  message_id       = {struct.unpack_from('<i', data, off)[0]}"); off += 4
    ts = struct.unpack_from('<Q', data, off)[0]; off += 8
    print(f"  timestamp_send   = {ts}")
    h = struct.unpack_from('<Q', data, off)[0]; off += 8
    print(f"  scene validation_hash = {h}")
    flags = struct.unpack_from('<I', data, off)[0]; off += 4
    print(f"  scene data_flags = {bin(flags)}")

    # Optional live probe: only send when a REAL MeshSyncServer is listening.
    # (Probe /protocol_version via HTTP — other services on the port will 404.)
    from unity_mesh_sync.meshsync.client import DEFAULT_PORT
    host, port = "127.0.0.1", DEFAULT_PORT
    try:
        from unity_mesh_sync.meshsync.client import MeshSyncClient, MeshSyncClientError
        client = MeshSyncClient(host, port)
        version = client.query_protocol_version()
        print(f"[smoke] Unity MeshSyncServer found (protocol {version}) → sending")
        client.send_set(data)
        print("[smoke] send_set → HTTP 200 OK")
    except MeshSyncClientError as e:
        print(f"[smoke] no MeshSyncServer on {host}:{port} — skipping live send: {e}")
    except Exception as e:  # noqa: BLE001
        print(f"[smoke] live send skipped (server not reachable): {e!r}")
    print("[smoke] OK")


if __name__ == "__main__":
    main()
