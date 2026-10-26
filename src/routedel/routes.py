#!/usr/bin/env python3

# File: src/routedel/routes.py
# Author: Hadi Cahyadi <cumulus13@gmail.com>
# Date: 2026-10-26
# Description: Route table reading, parsing and modification (Linux `ip` / `route`).
# License: MIT

"""Route table reading, parsing and modification (Linux `ip` / `route`)."""
import ipaddress
import logging
import re
import shutil
import subprocess
from typing import Any, Dict, List, Tuple

from .notify import Notifier

log = logging.getLogger("routedel")

Route = Dict[str, str]
Routes = Dict[int, Route]
COLS = ["Destination", "Gateway", "Genmask", "Flags", "Metric", "Ref", "Use", "Iface"]


def netmask(prefix: int) -> str:
    return str(ipaddress.ip_network(f"0.0.0.0/{prefix}").netmask)


def prefixlen(mask: str) -> int:
    return ipaddress.ip_network(f"0.0.0.0/{mask}").prefixlen


def is_default(r: Route) -> bool:
    return r.get("Destination") == "0.0.0.0" and r.get("Genmask") == "0.0.0.0"


def parse_route_table(text: str) -> Routes:
    """Parse `route -n` style text (optional leading '#' / index column)."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    hdr = next((i for i, ln in enumerate(lines) if "Destination" in ln and "Gateway" in ln), None)
    out: Routes = {}
    for ln in (lines[hdr + 1:] if hdr is not None else lines):
        parts = re.sub(r"^\s*#\s*", "", ln).split()
        if len(parts) == len(COLS) + 1 and parts[0].isdigit():
            parts = parts[1:]
        if len(parts) != len(COLS):
            continue
        out[len(out)] = dict(zip(COLS, parts))
    return out


def parse_ip_route(text: str) -> Routes:
    """Parse `ip -4 route show` output into the same shape as parse_route_table."""
    out: Routes = {}
    for ln in text.splitlines():
        p = ln.split()
        if not p or p[0] in ("blackhole", "unreachable", "prohibit", "throw"):
            continue
        dest = p[0]
        kv = {p[i]: p[i + 1] for i in range(len(p) - 1) if p[i] in ("via", "dev", "metric")}
        try:
            if dest == "default":
                dest_ip, mask = "0.0.0.0", "0.0.0.0"
            elif "/" in dest:
                ip, pre = dest.split("/")
                dest_ip, mask = ip, netmask(int(pre))
            else:
                dest_ip, mask = dest, "255.255.255.255"
            ipaddress.ip_address(dest_ip)
        except ValueError:
            continue
        out[len(out)] = {"Destination": dest_ip, "Gateway": kv.get("via", "0.0.0.0"), "Genmask": mask,
                         "Flags": "UG" if "via" in kv else "U", "Metric": kv.get("metric", "0"),
                         "Ref": "0", "Use": "0", "Iface": kv.get("dev", "")}
    return out


def get_routes() -> Routes:
    try:
        if shutil.which("ip"):
            p = subprocess.run(["ip", "-4", "route", "show"], capture_output=True, text=True)
            if p.returncode == 0:
                return parse_ip_route(p.stdout)
        if shutil.which("route"):
            p = subprocess.run(["route", "-n"], capture_output=True, text=True)
            return parse_route_table(p.stdout)
    except Exception as e:
        log.error("Failed to read routes: %s", e)
    return {}


def find_by_metric(data: Routes, metric: Any) -> List[Tuple[int, Route]]:
    return [(k, e) for k, e in data.items() if str(e.get("Metric", "")) == str(metric)]


def _run(cmd: List[str]) -> Tuple[bool, str]:
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode == 0, (p.stderr or p.stdout).strip()


def build_cmd(action: str, dest: str, mask: str, gw: str, iface: str, metric: str) -> List[str]:
    """Build the add/del command. action: 'add' | 'del'."""
    has_gw = gw not in ("", "0.0.0.0")
    has_metric = metric not in ("", "0", None)
    default = dest == "0.0.0.0" and mask == "0.0.0.0"
    if shutil.which("ip"):
        cmd = ["ip", "route", action, "default" if default else f"{dest}/{prefixlen(mask)}"]
        if has_gw:
            cmd += ["via", gw]
        cmd += ["dev", iface]
        if has_metric:
            cmd += ["metric", str(metric)]
        return cmd
    cmd = ["route", action]
    cmd += ["default"] if default else ["-net", dest, "netmask", mask]
    if has_gw:
        cmd += ["gw", gw]
    if has_metric:
        cmd += ["metric", str(metric)]
    return cmd + ["dev", iface]


def route_action(action: str, dest: str, mask: str, gw: str, iface: str, metric: str,
                 notifier: Notifier) -> bool:
    desc = f"{dest}/{prefixlen(mask)} via {gw} dev {iface} metric {metric or 0}"
    cmd = build_cmd(action, dest, mask, gw, iface, metric)
    log.warning("%s: %s", action, " ".join(cmd))
    ok, msg = _run(cmd)
    verb = "added" if action == "add" else "deleted"
    if ok:
        log.info("Route %s: %s", verb, desc)
        notifier.send(f"Route {verb}: {desc}", "info")
    else:
        log.error("Failed to %s route: %s", action, msg)
        notifier.send(f"FAILED to {action} route: {desc}\n{msg}", "error")
    return ok


def delete_entry(e: Route, notifier: Notifier) -> bool:
    if not e.get("Iface"):
        log.error("Entry missing Iface, skipping: %s", e)
        return False
    return route_action("del", e["Destination"], e["Genmask"], e["Gateway"], e["Iface"], e["Metric"], notifier)


def delete_default(gw: str, metric: str, iface: str, notifier: Notifier) -> bool:
    return route_action("del", "0.0.0.0", "0.0.0.0", gw, iface, metric, notifier)
