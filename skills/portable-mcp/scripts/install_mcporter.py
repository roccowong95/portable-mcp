#!/usr/bin/env python3
"""Explicit skill-local mcporter install; never upgrades Node or runs during calls.

Requires Python 3.9+, an existing Node and npm's own semver. The default reuses a
valid compatible installation without network access. --update explicitly selects
the newest compatible stable release; --version selects a validated exact release.
"""
import argparse
from contextlib import contextmanager
import datetime
import errno
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

SCRIPTS = Path(__file__).resolve().parent
RUNTIME_PARENT = SCRIPTS / ".runtime"
RUNTIME = RUNTIME_PARENT / "mcporter"
PACKAGE_REL = Path("node_modules/mcporter")
CLI_REL = "node_modules/mcporter/dist/cli.js"
HELPER = SCRIPTS / "mcporter_versions.cjs"
MARKER_NAME = "skill-install.json"
MAX_METADATA_BYTES = 64 * 1024 * 1024


@contextmanager
def install_lock(timeout=30):
    """Serialize install/promotion and CLI use; callers hold this for whole use.

    The lock file is permanent (never unlink it: that would permit inode races).
    OS locks are released on process exit, unlike stale exclusive-create locks.
    --check intentionally does not acquire this filesystem-mutating lock.
    """
    if RUNTIME_PARENT.is_symlink():
        raise RuntimeError("Refusing symlink runtime parent")
    RUNTIME_PARENT.mkdir(mode=0o700, exist_ok=True)
    lock_path = RUNTIME_PARENT / ".mcporter-install.lock"
    if lock_path.is_symlink() or (lock_path.exists() and not lock_path.is_file()):
        raise RuntimeError("Runtime lock must be a regular non-symlink file")
    flags = (os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
             | getattr(os, "O_NONBLOCK", 0))
    descriptor = os.open(str(lock_path), flags, 0o600)
    locked = False
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise RuntimeError("Runtime lock must be a regular file")
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"\0")
        deadline = time.monotonic() + timeout
        while True:
            try:
                os.lseek(descriptor, 0, os.SEEK_SET)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                if time.monotonic() >= deadline:
                    raise RuntimeError("mcporter runtime is busy; retry after the active command or installer exits") from None
                time.sleep(0.1)
        yield
    finally:
        try:
            if locked:
                os.lseek(descriptor, 0, os.SEEK_SET)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def run_json(command, payload, env):
    result = subprocess.run(command, input=json.dumps(payload), capture_output=True,
                            text=True, env=env, shell=False, timeout=60)
    if result.returncode:
        # The helper prints fixed errors, not registry metadata or tokens.
        raise RuntimeError(result.stderr.strip() or "npm semver helper failed")
    value = json.loads(result.stdout)
    if not isinstance(value, dict) or not isinstance(value.get("version"), str):
        raise RuntimeError("Unexpected npm semver helper response")
    return value


def safe_env(node):
    # Do not inherit global installs, force/ignore-engines, alternate lockfile
    # policy, user configs, lifecycle hooks or Node preload/search overrides.
    env = {key: value for key, value in os.environ.items()
           if not key.lower().startswith(("npm_config_", "npm_package_", "npm_lifecycle_"))
           and key.upper() not in ("NODE_OPTIONS", "NODE_PATH")}
    env["PATH"] = str(Path(node).parent) + os.pathsep + env.get("PATH", "")
    return env


def resolve_node(requested):
    found = shutil.which(requested or "node")
    if not found:
        raise RuntimeError("Node not found; select an existing runtime with --node. Node will not be installed or upgraded")
    node = str(Path(found).resolve(strict=True))
    result = subprocess.run([node, "--version"], capture_output=True, text=True,
                            check=True, shell=False, timeout=30, env=safe_env(node))
    return node, result.stdout.strip()


