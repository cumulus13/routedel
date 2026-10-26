#!/usr/bin/env python3

# File: src/routedel/cli.py
# Author: Hadi Cahyadi <cumulus13@gmail.com>
# Date: 2026-10-26
# Description: Command line interface.
# License: MIT

"""Command line interface."""
import argparse
import ipaddress
import os
import sys

from rchf import CustomRichHelpFormatter
from richcolorlog import setup_logging

from . import __version__
from .display import console, create_route_table, monitor_routes
from .notify import APP_NAME, build_notifier
from .routes import (
    delete_default,
    delete_entry,
    find_by_metric,
    get_routes,
    parse_route_table,
    route_action,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(formatter_class=CustomRichHelpFormatter, prog=APP_NAME)
    p.add_argument('data', nargs="*", help='Route string, or "c" to read from clipboard')
    p.add_argument('-V', '--version', action='version', version=f"{APP_NAME} {__version__}")
    p.add_argument('-m', '--metric', help='Remove route(s) by metric')
    p.add_argument('-l', '--list', action='store_true', help='List current routes')
    p.add_argument('-a', '--add', action='store_true', help='Add route (needs -g and -i; DATA[0]=CIDR unless -d)')
    p.add_argument('-d', '--default', action='store_true', help='Add as default route')
    p.add_argument('-g', '--gateway', help='Gateway IP for adding route')
    p.add_argument('-i', '--interface', help='Interface name for adding route')
    p.add_argument('--met', type=int, default=0, help='Metric for adding route')
    p.add_argument('--monitor', action='store_true', help='Monitor routing table in real-time')
    p.add_argument('--refresh', type=float, default=2.0, help='Monitor refresh seconds (default: 2.0)')
    p.add_argument('--ntfy', action='append', metavar='URL', help='ntfy topic URL, e.g. https://ntfy.sh/topic (repeatable)')
    p.add_argument('--growl', action='append', metavar='HOST[:PORT]', help='Growl/GNTP server (repeatable)')
    p.add_argument('--config', help='Notification config JSON file')
    p.add_argument('--no-notify', action='store_true', help='Disable all notifications')
    p.add_argument('--test-notify', action='store_true', help='Send a test notification and exit')
    return p


def main(argv=None):
    log = setup_logging(exceptions=['pika', 'urllib3', 'urllib2', 'urllib', 'clipboard'])
    p = build_parser()
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        p.print_help()
        sys.exit(0)
    args = p.parse_args(argv)
    notifier = build_notifier(args.no_notify, args.config, args.ntfy, args.growl)

    if args.test_notify:
        if not notifier:
            log.error("No notification targets configured.")
            sys.exit(1)
        notifier.send("Test notification", "info")
        return

    if args.monitor:
        monitor_routes(args.refresh, notifier)
        return

    if args.list:
        console.print(create_route_table(get_routes()))
        return

    if (args.add or args.data or args.metric) and hasattr(os, "geteuid") and os.geteuid() != 0:
        log.warning("Not running as root; route changes will likely fail.")

    if args.add:
        if not (args.gateway and args.interface):
            log.error("--add requires -g GATEWAY and -i INTERFACE")
            sys.exit(1)
        if args.default:
            dest, mask = "0.0.0.0", "0.0.0.0"
        elif args.data:
            try:
                net = ipaddress.ip_network(args.data[0], strict=False)
            except ValueError as e:
                log.error("Invalid network '%s': %s", args.data[0], e)
                sys.exit(1)
            dest, mask = str(net.network_address), str(net.netmask)
        else:
            log.error("Provide DATA (CIDR) or use -d for default route")
            sys.exit(1)
        sys.exit(0 if route_action("add", dest, mask, args.gateway, args.interface,
                                   str(args.met), notifier) else 1)

    if args.data:
        if args.data == ['c']:
            try:
                import clipboard
            except ImportError:
                log.error("Clipboard support missing: pip install 'routedel[clipboard]'")
                sys.exit(1)
            tokens = clipboard.paste().split()
        else:
            tokens = args.data
        if len(tokens) in (8, 9):  # full row, optional leading index
            e = parse_route_table(" ".join(tokens)).get(0)
            if not e:
                log.error("Could not parse route row")
                sys.exit(1)
            sys.exit(0 if delete_entry(e, notifier) else 1)
        if len(tokens) == 4:  # legacy: X GW METRIC DEV
            sys.exit(0 if delete_default(tokens[1], tokens[2], tokens[3], notifier) else 1)
        log.error("Unsupported data format (%d tokens)", len(tokens))
        sys.exit(1)

    if args.metric:
        matches = find_by_metric(get_routes(), args.metric)
        if not matches:
            log.error("No route found with metric %s", args.metric)
            sys.exit(1)
        to_delete = matches
        if len(matches) > 1:
            log.warning("Multiple routes found with metric %s:", args.metric)
            for idx, e in matches:
                print(f"  [{idx}] {e}")
            q = input("Index to delete, 'a' = all, 'c' = cancel: ").strip().lower()
            if q == 'c':
                log.info("Operation cancelled.")
                return
            if q == 'a':
                pass
            elif q.isdigit() and any(m[0] == int(q) for m in matches):
                to_delete = [m for m in matches if m[0] == int(q)]
            else:
                log.error("Invalid input, operation cancelled.")
                sys.exit(1)
        ok = [delete_entry(e, notifier) for _, e in to_delete]
        sys.exit(0 if all(ok) else 1)

    log.error("Invalid arguments. Provide route details, -m METRIC, -a, -l or --monitor.")
    p.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
