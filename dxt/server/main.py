"""Shim entry point for the Desktop Extension (.dxt) package.

The manifest at the bundle root declares `entry_point: "server/main.py"`. The
actual MCP server lives in the `sciple-mcp` package on PyPI; we run it via
`uvx sciple-mcp` (configured in manifest.json's `mcp_config.command`). This
file exists to satisfy the manifest's entry_point reference and to surface a
useful error if Claude Desktop ever falls back to invoking the file directly
without `uv`/`uvx` available on PATH.
"""
from __future__ import annotations

import shutil
import sys


def main() -> int:
    if shutil.which("uvx") is None:
        sys.stderr.write(
            "sciple-mcp Desktop Extension requires `uv` (which provides `uvx`).\n"
            "Install once with:  curl -LsSf https://astral.sh/uv/install.sh | sh\n"
            "Then restart Claude Desktop.\n"
        )
        return 127

    try:
        from sciple_mcp.server import main as server_main
    except ImportError:
        sys.stderr.write(
            "sciple-mcp is not yet installed in the active environment.\n"
            "The Desktop Extension is configured to run `uvx sciple-mcp`, which "
            "fetches it from PyPI on demand — this fallback path means Claude "
            "invoked the entry_point Python file directly. Run `uvx sciple-mcp` "
            "from a terminal once to prime the cache.\n"
        )
        return 1
    server_main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
