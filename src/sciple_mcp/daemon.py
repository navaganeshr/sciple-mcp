"""`sciple-mcp install` — drop a launchd plist so `serve` runs at login.

macOS-only. The plist lives at `~/Library/LaunchAgents/cloud.sciple.mcp.plist`
and runs `sciple-mcp serve` as the logged-in user. Standard `brew services`
pattern.

`uninstall` is the symmetric cleanup. Both are idempotent.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

PLIST_LABEL = "cloud.sciple.mcp"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{PLIST_LABEL}.plist"
DEFAULT_PORT = 8765
DEFAULT_LOG_DIR = Path.home() / "Library" / "Logs" / "sciple-mcp"


PLIST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{executable}</string>
        <string>serve</string>
        <string>--host</string>
        <string>127.0.0.1</string>
        <string>--port</string>
        <string>{port}</string>
        <string>--platform-url</string>
        <string>{platform_url}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{stdout}</string>
    <key>StandardErrorPath</key>
    <string>{stderr}</string>
</dict>
</plist>
"""


def _executable() -> str:
    """Path that the plist should invoke.

    Prefers an `sciple-mcp` on PATH so `uv tool install`d installs work.
    Falls back to `<sys.executable> -m sciple_mcp.server` for editable
    installs / venv runs.
    """
    found = shutil.which("sciple-mcp")
    return found or f"{sys.executable} -m sciple_mcp.server"


def install(port: int, platform_url: str) -> None:
    if sys.platform != "darwin":
        raise RuntimeError("`sciple-mcp install` is macOS-only (launchd).")

    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_LOG_DIR.mkdir(parents=True, exist_ok=True)

    plist = PLIST_TEMPLATE.format(
        label=PLIST_LABEL,
        executable=_executable(),
        port=port,
        platform_url=platform_url,
        stdout=str(DEFAULT_LOG_DIR / "stdout.log"),
        stderr=str(DEFAULT_LOG_DIR / "stderr.log"),
    )
    PLIST_PATH.write_text(plist, encoding="utf-8")
    os.chmod(PLIST_PATH, 0o644)

    # Unload (ignoring errors — fine if not loaded) then load. `bootstrap`
    # is the modern verb; fall back to `load` for older macOS.
    uid = os.getuid()
    subprocess.run(
        ["launchctl", "bootout", f"gui/{uid}", str(PLIST_PATH)],
        capture_output=True, check=False,
    )
    result = subprocess.run(
        ["launchctl", "bootstrap", f"gui/{uid}", str(PLIST_PATH)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        # Fallback for older launchctl versions.
        subprocess.run(["launchctl", "load", "-w", str(PLIST_PATH)], check=True)


def uninstall() -> None:
    if sys.platform != "darwin":
        raise RuntimeError("`sciple-mcp uninstall` is macOS-only (launchd).")

    uid = os.getuid()
    if PLIST_PATH.exists():
        subprocess.run(
            ["launchctl", "bootout", f"gui/{uid}", str(PLIST_PATH)],
            capture_output=True, check=False,
        )
        subprocess.run(
            ["launchctl", "unload", str(PLIST_PATH)],
            capture_output=True, check=False,
        )
        PLIST_PATH.unlink()


# ── CLI ────────────────────────────────────────────────────────────────


def main_install(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sciple-mcp install",
        description="Install a launchd agent so `sciple-mcp serve` runs at login.",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--platform-url", default="http://localhost:5175")
    args = parser.parse_args(argv)

    try:
        install(port=args.port, platform_url=args.platform_url)
    except Exception as exc:
        print(f"  ❌ install failed: {exc}", file=sys.stderr)
        return 1
    print(f"  ✅ installed launchd agent at {PLIST_PATH}")
    print(f"  serving on http://127.0.0.1:{args.port}/mcp")
    print(f"  logs:  {DEFAULT_LOG_DIR}")
    return 0


def main_uninstall(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(
        prog="sciple-mcp uninstall",
        description="Remove the sciple-mcp launchd agent.",
    ).parse_args(argv)

    try:
        uninstall()
    except Exception as exc:
        print(f"  ❌ uninstall failed: {exc}", file=sys.stderr)
        return 1
    print(f"  ✅ removed {PLIST_PATH}")
    return 0
