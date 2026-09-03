"""meshsync.wire — binary writer for the MeshSync wire protocol (version 124).

Encoding rules reverse-engineered from the C++ msFoundation.h implementation:
- little-endian
- 4-byte alignment: bool is 1 byte padded to 4; strings are len+bytes padded to 4
  by their length; SharedVector arrays are count+raw bytes padded to 4.
- strings: uint32 len + bytes + zero padding to 4
- vhash (used by Scene validation_hash) = for each SharedVector of >=8 bytes of raw
  data, the LAST 8 bytes interpreted as uint64 LE, summed over all geometry attrs.

The Writer tracks the C++ vhash accumulator automatically so callers can emit
Scene.validation_hash without a second pass.
"""

import struct

PAD4 = b"\x00\x00\x00"
MASK64 = 0xFFFFFFFFFFFFFFFF


class Writer:
    """Accumulates bytes. Field order matters — call in the same order C++ does."""

    __slots__ = ("buf", "_hash")

    def __init__(self) -> None:
        self.buf = bytearray()
        self._hash = 0  # C++ vhash accumulator over geometry SharedVectors

    # --- raw primitives -------------------------------------------------
    def i8(self, v: int) -> None:
        self.buf += struct.pack("<b", v)

    def u8(self, v: int) -> None:
        self.buf += struct.pack("<B", v)

    def i16(self, v: int) -> None:
        self.buf += struct.pack("<h", v)

    def u16(self, v: int) -> None:
        self.buf += struct.pack("<H", v)

    def i32(self, v: int) -> None:
        self.buf += struct.pack("<i", v)

    def u32(self, v: int) -> None:
        self.buf += struct.pack("<I", v)

    def i64(self, v: int) -> None:
        self.buf += struct.pack("<q", v)

    def u64(self, v: int) -> None:
        self.buf += struct.pack("<Q", v & MASK64)

    def f32(self, v: float) -> None:
        self.buf += struct.pack("<f", v)

    def bool_(self, v: bool) -> None:
        """C++ bool: 1 byte, then pad to 4."""
        self.buf += b"\x01" if v else b"\x00"
        self.buf += PAD4  # 3 pad bytes (bool is 1 byte → always padded)

    def string(self, s: str) -> None:
        """std::string: uint32 len + utf-8 bytes + pad to 4."""
        data = s.encode("utf-8")
        self.u32(len(data))
        self.buf += data
        rem = len(data) % 4
        if rem:
            self.buf += PAD4[: 4 - rem]

    # --- math types -----------------------------------------------------
    def float2(self, x: float, y: float) -> None:
        self.buf += struct.pack("<ff", x, y)

    def float3(self, x: float, y: float, z: float) -> None:
        self.buf += struct.pack("<fff", x, y, z)

    def float4(self, x: float, y: float, z: float, w: float) -> None:
        self.buf += struct.pack("<ffff", x, y, z, w)

    def quat(self, x: float, y: float, z: float, w: float) -> None:
        """mu::quatf — stored x,y,z,w like float4 (16 bytes)."""
        self.buf += struct.pack("<ffff", x, y, z, w)

    def mat4(self, m) -> None:
        """mu::float4x4 — 16 floats, column-major C++ memory layout."""
        if len(m) != 16:
            raise ValueError("mat4 needs 16 floats")
        self.buf += struct.pack("<16f", *m)

    # --- SharedVector helpers -------------------------------------------
    def _shared_raw(self, raw: bytes) -> None:
        """Emit uint32 count(=len(raw)//item_size already known by caller? NO).

        Callers use the typed helpers below; this assumes raw already contains the
        count-prefix handled by them.
        """
        raise NotImplementedError

    @staticmethod
    def _vhash(raw: bytes) -> int:
        """vhash of one SharedVector payload (bytes AFTER the uint32 count):
        if len>=8 → last 8 bytes as uint64 LE, else 0."""
        if len(raw) >= 8:
            return struct.unpack("<Q", raw[-8:])[0]
        return 0

    def _emit_array(self, raw: bytes) -> None:
        self.buf += raw
        rem = len(raw) % 4
        if rem:
            self.buf += PAD4[: 4 - rem]

    def shared_vector_f3(self, items) -> None:
        """SharedVector<float3>: uint32 count + raw bytes; hash += tail 8 bytes."""
        raw = struct.pack("<%df" % (len(items) * 3), *[v for t in items for v in t])
        self.u32(len(items))
        self._emit_array(raw)
        self._hash = (self._hash + self._vhash(raw)) & MASK64

    def shared_vector_f4(self, items) -> None:
        raw = struct.pack("<%df" % (len(items) * 4), *[v for t in items for v in t])
        self.u32(len(items))
        self._emit_array(raw)
        self._hash = (self._hash + self._vhash(raw)) & MASK64

    def shared_vector_f2(self, items) -> None:
        raw = struct.pack("<%df" % (len(items) * 2), *[v for t in items for v in t])
        self.u32(len(items))
        self._emit_array(raw)
        self._hash = (self._hash + self._vhash(raw)) & MASK64

    def shared_vector_i32(self, items) -> None:
        raw = struct.pack("<%di" % len(items), *items)
        self.u32(len(items))
        self._emit_array(raw)
        self._hash = (self._hash + self._vhash(raw)) & MASK64

    def shared_vector_raw(self, item_fmt: str, items) -> None:
        """Generic SharedVector from pre-packed items. items is a bytes blob of the
        element payload; count = len(items)//struct.calcsize(item_fmt)."""
        n = struct.calcsize(item_fmt)
        if n == 0 or len(items) % n:
            raise ValueError("payload not a whole number of items")
        self.u32(len(items) // n)
        self._emit_array(items)
        self._hash = (self._hash + self._vhash(items)) & MASK64

    # --- totals ---------------------------------------------------------
    def hash(self) -> int:
        """Current vhash accumulator (validation hash contribution)."""
        return self._hash

    def bytes(self) -> bytes:
        return bytes(self.buf)
