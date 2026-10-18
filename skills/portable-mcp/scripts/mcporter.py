#!/usr/bin/env python3
"""Private, version-independent MCPorter entry. Never installs or upgrades Node."""
import argparse
from contextlib import contextmanager, nullcontext
from install_mcporter import install_lock, resolve_npm_cli, safe_env
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import time

SCRIPTS = Path(__file__).resolve().parent
RUNTIME = SCRIPTS / ".runtime" / "mcporter"
PACKAGE = RUNTIME / "node_modules" / "mcporter"
MAX_CONFIG = 1024 * 1024
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def fail(message):
    raise RuntimeError(message)


def no_links(path):
    for item in (path, *path.parents):
        if item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction()):
            fail("Symlinks/junctions are not allowed in private state paths")


def private_path(path, directory=False):
    no_links(path)
    info = path.stat()
    if directory != stat.S_ISDIR(info.st_mode):
        fail("Private state contains an unexpected file type")
    if not directory and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
        fail("Private state files must be regular single-link files")
    if os.name == "posix" and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077):
        fail("Private state must be owned by this user: directories 0700, files 0600")


def windows_acl(root):
    # Read-only verification, never silently rewrite an existing ACL. Administrators
    # and SYSTEM remain trusted. Protect the directory before storing credentials.
    script = r"""
$ErrorActionPreference='Stop'
$root=$env:PMCP_ACL_ROOT
$sid=[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$allowed=@($sid,'S-1-5-18','S-1-5-32-544')
$items=@(Get-Item -LiteralPath $root -Force)+@(Get-ChildItem -LiteralPath $root -Recurse -Force)
foreach($item in $items){
 if(($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0){throw 'reparse'}
 $acl=Get-Acl -LiteralPath $item.FullName
 if($item.FullName -eq $root -and -not $acl.AreAccessRulesProtected){throw 'inheritance'}
 if($acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value -notin $allowed){throw 'owner'}
 foreach($rule in $acl.GetAccessRules($true,$true,[System.Security.Principal.SecurityIdentifier])){
  if($rule.AccessControlType -eq 'Allow' -and $rule.IdentityReference.Value -notin $allowed){throw 'access'}
 }
}
"""
    exe = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    env = os.environ.copy()
    env["PMCP_ACL_ROOT"] = str(root)
    result = subprocess.run([str(exe), "-NoProfile", "-NonInteractive", "-Command", script],
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode:
        fail("Windows private ACL check failed; pre-create a protected current-user-only state directory")


def check_tree(root):
    private_path(root, directory=True)
    for base, dirs, files in os.walk(root, followlinks=False):
        for name in dirs:
            private_path(Path(base) / name, directory=True)
        for name in files:
            private_path(Path(base) / name)
    if os.name == "nt":
        windows_acl(root)


def prepare_state(raw):
    if not raw:
        fail("Specify --state-dir ABSOLUTE_PRIVATE_PATH or PMCP_STATE_DIR consistently")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        fail("State directory must be absolute")
    no_links(path)
    state = path.resolve()
    skill = SCRIPTS.parent
    if state == skill or skill in state.parents:
        fail("Keep state and credentials outside the distributed skill")
    os.umask(0o077)
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    check_tree(state)
    for folder in ("home", "config", "data", "cache", "state", "broker"):
        (state / folder).mkdir(mode=0o700, exist_ok=True)
    return state


@contextmanager
def profile_lock(state, timeout):
    """OS lock survives crashes without stale-directory guessing; all entry calls serialize."""
    path = state / ".pmcp.lock"
    if path.exists():
        private_path(path)
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(str(path), flags, 0o600)
    stream = os.fdopen(fd, "r+b")
    held = False
    try:
        private_path(path)
        if os.fstat(stream.fileno()).st_size == 0:
            stream.write(b"\0")
            stream.flush()
        end = time.monotonic() + timeout
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                held = True
                break
            except (BlockingIOError, OSError):
                if time.monotonic() >= end:
                    fail("Profile is busy; no request was dispatched (do not bypass the lock)")
                time.sleep(0.1)
        yield
    finally:
        if held:
            if os.name == "nt":
                import msvcrt
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


def read_config(path):
    private_path(path)
    if path.stat().st_size > MAX_CONFIG:
        fail("Configuration exceeds 1 MiB")
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                fail("Duplicate configuration keys are not allowed")
            obj[key] = value
        return obj
    data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    if (not isinstance(data, dict) or data.get("imports") != [] or
            set(data) - {"imports", "mcpServers"}):
        fail('Configuration supports only mcpServers and explicit "imports": []')
    entries = data.get("mcpServers")
    if not isinstance(entries, dict):
        fail("Configuration must contain an mcpServers object")
    for name, entry in entries.items():
        if not NAME.fullmatch(name) or not isinstance(entry, dict):
            fail("Invalid named server definition")
        lifecycle = entry.get("lifecycle")
        if lifecycle != "ephemeral" and lifecycle != {"mode": "ephemeral"}:
            fail("Every server must explicitly set lifecycle ephemeral; keep-alive is not enabled")
        if "cwd" in entry:
            cwd = entry["cwd"]
            if (not isinstance(cwd, str) or not Path(cwd).is_absolute() or
                    not Path(cwd).is_dir() or not entry.get("command") or
                    any(key in entry for key in ("url", "baseUrl", "serverUrl"))):
                fail("cwd is supported only for stdio and must be an existing absolute directory")
        if "tokenCacheDir" in entry or "token_cache_dir" in entry:
            fail("Use the private shared vault; per-server tokenCacheDir is not supported")
        if entry.get("auth") not in (None, "oauth"):
            fail("Only ordinary HTTP headers or OAuth authentication are supported")
        for field in ("env", "headers"):
            values = entry.get(field, {})
            if not isinstance(values, dict):
                fail("Server environment/headers must be objects")
            if field == "env":
                for key in values:
                    if key.upper() in {"HOME", "USERPROFILE", "NODE_OPTIONS"} or key.upper().startswith(("XDG_", "MCPORTER_", "PMCP_")):
                        fail("Server environment cannot override portable isolation or runtime controls")
        if any(key in entry for key in ("record", "recording", "replay", "refreshable_bearer", "refresh")):
            fail("Recording/replay and refreshable bearer extensions are not supported")
    return data


def check_vault_json(state):
    # Legacy vault readers swallow parse failures and can overwrite an empty
    # replacement. Reject known corrupt vaults before *any* backend command.
    # This does not make legacy writes atomic or repair crash damage.
    for path in (state / "home" / ".mcporter" / "credentials.json",
                 state / "data" / "mcporter" / "credentials.json"):
        if not path.exists():
            continue
        private_path(path)
        if path.stat().st_size > 16 * 1024 * 1024:
            fail("Private vault exceeds safety limit; inspect privately, do not reset or replay automatically")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            fail("Private vault is unreadable or corrupt; preserve it and recover privately, no automatic reset")
        if not isinstance(value, dict):
            fail("Private vault has an invalid structure; preserve it and recover privately")


def child_environment(state):
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith(("MCPORTER_", "XDG_", "PMCP_"))
           and key.upper() not in {"NODE_OPTIONS", "NODE_PATH"}}
    env.update({"HOME": str(state / "home"), "USERPROFILE": str(state / "home"),
                "XDG_CONFIG_HOME": str(state / "config"), "XDG_DATA_HOME": str(state / "data"),
                "XDG_CACHE_HOME": str(state / "cache"), "XDG_STATE_HOME": str(state / "state"),
                "MCPORTER_DAEMON_DIR": str(state / "broker"),
                "MCPORTER_CONFIG": str(state / "config" / "mcporter.json"),
                "MCPORTER_LOG_LEVEL": "error", "MCPORTER_NO_FORCE_EXIT": "1",
                "MCPORTER_DISABLE_KEEPALIVE": "*"})
    return env


