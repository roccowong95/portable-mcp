#!/usr/bin/env python3
"""Portable-mcp entry: private MCP operations and skill-local capability metadata.

Never installs or upgrades Node. The meta-* commands need only Python and this
skill's files; they do not initialize account state or load the MCP runtime.
"""
import argparse
from contextlib import contextmanager, nullcontext
from install_runtime import install_lock, resolve_node, resolve_npm_cli, safe_env
import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import time
import tempfile
import unicodedata
from urllib.parse import urlsplit

SCRIPTS = Path(__file__).resolve().parent
RUNTIME = SCRIPTS / ".runtime" / "mcporter"
PACKAGE = RUNTIME / "node_modules" / "mcporter"
MAX_CONFIG = 1024 * 1024
LOCK_TIMEOUT_SECONDS = 30
OPERATION_TIMEOUT_MS = 60000
AUTH_TIMEOUT_SECONDS = 600
CLEANUP_GRACE_SECONDS = 5
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


def account_home():
    """Use the OS account database, never caller-supplied HOME/USERPROFILE."""
    if os.name == "posix":
        import pwd
        try:
            raw = pwd.getpwuid(os.getuid()).pw_dir
        except KeyError:
            fail("Current user is absent from the OS account database")
    elif os.name == "nt":
        import ctypes
        buffer = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x28, None, 0, buffer) != 0:
            fail("Cannot determine the current Windows account profile")
        raw = buffer.value
    else:
        fail("Unsupported operating system")
    home = Path(raw)
    if not home.is_absolute() or not home.is_dir():
        fail("OS account home must be an existing absolute directory")
    return home


def prepare_state():
    path = account_home() / ".pmcp"
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


def config_unique(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            fail("Duplicate configuration keys are not allowed")
        obj[key] = value
    return obj


def read_config(path):
    private_path(path)
    if path.stat().st_size > MAX_CONFIG:
        fail("Configuration exceeds 1 MiB")
    data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=config_unique)
    return validate_config(data)


def validate_config(data):
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
                    if key.upper() in {"HOME", "USERPROFILE"} or key.upper().startswith(("XDG_", "MCPORTER_", "PMCP_", "NODE_", "NPM_", "COREPACK_", "MCPC_", "PORTABLE_MCP_")):
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


def child_environment(state, node):
    env = safe_env(node)
    env.update({"HOME": str(state / "home"), "USERPROFILE": str(state / "home"),
                "XDG_CONFIG_HOME": str(state / "config"), "XDG_DATA_HOME": str(state / "data"),
                "XDG_CACHE_HOME": str(state / "cache"), "XDG_STATE_HOME": str(state / "state"),
                "MCPORTER_DAEMON_DIR": str(state / "broker"),
                "MCPORTER_CONFIG": str(state / "config" / "mcp.json"),
                "MCPORTER_LOG_LEVEL": "error", "MCPORTER_NO_FORCE_EXIT": "1",
                "MCPORTER_DISABLE_KEEPALIVE": "*"})
    return env


def runtime():
    meta = json.loads((RUNTIME / "skill-install.json").read_text(encoding="utf-8"))
    pkg = json.loads((PACKAGE / "package.json").read_text(encoding="utf-8"))
    if (not isinstance(meta, dict) or not isinstance(pkg, dict) or
            meta.get("schemaVersion") != 1 or meta.get("package") != "mcporter" or
            not isinstance(pkg.get("version"), str) or
            meta.get("version") != pkg.get("version") or pkg.get("name") != "mcporter" or
            meta.get("cli") != "node_modules/mcporter/dist/cli.js"):
        fail("Installed runtime does not match its installation record; reinstall explicitly")
    node, version = resolve_node()
    env = safe_env(node)
    if version != meta.get("nodeVersion"):
        fail("Node version changed; explicitly run installer --update to revalidate transitive engines (Node is never upgraded)")
    # Locate npm again after relocation; do not embed any package version in the entry.
    npm_cli = resolve_npm_cli(node)
    helper = [node, str(SCRIPTS / "runtime_versions.cjs"), "--npm-cli", npm_cli, "check-installed"]
    result = subprocess.run(helper, input=json.dumps({"nodeVersion": version, "package": pkg}),
                            capture_output=True, text=True, env=env, timeout=60)
    if result.returncode:
        fail("Installed runtime is incompatible with this Node, or npm semver is unavailable; run installer explicitly")
    return node, pkg["version"]


