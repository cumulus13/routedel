#!/usr/bin/env python3

# File: tests/test_notify.py
# Author: Hadi Cahyadi <cumulus13@gmail.com>
# Date: 2026-10-26
# Description: 
# License: MIT

import hashlib
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from routedel import notify


class _Ntfy(BaseHTTPRequestHandler):
    got = [] # noqa
    status = 200

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.got.append((self.path, dict(self.headers), body.decode()))
        self.send_response(_Ntfy.status)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *a):
        pass


def _ntfy_server():
    _Ntfy.got, _Ntfy.status = [], 200
    srv = HTTPServer(("127.0.0.1", 0), _Ntfy)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _gntp_server(password="", reply_ok=True):
    """Fake GNTP server: records requests, optionally verifies the key hash."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    seen = []

    def run():
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                return
            buf = b""
            while b"\r\n\r\n" not in buf or (buf.count(b"\r\n\r\n") < 2 and b"REGISTER" in buf.split(b"\r\n")[0]):
                d = c.recv(4096)
                if not d:
                    break
                buf += d
            text = buf.decode()
            first = text.split("\r\n")[0]
            auth_ok = True
            if password:
                tok = first.split()[-1]  # SHA256:HASH.SALT
                _algo, rest = tok.split(":")
                h, salt = rest.split(".")
                key = hashlib.sha256(password.encode() + bytes.fromhex(salt)).digest()
                auth_ok = hashlib.sha256(key).hexdigest().upper() == h
            seen.append((first, text, auth_ok))
            kind = "-OK" if (reply_ok and auth_ok) else "-ERROR"
            c.sendall(f"GNTP/1.0 {kind} NONE\r\nResponse-Action: X\r\n\r\n".encode())
            c.close()

    threading.Thread(target=run, daemon=True).start()
    return srv, seen


def test_ntfy_url_headers_auth():
    srv = _ntfy_server()
    base = f"http://127.0.0.1:{srv.server_port}"
    notify._ntfy_send({"url": base, "topic": "t1", "token": "tk_abc"}, "T", "hello", "error")
    path, h, body = _Ntfy.got[0]
    assert path == "/t1" and body == "hello"
    assert h["Authorization"] == "Bearer tk_abc" and h["Priority"] == "5" and h["Title"] == "T"
    notify._ntfy_send({"url": base + "/t2", "user": "u", "password": "p"}, "T", "x", "info")
    assert _Ntfy.got[1][0] == "/t2" and _Ntfy.got[1][1]["Authorization"].startswith("Basic ")
    srv.shutdown()


def test_ntfy_http_error_raises():
    srv = _ntfy_server()
    _Ntfy.status = 403
    try:
        notify._ntfy_send({"url": f"http://127.0.0.1:{srv.server_port}", "topic": "t"}, "T", "x", "info")
        assert False, "should raise"
    except Exception as e: # noqa
        assert "403" in str(e)
    srv.shutdown()


def test_gntp_no_password_register_and_notify():
    srv, seen = _gntp_server()
    notify._gntp_send({"host": "127.0.0.1", "port": srv.getsockname()[1]}, "Title", "line1\nline2", "warning")
    assert [s[0] for s in seen] == ["GNTP/1.0 REGISTER NONE", "GNTP/1.0 NOTIFY NONE"]
    assert "Notification-Text: line1; line2" in seen[1][1]
    assert "Notification-Priority: 1" in seen[1][1]
    assert "Application-Name: routedel" in seen[0][1]
    srv.close()


def test_gntp_password_hash_valid():
    srv, seen = _gntp_server(password="secret")
    notify._gntp_send({"host": "127.0.0.1", "port": srv.getsockname()[1], "password": "secret"}, "T", "m", "info")
    assert len(seen) == 2 and all(s[2] for s in seen)
    srv.close()


def test_gntp_error_response_raises():
    srv, _ = _gntp_server(password="right")
    try:
        notify._gntp_send({"host": "127.0.0.1", "port": srv.getsockname()[1], "password": "wrong"}, "T", "m", "info")
        assert False, "should raise"
    except RuntimeError as e:
        assert "ERROR" in str(e)
    srv.close()


def test_multi_server_one_fails_others_succeed():
    ntfy = _ntfy_server()
    g1, seen1 = _gntp_server()
    g2, seen2 = _gntp_server()
    n = notify.Notifier(
        [{"url": f"http://127.0.0.1:{ntfy.server_port}", "topic": "a"},
         {"url": "http://127.0.0.1:1", "topic": "dead", "timeout": 1}],
        [{"host": "127.0.0.1", "port": g1.getsockname()[1]},
         {"host": "127.0.0.1", "port": g2.getsockname()[1]},
         {"host": "127.0.0.1", "port": 1, "timeout": 1}])
    assert len(n.targets) == 5 and n
    n.send("multi", "info")
    assert len(_Ntfy.got) == 1 and len(seen1) == 2 and len(seen2) == 2
    ntfy.shutdown()
    g1.close()
    g2.close()


def test_empty_notifier_falsy_and_noop():
    n = notify.Notifier([], [])
    assert not n
    n.send("nothing")


def test_build_notifier_cli_and_config(tmp_path):
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"ntfy": [{"url": "https://a", "topic": "x"}], "growl": [{"host": "h1"}]}))
    n = notify.build_notifier(config=str(cfg), ntfy_urls=["https://ntfy.sh/my-topic"],
                              growl_hosts=["h2:9999", "h3"])
    kinds = [(k, c.get("url") or c["host"], c.get("topic"), c.get("port")) for k, c in n.targets]
    assert ("ntfy", "https://a", "x", None) in kinds
    assert ("ntfy", "https://ntfy.sh", "my-topic", None) in kinds
    assert ("growl", "h2", None, 9999) in kinds and ("growl", "h3", None, 23053) in kinds
    assert not notify.build_notifier(no_notify=True, config=str(cfg))