def runtime(node_override):
    meta = json.loads((RUNTIME / "skill-install.json").read_text(encoding="utf-8"))
    pkg = json.loads((PACKAGE / "package.json").read_text(encoding="utf-8"))
    if (meta.get("schemaVersion") != 1 or meta.get("package") != "mcporter" or
            meta.get("version") != pkg.get("version") or pkg.get("name") != "mcporter" or
            meta.get("cli") != "node_modules/mcporter/dist/cli.js"):
        fail("Installed runtime does not match its installation record; reinstall explicitly")
    chosen = shutil.which(node_override or meta.get("nodeExecutable") or "node")
    if not chosen:
        fail("Node executable missing; use --node with the existing compatible Node")
    node = str(Path(chosen).resolve(strict=True))
    env = safe_env(node)
    version = subprocess.run([node, "--version"], check=True, capture_output=True,
                             text=True, env=env, timeout=30).stdout.strip()
    if version != meta.get("nodeVersion"):
        fail("Node version changed; explicitly run installer --update to revalidate transitive engines (Node is never upgraded)")
    # Locate npm again after relocation; do not embed any package version in the entry.
    npm_cli = resolve_npm_cli(node, None, meta)
    helper = [node, str(SCRIPTS / "mcporter_versions.cjs"), "--npm-cli", npm_cli, "check-installed"]
    result = subprocess.run(helper, input=json.dumps({"nodeVersion": version, "package": pkg}),
                            capture_output=True, text=True, env=env, timeout=60)
    if result.returncode:
        fail("Installed mcporter is incompatible with this Node, or npm semver is unavailable; run installer explicitly")
    return node, pkg["version"]


