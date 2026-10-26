# Changelog

## 1.0.4
- New `routedel config` subcommands: `path [--all]`, `show [--json] [--reveal]` (alias `list`/`ls`),
  `init [--force] [--example]`, `add ntfy|growl ...`, `remove|rm ntfy|growl TARGET`, `validate`, `edit`, `test`.
- Config files are written atomically with mode 0600; secrets are masked in `show`.
- `--test-notify` and `config test` now exit 1 if any target failed (`Notifier.send` returns the failure count).
- Fix: `--ntfy https://host` (no topic) is now rejected instead of being mis-split; invalid `--growl host:port` is rejected.
- Fix: `--config FILE` pointing to a missing file is now an error instead of silently falling back.

## 1.0.0
- Packaged for PyPI (src layout, `routedel` console script).
- ntfy and Growl (GNTP 1.0) notifications, multiple servers, parallel send.
- `--add` / `--default` implemented; non-default routes deleted with correct dest/netmask.
- `ip route` preferred, `route -n` fallback; no shell (`subprocess` list args).
- Monitor notifies on route add/remove, start and stop.
