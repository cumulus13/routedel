# routedel

Delete, add, list and monitor IPv4 routes on Linux, with notifications to **multiple ntfy and Growl (GNTP) servers**.

## Install

```bash
pip install routedel
pip install "routedel[clipboard]"   # optional: read route rows from the clipboard
```

## Usage

```bash
routedel -l                                    # list routes
routedel -m 100                                # delete route(s) by metric
routedel 0.0.0.0 192.168.1.1 0.0.0.0 UG 100 0 0 eth0   # delete a full `route -n` row
routedel 0.0.0.0 192.168.1.1 100 eth0          # legacy: X GW METRIC DEV (default route)
routedel c                                     # delete using a route row from the clipboard
sudo routedel -a 10.0.0.0/8 -g 192.168.1.1 -i eth0 --met 50   # add route
sudo routedel -a -d -g 192.168.1.1 -i eth0 --met 100          # add default route
routedel --monitor --refresh 2                 # live monitor, notifies on changes
```

Route changes need root.

## Notifications

Any number of servers of each type. Via CLI (repeatable):

```bash
routedel -m 100 --ntfy https://ntfy.sh/my-routes --ntfy https://ntfy.example.com/alerts \
                --growl 192.168.1.10 --growl 192.168.1.20:23053
```

Or via a JSON config (first found wins): `--config FILE`, `$ROUTEDEL_CONFIG`,
`~/.config/routedel/config.json`, `~/.routedel.json`. CLI targets are added to the config targets.

```json
{
  "ntfy":  [{"url": "https://ntfy.sh", "topic": "my-routes", "token": "tk_xxx"},
            {"url": "https://ntfy.example.com", "topic": "alerts", "user": "u", "password": "p"}],
  "growl": [{"host": "192.168.1.10", "port": 23053, "password": "secret"},
            {"host": "192.168.1.20"}]
}
```

Test with `routedel --test-notify` (or `routedel config test`); exit code is 1 if any target failed.
Disable with `--no-notify`.

### Managing the config: `routedel config`

```bash
routedel config init                      # create ~/.config/routedel/config.json (mode 0600); --example, --force
routedel config path [--all]              # file in use / full lookup order
routedel config add ntfy https://ntfy.sh/my-routes --token tk_xxx
routedel config add ntfy https://ntfy.example.com --topic alerts --user u --password p
routedel config add growl 192.168.1.10:23053 --password secret
routedel config show [--json [--reveal]]  # table of targets (secrets masked); aliases: list, ls
routedel config remove ntfy 2             # by # from `show`, or by text: `rm growl 192.168.1.20`
routedel config validate                  # schema check, exit 1 on errors
routedel config edit                      # $VISUAL / $EDITOR, then validates
routedel config test                      # send a test to every target
```

Every subcommand accepts `-c/--config FILE` to operate on a specific file.
Servers are contacted in parallel; one failing server does not affect the others.
Dependencies for notifications: none (stdlib `urllib` + raw GNTP 1.0 over sockets).

## License

MIT

---

## 👤 Author
        
[Hadi Cahyadi](mailto:cumulus13@gmail.com)
    

[![Buy Me a Coffee](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/cumulus13)

[![Donate via Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/cumulus13)
 
[Support me on Patreon](https://www.patreon.com/cumulus13)
