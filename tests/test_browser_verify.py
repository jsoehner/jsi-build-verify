from __future__ import annotations

import base64
import hashlib
import json
import socket
import struct
import threading

import browser_verify
import pytest


def _ws_send_server_frame(conn: socket.socket, payload: bytes, opcode: int = 1) -> None:
    header = bytearray([0x80 | opcode])
    length = len(payload)
    if length < 126:
        header.append(length)
    elif length < 65536:
        header.append(126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(127)
        header.extend(struct.pack("!Q", length))
    conn.sendall(bytes(header) + payload)


def _ws_recv_client_frame(conn: socket.socket) -> tuple[int, bytes]:
    def recv_exact(n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("closed")
            buf.extend(chunk)
        return bytes(buf)

    b1, b2 = recv_exact(2)
    opcode = b1 & 0x0F
    masked = (b2 & 0x80) != 0
    length = b2 & 0x7F
    if length == 126:
        length = struct.unpack("!H", recv_exact(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", recv_exact(8))[0]
    mask = recv_exact(4) if masked else b""
    data = recv_exact(length)
    if masked:
        data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    return opcode, data


def test_find_chrome_falls_back_to_macos_app(monkeypatch) -> None:
    monkeypatch.setattr(browser_verify.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        browser_verify.os.path,
        "isfile",
        lambda p: p == browser_verify.MACOS_CHROME_CANDIDATES[0],
    )
    monkeypatch.setattr(browser_verify.os, "access", lambda _p, _m: True)
    assert browser_verify.find_chrome() == browser_verify.MACOS_CHROME_CANDIDATES[0]


def test_find_chrome_raises_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(browser_verify.shutil, "which", lambda _name: None)
    monkeypatch.setattr(browser_verify.os.path, "isfile", lambda _p: False)
    with pytest.raises(FileNotFoundError):
        browser_verify.find_chrome()


def test_pick_free_port() -> None:
    port = browser_verify.pick_free_port()
    assert isinstance(port, int) and 1024 <= port <= 65535


def test_evaluate_events_and_compute_verdict() -> None:
    events = [
        {
            "method": "Network.responseReceived",
            "params": {"type": "Document", "response": {"url": "http://localhost:3000/", "status": 200}},
        },
        {
            "method": "Runtime.consoleAPICalled",
            "params": {"type": "error", "args": [{"value": "boom"}]},
        },
        {
            "method": "Runtime.exceptionThrown",
            "params": {"exceptionDetails": {"text": "Uncaught TypeError"}},
        },
    ]
    status, console_errors, exceptions = browser_verify.evaluate_events(events, "http://localhost:3000")
    assert status == 200
    assert console_errors == ["boom"]
    assert exceptions == ["Uncaught TypeError"]

    # Console errors fail by default, pass when allow_console_errors=True
    base = {
        "http_status": 200,
        "expect_text_found": True,
        "title": "App",
        "body_snippet": "Hello",
        "console_errors": ["boom"],
        "exceptions": [],
        "click_result": "CLICKED",
    }
    assert browser_verify.compute_verdict(base, allow_console_errors=False) is False
    assert browser_verify.compute_verdict(base, allow_console_errors=True) is True

    # Missing click selector must fail verdict
    missing_click = {**base, "console_errors": [], "click_result": [{"selector": "#x", "status": "NOT_FOUND"}]}
    assert browser_verify.compute_verdict(missing_click) is False


def test_slugify_and_capture_screenshot(tmp_path) -> None:
    assert browser_verify._slugify("#login-btn > span") == "login-btn-span"
    assert browser_verify._slugify("!!!") == "step"

    png_bytes = b"\x89PNG\r\n\x1a\nfake-png-data"
    calls: list[tuple[str, dict]] = []

    class _FakeClient:
        def send(self, method: str, params: dict | None = None) -> dict:
            calls.append((method, params or {}))
            return {"result": {"data": base64.b64encode(png_bytes).decode("ascii")}}

    out = tmp_path / "shots" / "00-initial.png"
    meta = browser_verify.capture_screenshot(_FakeClient(), out, step="initial", full_page=True)  # type: ignore[arg-type]
    assert meta == {"step": "initial", "path": str(out), "bytes": len(png_bytes)}
    assert out.read_bytes() == png_bytes
    assert calls == [("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True})]


def test_simple_cdp_client_loopback_handshake_ping_and_events() -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    received_pongs: list[bytes] = []

    def server_worker() -> None:
        conn, _ = srv.accept()
        with conn:
            req = conn.recv(4096).decode("ascii")
            key = [line.split(": ", 1)[1] for line in req.splitlines() if line.startswith("Sec-WebSocket-Key:")][0]
            accept = base64.b64encode(
                hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
            ).decode("ascii")
            conn.sendall(
                (
                    "HTTP/1.1 101 Switching Protocols\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
                ).encode("ascii")
            )
            opcode, data = _ws_recv_client_frame(conn)
            assert opcode == 1
            msg = json.loads(data.decode("utf-8"))
            # Send a ping first, then an async event, then the matching response
            _ws_send_server_frame(conn, b"ping-data", opcode=9)
            pong_op, pong_data = _ws_recv_client_frame(conn)
            assert pong_op == 10
            received_pongs.append(pong_data)
            _ws_send_server_frame(conn, json.dumps({"method": "Page.loadEventFired", "params": {}}).encode("utf-8"))
            _ws_send_server_frame(conn, json.dumps({"id": msg["id"], "result": {"ok": True}}).encode("utf-8"))

    t = threading.Thread(target=server_worker, daemon=True)
    t.start()
    try:
        client = browser_verify.SimpleCDPClient(f"ws://127.0.0.1:{port}/devtools/page/1", timeout=5.0)
        try:
            resp = client.send("Page.enable", timeout=5.0)
            assert resp == {"id": 1, "result": {"ok": True}}
            assert received_pongs == [b"ping-data"]
            assert any(ev.get("method") == "Page.loadEventFired" for ev in client.events)
        finally:
            client.close()
    finally:
        t.join(timeout=5.0)
        srv.close()
