#!/usr/bin/env python3

# File: tests/test_cli.py
# Author: Hadi Cahyadi <cumulus13@gmail.com>
# Date: 2026-10-26
# Description: 
# License: MIT

import pytest

from routedel import cli, routes


def test_no_args_prints_help(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main([])
    assert e.value.code == 0


def test_version(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--version"])
    assert "routedel 1." in capsys.readouterr().out


def test_test_notify_without_targets_fails(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("ROUTEDEL_CONFIG", raising=False)
    with pytest.raises(SystemExit) as e:
        cli.main(["--test-notify"])
    assert e.value.code == 1


def test_add_requires_gateway_and_iface(monkeypatch):
    with pytest.raises(SystemExit) as e:
        cli.main(["-a", "10.0.0.0/8", "--no-notify"])
    assert e.value.code == 1


def test_add_invalid_cidr(monkeypatch):
    with pytest.raises(SystemExit) as e:
        cli.main(["-a", "notanet", "-g", "1.1.1.1", "-i", "eth0", "--no-notify"])
    assert e.value.code == 1


def test_add_calls_route_action(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "route_action", lambda *a: calls.append(a) or True)
    with pytest.raises(SystemExit) as e:
        cli.main(["-a", "10.1.2.3/16", "-g", "1.1.1.1", "-i", "eth0", "--met", "7", "--no-notify"])
    assert e.value.code == 0
    assert calls[0][:6] == ("add", "10.1.0.0", "255.255.0.0", "1.1.1.1", "eth0", "7")
    calls.clear()
    with pytest.raises(SystemExit):
        cli.main(["-a", "-d", "-g", "1.1.1.1", "-i", "eth0", "--no-notify"])
    assert calls[0][1:3] == ("0.0.0.0", "0.0.0.0")


def test_delete_full_row_and_legacy(monkeypatch):
    got = []
    monkeypatch.setattr(cli, "delete_entry", lambda e, n: got.append(e) or True)
    monkeypatch.setattr(cli, "delete_default", lambda *a: got.append(a) or True)
    with pytest.raises(SystemExit) as e:
        cli.main(["0.0.0.0", "192.168.1.1", "0.0.0.0", "UG", "100", "0", "0", "eth0", "--no-notify"])
    assert e.value.code == 0 and got[0]["Iface"] == "eth0" and got[0]["Metric"] == "100"
    with pytest.raises(SystemExit):  # 9 tokens, leading index
        cli.main(["0", "0.0.0.0", "192.168.1.1", "0.0.0.0", "UG", "100", "0", "0", "eth0", "--no-notify"])
    assert got[1]["Gateway"] == "192.168.1.1"
    with pytest.raises(SystemExit):
        cli.main(["X", "192.168.1.1", "100", "eth0", "--no-notify"])
    assert got[2] == ("192.168.1.1", "100", "eth0", got[2][3])


def test_delete_unsupported_token_count():
    with pytest.raises(SystemExit) as e:
        cli.main(["a", "b", "c", "--no-notify"])
    assert e.value.code == 1


def test_metric_not_found(monkeypatch):
    monkeypatch.setattr(cli, "get_routes", dict)
    with pytest.raises(SystemExit) as e:
        cli.main(["-m", "5", "--no-notify"])
    assert e.value.code == 1


def test_metric_multiple_select(monkeypatch):
    rt = routes.parse_ip_route("default via 1.1.1.1 dev eth0 metric 5\ndefault via 2.2.2.2 dev wlan0 metric 5\n")
    monkeypatch.setattr(cli, "get_routes", lambda: rt)
    deleted = []
    monkeypatch.setattr(cli, "delete_entry", lambda e, n: deleted.append(e["Iface"]) or True)
    monkeypatch.setattr("builtins.input", lambda _: "1")
    with pytest.raises(SystemExit) as e:
        cli.main(["-m", "5", "--no-notify"])
    assert e.value.code == 0 and deleted == ["wlan0"]
    deleted.clear()
    monkeypatch.setattr("builtins.input", lambda _: "a")
    with pytest.raises(SystemExit):
        cli.main(["-m", "5", "--no-notify"])
    assert deleted == ["eth0", "wlan0"]
    monkeypatch.setattr("builtins.input", lambda _: "c")
    deleted.clear()
    cli.main(["-m", "5", "--no-notify"])
    assert deleted == []


def test_list(monkeypatch, capsys):
    monkeypatch.setattr(cli, "get_routes", lambda: routes.parse_ip_route("default via 1.1.1.1 dev eth0 metric 5\n"))
    cli.main(["-l"])
    assert "1.1.1.1" in capsys.readouterr().out