def execute(argv, env, deadline, quiet=False):
    """Never log tokens or replay; config generation suppresses third-party output."""
    kwargs = {"env": env}
    if quiet:
        kwargs.update(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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


def config_add_options(args):
    """Validate a finite add interface; never forward arbitrary native CLI flags."""
    if not NAME.fullmatch(args.server):
        fail("Invalid exact server name")
    if args.url:
        try:
            url = urlsplit(args.url)
            port = url.port
        except ValueError:
            fail("Invalid MCP URL")
        if (url.scheme not in ("https", "http") or not url.hostname or
                url.username is not None or url.password is not None or
                "#" in args.url or "\\" in args.url or
                any(ord(char) <= 32 or ord(char) == 127 for char in args.url)):
            fail("MCP URL must be HTTP(S) without userinfo, fragment, backslashes or whitespace")
        if args.arg or args.cwd or args.env:
            fail("args, cwd and env are supported only for stdio")
    else:
        if (not args.executable or args.executable.startswith("-") or
                any(ord(char) < 32 or ord(char) == 127 for char in args.executable)):
            fail("stdio command must be a nonempty executable, not a shell command or flag")
        if args.header or args.oauth:
            fail("headers and OAuth are supported only for HTTP")
    extra = {}
    if args.executable:
        if any(any(ord(char) < 32 or ord(char) == 127 for char in arg) for arg in args.arg):
            fail("stdio arguments cannot contain control characters")
        extra["args"] = args.arg
    if args.cwd:
        if not Path(args.cwd).is_absolute() or not Path(args.cwd).is_dir():
            fail("cwd must be an existing absolute stdio directory")
        extra["cwd"] = args.cwd
    reference = r"\$\{[A-Za-z_][A-Za-z0-9_]*\}"
    for field, pairs in (("env", args.env), ("headers", args.header)):
        values = {}
        for pair in pairs:
            key, separator, value = pair.partition("=")
            pattern = r"[A-Za-z_][A-Za-z0-9_]*" if field == "env" else r"[A-Za-z0-9!#$%&'*+.^_`|~-]+"
            if not separator or not re.fullmatch(pattern, key):
                fail("env/header requires a valid KEY=environment-reference pair")
            if key.lower() in {existing.lower() for existing in values}:
                fail("Duplicate env/header keys are not allowed")
            allowed_value = reference if field == "env" else r"(?:Bearer )?" + reference
            if not re.fullmatch(allowed_value, value):
                fail("env/header values must be environment references, never literal credentials (headers may use Bearer prefix)")
            values[key] = value
        if values:
            extra[field] = values
    definition = {"baseUrl": args.url} if args.url else {"command": args.executable}
    definition.update(extra)
    definition["lifecycle"] = "ephemeral"
    if args.oauth:
        definition["auth"] = "oauth"
    validate_config({"mcpServers": {args.server: definition}, "imports": []})
    return extra


def config_add(args, state, config, data, node, env):
    """Use native add only to generate one entry, then validate and atomically publish.

    Native parsers may consume child --config/--root args or strip existing cwd.
    Therefore never pass child args or the original config through native add.
    """
    extra = config_add_options(args)
    original = config.read_bytes()
    identity = config.stat()
    # runtime() may take time: merge from a fresh snapshot, never the caller's
    # earlier parsed data. The pre-publish identity/byte check covers this read too.
    data = read_config(config)
    if args.server in data["mcpServers"]:
        fail("Server already exists; config-add never replaces an existing identity")
    # Dedicated private directory confines even a native lock/temp-file writer.
    with tempfile.TemporaryDirectory(prefix=".pmcp-add-", dir=str(config.parent)) as folder:
        staged = Path(folder) / "mcp.json"
        staged.write_text('{"mcpServers":{},"imports":[]}\n', encoding="utf-8")
        cli = [node, str(PACKAGE / "dist" / "cli.js"), "--config", str(staged),
               "config", "add", args.server]
        target = {"baseUrl": args.url} if args.url else {"command": args.executable}
        cli += ["--url", args.url] if args.url else ["--command", args.executable]
        if args.oauth:
            cli += ["--auth", "oauth"]
            target["auth"] = "oauth"
        if execute(cli, env, OPERATION_TIMEOUT_MS / 1000 + CLEANUP_GRACE_SECONDS, quiet=True):
            fail("Native config add failed; existing configuration was not changed")
        private_path(staged)
        if staged.stat().st_size > MAX_CONFIG:
            fail("Generated config exceeds safety limit")
        generated = json.loads(staged.read_text(encoding="utf-8"), object_pairs_hook=config_unique)
        # Fail closed for backend shape changes; only the exact approved target
        # is accepted, without additional imports, fields or implicit defaults.
        if (not isinstance(generated, dict) or generated.get("imports") != [] or
                set(generated) != {"mcpServers", "imports"} or
                generated.get("mcpServers") != {args.server: target}):
            fail("Native config add produced an unexpected entry; existing configuration was not changed")
        target.update(extra)
        target["lifecycle"] = "ephemeral"
        merged = {**data, "mcpServers": {**data["mcpServers"], args.server: target}}
        with staged.open("w", encoding="utf-8") as stream:
            json.dump(merged, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        read_config(staged)
        check_tree(state)
        private_path(config)
        current = config.stat()
        if ((current.st_dev, current.st_ino, current.st_mtime_ns, current.st_size) !=
                (identity.st_dev, identity.st_ino, identity.st_mtime_ns, identity.st_size) or
                config.read_bytes() != original):
            fail("Configuration changed outside the profile lock; no overwrite was performed")
        if not args.dry_run:
            os.replace(staged, config)
        print(json.dumps({"server": args.server, "config": str(config),
                          "dryRun": args.dry_run, "written": not args.dry_run,
                          "connected": False}))
    return 0


# Metadata stays skill-local and uses a separate writer lock, not account state.
META_ROOT = SCRIPTS.parent
META_SKILL = META_ROOT / "SKILL.md"
META_MARKER = "PMCP_CAPABILITIES="
META_MAX_FILE_BYTES = 256 * 1024
META_MAX_INPUT_BYTES = 64 * 1024
META_MAX_ITEMS = 24
META_MAX_SUMMARY = 160
META_MAX_INDEX_BYTES = 4096
META_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}\Z")


class MetaError(Exception):
    pass


def meta_require(condition, message):
    if not condition:
        raise MetaError(message)


def meta_pairs_unique(pairs):
    result = {}
    for key, value in pairs:
        meta_require(key not in result, "Duplicate JSON key; repair the index manually")
        result[key] = value
    return result


def meta_validate_name(name):
    meta_require(isinstance(name, str) and META_NAME.fullmatch(name),
            "Name must be 1..64 ASCII letters/digits/._-, starting with a letter/digit")


def meta_validate_summary(value):
    meta_require(isinstance(value, str) and value == value.strip() and 0 < len(value) <= META_MAX_SUMMARY,
            "Summary must be 1..160 characters with no leading/trailing whitespace")
    meta_require(not any(unicodedata.category(c).startswith("C") or c in "\u2028\u2029" for c in value),
            "Summary cannot contain control, format, surrogate or line-separator characters")
    meta_require(META_MARKER not in value, "Summary cannot contain the reserved capability marker")


def meta_encode_index(index):
    meta_require(isinstance(index, dict), "Capability index must be a JSON object")
    meta_require(len(index) <= META_MAX_ITEMS, "At most 24 capability entries are allowed")
    for name, summary in index.items():
        meta_validate_name(name)
        meta_validate_summary(summary)
    data = json.dumps(index, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    meta_require(len(data.encode("utf-8")) <= META_MAX_INDEX_BYTES, "Capability index exceeds 4096 UTF-8 bytes")
    return data


def meta_read_skill():
    info = META_SKILL.lstat()
    meta_require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
            "SKILL.md must be a regular, non-symlink, single-link file")
    meta_require(info.st_size <= META_MAX_FILE_BYTES, "SKILL.md is unexpectedly large")
    if os.name == "posix":
        meta_require(info.st_uid == os.getuid(), "Refusing to replace a file owned by another user")
    raw = META_SKILL.read_bytes()
    meta_require(len(raw) <= META_MAX_FILE_BYTES, "SKILL.md is unexpectedly large")
    text = raw.decode("utf-8")
    meta_require("\r" not in text.replace("\r\n", ""), "Unsupported newline format")
    return raw, text, info


def meta_parse_index(text):
    # Deliberately NOT a general YAML rewriter. Only the documented folded scalar
    # is supported. Refuse ambiguous formats instead of rewriting other metadata.
    lines = text.splitlines(keepends=True)
    meta_require(lines and lines[0].rstrip("\r\n") == "---", "Missing YAML frontmatter")
    endings = [i for i in range(1, len(lines)) if lines[i].rstrip("\r\n") == "---"]
    meta_require(bool(endings), "Unterminated YAML frontmatter")
    end = endings[0]
    # Restrict top-level keys to plain identifiers, so quoted/escaped duplicate
    # YAML keys cannot change which description a host actually sees.
    keys = {}
    for i in range(1, end):
        line = lines[i].rstrip("\r\n")
        if not line or line.startswith((" ", "#")):
            continue
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*) *:(?: +|$)", line)
        meta_require(match is not None, "Unsupported top-level YAML syntax; review manually")
        key = match.group(1)
        meta_require(key not in keys, "Duplicate top-level YAML key; review manually")
        keys[key] = i
    descriptions = [keys["description"]] if "description" in keys else []
    meta_require(len(descriptions) == 1, "Expected exactly one description field")
    start = descriptions[0]
    meta_require(lines[start].rstrip("\r\n") == "description: >-",
            "Expected description: >-; custom YAML forms require manual review")
    stop = start + 1
    while stop < end and lines[stop].startswith("  "):
        stop += 1
    # Blank lines do not terminate a YAML block scalar. Refuse any later
    # indented continuation rather than silently editing only half the scalar.
    following = stop
    while following < end and (not lines[following].strip() or lines[following].startswith("#")):
        following += 1
    meta_require(following == end or not lines[following].startswith((" ", "\t")),
            "Description continuation after a blank line is unsupported")
    content = [line.rstrip("\r\n") for line in lines[start + 1:stop]]
    meta_require(content and all(line.startswith("  ") and line[2:] and not line[2:].startswith(" ")
                            for line in content), "Expected nonempty, exactly two-space-indented description lines")
    marker_lines = [i for i, line in enumerate(content) if line.startswith("  " + META_MARKER)]
    meta_require(marker_lines == [len(content) - 1] and len(content) >= 2,
            "Expected one final PMCP_CAPABILITIES JSON line after the fixed description")
    meta_require(sum(line.count(META_MARKER) for line in lines[1:end]) == 1,
            "Ambiguous capability marker in frontmatter")
    target = start + 1 + marker_lines[0]
    payload = content[-1][2 + len(META_MARKER):]
    index = json.loads(payload, object_pairs_hook=meta_pairs_unique)
    meta_encode_index(index)
    offset = sum(len(line) for line in lines[:target]) + 2 + len(META_MARKER)
    return index, offset, offset + len(payload)


