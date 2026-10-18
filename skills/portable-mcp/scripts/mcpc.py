#!/usr/bin/env python3
"""Retired mcpc entry: fail closed rather than reuse old credentials or runtime."""
import sys

if __name__ == "__main__":
    print("MCPC_RETIRED: use mcporter.py with a new private --state-dir; old runtime and credentials were not changed", file=sys.stderr)
    sys.exit(1)
