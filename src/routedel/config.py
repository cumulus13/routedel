"""Config file handling and the `routedel config ...` subcommands."""
from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from rchf import CustomRichHelpFormatter
from rich.console import Console
from rich.markup import escape
from rich.table import Table

log = logging.getLogger("routedel")
console = Console()

DEFAULT_GNTP_PORT = 23053
SECRET_KEYS = ("token", "password")
MASK = "********"
EMPTY: dict[str, list] = {"ntfy": [], "growl": []}
EXAMPLE: dict[str, list] = {
    "ntfy": [{"url": "https://ntfy.sh", "topic": "my-routes", "token": "tk_xxx"}],
    "growl": [{"host": "192.168.1.10", "port": DEFAULT_GNTP_PORT, "password": "secret"}],
}
ALLOWED = {
    "ntfy": {"url", "topic", "token", "user", "password", "timeout"},
    "growl": {"host", "port", "password", "timeout"},
}


# ───────────────────────────── paths ─────────────────────────────

def default_path() -> Path:
    return Path.home() / ".config" / "routedel" / "config.json"


def candidates(explicit: str | None = None) -> list[tuple[str, Path]]:
    """Lookup order; the first existing file wins."""
    out: list[tuple[str, Path]] = []
    if explicit:
        out.append(("--config", Path(explicit).expanduser()))
    env = os.environ.get("ROUTEDEL_CONFIG")
    if env:
        out.append(("$ROUTEDEL_CONFIG", Path(env).expanduser()))
    out.append(("user", default_path()))
    out.append(("legacy", Path.home() / ".routedel.json"))
    return out


def active_path(explicit: str | None = None) -> Path | None:
    for _, p in candidates(explicit):
        if p.is_file():
            return p
    return None


def target_path(explicit: str | None = None) -> Path:
    """Where a write goes: --config, $ROUTEDEL_CONFIG, existing config, else the default location."""
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("ROUTEDEL_CONFIG")
    if env:
        return Path(env).expanduser()
    return active_path() or default_path()


# ───────────────────────────── read / write ─────────────────────────────

def read_file(p: Path) -> dict:
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e: # noqa
        log.error("Bad config %s: %s", p, e)
        sys.exit(1)
    if not isinstance(data, dict):
        log.error("Bad config %s: top level must be a JSON object", p)
        sys.exit(1)
    return data


def load_config(explicit: str | None = None) -> dict:
    if explicit and not Path(explicit).expanduser().is_file():
        log.error("Config file not found: %s", explicit)
        sys.exit(1)
    p = active_path(explicit)
    return read_file(p) if p else {}


def save(p: Path, data: dict):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)  # may hold tokens/passwords
    except OSError:
        pass
    os.replace(tmp, p)


# ───────────────────────────── parsing helpers ─────────────────────────────

def split_ntfy_url(u: str) -> tuple[str, str | None]:
    """'https://host[/prefix]/topic' -> (base, topic). topic is None if the URL has no path."""
    u = u.strip().rstrip("/")
    sp = urlsplit(u)
    if sp.scheme not in ("http", "https") or not sp.netloc:
        raise ValueError(f"invalid ntfy URL: {u!r}")
    path = sp.path.rstrip("/")
    if not path:
        return f"{sp.scheme}://{sp.netloc}", None
    base_path, _, topic = path.rpartition("/")
    return f"{sp.scheme}://{sp.netloc}{base_path}", topic


def parse_growl(s: str) -> tuple[str, int]:
    """'host[:port]' -> (host, port)."""
    s = s.strip()
    host, sep, port = s.rpartition(":")
    if not sep:
        if not s:
            raise ValueError("empty Growl host")
        return s, DEFAULT_GNTP_PORT
    if not host or not port.isdigit() or not 0 < int(port) < 65536:
        raise ValueError(f"invalid Growl host[:port]: {s!r}")
    return host, int(port)


# ───────────────────────────── model helpers ─────────────────────────────

