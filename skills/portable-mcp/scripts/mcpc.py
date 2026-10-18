#!/usr/bin/env python3
"""Stable skill-local entry. Forward argv/stdin/stdout without a shell or retries."""
import argparse
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

SCRIPTS = Path(__file__).resolve().parent
PACKAGE = SCRIPTS / ".runtime/node_modules/@apify/mcpc"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--state-dir", help="Private state outside the distributed skill; or set MCPC_HOME_DIR")
    p.add_argument("--node", help="Node executable; optional override after moving installation")
    p.add_argument("mcpc_args", nargs=argparse.REMAINDER, help="Use -- before mcpc arguments")
    args = p.parse_args()
    cli_args = args.mcpc_args
    if cli_args[:1] == ["--"]:
        cli_args = cli_args[1:]
    raw = args.state_dir or os.environ.get("MCPC_HOME_DIR")
    if not raw:
        raise RuntimeError("Specify --state-dir ABSOLUTE_PRIVATE_PATH or MCPC_HOME_DIR consistently")
    state_input = Path(raw).expanduser()
    if not state_input.is_absolute() or state_input.is_symlink():
        raise RuntimeError("State must be absolute and not a symlink")
    state = state_input.resolve()
    skill = SCRIPTS.parent
    if state == skill or skill in state.parents:
        raise RuntimeError("Keep credentials/state outside skill distribution directory")
    os.umask(0o077)
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name == "posix":
        st = state.stat()
        if st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077:
            raise RuntimeError("State must be owned by current user with no group/other access")
        credential = state / "credentials.json"
        if credential.is_symlink():
            raise RuntimeError("Refusing symlink credentials.json")
        if credential.exists():
            st = credential.stat()
            if st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077:
                raise RuntimeError("Existing credential file ownership/mode is not private")
    marker = SCRIPTS / ".runtime/skill-install.json"
    if not marker.is_file():
        raise RuntimeError("Runtime missing; run install_mcpc.py explicitly after approval")
    meta = json.loads(marker.read_text(encoding="utf-8"))
    pkg = json.loads((PACKAGE / "package.json").read_text(encoding="utf-8"))
    if meta.get("version") != "0.7.0" or pkg.get("name") != "@apify/mcpc" or pkg.get("version") != "0.7.0":
        raise RuntimeError("Pinned runtime mismatch; review version before use")
    chosen = args.node or meta.get("node") or "node"
    node = shutil.which(chosen)
    if not node or not Path(node).is_file():
        raise RuntimeError("Node not found; use --node /absolute/path/to/node")
    env = os.environ.copy()
    env["MCPC_HOME_DIR"] = str(state)
    # Deliberately inherit stdio; do not capture token-bearing login output in a log.
    # The operator/Agent must still use a private terminal for real OAuth callbacks.
    r = subprocess.run([str(node), str(PACKAGE / "dist/cli/index.js"), *cli_args], env=env)
    return r.returncode


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as e:
        print("MCPC_ENTRY_FAILED: " + str(e), file=sys.stderr)
        sys.exit(1)
