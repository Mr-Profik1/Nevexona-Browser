"""Tests the AI client against a local HTTP server that speaks the OpenAI wire format.

This server exists only in the tests; the application itself never fakes a reply.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from nevex import ai


class Handler(BaseHTTPRequestHandler):
    seen = {}

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/v1/models":
            self._send(200, {"data": [{"id": "m-b"}, {"id": "m-a"}]})
        else:
            self._send(404, {"error": {"message": "nope"}})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n))
        Handler.seen = {"auth": self.headers.get("Authorization"), "body": body, "path": self.path}
        model = body["model"]
        if model == "bad-key":
            return self._send(401, {"error": {"message": "Incorrect API key"}})
        if model == "plain":
            return self._send(200, {"choices": [{"message": {"content": "whole reply"}}]})
        if model == "empty":
            return self._send(200, b"data: [DONE]\n\n", "text/event-stream")
        lines = b""
        for piece in ("Hel", "lo", " wor", "ld"):
            lines += b"data: " + json.dumps({"choices": [{"delta": {"content": piece}}]}).encode() + b"\n\n"
        lines += b"data: [DONE]\n\n"
        self._send(200, lines, "text/event-stream")


@pytest.fixture(scope="module")
def server():
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield "http://127.0.0.1:%d/v1" % srv.server_port
    srv.shutdown()


MSGS = [{"role": "user", "content": "hi"}]


def test_streaming(server):
    out = list(ai.stream_chat(server, "sk-123", "m-a", MSGS))
    assert "".join(out) == "Hello world" and len(out) == 4
    assert Handler.seen["auth"] == "Bearer sk-123"
    assert Handler.seen["body"]["stream"] is True
    assert Handler.seen["path"] == "/v1/chat/completions"


def test_no_key_sends_no_auth_header(server):
    list(ai.stream_chat(server, "", "m-a", MSGS))
    assert Handler.seen["auth"] is None


def test_non_streaming_fallback(server):
    assert "".join(ai.stream_chat(server, "", "plain", MSGS)) == "whole reply"


def test_http_error_message(server):
    with pytest.raises(ai.AIError) as e:
        list(ai.stream_chat(server, "x", "bad-key", MSGS))
    assert "401" in str(e.value) and "Incorrect API key" in str(e.value)
    assert "x" != str(e.value)  # key is not echoed
    assert "sk-" not in str(e.value)


def test_empty_reply(server):
    with pytest.raises(ai.AIError):
        list(ai.stream_chat(server, "", "empty", MSGS))


def test_cancel(server):
    ev = __import__("threading").Event()
    ev.set()
    assert list(ai.stream_chat(server, "", "m-a", MSGS, cancel=ev)) == []


def test_list_models(server):
    assert ai.list_models(server, "") == ["m-a", "m-b"]


def test_config_errors():
    with pytest.raises(ai.AIError):
        list(ai.stream_chat("", "", "m", MSGS))
    with pytest.raises(ai.AIError):
        list(ai.stream_chat("http://127.0.0.1:1/v1", "", "", MSGS))
    with pytest.raises(ai.AIError):
        ai.normalize_endpoint("ftp://x/v1")
    with pytest.raises(ai.AIError) as e:
        ai.normalize_endpoint("http://api.example.com/v1")
    assert "https" in str(e.value)
    assert ai.normalize_endpoint("http://192.168.1.5:11434/v1/") == "http://192.168.1.5:11434/v1"
    assert ai.normalize_endpoint("https://api.example.com/v1") == "https://api.example.com/v1"


def test_connection_refused_is_clean_error():
    with pytest.raises(ai.AIError) as e:
        list(ai.stream_chat("http://127.0.0.1:9/v1", "", "m", MSGS, timeout=3))
    assert "Cannot reach" in str(e.value) or "Network error" in str(e.value)


def test_url_building():
    assert ai.chat_url("https://h/v1") == "https://h/v1/chat/completions"
    assert ai.chat_url("https://h/v1/chat/completions") == "https://h/v1/chat/completions"
    assert ai.models_url("https://h/v1/chat/completions") == "https://h/v1/models"