def execute(argv, env, deadline):
    """Inherit private input/output; never log tokens or replay a failed call."""
    kwargs = {"env": env}
    if os.name == "posix":
        kwargs["start_new_session"] = True
    process = subprocess.Popen(argv, **kwargs)
    try:
        return process.wait(timeout=deadline)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
            # Parent exit is not proof its stdio descendants exited. Always reap
            # the remaining group before releasing either credential/runtime lock.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            exe = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/taskkill.exe"
            subprocess.run([str(exe), "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        process.wait()
        fail("Request interrupted or timed out; outcome may be unknown. It was NOT replayed")


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--state-dir", default=os.environ.get("PMCP_STATE_DIR"))
    p.add_argument("--node", help="Existing Node executable; never installed or upgraded")
    p.add_argument("--lock-timeout", type=float, default=30)
    p.add_argument("--timeout", type=int, default=60000, help="Operation timeout in milliseconds")
    sub = p.add_subparsers(dest="command", required=True)
    for op in ("init", "version", "servers", "doctor"):
        sub.add_parser(op)
    tools = sub.add_parser("tools")
    tools.add_argument("server")
    tools.add_argument("--query", help="Literal case-insensitive name/description substring")
    for op in ("schema", "call"):
        cmd = sub.add_parser(op)
        cmd.add_argument("server")
        cmd.add_argument("tool")
    auth = sub.add_parser("auth")
    auth.add_argument("server")
    auth.add_argument("--reset", action="store_true")
    auth.add_argument("--no-browser", action="store_true")
    auth.add_argument("--allow-legacy-oauth", action="store_true",
                      help="Explicitly accept v0.9's known callback state validation risk")
    logout = sub.add_parser("logout")
    logout.add_argument("server")
    return p


def main():
    args = parser().parse_args()
    if not 0 <= args.lock_timeout <= 600 or not 100 <= args.timeout <= 900000:
        fail("Lock timeout must be 0..600 seconds; operation timeout 100..900000 ms")
    state = prepare_state(args.state_dir)
    config = state / "config" / "mcporter.json"
    with profile_lock(state, args.lock_timeout), (nullcontext() if args.command == "init" else install_lock(args.lock_timeout)):
        if args.command == "init":
            if not config.exists():
                with config.open("x", encoding="utf-8") as stream:
                    json.dump({"mcpServers": {}, "imports": []}, stream, indent=2)
                    stream.write("\n")
            read_config(config)
            print(json.dumps({"initialized": True, "config": str(config)}))
            return 0
        check_tree(state)
        check_vault_json(state)
        data = read_config(config)
        server = getattr(args, "server", None)
        if server and server not in data["mcpServers"]:
            fail("Unknown exact server name; configure it explicitly before connecting")
        node, version = runtime(args.node)
        env = child_environment(state)
        # Node selected here also resolves stdio server shebangs consistently.
        env["PATH"] = str(Path(node).parent) + os.pathsep + env.get("PATH", "")
        if args.command == "version":
            print(json.dumps({"package": "mcporter", "version": version, "node": node}))
            return 0
        cli = [node, str(PACKAGE / "dist" / "cli.js"), "--config", str(config)]
        if args.command in ("auth", "logout"):
            if args.command == "logout":
                argv = cli + ["config", "logout", server]
            else:
                parts = tuple(int(part) for part in version.split(".")[:3])
                if parts < (0, 10, 0) and not args.allow_legacy_oauth:
                    fail("Legacy OAuth callback accepts missing state; explicit risk acceptance via --allow-legacy-oauth is required, see authentication guide")
                argv = cli + ["auth", server]
                if args.reset:
                    argv.append("--reset")
                if args.no_browser:
                    parts = tuple(int(part) for part in version.split(".")[:3])
                    if parts < (0, 15, 0):
                        fail("--no-browser is verified only for mcporter >=0.15.0; never assume old auth is headless")
                    argv.append("--no-browser")
            code = execute(argv, env, args.timeout / 1000 + 5)
        else:
            argv = [node, str(SCRIPTS / "mcporter_bridge.mjs"), str(PACKAGE), str(config), args.command]
            if server:
                argv.append(server)
            if getattr(args, "tool", None):
                argv.append(args.tool)
            if getattr(args, "query", None):
                argv.extend(["--query", args.query])
            argv.extend(["--timeout", str(args.timeout)])
            code = execute(argv, env, args.timeout / 1000 + 5)
        check_tree(state)
        return code if code >= 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError):
        # Exception text from OAuth, config, or third-party code can contain secrets.
        # Our own RuntimeError diagnostics are intentionally credential-free.
        error = sys.exc_info()[1]
        message = str(error) if isinstance(error, RuntimeError) else "Cannot read private state/runtime; run init/install explicitly and check permissions"
        print("PMCP_ENTRY_FAILED: " + message, file=sys.stderr)
        sys.exit(1)
