#!/usr/bin/env python3
"""Optional audited patch for an isolated @apify/mcpc 0.7.0 copy. Never migrates secrets."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ORIGINAL = "347235ccd693c74325fb37b49ec29a0b73128cc2d9c2cd42e55dd2ec18d93762"
PATCHED = "51fac25726f5d15a78882780bc657cdac13831e1b847b324b85394342370829c"
REPLACEMENT = ("async function ensureProbed() {\n"
               "    // Local deployment override: use mcpc built-in file storage, never OS keyring.\n"
               "    keychainAvailable = false;\n}")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--package", required=True, help="Isolated @apify/mcpc package directory")
    p.add_argument("--apply", action="store_true", help="Explicitly approve the source modification")
    args = p.parse_args()
    root = Path(args.package).expanduser().resolve(strict=True)
    meta = json.loads((root / "package.json").read_text(encoding="utf-8"))
    if meta.get("name") != "@apify/mcpc" or meta.get("version") != "0.7.0":
        raise RuntimeError("Only the audited @apify/mcpc 0.7.0 implementation is supported")
    target = root / "dist/lib/auth/keychain.js"
    if target.is_symlink():
        raise RuntimeError("Refusing symlink source file")
    data = target.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest == PATCHED:
        print("Already forced to file fallback (audited hash matches)")
        return
    if digest != ORIGINAL:
        raise RuntimeError("Source hash differs; refuse patch. Review this package implementation first")
    if not args.apply:
        print("Audited original hash matches. No change; --apply is required")
        return
    s = data.decode("utf-8")
    start = s.index("async function ensureProbed() {")
    end = s.index("\nasync function withKeychain(", start)
    out = (s[:start] + REPLACEMENT + s[end:]).encode("utf-8")
    if hashlib.sha256(out).hexdigest() != PATCHED:
        raise RuntimeError("Unexpected patched hash")
    os.umask(0o077)
    backup = target.with_name("keychain.js.before-file-store")
    with backup.open("xb") as f:
        f.write(data)
    # Not a transaction against concurrent package management; stop users of this copy first.
    if target.read_bytes() != data:
        raise RuntimeError("Source changed during preparation; stopped before patch")
    target.write_bytes(out)
    if hashlib.sha256(target.read_bytes()).hexdigest() != PATCHED:
        raise RuntimeError("Post-write verification failed")
    print("File fallback forced. Backup saved; no credentials read, copied, or printed")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError) as e:
        print("PATCH_FAILED: " + str(e), file=sys.stderr)
        sys.exit(1)
