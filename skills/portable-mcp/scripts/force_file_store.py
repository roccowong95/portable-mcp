#!/usr/bin/env python3
"""Retired mcpc patch. MCPorter has a native file vault; no source patch is needed."""
import sys

if __name__ == "__main__":
    print("FILE_STORE_PATCH_RETIRED: no package source was modified; migrate explicitly using the mcporter file-storage guide", file=sys.stderr)
    sys.exit(1)
