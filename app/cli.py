from __future__ import annotations

import argparse
import os

import uvicorn

from . import __version__
from .config import load_settings


def build_parser() -> argparse.ArgumentParser:
    settings = load_settings()
    parser = argparse.ArgumentParser(
        prog="ocs-llm-answerer",
        description="Local LLM-backed answerer for OCS (AnswererWrapper protocol).",
    )
    parser.add_argument("--host", default=settings.host, help="Bind address (default: %(default)s)")
    parser.add_argument("--port", type=int, default=settings.port, help="Bind port (default: %(default)s)")
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable Uvicorn auto-reload for local development.",
    )
    parser.add_argument(
        "--log-level",
        default=settings.log_level.lower(),
        help="Uvicorn log level (default: %(default)s)",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    # 让运行中的 /api/config 和 OCS 配置生成能反映 CLI 传入的地址/端口。
    os.environ["HOST"] = args.host
    os.environ["PORT"] = str(args.port)
    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    main()