def mask(data: dict) -> dict:
    out = copy.deepcopy(data)
    for kind in ("ntfy", "growl"):
        for c in out.get(kind, []) if isinstance(out.get(kind), list) else []:
            if isinstance(c, dict):
                for k in SECRET_KEYS:
                    if c.get(k):
                        c[k] = MASK
    return out


def describe(kind: str, c: dict) -> str:
    if kind == "ntfy":
        return f"{str(c.get('url', '')).rstrip('/')}/{c['topic']}" if c.get("topic") else str(c.get("url", ""))
    return f"{c.get('host', '')}:{c.get('port', DEFAULT_GNTP_PORT)}"


def auth_of(kind: str, c: dict) -> str:
    if kind == "ntfy":
        return "token" if c.get("token") else ("basic" if c.get("user") else "none")
    return "password" if c.get("password") else "none"


def validate(data: Any) -> list[tuple[str, str]]:
    """Return [(level, message)], level in {'error','warning'}."""
    if not isinstance(data, dict):
        return [("error", "top level must be a JSON object")]
    issues: list[tuple[str, str]] = []
    for k in data:
        if k not in ALLOWED:
            issues.append(("warning", f"unknown key '{k}'"))
    for kind, req in (("ntfy", "url"), ("growl", "host")):
        items = data.get(kind, [])
        if not isinstance(items, list):
            issues.append(("error", f"'{kind}' must be a list"))
            continue
        for i, c in enumerate(items, 1):
            w = f"{kind}[{i}]"
            if not isinstance(c, dict):
                issues.append(("error", f"{w}: must be an object"))
                continue
            v = c.get(req)
            if not isinstance(v, str) or not v.strip():
                issues.append(("error", f"{w}: missing '{req}'"))
            elif kind == "ntfy" and not v.startswith(("http://", "https://")):
                issues.append(("error", f"{w}: url must start with http:// or https://"))
            for k in c:
                if k not in ALLOWED[kind]:
                    issues.append(("warning", f"{w}: unknown key '{k}'"))
            for k in ("topic", "token", "user", "password"):
                if k in c and not isinstance(c[k], str):
                    issues.append(("error", f"{w}: '{k}' must be a string"))
            if "port" in c and (isinstance(c["port"], bool) or not isinstance(c["port"], int)
                                or not 0 < c["port"] < 65536):
                issues.append(("error", f"{w}: 'port' must be an integer 1-65535"))
            if "timeout" in c and (isinstance(c["timeout"], bool) or not isinstance(c["timeout"], (int, float))
                                   or c["timeout"] <= 0):
                issues.append(("error", f"{w}: 'timeout' must be a number > 0"))
            if kind == "ntfy" and c.get("token") and c.get("user"):
                issues.append(("warning", f"{w}: both token and user set; token is used"))
    return issues


def _need_file(explicit: str | None) -> Path | None:
    if explicit and not Path(explicit).expanduser().is_file():
        log.error("Config file not found: %s", explicit)
        return None
    p = active_path(explicit)
    if not p:
        log.error("No config file found. Create one with: routedel config init")
    return p


# ───────────────────────────── subcommands ─────────────────────────────

def cmd_path(a) -> int:
    if a.all:
        act = active_path(a.config)
        t = Table(title="Config lookup order", title_style="bold magenta")
        for col in ("#", "Source", "Path", "Exists", "Active"):
            t.add_column(col)
        for i, (label, p) in enumerate(candidates(a.config), 1):
            t.add_row(str(i), label, str(p), "yes" if p.is_file() else "no", "<-" if p == act else "")
        console.print(t)
        return 0
    p = active_path(a.config) or target_path(a.config)
    print(p)
    if not p.is_file():
        print("(not found; create it with: routedel config init)", file=sys.stderr)
    return 0


