"""meshsync.client — HTTP transport for the MeshSync Unity server.

Matches msClient.cpp behavior: POST /set, /delete, /fence with
application/octet-stream bodies; GET /protocol_version for handshake.
Default Unity MeshSyncServer port is 8080.
"""

from __future__ import annotations

import http.client
import struct

DEFAULT_PORT = 18080
PROTOCOL_VERSION = 124


class MeshSyncClientError(RuntimeError):
    pass


class MeshSyncClient:
    def __init__(self, host: str = "127.0.0.1", port: int = DEFAULT_PORT,
                 timeout: float = 10.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.session_id = -1

    # -- low-level --------------------------------------------------------
    def _post(self, path: str, body: bytes) -> http.client.HTTPResponse:
        conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        try:
            conn.putrequest("POST", path)
            conn.putheader("Content-Type", "application/octet-stream")
            conn.putheader("Content-Length", str(len(body)))
            conn.putheader("Expect", "100-continue")
            conn.endheaders()
            conn.send(body)
            resp = conn.getresponse()
            resp.read()  # drain
            return resp
        finally:
            conn.close()

    def _get(self, path: str) -> "tuple[int, bytes]":
        conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        try:
            conn.request("GET", path)
            resp = conn.getresponse()
            body = resp.read()
            return resp.status, body
        finally:
            conn.close()

    # -- protocol version handshake ---------------------------------------
    def query_protocol_version(self) -> int:
        """GET /protocol_version — the C++ client uses this as a connectivity probe
        (Client::sync → Server::serveQuery with QueryType::ProtocolVersion)."""
        status, data = self._get("/protocol_version")
        if status != 200:
            raise MeshSyncClientError(f"protocol_version probe failed: HTTP {status}")
        # Server replies with plain text (std::to_string(msProtocolVersion) →
        # serveText), e.g. b"124". Accept raw int32 too for robustness.
        try:
            return int(data.decode().strip())
        except Exception:
            pass
        if len(data) >= 4:
            return struct.unpack("<i", data[:4])[0]
        raise MeshSyncClientError(f"unparseable protocol_version response: {data!r}")

    # -- messages ---------------------------------------------------------
    def send_set(self, body: bytes) -> None:
        resp = self._post("set", body)
        if resp.status != 200:
            raise MeshSyncClientError(f"set failed: HTTP {resp.status}")

    def send_fence(self, body: bytes) -> None:
        resp = self._post("fence", body)
        if resp.status != 200:
            raise MeshSyncClientError(f"fence failed: HTTP {resp.status}")

    def send_delete(self, body: bytes) -> None:
        resp = self._post("delete", body)
        if resp.status != 200:
            raise MeshSyncClientError(f"delete failed: HTTP {resp.status}")
