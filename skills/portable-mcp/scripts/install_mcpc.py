#!/usr/bin/env python3
"""Explicit, per-skill pinned install. Never runs automatically during a call."""
import argparse
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

VERSION = "0.7.0"
DEFAULT_REGISTRY = "https://registry.npmmirror.com"
SCRIPTS = Path(__file__).resolve().parent
RUNTIME = SCRIPTS / ".runtime"
PACKAGE = RUNTIME / "node_modules" / "@apify" / "mcpc"


def node_version(node):
    r = subprocess.run([node, "--version"], capture_output=True, text=True, check=True)
    parts = tuple(int(x) for x in r.stdout.strip().lstrip("v").split(".")[:3])
    if parts < (22, 12, 0):
        raise RuntimeError("Node.js >=22.12.0 required for the pinned mcpc baseline")
    return r.stdout.strip()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--node", help="Node executable; defaults to PATH")
    p.add_argument("--npm-cli", help="npm-cli.js path; useful when npm.cmd cannot be directly executed")
    p.add_argument("--registry", default=DEFAULT_REGISTRY,
                   help=f"npm registry for the pinned package (default: {DEFAULT_REGISTRY})")
    args = p.parse_args()
    registry = args.registry.strip().rstrip("/")
    if not registry.startswith("https://"):
        raise RuntimeError("Registry must be an https:// URL; use --registry to override")
    node = shutil.which(args.node or "node")
    if not node:
        raise RuntimeError("Node not found; install a supported Node runtime first")
    node = str(Path(node).resolve())
    version = node_version(node)
    if RUNTIME.is_symlink():
        raise RuntimeError("Refusing symlink runtime directory")
    if RUNTIME.exists() and any(RUNTIME.iterdir()):
        marker = RUNTIME / "skill-install.json"
        if marker.exists() and (PACKAGE / "package.json").exists():
            meta = json.loads(marker.read_text(encoding="utf-8"))
            pkg = json.loads((PACKAGE / "package.json").read_text(encoding="utf-8"))
            if meta.get("version") == VERSION and pkg.get("name") == "@apify/mcpc" and pkg.get("version") == VERSION:
                subprocess.run([node, str(PACKAGE / "dist/cli/index.js"), "--version"], check=True)
                print("Pinned runtime already installed; no install or upgrade performed")
                return
        raise RuntimeError("Runtime not empty or incomplete; inspect it, do not overwrite blindly")
    os.umask(0o077)
    RUNTIME.mkdir(mode=0o700, exist_ok=True)
    npm = shutil.which("npm")
    if args.npm_cli:
        npm_argv = [node, str(Path(args.npm_cli).resolve(strict=True))]
    elif os.name == "nt":
        candidates = []
        if npm:
            candidates.append(Path(npm).parent / "node_modules/npm/bin/npm-cli.js")
        candidates.extend([Path(node).parent / "node_modules/npm/bin/npm-cli.js",
                           Path(node).parent.parent / "node_modules/npm/bin/npm-cli.js"])
        cli = next((c for c in candidates if c.is_file()), None)
        if not cli:
            raise RuntimeError("Locate npm-cli.js and retry with --npm-cli; no shell=True fallback")
        npm_argv = [node, str(cli)]
    else:
        if not npm:
            raise RuntimeError("npm missing; provide --npm-cli /path/to/npm-cli.js")
        npm_argv = [npm]
    # Distinct private configs avoid unrelated user/global npm config mutation.
    # Inherits proxy/registry environment settings; registry auth is not bundled.
    for name in ("npm-user.conf", "npm-global.conf"):
        (RUNTIME / name).write_text("", encoding="utf-8")
    env = os.environ.copy()
    # npm's POSIX shebang is commonly /usr/bin/env node; pin that resolution too.
    env["PATH"] = str(Path(node).parent) + os.pathsep + env.get("PATH", "")
    env.update({"npm_config_userconfig": str(RUNTIME / "npm-user.conf"),
                "npm_config_globalconfig": str(RUNTIME / "npm-global.conf"),
                "npm_config_cache": str(RUNTIME / "npm-cache")})
    subprocess.run(npm_argv + ["install", "--prefix", str(RUNTIME), "--save-exact",
                               "--ignore-scripts", "--no-audit", "--no-fund",
                               "--registry", registry,
                               "@apify/mcpc@" + VERSION], env=env, check=True)
    pkg = json.loads((PACKAGE / "package.json").read_text(encoding="utf-8"))
    if pkg.get("name") != "@apify/mcpc" or pkg.get("version") != VERSION:
        raise RuntimeError("Installed package version/name mismatch")
    subprocess.run([node, str(PACKAGE / "dist/cli/index.js"), "--version"], check=True)
    meta = {"version": VERSION, "node": node, "nodeVersion": version,
            "installedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "installScripts": False}
    (RUNTIME / "skill-install.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"Installed per-skill runtime from {registry}; package-lock.json retained. No MCP connected.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as e:
        print("INSTALL_FAILED: " + str(e), file=sys.stderr)
        sys.exit(1)