def cmd_show(a) -> int:
    p = _need_file(a.config)
    if not p:
        return 1
    data = read_file(p)
    if a.json:
        print(json.dumps(data if a.reveal else mask(data), indent=2, ensure_ascii=False))
        return 0
    console.print(f"[bold]Config:[/bold] {escape(str(p))}")
    t = Table(title="Notification targets", title_style="bold magenta")
    for col, st in (("Kind", "bold cyan"), ("#", "cyan"), ("Target", "bold yellow"),
                    ("Auth", "green"), ("Timeout", "white")):
        t.add_column(col, style=st)
    n = 0
    for kind in ("ntfy", "growl"):
        items = data.get(kind, [])
        for i, c in enumerate(items if isinstance(items, list) else [], 1):
            if isinstance(c, dict):
                t.add_row(kind, str(i), escape(describe(kind, c)), auth_of(kind, c), str(c.get("timeout", 5)))
                n += 1
    console.print(t if n else "[dim]No targets configured.[/dim]")
    errs = [m for lv, m in validate(data) if lv == "error"]
    if errs:
        console.print(f"[bold red]{len(errs)} problem(s)[/bold red] - run: routedel config validate")
    return 0


def cmd_init(a) -> int:
    p = target_path(a.config)
    if p.exists() and not a.force:
        log.error("%s already exists (use --force to overwrite)", p)
        return 1
    save(p, copy.deepcopy(EXAMPLE if a.example else EMPTY))
    log.info("Created %s", p)
    console.print("Next: [bold]routedel config add ntfy https://ntfy.sh/TOPIC[/bold]  |  "
                  "[bold]routedel config add growl HOST[:PORT][/bold]")
    return 0


def cmd_add(a) -> int:
    p = target_path(a.config)
    data = read_file(p) if p.is_file() else copy.deepcopy(EMPTY)
    entry: dict[str, Any] = {}
    try:
        if a.kind == "ntfy":
            base, topic = split_ntfy_url(a.target)
            topic = a.topic or topic
            if not topic:
                raise ValueError("ntfy needs a topic: https://host/TOPIC or --topic TOPIC")
            entry = {"url": base, "topic": topic}
            for k in ("token", "user", "password"):
                if getattr(a, k):
                    entry[k] = getattr(a, k)
        else:
            host, port = parse_growl(a.target)
            port = a.port or port
            entry = {"host": host}
            if port != DEFAULT_GNTP_PORT:
                entry["port"] = port
            if a.password:
                entry["password"] = a.password
    except ValueError as e:
        log.error("%s", e)
        return 1
    if a.timeout:
        entry["timeout"] = a.timeout
    items = data.setdefault(a.kind, [])
    if not isinstance(items, list):
        log.error("'%s' in %s is not a list; fix it with: routedel config edit", a.kind, p)
        return 1
    if any(isinstance(c, dict) and describe(a.kind, c) == describe(a.kind, entry) for c in items):
        log.error("Already configured: %s", describe(a.kind, entry))
        return 1
    items.append(entry)
    save(p, data)
    log.info("Added %s target %s -> %s", a.kind, describe(a.kind, entry), p)
    return 0


def cmd_remove(a) -> int:
    p = _need_file(a.config)
    if not p:
        return 1
    data = read_file(p)
    items = data.get(a.kind, [])
    if not isinstance(items, list) or not items:
        log.error("No %s targets configured", a.kind)
        return 1
    if a.target.isdigit():
        idx = int(a.target) - 1
        if not 0 <= idx < len(items):
            log.error("No %s target #%s (have %d)", a.kind, a.target, len(items))
            return 1
    else:
        hits = [i for i, c in enumerate(items) if isinstance(c, dict) and a.target in describe(a.kind, c)]
        if not hits:
            log.error("No %s target matches %r", a.kind, a.target)
            return 1
        if len(hits) > 1:
            log.error("%r is ambiguous (%d matches); use the # from `routedel config show`", a.target, len(hits))
            return 1
        idx = hits[0]
    removed = items.pop(idx)
    save(p, data)
    log.info("Removed %s target %s", a.kind, describe(a.kind, removed) if isinstance(removed, dict) else removed)
    return 0


def cmd_validate(a) -> int:
    p = _need_file(a.config)
    if not p:
        return 1
    data = read_file(p)
    issues = validate(data)
    for lv, msg in issues:
        console.print(f"[{'red' if lv == 'error' else 'yellow'}]{lv}[/]: {escape(msg)}")
    if any(lv == "error" for lv, _ in issues):
        return 1
    n = sum(len(data.get(k, [])) for k in ("ntfy", "growl"))
    console.print(f"[green]OK[/green]: {escape(str(p))} ({n} target(s))")
    return 0