def meta_load_sync_input(path_text):
    """Read and validate a local, non-secret sync manifest.

    Accepted shapes:
      {"notion": "搜索和读取 Notion 页面", "logseq": "检索 Logseq 知识库"}
      [{"name": "notion", "summary": "搜索和读取 Notion 页面"}]
    """
    path = Path(path_text).expanduser()
    info = path.lstat()
    meta_require(stat.S_ISREG(info.st_mode) and not path.is_symlink(),
            "Sync input must be a regular, non-symlink file")
    meta_require(info.st_size <= META_MAX_INPUT_BYTES,
            f"Sync input exceeds {META_MAX_INPUT_BYTES} bytes")
    raw = path.read_bytes()
    meta_require(len(raw) <= META_MAX_INPUT_BYTES, f"Sync input exceeds {META_MAX_INPUT_BYTES} bytes")
    data = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=meta_pairs_unique)
    if isinstance(data, dict):
        items = dict(data)
    elif isinstance(data, list):
        items = {}
        for index, item in enumerate(data):
            meta_require(isinstance(item, dict), f"Sync input item {index} must be an object")
            extra = sorted(set(item) - {"name", "summary"})
            meta_require(not extra, f"Sync input item {index} has unexpected fields: {', '.join(extra)}")
            name = item.get("name")
            summary = item.get("summary")
            meta_require(isinstance(name, str), f"Sync input item {index} name must be a string")
            meta_require(isinstance(summary, str), f"Sync input item {index} summary must be a string")
            meta_require(name not in items, f"Duplicate sync input name: {name}")
            items[name] = summary
    else:
        raise MetaError("Sync input must be a JSON object or array")
    meta_require(len(items) <= META_MAX_ITEMS, f"At most {META_MAX_ITEMS} capability entries are allowed")
    for name, summary in items.items():
        meta_validate_name(name)
        meta_validate_summary(summary)
    return items


