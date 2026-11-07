"""Client for OpenAI-compatible chat endpoints. Pure Python (urllib only).

Nothing here runs unless the user enables the assistant and sends a message.
There is no built-in or simulated model: every answer comes from the endpoint
the user configured.
"""
from __future__ import annotations

import ipaddress
import json
import urllib.error
import urllib.request
from urllib.parse import urlsplit

SYSTEM_PROMPT = "You are NEVEX AI, a concise assistant inside a web browser."


class AIError(Exception):
    """An error with a message that is safe to show to the user."""


def _is_private_host(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private


def normalize_endpoint(endpoint: str) -> str:
    ep = (endpoint or "").strip().rstrip("/")
    if not ep:
        raise AIError("No API endpoint configured. Set one in Settings.")
    parts = urlsplit(ep)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise AIError("API endpoint must be an http(s) URL, e.g. https://host/v1")
    if parts.scheme == "http" and not _is_private_host(parts.hostname):
        raise AIError(
            "Refusing to send requests over plain http to a non-local host. Use https."
        )
    return ep


def chat_url(endpoint: str) -> str:
    ep = normalize_endpoint(endpoint)
    return ep if ep.endswith("/chat/completions") else ep + "/chat/completions"


def models_url(endpoint: str) -> str:
    ep = normalize_endpoint(endpoint)
    if ep.endswith("/chat/completions"):
        ep = ep[: -len("/chat/completions")]
    return ep + "/models"


def _headers(api_key: str) -> dict:
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if api_key:
        h["Authorization"] = "Bearer " + api_key
    return h


def _error_from_http(e: urllib.error.HTTPError) -> AIError:
    detail = ""
    try:
        body = e.read(4000).decode("utf-8", "replace")
        try:
            j = json.loads(body)
            err = j.get("error", j) if isinstance(j, dict) else j
            detail = err.get("message", "") if isinstance(err, dict) else str(err)
        except ValueError:
            detail = body.strip()[:300]
    except Exception:
        pass
    hint = {401: " (check your API key)", 403: " (access denied)", 404: " (check endpoint and model name)",
            429: " (rate limited)"}.get(e.code, "")
    return AIError("HTTP %d%s%s" % (e.code, hint, (": " + detail) if detail else ""))


def _open(req, timeout):
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        raise _error_from_http(e) from None
    except urllib.error.URLError as e:
        raise AIError("Cannot reach the API server: %s" % (getattr(e, "reason", e),)) from None
    except (TimeoutError, OSError) as e:
        raise AIError("Network error: %s" % e) from None


def list_models(endpoint: str, api_key: str, timeout: float = 15.0) -> list:
    req = urllib.request.Request(models_url(endpoint), headers=_headers(api_key))
    with _open(req, timeout) as resp:
        try:
            data = json.loads(resp.read(2_000_000).decode("utf-8", "replace"))
        except ValueError:
            raise AIError("The server returned something that is not JSON for /models.") from None
    items = data.get("data", data) if isinstance(data, dict) else data
    ids = sorted({m["id"] for m in items if isinstance(m, dict) and isinstance(m.get("id"), str)})
    if not ids:
        raise AIError("The server did not list any models.")
    return ids


def stream_chat(endpoint, api_key, model, messages, timeout=60.0, cancel=None):
    """Yield text chunks of the assistant reply. Raises AIError on failure.

    `cancel` may be a threading.Event; set it to stop early.
    """
    if not (model or "").strip():
        raise AIError("No model selected. Choose one in Settings.")
    payload = json.dumps({"model": model, "messages": messages, "stream": True}).encode("utf-8")
    req = urllib.request.Request(chat_url(endpoint), data=payload, headers=_headers(api_key), method="POST")
    with _open(req, timeout) as resp:
        ctype = resp.headers.get("Content-Type", "")
        if "event-stream" not in ctype:  # server ignored stream=true
            try:
                data = json.loads(resp.read(4_000_000).decode("utf-8", "replace"))
                text = data["choices"][0]["message"]["content"]
            except (ValueError, KeyError, IndexError, TypeError):
                raise AIError("Unexpected response format from the server.") from None
            if text:
                yield text
            return
        got_any = False
        while True:
            if cancel is not None and cancel.is_set():
                return
            try:
                raw = resp.readline()
            except (TimeoutError, OSError) as e:
                raise AIError("Connection lost while streaming: %s" % e) from None
            if not raw:
                break
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            chunk = line[5:].strip()
            if chunk == "[DONE]":
                break
            try:
                obj = json.loads(chunk)
            except ValueError:
                continue
            if isinstance(obj, dict) and "error" in obj:
                err = obj["error"]
                raise AIError(str(err.get("message", err)) if isinstance(err, dict) else str(err))
            try:
                piece = obj["choices"][0].get("delta", {}).get("content")
            except (KeyError, IndexError, AttributeError, TypeError):
                piece = None
            if piece:
                got_any = True
                yield piece
        if not got_any and not (cancel is not None and cancel.is_set()):
            raise AIError("The server returned an empty reply.")
