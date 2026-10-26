#!/usr/bin/env python3

# File: tests/test_routes.py
# Author: Hadi Cahyadi <cumulus13@gmail.com>
# Date: 2026-10-26
# Description: 
# License: MIT

from routedel import routes
from routedel.display import diff_routes, route_key

ROUTE_N = """Kernel IP routing table
Destination     Gateway         Genmask         Flags Metric Ref    Use Iface
0.0.0.0         192.168.1.1     0.0.0.0         UG    100    0        0 eth0
172.17.0.0      0.0.0.0         255.255.0.0     U     0      0        0 docker0
"""

IP_ROUTE = """default via 192.168.1.1 dev eth0 proto dhcp metric 100
172.17.0.0/16 dev docker0 proto kernel scope link src 172.17.0.1
192.168.1.0/24 dev eth0 proto kernel scope link src 192.168.1.5 metric 100
blackhole 10.9.9.0/24
"""


def test_parse_route_n():
    r = routes.parse_route_table(ROUTE_N)
    assert len(r) == 2
    assert r[0]["Gateway"] == "192.168.1.1" and r[0]["Iface"] == "eth0"
    assert routes.is_default(r[0]) and not routes.is_default(r[1])


def test_parse_with_index_and_hash():
    r = routes.parse_route_table("# 3 0.0.0.0 10.0.0.1 0.0.0.0 UG 50 0 0 wlan0")
    assert r[0]["Metric"] == "50" and r[0]["Iface"] == "wlan0"


def test_parse_ip_route():
    r = routes.parse_ip_route(IP_ROUTE)
    assert len(r) == 3  # blackhole skipped
    assert r[0]["Destination"] == "0.0.0.0" and r[0]["Genmask"] == "0.0.0.0" and r[0]["Flags"] == "UG"
    assert r[1]["Genmask"] == "255.255.0.0" and r[1]["Gateway"] == "0.0.0.0"
    assert r[2]["Genmask"] == "255.255.255.0" and r[2]["Metric"] == "100"


def test_netmask_prefix_roundtrip():
    for n in (0, 8, 16, 24, 32):
        assert routes.prefixlen(routes.netmask(n)) == n


def test_find_by_metric():
    r = routes.parse_ip_route(IP_ROUTE)
    assert [k for k, _ in routes.find_by_metric(r, 100)] == [0, 2]
    assert routes.find_by_metric(r, "999") == []


def test_build_cmd_ip(monkeypatch):
    monkeypatch.setattr(routes.shutil, "which", lambda n: "/sbin/ip" if n == "ip" else None)
    assert routes.build_cmd("del", "0.0.0.0", "0.0.0.0", "192.168.1.1", "eth0", "100") == \
        ["ip", "route", "del", "default", "via", "192.168.1.1", "dev", "eth0", "metric", "100"]
    assert routes.build_cmd("add", "10.0.0.0", "255.0.0.0", "192.168.1.1", "eth0", "0") == \
        ["ip", "route", "add", "10.0.0.0/8", "via", "192.168.1.1", "dev", "eth0"]
    assert routes.build_cmd("del", "172.17.0.0", "255.255.0.0", "0.0.0.0", "docker0", "0") == \
        ["ip", "route", "del", "172.17.0.0/16", "dev", "docker0"]


def test_build_cmd_route_fallback(monkeypatch):
    monkeypatch.setattr(routes.shutil, "which", lambda n: None)
    assert routes.build_cmd("del", "10.0.0.0", "255.0.0.0", "192.168.1.1", "eth0", "5") == \
        ["route", "del", "-net", "10.0.0.0", "netmask", "255.0.0.0", "gw", "192.168.1.1",
         "metric", "5", "dev", "eth0"]
    assert routes.build_cmd("add", "0.0.0.0", "0.0.0.0", "192.168.1.1", "eth0", "0") == \
        ["route", "add", "default", "gw", "192.168.1.1", "dev", "eth0"]


def test_diff_routes():
    a = {route_key(e): e for e in routes.parse_ip_route(IP_ROUTE).values()}
    assert diff_routes(a, dict(a)) == ([], False)
    b = dict(a)
    gone = next(k for k in b if k[0] == "0.0.0.0")
    del b[gone]
    lines, dflt = diff_routes(a, b)
    assert dflt and lines == ["- 0.0.0.0/0 via 192.168.1.1 dev eth0 metric 100"]
    c = dict(a)
    c[("10.1.0.0", "0.0.0.0", "255.255.0.0", "0", "eth1")] = {}
    lines, dflt = diff_routes(a, c)
    assert not dflt and lines[0].startswith("+ 10.1.0.0/16")


class Rec:
    def __init__(self):
        self.msgs = []

    def send(self, m, level="info", **kw):
        self.msgs.append((m, level))


def test_route_action_failure_notifies(monkeypatch):
    monkeypatch.setattr(routes, "_run", lambda cmd: (False, "RTNETLINK answers: Operation not permitted"))
    n = Rec()
    assert routes.route_action("del", "0.0.0.0", "0.0.0.0", "1.1.1.1", "eth0", "10", n) is False
    assert n.msgs[0][1] == "error" and "FAILED" in n.msgs[0][0]


def test_route_action_success_notifies(monkeypatch):
    monkeypatch.setattr(routes, "_run", lambda cmd: (True, ""))
    n = Rec()
    assert routes.route_action("add", "10.0.0.0", "255.0.0.0", "1.1.1.1", "eth0", "10", n) is True
    assert n.msgs == [("Route added: 10.0.0.0/8 via 1.1.1.1 dev eth0 metric 10", "info")]