@contextmanager
def meta_writer_lock(timeout):
    lock = META_ROOT / ".pmcp-meta.lock"
    deadline = time.monotonic() + timeout
    while True:
        try:
            lock.mkdir(mode=0o700)
            break
        except FileExistsError:
            meta_require(time.monotonic() < deadline,
                    "Metadata writer lock is busy; after a crash, verify no writer is running before removing .pmcp-meta.lock")
            time.sleep(min(0.05, max(0, deadline - time.monotonic())))
    try:
        yield
    finally:
        # Only remove the empty lock directory created by this writer.
        lock.rmdir()


def meta_file_identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_mode)


def meta_replace_skill(before, info, after):
    fd, name = tempfile.mkstemp(prefix=".pmcp-meta-", suffix=".tmp", dir=META_ROOT)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(after)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(temporary, stat.S_IMODE(info.st_mode))
        current, _, current_info = meta_read_skill()
        meta_require(current == before and meta_file_identity(current_info) == meta_file_identity(info),
                "SKILL.md changed outside pmcp.py metadata commands; no replacement performed")
        os.replace(temporary, META_SKILL)
        # Atomic replacement for readers, not a guarantee against power loss or
        # uncooperative writers. POSIX mode retained; custom ACLs are not copied.
    finally:
        if temporary.exists():
            temporary.unlink()


