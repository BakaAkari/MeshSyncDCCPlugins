"""Tests for meshsync.client HTTP layer (no Blender, no real server required).

Locks in the /protocol_version handshake contract: MeshSyncServer answers with
plain text (std::to_string(msProtocolVersion) via serveText), and the body must
be read from the GET response — regression: _get() used to drain the body and
return the response object, so query_protocol_version always saw b''.
"""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from unity_mesh_sync.meshsync import client as C  # noqa: E402


class FakeResp:
    def __init__(self, status: int, body: bytes):
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body


class FakeConn:
    body = b""

    def __init__(self, *args, **kwargs):
        pass

    def request(self, method, path):
        pass

    def getresponse(self):
        return FakeResp(200, type(self).body)

    def close(self):
        pass


def run(body: bytes) -> int:
    FakeConn.body = body
    with patch.object(C.http.client, "HTTPConnection", FakeConn):
        return C.MeshSyncClient("127.0.0.1", 18080).query_protocol_version()


def test_protocol_version_text_response():
    # Real server behavior: serveText(std::to_string(msProtocolVersion))
    assert run(b"124") == 124


def test_protocol_version_raw_int32_fallback():
    import struct
    assert run(struct.pack("<i", 124)) == 124


def test_protocol_version_empty_body_raises():
    try:
        run(b"")
    except C.MeshSyncClientError:
        pass
    else:
        raise AssertionError("empty body must raise MeshSyncClientError")


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  PASS {name}")
    print(f"\n{sum(1 for n, f in globals().items() if n.startswith('test_') and callable(f))} passed")
