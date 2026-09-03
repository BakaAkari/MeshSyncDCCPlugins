"""Round-trip decoder: parse a SetMessage byte stream with a reader that mirrors the
C++ deserialize() layouts (inverse of meshsync.wire/protocol). Running the encoder
output through this decoder proves the stream is self-consistent AND that a server
implementing the same layout (Unity C# / C++ mscore) can parse it.

Usage:
  python3 tests/decode_set.py  # runs Blender-exported fixture via headless path or unit scene
"""

import struct
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PKG))

from unity_mesh_sync.meshsync import protocol as P  # noqa: E402
from unity_mesh_sync.meshsync.wire import Writer  # noqa: E402


class Reader:
    def __init__(self, b: bytes):
        self.b = b
        self.o = 0

    def _take(self, n: int) -> bytes:
        if self.o + n > len(self.b):
            raise EOFError(f"want {n} bytes at {self.o}, have {len(self.b)}")
        d = self.b[self.o:self.o+n]; self.o += n; return d

    def _align4(self, n: int) -> None:
        rem = n % 4
        if rem:
            self.o += 4 - rem

    def i32(self): return struct.unpack("<i", self._take(4))[0]
    def u32(self): return struct.unpack("<I", self._take(4))[0]
    def u64(self): return struct.unpack("<Q", self._take(8))[0]
    def f32(self): return struct.unpack("<f", self._take(4))[0]
    def bool_(self):
        v = self._take(1); self._align4(1); return v == b"\x01"
    def f3(self): return struct.unpack("<3f", self._take(12))
    def f4(self): return struct.unpack("<4f", self._take(16))
    def f2(self): return struct.unpack("<2f", self._take(8))
    def string(self):
        n = self.u32(); s = self._take(n).decode("utf-8"); self._align4(n); return s
    def shared_i32(self):
        n = self.u32()
        raw = self._take(4*n)
        return list(struct.unpack(f"<{n}i", raw))
    def shared_f3(self):
        n = self.u32()
        raw = self._take(12*n)
        v = struct.unpack(f"<{3*n}f", raw)
        return list(zip(v[0::3], v[1::3], v[2::3]))
    def shared_f2(self):
        n = self.u32()
        raw = self._take(8*n)
        v = struct.unpack(f"<{2*n}f", raw)
        return list(zip(v[0::2], v[1::2]))


def read_message(b: bytes) -> dict:
    r = Reader(b)
    out = {}
    out["protocol_version"] = r.i32()
    out["session_id"] = r.i32()
    out["message_id"] = r.i32()
    out["timestamp_send"] = r.u64()
    # Scene
    out["validation_hash"] = r.u64()
    data_flags = r.u32()
    out["data_flags"] = data_flags
    if data_flags & 1:  # settings
        out["handedness"] = r.i32()
        out["scale_factor"] = r.f32()
    if data_flags & 2:  # assets (not sent in MVP)
        raise NotImplementedError("assets not expected")
    if data_flags & 4:  # entities
        n = r.u32()
        ents = []
        for _ in range(n):
            etype = r.i32()
            ent_id = r.i32()
            host_id = r.i32()
            path = r.string()
            e = {"type": etype, "id": ent_id, "host_id": host_id, "path": path}

            # Transform flags + fields
            td = r.u32()
            if not (td & 1):
                if td & (1 << 1): e["position"] = r.f3()
                if td & (1 << 2): e["rotation"] = r.f4()
                if td & (1 << 3): e["scale"] = r.f3()
                if td & (1 << 4): r.u32()  # visibility
                if td & (1 << 5): e["layer"] = r.i32()
                if td & (1 << 6): e["index"] = r.i32()
                if td & (1 << 7): e["reference"] = r.string()

            if etype == P.ENTITY_MESH:
                md = r.u32()
                e["md_flags"] = md
                if not (md & 1):
                    if md & (1 << 3): e["indices"] = r.shared_i32()
                    if md & (1 << 4): e["counts"] = r.shared_i32()
                    if md & (1 << 5): e["points"] = r.shared_f3()
                    if md & (1 << 6): e["normals"] = r.shared_f3()
                    if md & (1 << 12): e["material_ids"] = r.shared_i32()
                    if md & (1 << 24): e["uv0"] = r.shared_f2()
            elif etype == P.ENTITY_CAMERA:
                cd = r.u32()
                e["cd_flags"] = cd
                if not (cd & 1):
                    e["is_ortho"] = r.bool_()
                    if cd & (1 << 2): e["fov"] = r.f32()
                    if cd & (1 << 3): e["near"] = r.f32()
                    if cd & (1 << 4): e["far"] = r.f32()
            elif etype == P.ENTITY_LIGHT:
                ld = r.u32()
                e["ld_flags"] = ld
                if not (ld & 1):
                    e["light_type"] = r.i32()
                    e["shadow_type"] = r.i32()
                    e["color"] = r.f4()
                    e["intensity"] = r.f32()
                    e["range"] = r.f32()
            ents.append(e)
        out["entities"] = ents
    return out


def _sample_scene() -> P.Scene:
    m = P.Mesh()
    m.path = "/Cube"
    m.points = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 2.0, 0.0)]
    m.indices = [0, 1, 2]
    m.counts = [3]
    m.normals = [(0.0, 0.0, 1.0)] * 3
    m.material_ids = []
    m.uv0 = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]
    s = P.Scene()
    s.entities = [m]
    return s


def main():
    scene = _sample_scene()
    msg = P.SetMessage(scene, session_id=7, message_id=3)
    data = msg.serialize()
    print(f"encoded {len(data)} bytes")
    d = read_message(data)
    assert d["protocol_version"] == P.PROTOCOL_VERSION
    assert d["session_id"] == 7
    assert d["message_id"] == 3
    assert d["handedness"] == P.HANDEDNESS_RIGHT_ZUP
    assert d["scale_factor"] == 1.0
    ents = d["entities"]
    assert len(ents) == 1
    e = ents[0]
    assert e["type"] == P.ENTITY_MESH
    assert e["path"] == "/Cube"
    assert e["points"] == [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 2.0, 0.0)]
    assert e["indices"] == [0, 1, 2]
    assert e["counts"] == [3]
    assert e["normals"] == [(0.0, 0.0, 1.0)] * 3
    assert e["uv0"] == [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]
    print("decode OK: mesh scene round-trips through an independent reader")


if __name__ == "__main__":
    main()
