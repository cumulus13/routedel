#!/usr/bin/env python3

# File: src/routedel/display.py
# Author: Hadi Cahyadi <cumulus13@gmail.com>
# Date: 2026-10-26
# Description: Rich display and live monitor.
# License: MIT

"""Rich display and live monitor."""
import signal
import threading
from datetime import datetime
from typing import Tuple

from rich.align import Align
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .notify import Notifier
from .routes import COLS, Route, Routes, get_routes, is_default, prefixlen

console = Console()


def create_route_table(routes: Routes, title: str = "Current Routes") -> Table:
    t = Table(title=title, title_style="bold magenta", expand=True, padding=(0, 1))
    styles = [("Idx", "cyan", 3), ("Destination", "bold cyan", 15), ("Gateway", "bold yellow", 15),
              ("Genmask", "bold blue", 15), ("Flags", "bold magenta", 5), ("Metric", "bold green", 6),
              ("Ref", "bold red", 3), ("Use", "bold white", 3), ("Iface", "bold cyan", 8)]
    for name, style, width in styles:
        t.add_column(name, style=style, no_wrap=True, min_width=width)
    for idx, e in routes.items():
        t.add_row(f"[{'bold red' if is_default(e) else 'cyan'}]{idx}[/]", *(e.get(c, "") for c in COLS))
    return t


def create_monitor_layout(routes: Routes, last_update: str, interval: float, n_targets: int) -> Layout:
    head = Text()
    head.append("Route Monitor", style="bold magenta")
    head.append(f" | {last_update} | refresh {interval}s | notify targets: {n_targets} | Ctrl+C to exit", style="dim")
    ifaces = sorted({e["Iface"] for e in routes.values() if e.get("Iface")})
    stats = Text()
    stats.append(f"Routes: {len(routes)}", style="bold white")
    stats.append(f" | Default: {sum(map(is_default, routes.values()))}", style="bold red")
    stats.append(f" | Interfaces: {', '.join(ifaces)}", style="cyan")
    layout = Layout()
    layout.split_column(
        Layout(Panel(Align.center(head), style="bold blue"), size=3),
        Layout(create_route_table(routes, f"Routing Table ({len(routes)} routes)")),
        Layout(Panel(Align.center(stats), title="Statistics", style="dim"), size=3),
    )
    return layout


def route_key(e: Route) -> Tuple[str, ...]:
    return tuple(e.get(c, "") for c in ("Destination", "Gateway", "Genmask", "Metric", "Iface"))


def fmt_key(k: Tuple[str, ...]) -> str:
    d, g, m, met, i = k
    return f"{d}/{prefixlen(m)} via {g} dev {i} metric {met}"


def diff_routes(prev: dict, cur: dict):
    """Return (message_lines, default_changed) for two {key: route} maps; ([], False) if equal."""
    added, removed = cur.keys() - prev.keys(), prev.keys() - cur.keys()
    if not (added or removed):
        return [], False
    lines = [f"+ {fmt_key(k)}" for k in sorted(added)] + [f"- {fmt_key(k)}" for k in sorted(removed)]
    if len(lines) > 10:
        lines = lines[:10] + [f"... +{len(lines) - 10} more"]
    dflt = any(k[0] == "0.0.0.0" and k[2] == "0.0.0.0" for k in added | removed)
    return lines, dflt


def monitor_routes(interval: float, notifier: Notifier):
    stop = threading.Event()
    handler = lambda s, f: stop.set()
    for name in ("SIGINT", "SIGTERM", "SIGHUP"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), handler)

    prev = {route_key(e): e for e in get_routes().values()}
    notifier.send(f"Monitor started ({len(prev)} routes)", "info", wait=False)
    try:
        with Live(console=console, screen=True, auto_refresh=False) as live:
            while not stop.is_set():
                try:
                    routes = get_routes()
                    cur = {route_key(e): e for e in routes.values()}
                    lines, dflt = diff_routes(prev, cur)
                    if lines:
                        notifier.send("Routing table changed:\n" + "\n".join(lines),
                                      "warning" if dflt else "info", wait=False)
                        prev = cur
                    live.update(create_monitor_layout(routes, datetime.now().strftime("%H:%M:%S"),
                                                      interval, len(notifier.targets)))
                    live.refresh()
                except Exception as e:
                    live.update(Panel(Align.center(Text(f"Error: {e}\nRetrying in {interval}s", style="bold red")),
                                      title="Error", style="bold red"))
                    live.refresh()
                stop.wait(interval)
    finally:
        notifier.send("Monitor stopped", "info", wait=True)
        console.print("[green]Route monitoring stopped.[/green]")
