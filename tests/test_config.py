import json
import os
import stat

import pytest

from routedel import cli, config, notify


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("ROUTEDEL_CONFIG", raising=False)
    return tmp_path


def run(*argv):
    return config.run(list(argv))


def test_split_ntfy_url():
    assert config.split_ntfy_url("https://ntfy.sh/topic") == ("https://ntfy.sh", "topic")
    assert config.split_ntfy_url("https://ntfy.sh/") == ("https://ntfy.sh", None)
    assert config.split_ntfy_url("https://h.example/prefix/topic/") == ("https://h.example/prefix", "topic")
    assert config.split_ntfy_url("http://127.0.0.1:8080/t") == ("http://127.0.0.1:8080", "t")
    with pytest.raises(ValueError):
        config.split_ntfy_url("ntfy.sh/topic")


def test_parse_growl():
    assert config.parse_growl("h") == ("h", 23053)
    assert config.parse_growl("h:9999") == ("h", 9999)
    for bad in ("", "h:abc", "h:0", "h:70000", ":23053"):
        with pytest.raises(ValueError):
            config.parse_growl(bad)


def test_cli_ntfy_without_topic_errors():
    with pytest.raises(SystemExit):
        notify.build_notifier(ntfy_urls=["https://ntfy.sh"])


def test_init_creates_private_file_and_refuses_overwrite(home):
    assert run("init") == 0
    p = home / ".config/routedel/config.json"
    assert json.loads(p.read_text()) == {"ntfy": [], "growl": []}
    if os.name == "posix":
        assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert run("init") == 1
    assert run("init", "--force", "--example") == 0
    assert json.loads(p.read_text())["ntfy"][0]["topic"] == "my-routes"


def test_init_explicit_path(tmp_path):
    f = tmp_path / "sub" / "c.json"
    assert run("init", "-c", str(f)) == 0 and f.is_file()


def test_path_and_lookup_order(home, monkeypatch, capsys):
    assert run("path") == 0
    out = capsys.readouterr()
    assert out.out.strip() == str(home / ".config/routedel/config.json") and "not found" in out.err
    legacy = home / ".routedel.json"
    legacy.write_text("{}")
    run("path")
    assert capsys.readouterr().out.strip() == str(legacy)
    env = home / "env.json"
    env.write_text("{}")
    monkeypatch.setenv("ROUTEDEL_CONFIG", str(env))
    run("path")
    assert capsys.readouterr().out.strip() == str(env)
    explicit = home / "x.json"
    explicit.write_text("{}")
    run("path", "-c", str(explicit))
    assert capsys.readouterr().out.strip() == str(explicit)
    assert run("path", "--all") == 0
    assert "Config lookup order" in capsys.readouterr().out


def test_add_ntfy_growl_and_show(home, capsys):
    assert run("add", "ntfy", "https://ntfy.sh/mytopic", "--token", "tk_secret") == 0
    assert run("add", "ntfy", "https://ntfy.example.com", "--topic", "alerts", "--user", "u", "--password", "pw") == 0
    assert run("add", "growl", "10.0.0.5") == 0
    assert run("add", "growl", "10.0.0.6:9999", "--password", "gp", "--timeout", "2") == 0
    data = json.loads((home / ".config/routedel/config.json").read_text())
    assert data["ntfy"][0] == {"url": "https://ntfy.sh", "topic": "mytopic", "token": "tk_secret"}
    assert data["ntfy"][1]["user"] == "u"
    assert data["growl"][0] == {"host": "10.0.0.5"}
    assert data["growl"][1] == {"host": "10.0.0.6", "port": 9999, "password": "gp", "timeout": 2.0}
    capsys.readouterr()
    assert run("show") == 0
    out = capsys.readouterr().out
    assert "https://ntfy.sh/mytopic" in out and "10.0.0.6:9999" in out
    assert "tk_secret" not in out and "gp" not in out.replace("growl", "")
    run("show", "--json")
    j = json.loads(capsys.readouterr().out)
    assert j["ntfy"][0]["token"] == config.MASK and j["growl"][1]["password"] == config.MASK
    run("ls", "--json", "--reveal")
    assert json.loads(capsys.readouterr().out)["ntfy"][0]["token"] == "tk_secret"


def test_add_duplicate_and_bad_input(home):
    assert run("add", "ntfy", "https://ntfy.sh/t") == 0
    assert run("add", "ntfy", "https://ntfy.sh/t") == 1
    assert run("add", "ntfy", "https://ntfy.sh") == 1          # no topic
    assert run("add", "ntfy", "not-a-url") == 1
    assert run("add", "growl", "h:abc") == 1


