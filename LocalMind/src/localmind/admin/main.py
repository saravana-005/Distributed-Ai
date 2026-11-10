from __future__ import annotations

import argparse

import uvicorn

from localmind.admin.app import create_app
from localmind.admin.config import AdminConfig


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LocalMind Admin")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--data-dir", default=None)
    args = parser.parse_args(argv)

    config = AdminConfig(
        host=args.host or "0.0.0.0",
        port=args.port or 8000,
        data_dir=args.data_dir or "./data",
    )
    app = create_app(config)
    uvicorn.run(app, host=config.host, port=config.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
