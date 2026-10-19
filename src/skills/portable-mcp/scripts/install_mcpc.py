#!/usr/bin/env python3
"""Retired installer: intentionally does not modify Node, old runtime or secrets."""
import sys

if __name__ == "__main__":
    print("MCPC_INSTALL_RETIRED: use install_runtime.py explicitly; Node is never upgraded and the old runtime is preserved", file=sys.stderr)
    sys.exit(1)