def test_remove_by_index_and_text(home):
    for u in ("https://a.example/one", "https://b.example/two", "https://b.example/three"):
        run("add", "ntfy", u)
    run("add", "growl", "h1")
    assert run("remove", "ntfy", "9") == 1
    assert run("remove", "ntfy", "b.example") == 1               # ambiguous
    assert run("remove", "ntfy", "nomatch") == 1
    assert run("rm", "ntfy", "a.example") == 0
    assert run("remove", "ntfy", "1") == 0                       # now b.example/two
    data = json.loads((home / ".config/routedel/config.json").read_text())
    assert [c["topic"] for c in data["ntfy"]] == ["three"]
    assert run("remove", "growl", "h1") == 0
    assert run("remove", "growl", "1") == 1


def test_show_remove_validate_without_config(home):
    assert run("show") == 1
    assert run("remove", "ntfy", "1") == 1
    assert run("validate") == 1
    assert run("show", "-c", str(home / "missing.json")) == 1


def test_validate(home, capsys):
    f = home / "c.json"
    f.write_text(json.dumps({"ntfy": [{"url": "https://a/t", "topic": "t"}], "growl": [{"host": "h", "port": 23053}]}))
    assert run("validate", "-c", str(f)) == 0
    f.write_text(json.dumps({
        "bogus": 1,
        "ntfy": [{"topic": "t"}, {"url": "ftp://x"}, {"url": "https://a", "token": "x", "user": "u", "extra": 1}, 5],
        "growl": [{"host": "h", "port": "23053"}, {"host": "h", "port": 99999}, {"host": "h", "timeout": -1}, {}]}))
    assert run("validate", "-c", str(f)) == 1
    out = capsys.readouterr().out
    for frag in ("unknown key 'bogus'", "missing 'url'", "must start with http", "unknown key 'extra'",
                 "both token and user", "must be an object", "'port' must be an integer", "'timeout' must be",
                 "missing 'host'"):
        assert frag in out, frag
    f.write_text("{not json")
    with pytest.raises(SystemExit):
        run("validate", "-c", str(f))
    f.write_text("[]")
    with pytest.raises(SystemExit):
        run("validate", "-c", str(f))


def test_edit(home, monkeypatch):
    calls = []
    monkeypatch.setenv("EDITOR", "myeditor --wait")

    class R:
        returncode = 0

    def fake(cmd):
        calls.append(cmd)
        open(cmd[-1], "w").write('{"ntfy": [{"url": "https://a/t"}], "growl": []}') # noqa
        return R()

    monkeypatch.setattr(config.subprocess, "run", fake)
    assert run("edit") == 0
    assert calls[0][:2] == ["myeditor", "--wait"] and calls[0][-1].endswith("config.json")

    def bad(cmd):
        open(cmd[-1], "w").write("{oops") # noqa
        return R()

    monkeypatch.setattr(config.subprocess, "run", bad)
    assert run("edit") == 1
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setattr(config.shutil, "which", lambda n: None)
    assert run("edit") == 1


def test_config_test_sends(home, monkeypatch):
    sent = []
    monkeypatch.setattr(notify.Notifier, "send", lambda self, m, level="info", **k: sent.append((len(self.targets), m)) or 0)
    assert run("test") == 1                                      # nothing configured
    run("add", "ntfy", "https://ntfy.sh/t")
    run("add", "growl", "h")
    assert run("test") == 0 and sent == [(2, "Test notification")]
    monkeypatch.setattr(notify.Notifier, "send", lambda self, m, level="info", **k: 1)
    assert run("test") == 1                                      # a failed target -> non-zero


def test_explicit_missing_config_is_error(home):
    with pytest.raises(SystemExit):
        notify.build_notifier(config=str(home / "nope.json"))


def test_cli_dispatches_config(home, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["config", "init"])
    assert e.value.code == 0 and (home / ".config/routedel/config.json").is_file()
    with pytest.raises(SystemExit) as e:
        cli.main(["config"])                                     # no subcommand -> help
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert "init" in out and "validate" in out


def test_broken_pipe_is_silent(home, monkeypatch):
    def boom(argv):
        raise BrokenPipeError

    dup = []
    monkeypatch.setattr(config, "run", boom)
    monkeypatch.setattr(cli.os, "dup2", lambda *a: dup.append(a))   # don't touch the real stdout fd
    with pytest.raises(SystemExit) as e:
        cli.main(["config", "show"])
    assert e.value.code == 0