def meta_add_commands(commands):
    for command in ("meta-add", "meta-rm", "meta-list"):
        sub = commands.add_parser(command)
        sub.add_argument("--dry-run", action="store_true", help="Show the resulting index; never write or lock")
        sub.add_argument("--lock-timeout", type=float, default=5.0,
                         help="Maximum wait for another writer, 0..60 seconds (default 5)")
        if command != "meta-list":
            sub.add_argument("name")
        if command == "meta-add":
            sub.add_argument("description", help="Approved, nonsecret service-level capability summary")
    sync = commands.add_parser("meta-sync")
    sync.add_argument("--input", required=True,
                      help="Local JSON manifest: {name: summary} or [{name, summary}]")
    sync.add_argument("--replace", action="store_true",
                      help="Replace the whole index instead of merging; removes entries absent from input")
    sync.add_argument("--dry-run", action="store_true", help="Show the resulting index; never write or lock")
    sync.add_argument("--lock-timeout", type=float, default=5.0,
                      help="Maximum wait for another writer, 0..60 seconds (default 5)")


def meta_run(args):
    meta_require(math.isfinite(args.lock_timeout) and 0 <= args.lock_timeout <= 60,
            "Lock timeout must be a finite number between 0 and 60")
    if args.command in ("meta-add", "meta-rm"):
        meta_validate_name(args.name)
    if args.command == "meta-add":
        meta_validate_summary(args.description)
    incoming = meta_load_sync_input(args.input) if args.command == "meta-sync" else None

    def operation():
        raw, text, info = meta_read_skill()
        index, start, stop = meta_parse_index(text)
        updated = dict(index)
        diff = None
        if args.command == "meta-add":
            updated[args.name] = args.description
        elif args.command == "meta-rm":
            updated.pop(args.name, None)  # Idempotent; no MCP is disconnected.
        elif args.command == "meta-sync":
            if args.replace:
                updated = dict(incoming)
            else:
                updated.update(incoming)
            diff = {
                "added": sorted(set(updated) - set(index)),
                "updated": sorted(k for k in incoming if k in index and index[k] != incoming[k]),
                "removed": sorted(set(index) - set(updated)),
                "unchanged": sorted(k for k in incoming if index.get(k) == incoming[k]),
            }
        changed = updated != index
        payload = meta_encode_index(updated)
        if changed:
            after = (text[:start] + payload + text[stop:]).encode("utf-8")
            # Dry runs validate the same candidate; only mutation is skipped.
            meta_require(len(after) <= META_MAX_FILE_BYTES, "Resulting SKILL.md would exceed the file size limit")
            meta_require(meta_parse_index(after.decode("utf-8"))[0] == updated, "Candidate validation failed")
            if not args.dry_run:
                meta_replace_skill(raw, info, after)
        print(json.dumps({"capabilities": updated, "changed": changed, "diff": diff,
                          "written": changed and not args.dry_run, "dryRun": args.dry_run},
                         ensure_ascii=True, sort_keys=True))

    if args.command == "meta-list" or args.dry_run:
        operation()
    else:
        with meta_writer_lock(args.lock_timeout):
            operation()
    return 0


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    for op in ("init", "version", "servers", "doctor"):
        sub.add_parser(op)
    add = sub.add_parser("config-add", help="Safely add one server without editing JSON or connecting")
    add.add_argument("server")
    target = add.add_mutually_exclusive_group(required=True)
    target.add_argument("--url")
    target.add_argument("--command", dest="executable")
    add.add_argument("--arg", action="append", default=[], help="stdio argument; use --arg=--flag for leading dashes")
    add.add_argument("--cwd", help="Existing absolute stdio directory")
    add.add_argument("--oauth", action="store_true", help="Configure HTTP OAuth, never start authorization")
    add.add_argument("--env", action="append", default=[], help="stdio KEY=${ENV_VAR} (no literal secrets)")
    add.add_argument("--header", action="append", default=[], help="HTTP KEY=${ENV_VAR} or KEY=Bearer ${ENV_VAR}")
    add.add_argument("--dry-run", action="store_true")
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
    logout = sub.add_parser("logout")
    logout.add_argument("server")
    meta_add_commands(sub)
    return p