def resolve_npm_cli(node, requested, previous):
    if requested:
        cli = Path(requested).expanduser().resolve(strict=True)
        if not cli.is_file() or cli.name != "npm-cli.js":
            raise RuntimeError("--npm-cli must identify an existing npm-cli.js file")
        return str(cli)
    candidates = []
    for name in ("npm", "npm.cmd"):
        found = shutil.which(name)
        if found:
            executable = Path(found)
            # On POSIX npm is normally a symlink to npm/bin/npm-cli.js.
            candidates.append(executable.resolve())
            candidates.append(executable.parent / "node_modules/npm/bin/npm-cli.js")
            candidates.append(executable.parent.parent / "lib/node_modules/npm/bin/npm-cli.js")
    node_dir = Path(node).parent
    candidates.extend([node_dir / "node_modules/npm/bin/npm-cli.js",
                       node_dir.parent / "lib/node_modules/npm/bin/npm-cli.js",
                       node_dir.parent / "node_modules/npm/bin/npm-cli.js"])
    if previous and isinstance(previous.get("npmCli"), str):
        candidates.append(Path(previous["npmCli"]))
    for candidate in candidates:
        if candidate.name == "npm-cli.js" and candidate.is_file():
            return str(candidate.resolve(strict=True))
    raise RuntimeError("Cannot locate npm-cli.js; specify --npm-cli /absolute/path/to/npm-cli.js (no shell fallback)")


def read_object(path):
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Expected regular non-symlink JSON file: " + str(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("Expected a JSON object: " + str(path))
    return data


def previous_install():
    if RUNTIME_PARENT.is_symlink() or RUNTIME.is_symlink():
        raise RuntimeError("Refusing symlink runtime directory")
    if not RUNTIME.exists():
        return None
    if not RUNTIME.is_dir():
        raise RuntimeError("Runtime path exists but is not a directory")
    # Never replace an unmarked, partial or unknown directory, even on --update.
    marker = read_object(RUNTIME / MARKER_NAME)
    if (marker.get("schemaVersion") != 1 or marker.get("package") != "mcporter"
            or marker.get("cli") != CLI_REL or not isinstance(marker.get("version"), str)):
        raise RuntimeError("Unrecognized mcporter install marker; inspect runtime manually, do not overwrite it")
    pkg = read_object(RUNTIME / PACKAGE_REL / "package.json")
    if pkg.get("name") != "mcporter" or pkg.get("version") != marker["version"]:
        raise RuntimeError("Installed package does not match mcporter marker; inspect runtime manually")
    cli = RUNTIME / CLI_REL
    if cli.is_symlink() or not cli.is_file():
        raise RuntimeError("Installed mcporter CLI is missing or a symlink")
    return marker


def validate_registry(raw):
    if not isinstance(raw, str):
        raise RuntimeError("Registry must be an HTTPS URL")
    raw = raw.strip()
    parsed = urllib.parse.urlsplit(raw)
    if (parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment
            or "\\" in raw or any(ord(char) < 33 for char in raw)):
        raise RuntimeError("Registry must be an HTTPS URL without credentials, query or fragment")
    # Validate malformed ports now, without including the URL in error output.
    try:
        parsed.port
    except ValueError:
        raise RuntimeError("Invalid registry port") from None
    return raw.rstrip("/") + "/"


def configured_registry(explicit, npm_cli, node):
    if explicit:
        return validate_registry(explicit)
    # Read only: honor operator-configured registry before isolating installation
    # configs. Never copy auth/config contents into the skill or its marker.
    env = os.environ.copy()
    env.pop("NODE_OPTIONS", None)
    env.pop("NODE_PATH", None)
    result = subprocess.run([node, npm_cli, "config", "get", "registry",
                             "--logs-max=0", "--update-notifier=false"],
                            cwd=str(SCRIPTS), env=env, capture_output=True, text=True,
                            shell=False, timeout=30)
    if result.returncode:
        raise RuntimeError("Cannot read configured npm registry; use --registry https://registry.npmjs.org/")
    return validate_registry(result.stdout)


class HTTPSRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # urllib otherwise permits an HTTPS -> HTTP metadata downgrade.
        validate_registry(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_versions(registry):
    request = urllib.request.Request(registry + "mcporter", headers={
        "Accept": "application/json",  # Full packument, including deprecations/engines.
        "User-Agent": "portable-mcp-mcporter-installer/1"})
    try:
        with urllib.request.build_opener(HTTPSRedirectHandler()).open(request, timeout=60) as response:
            body = response.read(MAX_METADATA_BYTES + 1)
    except (urllib.error.URLError, OSError):
        raise RuntimeError("Cannot fetch HTTPS mcporter metadata from configured registry (no auth is copied); check connectivity/registry") from None
    if len(body) > MAX_METADATA_BYTES:
        raise RuntimeError("Registry metadata exceeds the 64 MiB safety limit")
    metadata = json.loads(body)
    if (not isinstance(metadata, dict) or metadata.get("name") != "mcporter"
            or not isinstance(metadata.get("versions"), dict)):
        raise RuntimeError("Registry response is not full mcporter metadata")
    # All remote fields remain untrusted data, used only by the semver helper.
    return metadata["versions"]


def verify_package(directory, expected, node_version, helper_command, env):
    pkg = read_object(directory / PACKAGE_REL / "package.json")
    if pkg.get("name") != "mcporter" or pkg.get("version") != expected:
        raise RuntimeError("Installed mcporter package name/version mismatch")
    result = run_json(helper_command + ["check-installed"],
                      {"nodeVersion": node_version, "package": pkg}, env)
    cli = directory / CLI_REL
    if cli.is_symlink() or not cli.is_file():
        raise RuntimeError("mcporter dist/cli.js is missing or a symlink")
    return result


def install_staged(version, selection, registry, node, node_version, npm_cli, helper_command, env):
    os.umask(0o077)
    RUNTIME_PARENT.mkdir(mode=0o700, exist_ok=True)
    if RUNTIME_PARENT.is_symlink():
        raise RuntimeError("Refusing symlink runtime parent")
    stage = RUNTIME_PARENT / (".mcporter-stage-" + uuid.uuid4().hex)
    stage.mkdir(mode=0o700)
    print("Preparing private staging runtime: " + str(stage), flush=True)
    # Failed staging directories are retained for manual inspection, never blindly
    # removed. Existing/legacy runtimes and user temporary files are untouched.
    try:
        # Empty project config stops npm walking up to an unrelated .npmrc.
        for filename in ("npm-user.conf", "npm-global.conf", ".npmrc"):
            (stage / filename).write_text("", encoding="utf-8")
        (stage / "package.json").write_text(json.dumps({
            "name": "portable-mcporter-runtime", "version": "1.0.0", "private": True
        }, indent=2) + "\n", encoding="utf-8")
        install_env = env.copy()
        install_env.update({
            "npm_config_userconfig": str(stage / "npm-user.conf"),
            "npm_config_globalconfig": str(stage / "npm-global.conf"),
            "npm_config_cache": str(stage / "npm-cache"),
            "npm_config_update_notifier": "false",
        })
        npm_version = subprocess.run([node, npm_cli, "--version"], env=install_env,
                                     cwd=str(stage), capture_output=True, text=True,
                                     check=True, shell=False, timeout=30).stdout.strip()
        # Strict transitive engines are intentional. A compatible root package may
        # still have incompatible current dependencies: fail, do not retry with
        # --force/ignore-engines, pick another release, or change the host Node.
        subprocess.run([node, npm_cli, "install", "--prefix", str(stage),
                        "--global=false", "--workspaces=false", "--save-exact",
                        "--package-lock=true", "--ignore-scripts", "--engine-strict",
                        "--no-audit", "--no-fund", "--omit=dev", "--registry", registry,
                        "mcporter@" + version], cwd=str(stage), env=install_env,
                       check=True, shell=False)
        verified = verify_package(stage, version, node_version, helper_command, env)
        if verified["engineRange"] != selection["engineRange"]:
            raise RuntimeError("Installed engines.node differs from selected registry metadata")
        manifest = read_object(stage / "package.json")
        lock = read_object(stage / "package-lock.json")
        locked = lock.get("packages", {}).get("node_modules/mcporter", {})
        if manifest.get("dependencies", {}).get("mcporter") != version or locked.get("version") != version:
            raise RuntimeError("Exact mcporter dependency/package-lock verification failed")
        marker = {
            "schemaVersion": 1, "package": "mcporter", "version": version,
            "nodeVersion": node_version, "nodeExecutable": node, "npmCli": npm_cli,
            "npmVersion": npm_version, "registry": registry,
            "engineRange": verified["engineRange"], "cli": CLI_REL,
            "installedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "installScripts": False,
        }
        marker_tmp = stage / (MARKER_NAME + ".tmp")
        marker_tmp.write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")
        marker_tmp.replace(stage / MARKER_NAME)
    except Exception:
        print("Staging failed; existing runtime unchanged. Inspect retained directory: " + str(stage), file=sys.stderr)
        raise
    return stage


def promote(stage, previous):
    # Only same-parent renames: an update never changes a live marked runtime
    # until the new package and marker are complete. Keep backup for rollback.
    if previous is None:
        if RUNTIME.exists() or RUNTIME.is_symlink():
            raise RuntimeError("Runtime appeared during installation; staging retained, refusing overwrite")
        stage.rename(RUNTIME)
        return
    if previous_install() != previous:
        raise RuntimeError("Runtime changed during installation; refusing update")
    backup = RUNTIME_PARENT / (".mcporter-backup-" + uuid.uuid4().hex)
    RUNTIME.rename(backup)
    try:
        stage.rename(RUNTIME)
    except OSError as error:
        try:
            backup.rename(RUNTIME)
        except OSError:
            raise RuntimeError("Promotion and rollback failed; restore retained backup manually: " + str(backup)) from error
        raise RuntimeError("Promotion failed; previous runtime restored; staging retained") from error
    print("Previous runtime retained at: " + str(backup))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", help="Existing Node executable; defaults to PATH (never upgraded)")
    parser.add_argument("--npm-cli", help="Existing npm-cli.js; executed through the selected Node, never a shell")
    parser.add_argument("--registry", help="HTTPS npm registry; defaults to npm config get registry")
    parser.add_argument("--version", help="Exact stable mcporter version >=0.9.0, checked against actual Node")
    parser.add_argument("--update", action="store_true", help="Explicitly select and stage a compatible update")
    parser.add_argument("--check", action="store_true", help="Select/report without installing or changing files")
    args = parser.parse_args()
    if args.check:
        return main_locked(args)
    # Set before creating the parent/lock too, not only the staging directory.
    os.umask(0o077)
    with install_lock():
        return main_locked(args)


def main_locked(args):
    previous = previous_install()
    node, node_version = resolve_node(args.node)
    npm_cli = resolve_npm_cli(node, args.npm_cli, previous)
    env = safe_env(node)
    helper_command = [node, str(HELPER), "--npm-cli", npm_cli]
    if previous and not args.update:
        if previous.get("nodeVersion") != node_version:
            raise RuntimeError("Node version differs from installed runtime marker; use --update to stage strict transitive-engine revalidation (Node itself is never changed)")
        verified = verify_package(RUNTIME, previous["version"], node_version, helper_command, env)
        if args.version is not None and args.version != verified["version"]:
            raise RuntimeError("A different runtime is already installed; use --update --version EXACT to replace explicitly")
        print(json.dumps({"status": "already-installed", "version": verified["version"],
                          "nodeVersion": node_version, "engineRange": verified["engineRange"],
                          "cli": str(RUNTIME / CLI_REL), "network": False}))
        return 0
    # Validate actual Node and npm semver before any network access. The synthetic
    # package is local data, never interpreted as a selected registry release.
    run_json(helper_command + ["check-installed"], {
        "nodeVersion": node_version,
        "package": {"name": "mcporter", "version": "0.9.0", "engines": {"node": "*"}},
    }, env)
    registry = configured_registry(args.registry, npm_cli, node)
    payload = {"nodeVersion": node_version, "versions": fetch_versions(registry)}
    if args.version is not None:
        payload["requestedVersion"] = args.version
    selected = run_json(helper_command + ["select"], payload, env)
    print(json.dumps({"status": "selected", "version": selected["version"],
                      "nodeVersion": node_version, "engineRange": selected["engineRange"],
                      "registry": registry, "checkOnly": args.check}), flush=True)
    if args.check:
        return 0
    stage = install_staged(selected["version"], selected, registry, node, node_version,
                           npm_cli, helper_command, env)
    promote(stage, previous)
    print("Installed private mcporter runtime; exact package-lock retained. No MCP connected and Node unchanged.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        print("MCPORTER_INSTALL_FAILED: " + str(error), file=sys.stderr)
        sys.exit(1)
