from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import api_verify
import pytest


class _StubHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return

    def do_GET(self) -> None:
        if self.path == "/health":
            body = json.dumps({"status": "ok"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/items?page=200":
            body = json.dumps({"page": 200}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/protected":
            self.send_response(403)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"forbidden")
        elif self.path == "/binary":
            data = bytes([0x89, 0x50, 0x4E, 0x47, 0xFF, 0xFE, 0x00, 0x01])
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_response(404)
            self.end_headers()

    def do_HEAD(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()


@pytest.fixture(scope="module")
def stub_server_url():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    server.server_close()


def test_parse_expected_statuses() -> None:
    assert api_verify.parse_expected_statuses("200, 403, 999, abc") == {200, 403}
    assert api_verify.parse_expected_statuses("") is None
    assert api_verify.parse_expected_statuses(None) is None


def test_split_url_and_expected_handles_inline_status_and_query_strings() -> None:
    assert api_verify.split_url_and_expected("http://localhost:8000/me=403", None) == (
        "http://localhost:8000/me",
        {403},
    )
    assert api_verify.split_url_and_expected("http://localhost:8000/me=401,403", None) == (
        "http://localhost:8000/me",
        {401, 403},
    )
    # Regression: numeric query params must NOT be stripped as inline statuses
    assert api_verify.split_url_and_expected("http://localhost:8000/items?page=200", None) == (
        "http://localhost:8000/items?page=200",
        None,
    )


def test_probe_endpoint_live_curl_json_binary_head_and_status(stub_server_url: str) -> None:
    health = api_verify.probe_endpoint(f"{stub_server_url}/health")
    assert health["ok"] is True
    assert health["status_code"] == 200
    assert health["is_json"] is True
    assert health["is_binary"] is False

    query = api_verify.probe_endpoint(f"{stub_server_url}/items?page=200")
    assert query["ok"] is True
    assert query["url"].endswith("/items?page=200")

    protected = api_verify.probe_endpoint(f"{stub_server_url}/protected=403")
    assert protected["ok"] is True
    assert protected["status_code"] == 403
    assert protected["expected_statuses"] == [403]

    binary = api_verify.probe_endpoint(f"{stub_server_url}/binary")
    assert binary["ok"] is True
    assert binary["is_binary"] is True
    assert binary["body_bytes"] == 8

    head = api_verify.probe_endpoint(f"{stub_server_url}/health", method="HEAD")
    assert head["ok"] is True
    assert head["status_code"] == 200


def test_main_exit_code_reflects_failures(stub_server_url: str, capsys) -> None:
    assert api_verify.main([f"{stub_server_url}/health", f"{stub_server_url}/protected=403"]) == 0
    results = json.loads(capsys.readouterr().out)
    assert len(results) == 2

    assert api_verify.main([f"{stub_server_url}/missing"]) == 1