def _find_editor() -> str | None:
    ed = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if ed:
        return ed
    for name in ("nano", "vim", "vi", "notepad"):
        if shutil.which(name):
            return name
    return None


def cmd_edit(a) -> int:
    p = target_path(a.config)
    if not p.is_file():
        save(p, copy.deepcopy(EMPTY))
        log.info("Created %s", p)
    ed = _find_editor()
    if not ed:
        log.error("No editor found; set $EDITOR (file: %s)", p)
        return 1
    rc = subprocess.run(shlex.split(ed, posix=(os.name != "nt")) + [str(p)]).returncode # noqa
    try:
        errs = [m for lv, m in validate(json.loads(p.read_text(encoding="utf-8"))) if lv == "error"]
    except Exception as e: # noqa
        errs = [f"invalid JSON: {e}"]
    for m in errs:
        log.error("%s: %s", p, m)
    return rc or (1 if errs else 0)


def cmd_test(a) -> int:
    from .notify import build_notifier  # lazy: notify imports this module
    n = build_notifier(config=a.config)
    if not n:
        log.error("No notification targets configured.")
        return 1
    failed = n.send("Test notification", "info")
    if failed:
        log.error("%d of %d target(s) failed", failed, len(n.targets))
    return 1 if failed else 0


# ───────────────────────────── parser ─────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-c", "--config", metavar="FILE", help="Config file (default: auto-detected)")
    fmt = CustomRichHelpFormatter
    p = argparse.ArgumentParser(prog="routedel config", formatter_class=fmt,
                                description="Manage the routedel notification config.")
    sub = p.add_subparsers(dest="cmd", metavar="COMMAND")

    def add(name, func: Callable, help_, aliases=()):
        sp = sub.add_parser(name, parents=[common], formatter_class=fmt, help=help_, aliases=list(aliases))
        sp.set_defaults(func=func)
        return sp

    sp = add("path", cmd_path, "Print the config file path in use")
    sp.add_argument("--all", action="store_true", help="Show the full lookup order")
    sp = add("show", cmd_show, "Show configured targets (secrets hidden)", aliases=["list", "ls"])
    sp.add_argument("--json", action="store_true", help="Print the JSON instead of a table")
    sp.add_argument("--reveal", action="store_true", help="With --json: do not mask tokens/passwords")
    sp = add("init", cmd_init, "Create a new config file")
    sp.add_argument("--force", action="store_true", help="Overwrite an existing file")
    sp.add_argument("--example", action="store_true", help="Write example entries instead of empty lists")
    sp = add("add", cmd_add, "Add an ntfy or Growl target")
    sp.add_argument("kind", choices=["ntfy", "growl"])
    sp.add_argument("target", help="ntfy: https://host/TOPIC   growl: HOST[:PORT]")
    sp.add_argument("--topic", help="ntfy topic (if not part of the URL)")
    sp.add_argument("--token", help="ntfy bearer token")
    sp.add_argument("--user", help="ntfy basic-auth user")
    sp.add_argument("--password", help="ntfy basic-auth password / Growl password")
    sp.add_argument("--port", type=int, help="Growl port (default 23053)")
    sp.add_argument("--timeout", type=float, help="Per-target timeout in seconds (default 5)")
    sp = add("remove", cmd_remove, "Remove a target by # or by text match", aliases=["rm"])
    sp.add_argument("kind", choices=["ntfy", "growl"])
    sp.add_argument("target", help="# from `config show`, or part of the URL/host")
    add("validate", cmd_validate, "Check the config file for problems")
    add("edit", cmd_edit, "Open the config in $VISUAL/$EDITOR, then validate")
    add("test", cmd_test, "Send a test notification to every configured target")
    return p


def run(argv: list[str]) -> int:
    p = build_parser()
    a = p.parse_args(argv)
    if not getattr(a, "func", None):
        p.print_help()
        return 0
    return a.func(a)
