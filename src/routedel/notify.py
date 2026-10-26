"""ntfy (HTTP) and Growl (GNTP 1.0) notifications. Stdlib only. Multiple servers, sent in parallel."""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import re
import socket
import sys
import threading
import urllib.request

from .config import load_config, parse_growl, split_ntfy_url

APP_NAME = "routedel"
HOST = socket.gethostname()
log = logging.getLogger(APP_NAME)


def _ntfy_send(cfg: dict, title: str, message: str, level: str):
    url = cfg["url"].rstrip("/")
    if cfg.get("topic"):
        url = f"{url}/{cfg['topic']}"
    headers = {
        "Title": title.encode("ascii", "replace").decode(),
        "Priority": {"info": "3", "warning": "4", "error": "5"}.get(level, "3"),
        "Tags": {"info": "information_source", "warning": "warning", "error": "rotating_light"}.get(level, ""),
    }
    if cfg.get("token"):
        headers["Authorization"] = f"Bearer {cfg['token']}"
    elif cfg.get("user"):
        cred = base64.b64encode(f"{cfg['user']}:{cfg.get('password', '')}".encode()).decode()
        headers["Authorization"] = f"Basic {cred}"
    req = urllib.request.Request(url, data=message.encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=cfg.get("timeout", 5)) as r:
        if r.status >= 300:
            raise RuntimeError(f"HTTP {r.status}")


def _gntp_header(msg_type: str, password: str, algo: str = "SHA256") -> str:
    if not password:
        return f"GNTP/1.0 {msg_type} NONE\r\n"
    salt = os.urandom(16)
    key = hashlib.new(algo.lower(), password.encode("utf-8") + salt).digest()
    key_hash = hashlib.new(algo.lower(), key).hexdigest().upper()
    return f"GNTP/1.0 {msg_type} NONE {algo}:{key_hash}.{salt.hex().upper()}\r\n"


def _gntp_roundtrip(host: str, port: int, payload: str, timeout: float):
    with socket.create_connection((host, port), timeout=timeout) as s:
        s.sendall(payload.encode("utf-8"))
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
    text = buf.decode("utf-8", "replace")
    if "-OK" not in text.split("\r\n", 1)[0]:
        raise RuntimeError(text.strip().replace("\r\n", " | ") or "empty response")


def _gntp_send(cfg: dict, title: str, message: str, level: str):
    host, port = cfg["host"], int(cfg.get("port", 23053))
    pw, timeout = cfg.get("password", ""), cfg.get("timeout", 5)
    one = lambda s: re.sub(r"[\r\n]+", "; ", str(s))  # GNTP values are single-line

    reg = (_gntp_header("REGISTER", pw)
           + f"Application-Name: {APP_NAME}\r\nNotifications-Count: 1\r\n\r\n"
           + "Notification-Name: route-event\r\nNotification-Display-Name: Route Event\r\n"
           + "Notification-Enabled: True\r\n\r\n")
    _gntp_roundtrip(host, port, reg, timeout)

    prio = {"info": 0, "warning": 1, "error": 2}.get(level, 0)
    note = (_gntp_header("NOTIFY", pw)
            + f"Application-Name: {APP_NAME}\r\nNotification-Name: route-event\r\n"
            + f"Notification-Title: {one(title)}\r\nNotification-Text: {one(message)}\r\n"
            + f"Notification-Priority: {prio}\r\n\r\n")
    _gntp_roundtrip(host, port, note, timeout)


class Notifier:
    def __init__(self, ntfy: list[dict], growl: list[dict]):
        self.targets: list[tuple[str, dict]] = [("ntfy", c) for c in ntfy] + [("growl", c) for c in growl]

    def __bool__(self):
        return bool(self.targets)

    @staticmethod
    def _one(kind: str, cfg: dict, title: str, msg: str, level: str, results: list | None = None) -> bool:
        label = cfg.get("url") if kind == "ntfy" else f"{cfg.get('host')}:{cfg.get('port', 23053)}"
        ok = True
        try:
            (_ntfy_send if kind == "ntfy" else _gntp_send)(cfg, title, msg, level)
            log.info("[%s] sent -> %s", kind, label)
        except Exception as e: # noqa
            ok = False
            log.error("[%s] failed -> %s: %s", kind, label, e)
        if results is not None:
            results.append(ok)
        return ok

    def send(self, message: str, level: str = "info", wait: bool = True, title: str | None = None) -> int:
        """Send to all targets in parallel. With wait=True returns the number of failed targets."""
        if not self.targets:
            return 0
        title = title or f"{APP_NAME}@{HOST}"
        results: list = []
        threads = [threading.Thread(target=self._one, args=(k, c, title, message, level, results), daemon=True)
                   for k, c in self.targets]
        for t in threads:
            t.start()
        if not wait:
            return 0
        for t in threads:
            t.join(timeout=15)
        return results.count(False) + (len(self.targets) - len(results))  # unfinished threads count as failed


def build_notifier(no_notify: bool = False, config: str | None = None,
                   ntfy_urls: list[str] | None = None, growl_hosts: list[str] | None = None) -> Notifier:
    if no_notify:
        return Notifier([], [])
    cfg = load_config(config)
    ntfy, growl = list(cfg.get("ntfy", [])), list(cfg.get("growl", []))
    for u in ntfy_urls or []:  # https://host/topic
        try:
            base, topic = split_ntfy_url(u)
            if not topic:
                raise ValueError(f"--ntfy needs a topic: https://host/TOPIC (got {u!r})")
        except ValueError as e:
            log.error("%s", e)
            sys.exit(1)
        ntfy.append({"url": base, "topic": topic})
    for g in growl_hosts or []:  # host[:port]
        try:
            host, port = parse_growl(g)
        except ValueError as e:
            log.error("%s", e)
            sys.exit(1)
        growl.append({"host": host, "port": port})
    return Notifier(ntfy, growl)
