# Changelog

## 1.0.0
- Packaged for PyPI (src layout, `routedel` console script).
- ntfy and Growl (GNTP 1.0) notifications, multiple servers, parallel send.
- `--add` / `--default` implemented; non-default routes deleted with correct dest/netmask.
- `ip route` preferred, `route -n` fallback; no shell (`subprocess` list args).
- Monitor notifies on route add/remove, start and stop.