def main():
    args = parser().parse_args()
    # Metadata operations are skill-local: no account state, runtime, Node or MCP.
    if args.command in ("meta-add", "meta-rm", "meta-list", "meta-sync"):
        try:
            return meta_run(args)
        except (MetaError, OSError, UnicodeError, ValueError, RecursionError) as error:
            if isinstance(error, (MetaError, FileNotFoundError, PermissionError)):
                message = str(error)
            else:
                message = "Invalid UTF-8/JSON or filesystem operation failed; no automatic format repair"
            print("PMCP_META_FAILED: " + message, file=sys.stderr)
            return 1
    state = prepare_state()
    config = state / "config" / "mcp.json"
    with profile_lock(state, LOCK_TIMEOUT_SECONDS), (nullcontext() if args.command == "init" else install_lock(LOCK_TIMEOUT_SECONDS)):
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
        if args.command == "config-add":
            config_add_options(args)
            if server in data["mcpServers"]:
                fail("Server already exists; config-add never replaces an existing identity")
        elif server and server not in data["mcpServers"]:
            fail("Unknown exact server name; use config-add before connecting")
        node, version = runtime()
        # The same discovered Node resolves stdio server shebangs consistently.
        env = child_environment(state, node)
        if args.command == "config-add":
            return config_add(args, state, config, data, node, env)
        if args.command == "version":
            print(json.dumps({"backend": {"package": "mcporter", "version": version}, "node": node}))
            return 0
        cli = [node, str(PACKAGE / "dist" / "cli.js"), "--config", str(config)]
        if args.command in ("auth", "logout"):
            if args.command == "logout":
                argv = cli + ["config", "logout", server]
            else:
                parts = tuple(int(part) for part in version.split(".")[:3])
                if parts < (0, 15, 0):
                    fail("OAuth is unavailable with this compatible runtime: fixed headless safety baseline requires runtime >=0.15.0. Use header authentication; Node will not be changed")
                argv = cli + ["auth", server, "--no-browser"]
                if args.reset:
                    argv.append("--reset")
            code = execute(argv, env, AUTH_TIMEOUT_SECONDS + CLEANUP_GRACE_SECONDS)
        else:
            argv = [node, str(SCRIPTS / "mcp_bridge.mjs"), str(PACKAGE), str(config), args.command]
            if server:
                argv.append(server)
            if getattr(args, "tool", None):
                argv.append(args.tool)
            if getattr(args, "query", None):
                argv.extend(["--query", args.query])
            argv.extend(["--timeout", str(OPERATION_TIMEOUT_MS)])
            code = execute(argv, env, OPERATION_TIMEOUT_MS / 1000 + CLEANUP_GRACE_SECONDS)
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
