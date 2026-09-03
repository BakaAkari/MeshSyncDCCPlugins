"""End-to-end wire capture: run INSIDE Blender headless.

Spins a local HTTP listener posing as MeshSyncServer, performs the real addon
sync path (export_scene → SetMessage → MeshSyncClient.send_set), captures the
exact bytes on the wire, then:
  1. decodes them with the independent C++-layout reader (decode_set)
  2. re-computes the C++-side validation hash and compares with the header
  3. dumps a field-level trace so we can diff against C++ deserialize order

Usage:
  /Applications/Blender.app/Contents/MacOS/Blender --background --python tests/capture_wire.py
"""
import http.server
import struct
import sys
import threading
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PKG))
sys.path.insert(0, str(PKG / "tests"))

import bpy  # noqa: E402
from decode_set import read_message  # noqa: E402
from unity_mesh_sync.meshsync import protocol as P  # noqa: E402
from unity_mesh_sync.meshsync.client import MeshSyncClient  # noqa: E402

CAPTURED = {}


class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        # Blender's client sends "Expect: 100-continue"; BaseHTTPRequestHandler
        # handles it via handle_expect_100 (sends 100 Continue) by default.
        body = self.rfile.read(length)
        CAPTURED[self.path] = body
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"124")

    def log_message(self, *a):
        pass


def vhash_cpp(raw: bytes) -> int:
    """C++ vhash_impl<SharedVector<T>>: last 8 bytes of raw data if >=8 bytes."""
    if len(raw) >= 8:
        return struct.unpack("<Q", raw[-8:])[0]
    return 0


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_cube_add(size=2, location=(1, 2, 3))
    bpy.ops.object.light_add(type="POINT", location=(4, 5, 6))

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    from unity_mesh_sync.blender_exporter import export_scene
    scene = export_scene(bpy.context)
    print(f"[capture] entities: {[type(e).__name__ for e in scene.entities]}")

    client = MeshSyncClient("127.0.0.1", port)
    ver = client.query_protocol_version()
    print(f"[capture] handshake protocol version: {ver}")

    msg = P.SetMessage(scene, session_id=P.new_session_id())
    client.send_set(msg.serialize())
    server.shutdown()

    data = CAPTURED["set"]
    print(f"[capture] wire bytes: {len(data)}")

    # 1. independent decode
    decoded = read_message(data)
    ents = decoded["entities"]
    print(f"[capture] decode OK: {len(ents)} entities")
    for e in ents:
        tname = {P.ENTITY_MESH: "Mesh", P.ENTITY_CAMERA: "Camera",
                 P.ENTITY_LIGHT: "Light"}.get(e["type"], f"T{e['type']}")
        extra = ""
        if "points" in e:
            extra = f" pts={len(e['points'])} idx={len(e['indices'])}"
        print(f"  - {tname} path={e['path']} pos={e.get('position')}{extra}")

    # 2. recompute C++-side hash from the DECODED geometry and compare header
    header_hash = struct.unpack_from("<Q", data, 16)[0]
    # rebuild hash the C++ way: sum of vhash over each geometry SharedVector
    # (last 8 bytes of each emitted vector, in emit order) — replicate by
    # re-serializing the same scene and reading writer._hash.
    from unity_mesh_sync.meshsync.wire import Writer
    w = Writer()
    body = Writer()
    body.i32(scene.handedness)
    body.f32(scene.scale_factor)
    body.u32(len(scene.entities))
    for ent in scene.entities:
        ent.serialize(body)
    expected = body.hash()
    print(f"[capture] header hash={header_hash} recomputed={expected} "
          f"{'MATCH' if header_hash == expected else 'MISMATCH'}")

    # 3. byte-level header trace
    off = 0
    pv, sid, mid = struct.unpack_from("<iii", data, off); off += 12
    ts = struct.unpack_from("<Q", data, off)[0]; off += 8
    vh = struct.unpack_from("<Q", data, off)[0]; off += 8
    flags = struct.unpack_from("<I", data, off)[0]; off += 4
    handed, scale = struct.unpack_from("<if", data, off); off += 8
    count = struct.unpack_from("<I", data, off)[0]; off += 4
    print(f"[capture] header: pv={pv} sid={sid} mid={mid} hash={vh} "
          f"flags={bin(flags)} handed={handed} scale={scale} entities={count}")
    print("[capture] OK")


if __name__ == "__main__":
    main()
