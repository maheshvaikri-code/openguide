"""One-command Console demo: seed simulated data, serve the proxy + the built Console.

    python scripts/console_demo.py             # or:  make console-demo
    python scripts/console_demo.py --n 10000   # a bigger fleet

Open http://127.0.0.1:8088/console/ . All data is SIMULATED (model ids are `mock:*`).
ASCII-only output so Windows cp1252 consoles don't crash.
"""
from __future__ import annotations

import argparse
import os
import socket
import sys
import threading

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from benchmarks import console_seed  # noqa: E402
from proxy.app import create_app  # noqa: E402
from proxy.registry import ContractRegistry  # noqa: E402
from proxy.upstream import MockUpstream  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) != 0


def build_app(workdir: str, n: int, console_dir: str | None, admin_token: str | None = None):
    # The demo store is disposable: keep it in memory so there is no file to lock or leave stale.
    seeded = console_seed.seed(workdir, n=n, db=":memory:")
    registry = ContractRegistry()
    for c in seeded.contracts:
        registry.register(c)
    app = create_app(registry=registry, upstream=MockUpstream(lambda body: "ok"), store=seeded.store,
                     admin_token=admin_token, packs_dir=seeded.packs_dir, console_dir=console_dir)
    return app, seeded


def _live_tail(store, period: float, stop: threading.Event) -> None:
    i = 0
    while not stop.wait(period):
        console_seed.add_live_run(store, i)
        i += 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--n", type=int, default=2000, help="simulated fleet size (default 2000)")
    ap.add_argument("--port", type=int, default=8088)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--dir", default=os.path.join(ROOT, ".console-demo"))
    ap.add_argument("--no-live", action="store_true", help="disable the simulated live tail")
    ap.add_argument("--admin-token", default=os.environ.get("OPENGUIDE_ADMIN_TOKEN") or None)
    args = ap.parse_args()

    console_dir = os.path.join(ROOT, "console", "dist")
    if not os.path.isfile(os.path.join(console_dir, "index.html")):
        print("Console is not built. Run:  make console-build   (needs Node 20+)", file=sys.stderr)
        return 2

    if not port_is_free(args.host, args.port):
        print(f"Port {args.port} is already in use (is another console demo running?). "
              f"Stop it, or pass --port <other>.", file=sys.stderr)
        return 3

    print(f"seeding {args.n} simulated runs ...")
    app, seeded = build_app(args.dir, args.n, console_dir, args.admin_token)
    stop = threading.Event()
    if not args.no_live:
        threading.Thread(target=_live_tail, args=(seeded.store, 3.0, stop), daemon=True).start()

    import uvicorn

    print(f"Console:  http://{args.host}:{args.port}/console/   (SIMULATED data)")
    if args.admin_token:
        print("Admin token is required: enter it in the Console when prompted.")
    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    finally:
        stop.set()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
