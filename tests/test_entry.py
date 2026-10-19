"""Offline safety regressions. No package installation, MCP server or real vault."""
from contextlib import ExitStack
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "src" / "skills" / "portable-mcp" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import install_runtime as installer
spec = importlib.util.spec_from_file_location("portable_entry", SCRIPTS / "pmcp.py")
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)
ACCOUNT_HOME = entry.account_home


@unittest.skipUnless(os.name == "posix", "Private entry regression suite targets Linux")
class EntrySafetyTests(unittest.TestCase):
    def setUp(self):
        previous_umask = os.umask(0o077)
        self.addCleanup(os.umask, previous_umask)
        self.temp = tempfile.TemporaryDirectory(prefix="pmcp-entry-test-")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.home.chmod(0o700)
        self.patch_home = patch.object(entry, "account_home", return_value=self.home)
        self.patch_home.start()
        self.addCleanup(self.patch_home.stop)
        # ACL policy is tested separately on Windows; this suite targets Linux.
        self.state = entry.prepare_state()
        self.config = self.state / "config" / "mcp.json"

    def write_config(self, entries=None, **extras):
        data = {"imports": [], "mcpServers": entries or {}}
        data.update(extras)
        self.config.write_text(json.dumps(data), encoding="utf-8")
        self.config.chmod(0o600)
        return self.config

    def server(self, **extras):
        value = {"url": "https://example.invalid/mcp", "lifecycle": "ephemeral"}
        value.update(extras)
        return {"demo": value}

    def test_state_uses_account_home_not_overrides(self):
        with patch.dict(os.environ, {"HOME": "/untrusted", "PMCP_STATE_DIR": "/untrusted", "USERPROFILE": "/untrusted"}):
            self.assertEqual(entry.prepare_state(), self.home / ".pmcp")
        self.assertFalse((self.home / ".mcporter").exists())
        self.assertEqual(set(p.name for p in self.state.iterdir()), {"home", "config", "data", "cache", "state", "broker"})

    def test_real_home_lookup_ignores_environment_without_writing(self):
        import pwd
        expected = Path(pwd.getpwuid(os.getuid()).pw_dir)
        with patch.dict(os.environ, {"HOME": "/untrusted", "USERPROFILE": "/untrusted"}):
            self.assertEqual(ACCOUNT_HOME(), expected)
        # Lookup only; never call prepare_state with the real account's home.

    def test_child_controls_cannot_be_inherited(self):
        poison = {"NODE_OPTIONS": "--require bad", "NODE_PATH": "/bad", "npm_config_engine_strict": "false", "MCPORTER_ENABLE_KEEPALIVE": "*", "MCPORTER_CONFIG": "/bad", "MCPC_HOME_DIR": "/bad", "PORTABLE_MCP_HOME": "/bad", "XDG_DATA_HOME": "/bad", "PMCP_STATE_DIR": "/bad", "BUSINESS_TEST_TOKEN": "fixture-not-secret"}
        with patch.dict(os.environ, poison):
            env = entry.child_environment(self.state, sys.executable)
        for key in poison:
            if key not in {"XDG_DATA_HOME", "MCPORTER_CONFIG", "BUSINESS_TEST_TOKEN"}:
                self.assertNotIn(key, env)
        self.assertEqual(env["HOME"], str(self.state / "home"))
        self.assertEqual(env["USERPROFILE"], str(self.state / "home"))
        self.assertEqual(env["XDG_DATA_HOME"], str(self.state / "data"))
        self.assertEqual(env["MCPORTER_CONFIG"], str(self.config))
        self.assertEqual(env["MCPORTER_DISABLE_KEEPALIVE"], "*")
        self.assertEqual(env["MCPORTER_DAEMON_DIR"], str(self.state / "broker"))
        self.assertEqual(env["BUSINESS_TEST_TOKEN"], "fixture-not-secret")

    def test_minimal_config(self):
        self.assertEqual(entry.read_config(self.write_config()), {"imports": [], "mcpServers": {}})
        self.assertIn("demo", entry.read_config(self.write_config(self.server()))["mcpServers"])

    def test_ambient_imports_and_root_extensions_rejected(self):
        for extras in ({"imports": ["cursor"]}, {"imports": None}, {"other": True}):
            with self.subTest(extras=extras), self.assertRaises(RuntimeError):
                entry.read_config(self.write_config(**extras))
        self.config.write_text('{"imports":[],"imports":[],"mcpServers":{}}', encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "Duplicate"):
            entry.read_config(self.config)

    def test_unsafe_server_controls_rejected(self):
        for change in ({"lifecycle": "keep-alive"}, {"lifecycle": None}, {"tokenCacheDir": "/tmp/cache"}, {"token_cache_dir": "/tmp/cache"}, {"refresh": {}}, {"record": True}, {"auth": "refreshable_bearer"}, {"cwd": str(self.home)}, {"env": {"HOME": "/bad"}}, {"env": {"node_options": "bad"}}, {"env": {"MCPORTER_CONFIG": "/bad"}}):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                entry.read_config(self.write_config(self.server(**change)))

    def test_stdio_absolute_cwd_supported(self):
        servers = {"local": {"command": "/usr/bin/true", "args": [], "cwd": str(self.home), "lifecycle": {"mode": "ephemeral"}}}
        self.assertEqual(entry.read_config(self.write_config(servers))["mcpServers"], servers)

    @unittest.skipUnless(os.name == "posix", "Linux permission policy")
    def test_insecure_mode_and_symlink_rejected(self):
        self.write_config()
        self.config.chmod(0o644)
        with self.assertRaises(RuntimeError):
            entry.check_tree(self.state)
        self.config.chmod(0o600)
        link = self.state / "linked-config"
        link.symlink_to(self.config)
        with self.assertRaises(RuntimeError):
            entry.check_tree(self.state)
        link.unlink()
        entry.check_tree(self.state)

    def test_corrupt_vault_is_preserved(self):
        vault = self.state / "home" / ".mcporter" / "credentials.json"
        vault.parent.mkdir(mode=0o700)
        for raw in ("{broken", "[]"):
            vault.write_text(raw, encoding="utf-8")
            vault.chmod(0o600)
            with self.subTest(raw=raw), self.assertRaises(RuntimeError):
                entry.check_vault_json(self.state)
            self.assertEqual(vault.read_text(encoding="utf-8"), raw)
        vault.write_text("{}", encoding="utf-8")
        entry.check_vault_json(self.state)

    @unittest.skipUnless(os.name == "posix", "Linux flock policy")
    def test_profile_lock_serializes_independent_open(self):
        with entry.profile_lock(self.state, 0.2):
            with self.assertRaisesRegex(RuntimeError, "Profile is busy"):
                with entry.profile_lock(self.state, 0.01):
                    self.fail("A second descriptor acquired a held lock")
        with entry.profile_lock(self.state, 0.2):
            pass
        self.assertTrue((self.state / ".pmcp.lock").is_file())

    def test_removed_deployment_flags_rejected(self):
        for args in (["--state-dir", "/tmp/other", "version"], ["version", "--node", "/bin/node"], ["auth", "demo", "--allow-legacy-oauth"]):
            with self.subTest(args=args), patch("sys.stderr"), self.assertRaises(SystemExit) as caught:
                entry.parser().parse_args(args)
            self.assertEqual(caught.exception.code, 2)

    def test_legacy_oauth_rejected_before_dispatch(self):
        self.write_config(self.server(auth="oauth"))
        with patch.object(entry, "install_lock", return_value=entry.nullcontext()), patch.object(entry, "runtime", return_value=("/usr/bin/node", "0.9.0")), patch.object(entry, "execute") as execute, patch.object(sys, "argv", ["pmcp.py", "auth", "demo"]):
            with self.assertRaisesRegex(RuntimeError, "OAuth is unavailable"):
                entry.main()
            execute.assert_not_called()

    def test_modern_auth_has_fixed_no_browser_argument(self):
        self.write_config(self.server(auth="oauth"))
        with patch.object(entry, "install_lock", return_value=entry.nullcontext()), patch.object(entry, "runtime", return_value=("/usr/bin/node", "0.15.0")), patch.object(entry, "execute", return_value=0) as execute, patch.object(sys, "argv", ["pmcp.py", "auth", "demo"]):
            self.assertEqual(entry.main(), 0)
            execute.assert_called_once()
            argv, env, timeout = execute.call_args.args
            self.assertEqual(argv[-3:], ["auth", "demo", "--no-browser"])
            self.assertEqual(argv[2:4], ["--config", str(self.config)])
            self.assertEqual(env["HOME"], str(self.state / "home"))
            self.assertEqual(timeout, 605)

    def test_init_is_idempotent_and_preserves_config(self):
        with patch.object(sys, "argv", ["pmcp.py", "init"]), patch("builtins.print"):
            self.assertEqual(entry.main(), 0)
            self.write_config(self.server())
            before = self.config.read_bytes()
            self.assertEqual(entry.main(), 0)
            self.assertEqual(self.config.read_bytes(), before)

    def test_node_drift_refused_before_backend_execution(self):
        runtime = self.home / "runtime"
        package = runtime / "node_modules/mcporter"
        package.mkdir(parents=True)
        (runtime / "skill-install.json").write_text(json.dumps({
            "schemaVersion": 1, "package": "mcporter", "version": "0.9.0",
            "cli": "node_modules/mcporter/dist/cli.js", "nodeVersion": "v22.23.3",
        }), encoding="utf-8")
        (package / "package.json").write_text(json.dumps({"name": "mcporter", "version": "0.9.0"}), encoding="utf-8")
        with patch.object(entry, "RUNTIME", runtime), patch.object(entry, "PACKAGE", package), patch.object(entry, "resolve_node", return_value=("/usr/bin/node", "v24.21.0")), patch.object(entry, "resolve_npm_cli", side_effect=AssertionError("must stop on drift")):
            with self.assertRaisesRegex(RuntimeError, "Node version changed"):
                entry.runtime()

    def test_installer_reuse_is_offline(self):
        node_version = "v22.23.3"
        previous = {"version": "0.9.0", "nodeVersion": node_version}
        with patch.object(installer, "previous_install", return_value=previous), patch.object(installer, "resolve_node", return_value=("/usr/bin/node", node_version)), patch.object(installer, "resolve_npm_cli", return_value="/unused/npm-cli.js"), patch.object(installer, "verify_package", return_value={"version": "0.9.0", "engineRange": ">=20.11.0"}), patch.object(installer, "fetch_versions", side_effect=AssertionError("offline reuse attempted network")), patch.object(installer, "install_staged", side_effect=AssertionError("offline reuse attempted install")), patch.object(installer, "promote", side_effect=AssertionError("offline reuse attempted promotion")), patch.object(installer, "run_json", side_effect=AssertionError("unexpected metadata helper")), patch("builtins.print"):
            for check in (False, True):
                with self.subTest(check=check):
                    self.assertEqual(installer.main_locked(type("Args", (), {"update": False, "check": check})()), 0)


class ConfigAddTests(unittest.TestCase):
    """Native add is a local staged generator, never an MCP connection.

    Only Windows ACL inspection is mocked: this suite tests config semantics on
    both platforms, not Windows's independently enforced ACL security policy.
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pmcp-add-test-")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        if os.name == "posix":
            previous_umask = os.umask(0o077)
            self.addCleanup(os.umask, previous_umask)
            self.home.chmod(0o700)
        for name, value in (("account_home", self.home), ("windows_acl", None)):
            mocked = patch.object(entry, name, return_value=value)
            mocked.start()
            self.addCleanup(mocked.stop)
        self.state = entry.prepare_state()
        self.config = self.state / "config" / "mcp.json"
        self.config.write_text('{"mcpServers":{},"imports":[]}\n', encoding="utf-8")
        self.config.chmod(0o600)
        self.native_calls = []
        self.staged_paths = []
        self.node = str(self.home / "node")

    def snapshot(self):
        info = self.config.stat()
        return self.config.read_bytes(), info.st_ino, info.st_mtime_ns, info.st_mode

    def native(self, argv, env, deadline, *, quiet=False):
        self.assertTrue(quiet)
        self.assertEqual(argv[:3], [self.node, str(entry.PACKAGE / "dist" / "cli.js"), "--config"])
        staged = Path(argv[3])
        self.staged_paths.append(staged)
        self.assertNotEqual(staged, self.config)
        self.assertEqual(staged.parent.parent, self.config.parent)
        self.assertEqual(staged.name, "mcp.json")
        self.assertEqual(json.loads(staged.read_text(encoding="utf-8")),
                         {"mcpServers": {}, "imports": []})
        self.assertEqual(argv[4:6], ["config", "add"])
        self.assertIn(argv[7], ("--url", "--command"))
        self.assertEqual(argv[9:], ["--auth", "oauth"] if len(argv) > 9 else [])
        self.assertEqual(deadline, entry.OPERATION_TIMEOUT_MS / 1000 + entry.CLEANUP_GRACE_SECONDS)
        self.assertEqual(env["MCPORTER_CONFIG"], str(self.config))
        self.assertEqual(env["HOME"], str(self.state / "home"))
        target = {"baseUrl" if argv[7] == "--url" else "command": argv[8]}
        if len(argv) > 9:
            target["auth"] = "oauth"
        staged.write_text(json.dumps({"mcpServers": {argv[6]: target}, "imports": []}), encoding="utf-8")
        self.native_calls.append(list(argv))
        return 0

    def invoke(self, *args, native=None):
        with patch.object(entry, "runtime", return_value=(self.node, "0.15.0")) as runtime, \
                patch.object(entry, "install_lock", return_value=entry.nullcontext()), \
                patch.object(entry, "execute", side_effect=native or self.native) as execute, \
                patch.object(sys, "argv", ["pmcp.py", "config-add", *args]), \
                patch("sys.stdout", new_callable=io.StringIO) as output:
            result = entry.main()
        self.assertEqual(result, 0)
        runtime.assert_called_once_with()
        execute.assert_called_once()
        for staged in self.staged_paths:
            self.assertFalse(staged.parent.exists(), "Native staging directory leaked")
        return json.loads(output.getvalue())

    def assert_rejected_before_runtime(self, *args):
        before = self.snapshot()
        with patch.object(entry, "runtime", side_effect=AssertionError("invalid add reached runtime")) as runtime, \
                patch.object(entry, "install_lock", return_value=entry.nullcontext()), \
                patch.object(entry, "execute") as execute, \
                patch.object(sys, "argv", ["pmcp.py", "config-add", *args]), \
                self.assertRaises((RuntimeError, ValueError)):
            entry.main()
        runtime.assert_not_called()
        execute.assert_not_called()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(list(self.config.parent.glob(".pmcp-add-*")), [])

    def test_http_oauth_and_headers_are_merged_without_forwarding(self):
        result = self.invoke("web", "--url", "https://example.invalid/mcp", "--oauth",
                             "--header", "Authorization=Bearer ${ACCESS_TOKEN}",
                             "--header", "X-API-Key=${API_KEY}")
        self.assertEqual(result, {"server": "web", "config": str(self.config),
                                  "dryRun": False, "written": True, "connected": False})
        self.assertEqual(self.native_calls[0][4:], ["config", "add", "web", "--url",
                         "https://example.invalid/mcp", "--auth", "oauth"])
        self.assertEqual(entry.read_config(self.config), {"imports": [], "mcpServers": {"web": {
            "baseUrl": "https://example.invalid/mcp", "auth": "oauth", "lifecycle": "ephemeral",
            "headers": {"Authorization": "Bearer ${ACCESS_TOKEN}", "X-API-Key": "${API_KEY}"}}}})

    def test_stdio_args_cwd_and_env_are_merged_without_forwarding(self):
        self.invoke("local", "--command", "never-spawn", "--arg=--config", "--arg", "child.json",
                    "--arg=--root", "--arg", "a path with spaces", "--arg", "",
                    "--cwd", str(self.home), "--env", "SERVICE_TOKEN=${TOKEN}",
                    "--env", "OTHER=${OTHER_TOKEN}")
        self.assertEqual(self.native_calls[0][4:], ["config", "add", "local", "--command", "never-spawn"])
        self.assertEqual(entry.read_config(self.config)["mcpServers"]["local"], {
            "command": "never-spawn", "args": ["--config", "child.json", "--root", "a path with spaces", ""],
            "cwd": str(self.home), "env": {"SERVICE_TOKEN": "${TOKEN}", "OTHER": "${OTHER_TOKEN}"},
            "lifecycle": "ephemeral"})

    def test_preserves_sibling_cwd_and_unknown_supported_fields(self):
        sibling = {"command": "never-spawn", "args": ["--config", "own.json"], "cwd": str(self.home),
                   "lifecycle": {"mode": "ephemeral"}, "description": "中文", "futureField": {"nested": [1, True]}}
        self.config.write_text(json.dumps({"imports": [], "mcpServers": {"old": sibling}}), encoding="utf-8")
        self.invoke("new", "--url", "http://localhost:1234/mcp")
        data = entry.read_config(self.config)
        self.assertEqual(data["imports"], [])
        self.assertEqual(data["mcpServers"]["old"], sibling)
        self.assertEqual(set(data["mcpServers"]), {"old", "new"})

    def test_same_name_never_overwrites_before_runtime(self):
        self.config.write_text(json.dumps({"imports": [], "mcpServers": {
            "demo": {"command": "original", "lifecycle": "ephemeral"}}}), encoding="utf-8")
        self.assert_rejected_before_runtime("demo", "--url", "https://example.invalid/mcp")

    def test_init_is_required_before_native_or_runtime(self):
        self.config.unlink()  # Known temporary canonical fixture only.
        with patch.object(entry, "runtime") as runtime, patch.object(entry, "execute") as execute, \
                patch.object(entry, "install_lock", return_value=entry.nullcontext()), \
                patch.object(sys, "argv", ["pmcp.py", "config-add", "demo", "--command", "never-spawn"]), \
                self.assertRaises(OSError):
            entry.main()
        runtime.assert_not_called()
        execute.assert_not_called()
        self.assertFalse(self.config.exists())

    def test_old_state_is_not_automatically_migrated(self):
        legacy = self.home / ".portable-mcp" / "config"
        legacy.mkdir(parents=True)
        old = legacy / "mcporter.json"
        old.write_bytes(b"old-private-state-not-to-migrate")
        self.config.unlink()  # Known temporary canonical fixture only.
        with patch.object(sys, "argv", ["pmcp.py", "init"]), patch("builtins.print"):
            self.assertEqual(entry.main(), 0)
        self.assertEqual(entry.read_config(self.config), {"mcpServers": {}, "imports": []})
        self.assertEqual(old.read_bytes(), b"old-private-state-not-to-migrate")
        self.assertEqual(self.state, self.home / ".pmcp")

    def test_dry_run_preserves_canonical_bytes_identity_and_cleans_temp(self):
        before = self.snapshot()
        result = self.invoke("preview", "--command", "never-spawn", "--dry-run")
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(result["dryRun"])
        self.assertFalse(result["written"])
        self.assertFalse(result["connected"])

    def test_commit_is_one_atomic_replace_of_validated_staged_document(self):
        original = self.config.read_bytes()
        real_replace = os.replace
        def replace(source, destination):
            self.assertEqual(Path(destination), self.config)
            self.assertEqual(self.config.read_bytes(), original)
            self.assertEqual(entry.read_config(Path(source))["mcpServers"]["demo"]["lifecycle"], "ephemeral")
            return real_replace(source, destination)
        with patch.object(entry.os, "replace", side_effect=replace) as commit:
            self.invoke("demo", "--command", "never-spawn")
        commit.assert_called_once()
        if os.name == "posix":
            self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)

    def test_replace_failure_leaves_original_unchanged_and_cleans_temp(self):
        before = self.snapshot()
        with patch.object(entry.os, "replace", side_effect=OSError("fixture atomic replace failed")), \
                self.assertRaisesRegex(OSError, "fixture atomic replace failed"):
            self.invoke("demo", "--command", "never-spawn")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(list(self.config.parent.glob(".pmcp-add-*")), [])

    def test_nonzero_native_output_never_commits(self):
        before = self.snapshot()
        def failed(*args, **kwargs):
            self.native(*args, **kwargs)
            return 17
        with self.assertRaisesRegex(RuntimeError, "Native config add failed"):
            self.invoke("demo", "--command", "never-spawn", native=failed)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(list(self.config.parent.glob(".pmcp-add-*")), [])

    def test_malformed_or_unexpected_native_output_never_commits(self):
        bad = ("{broken", "[]", "null", '{"mcpServers":{}}',
               '{"mcpServers":{},"imports":[]}',
               '{"mcpServers":{"demo":{"command":"wrong"}},"imports":[]}',
               '{"mcpServers":{"demo":{"command":"never-spawn","auth":"oauth"}},"imports":[]}',
               '{"mcpServers":{"demo":{"command":"never-spawn"}},"imports":["cursor"]}',
               '{"mcpServers":{"demo":{"command":"never-spawn"}},"imports":[],"other":true}',
               '{"mcpServers":{"demo":{"command":"never-spawn"},"extra":{}},"imports":[]}',
               '{"mcpServers":{"demo":{"command":"never-spawn"}},"imports":[],"imports":[]}',
               '{"mcpServers":{"demo":{"command":"wrong","command":"never-spawn"}},"imports":[]}')
        for raw in bad:
            with self.subTest(raw=raw):
                before = self.snapshot()
                def malformed(*args, **kwargs):
                    self.native(*args, **kwargs)
                    self.staged_paths[-1].write_text(raw, encoding="utf-8")
                    return 0
                with self.assertRaises((RuntimeError, ValueError)):
                    self.invoke("demo", "--command", "never-spawn", native=malformed)
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(list(self.config.parent.glob(".pmcp-add-*")), [])

    def test_config_is_refreshed_after_runtime_before_merging(self):
        sibling = {"command": "external", "lifecycle": "ephemeral", "cwd": str(self.home)}
        def runtime_changed():
            self.config.write_text(json.dumps({"imports": [], "mcpServers": {"external": sibling}}), encoding="utf-8")
            return self.node, "0.15.0"
        with patch.object(entry, "runtime", side_effect=runtime_changed), \
                patch.object(entry, "install_lock", return_value=entry.nullcontext()), \
                patch.object(entry, "execute", side_effect=self.native), \
                patch.object(sys, "argv", ["pmcp.py", "config-add", "demo", "--command", "never-spawn"]), \
                patch("builtins.print"):
            self.assertEqual(entry.main(), 0)
        self.assertEqual(entry.read_config(self.config)["mcpServers"]["external"], sibling)
        self.assertIn("demo", entry.read_config(self.config)["mcpServers"])
        self.assertEqual(list(self.config.parent.glob(".pmcp-add-*")), [])

    def test_same_name_added_during_runtime_is_preserved(self):
        changed = b'{"imports":[],"mcpServers":{"demo":{"command":"external","lifecycle":"ephemeral"}}}'
        def runtime_changed():
            self.config.write_bytes(changed)
            return self.node, "0.15.0"
        with patch.object(entry, "runtime", side_effect=runtime_changed), \
                patch.object(entry, "install_lock", return_value=entry.nullcontext()), \
                patch.object(entry, "execute") as execute, \
                patch.object(sys, "argv", ["pmcp.py", "config-add", "demo", "--command", "never-spawn"]), \
                self.assertRaisesRegex(RuntimeError, "already exists"):
            entry.main()
        execute.assert_not_called()
        self.assertEqual(self.config.read_bytes(), changed)
        self.assertEqual(list(self.config.parent.glob(".pmcp-add-*")), [])

    def test_external_modification_is_detected_and_not_overwritten(self):
        changed = b'{"imports":[],"mcpServers":{"external":{"command":"keep","lifecycle":"ephemeral"}}}'
        def external(*args, **kwargs):
            self.native(*args, **kwargs)
            self.config.write_bytes(changed)
            return 0
        with self.assertRaisesRegex(RuntimeError, "changed outside the profile lock"):
            self.invoke("demo", "--command", "never-spawn", native=external)
        self.assertEqual(self.config.read_bytes(), changed)
        self.assertEqual(list(self.config.parent.glob(".pmcp-add-*")), [])

    def test_invalid_urls_fail_before_runtime(self):
        for url in ("ftp://example.invalid/mcp", "example.invalid", "https:///missing",
                    "https://user@example.invalid/mcp", "https://user:secret@example.invalid/mcp",
                    "https://example.invalid/mcp?token=secret", "https://example.invalid/mcp?",
                    "https://example.invalid/mcp#fragment", "https://example.invalid/mcp#",
                    "https://example.invalid:bad/mcp", "https://example.invalid:99999/mcp",
                    "https://example.invalid/a b", "https://example.invalid/\n", "https://example.invalid/\\bad"):
            with self.subTest(url=url):
                self.assert_rejected_before_runtime("demo", "--url", url)

    def test_transport_invalid_combinations_fail_before_runtime(self):
        for options in (("--url", "https://example.invalid", "--arg", "child"),
                        ("--url", "https://example.invalid", "--cwd", str(self.home)),
                        ("--url", "https://example.invalid", "--env", "TOKEN=${TOKEN}"),
                        ("--command", "never-spawn", "--oauth"),
                        ("--command", "never-spawn", "--header", "X-Key=${TOKEN}")):
            with self.subTest(options=options):
                self.assert_rejected_before_runtime("demo", *options)

    def test_literal_credentials_and_invalid_reference_pairs_fail_before_runtime(self):
        cases = (("--env", "TOKEN=literal-secret"), ("--env", "TOKEN=Bearer ${TOKEN}"),
                 ("--env", "TOKEN=$TOKEN"), ("--env", "TOKEN=${TOKEN}/suffix"),
                 ("--env", "TOKEN"), ("--env", "bad-key=${TOKEN}"),
                 ("--header", "Authorization=Bearer literal-secret"), ("--header", "X-Key=literal-secret"),
                 ("--header", "X-Key=${TOKEN}\r\nInjected: value"), ("--header", "Bad Header=${TOKEN}"))
        for flag, value in cases:
            with self.subTest(flag=flag, value=value):
                target = ["--command", "never-spawn"] if flag == "--env" else ["--url", "https://example.invalid"]
                self.assert_rejected_before_runtime("demo", *target, flag, value)
        for flag, target in (("--env", ["--command", "never-spawn"]),
                             ("--header", ["--url", "https://example.invalid"])):
            self.assert_rejected_before_runtime("demo", *target, flag, "KEY=${TOKEN}", flag, "key=${OTHER}")

    def test_isolation_environment_overrides_fail_before_runtime(self):
        for key in ("HOME", "home", "USERPROFILE", "XDG_DATA_HOME", "NODE_OPTIONS", "NPM_CONFIG_REGISTRY",
                    "MCPORTER_CONFIG", "PMCP_STATE_DIR", "MCPC_HOME_DIR", "PORTABLE_MCP_HOME", "COREPACK_HOME"):
            with self.subTest(key=key):
                self.assert_rejected_before_runtime("demo", "--command", "never-spawn", "--env", key + "=${TOKEN}")

    def test_invalid_names_commands_cwd_and_control_characters_fail_before_runtime(self):
        for name in ("../bad", ".bad", "bad name", "服务"):
            with self.subTest(name=name):
                self.assert_rejected_before_runtime(name, "--command", "never-spawn")
        for options in (("--command", ""), ("--command=--flag",), ("--command", "bad\ncommand"),
                        ("--command", "never-spawn", "--arg", "bad\nargument"),
                        ("--command", "never-spawn", "--cwd", "relative"),
                        ("--command", "never-spawn", "--cwd", str(self.home / "missing"))):
            with self.subTest(options=options):
                self.assert_rejected_before_runtime("demo", *options)

    def test_parser_requires_exactly_one_transport_and_rejects_unsupported_flags(self):
        for options in ((), ("--url", "https://example.invalid", "--command", "never-spawn"),
                        ("--command", "never-spawn", "--auth", "oauth"),
                        ("--command", "never-spawn", "--overwrite"),
                        ("--command", "never-spawn", "--transport", "stdio"),
                        ("--command", "never-spawn", "--scope", "project"),
                        ("--command", "never-spawn", "--lifecycle", "keep-alive"),
                        ("--command", "never-spawn", "--config", "other.json")):
            with self.subTest(options=options), patch("sys.stderr"), self.assertRaises(SystemExit) as error:
                entry.parser().parse_args(["config-add", "demo", *options])
            self.assertEqual(error.exception.code, 2)


class MetadataDispatchTests(unittest.TestCase):
    """Metadata dispatch must not even inspect real account or runtime state."""

    def test_metadata_runs_before_any_runtime_or_account_access(self):
        with tempfile.TemporaryDirectory(prefix="pmcp-meta-dispatch-") as temporary:
            root = Path(temporary)
            skill = root / "SKILL.md"
            skill.write_bytes((SCRIPTS.parent / "SKILL.md").read_bytes())
            manifest = root / "capabilities.json"
            manifest.write_text('{"second":"second service"}', encoding="utf-8")
            with ExitStack() as stack:
                stack.enter_context(patch.object(entry, "META_ROOT", root))
                stack.enter_context(patch.object(entry, "META_SKILL", skill))
                guards = {name: stack.enter_context(patch.object(
                    entry, name, side_effect=AssertionError("Metadata touched " + name)))
                    for name in ("account_home", "prepare_state", "profile_lock", "install_lock",
                                 "runtime", "resolve_node", "resolve_npm_cli", "execute")}
                calls = (("meta-list",), ("meta-add", "demo", "service"),
                         ("meta-sync", "--input", str(manifest), "--replace", "--dry-run"),
                         ("meta-rm", "demo"))
                for args in calls:
                    with self.subTest(args=args), patch.object(sys, "argv", ["pmcp.py", *args]), \
                            patch("sys.stdout", new_callable=io.StringIO) as output:
                        self.assertEqual(entry.main(), 0)
                        self.assertIn("capabilities", json.loads(output.getvalue()))
                with patch.object(sys, "argv", ["pmcp.py", "meta-add", "demo", "bad\nsummary"]), \
                        patch("sys.stderr", new_callable=io.StringIO) as error:
                    self.assertEqual(entry.main(), 1)
                    self.assertIn("PMCP_META_FAILED:", error.getvalue())
                for guard in guards.values():
                    guard.assert_not_called()
            self.assertEqual(sorted(p.name for p in root.iterdir()), ["SKILL.md", "capabilities.json"])

    def test_metadata_parser_retains_flags_and_backend_commands(self):
        cases = ((["meta-add", "demo", "summary", "--dry-run", "--lock-timeout", "0"],
                  {"command": "meta-add", "name": "demo", "description": "summary",
                   "dry_run": True, "lock_timeout": 0.0}),
                 (["meta-rm", "demo", "--dry-run"],
                  {"command": "meta-rm", "name": "demo", "dry_run": True}),
                 (["meta-list", "--lock-timeout", "2.5"],
                  {"command": "meta-list", "lock_timeout": 2.5}),
                 (["meta-sync", "--input", "fixture.json", "--replace", "--dry-run"],
                  {"command": "meta-sync", "input": "fixture.json", "replace": True, "dry_run": True}),
                 (["call", "demo", "tool"], {"command": "call", "server": "demo", "tool": "tool"}),
                 (["auth", "demo", "--reset"], {"command": "auth", "server": "demo", "reset": True}))
        for argv, expected in cases:
            with self.subTest(argv=argv):
                args = vars(entry.parser().parse_args(argv))
                for key, value in expected.items():
                    self.assertEqual(args[key], value)
        for argv in (["meta-sync"], ["meta-add", "demo"], ["meta-list", "--replace"],
                     ["meta-rm", "demo", "--input", "fixture.json"]):
            with self.subTest(argv=argv), patch("sys.stderr"), self.assertRaises(SystemExit) as error:
                entry.parser().parse_args(argv)
            self.assertEqual(error.exception.code, 2)

    def test_metadata_location_is_the_imported_skill_not_cwd(self):
        self.assertEqual(entry.META_ROOT, SCRIPTS.parent)
        self.assertEqual(entry.META_SKILL, SCRIPTS.parent / "SKILL.md")


class RegistryPolicyTests(unittest.TestCase):
    REGISTRY = "https://registry.npmmirror.com/"

    def test_fixed_registry_and_no_cli_override(self):
        self.assertEqual(installer.REGISTRY, self.REGISTRY)
        with patch.object(sys, "argv", ["install_runtime.py", "--registry", "https://example.invalid/"]), \
                patch("sys.stderr"), patch.object(installer, "main_locked") as dispatch, \
                self.assertRaises(SystemExit) as error:
            installer.main()
        self.assertEqual(error.exception.code, 2)
        dispatch.assert_not_called()

    def test_metadata_fetch_uses_fixed_mirror_despite_environment(self):
        versions = {"0.9.0": {"name": "mcporter", "version": "0.9.0"}}
        body = json.dumps({"name": "mcporter", "versions": versions}).encode("utf-8")
        with patch.dict(os.environ, {"NPM_CONFIG_REGISTRY": "https://example.invalid/",
                                     "npm_config_registry": "https://example.invalid/"}), \
                patch.object(installer.urllib.request, "build_opener") as build:
            response = build.return_value.open.return_value.__enter__.return_value
            response.read.return_value = body
            self.assertEqual(installer.fetch_versions(), versions)
        request = build.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, self.REGISTRY + "mcporter")
        self.assertEqual(request.get_header("Accept"), "application/json")
        self.assertEqual(build.return_value.open.call_args.kwargs, {"timeout": 60})
        response.read.assert_called_once_with(installer.MAX_METADATA_BYTES + 1)

    def test_mock_npm_install_has_exact_registry_and_safety_parameters(self):
        with tempfile.TemporaryDirectory(prefix="pmcp-mock-install-") as temporary:
            runtime_parent = Path(temporary) / ".runtime"
            node, npm_cli = str(Path(temporary) / "node"), str(Path(temporary) / "npm-cli.js")
            version, node_version = "0.9.0", "v22.23.3"
            selection = {"version": version, "engineRange": ">=20.11.0"}
            calls = []

            def fake_run(command, **kwargs):
                calls.append((command, kwargs))
                if command[-1] == "--version":
                    return subprocess.CompletedProcess(command, 0, stdout="10.9.2\n")
                # Generate only minimal local fixtures normally produced by npm.
                stage = Path(kwargs["cwd"])
                (stage / "package.json").write_text(json.dumps({
                    "dependencies": {"mcporter": version}}), encoding="utf-8")
                (stage / "package-lock.json").write_text(json.dumps({"packages": {
                    "node_modules/mcporter": {"version": version}}}), encoding="utf-8")
                return subprocess.CompletedProcess(command, 0)

            poison = {"npm_config_registry": "https://example.invalid/",
                      "NPM_CONFIG_USERCONFIG": "untrusted.conf", "NODE_OPTIONS": "--require untrusted"}
            old_umask = os.umask(0o077)
            self.addCleanup(os.umask, old_umask)
            with patch.dict(os.environ, poison), patch.object(installer, "RUNTIME_PARENT", runtime_parent), \
                    patch.object(installer.subprocess, "run", side_effect=fake_run), \
                    patch.object(installer, "verify_package", return_value=selection), \
                    patch.object(installer, "fetch_versions", side_effect=AssertionError("unexpected fetch")), \
                    patch("builtins.print"):
                stage = installer.install_staged(version, selection, node, node_version, npm_cli,
                                                [node, "helper.cjs"], installer.safe_env(node))
            self.assertEqual(len(calls), 2)
            command, options = calls[1]
            self.assertEqual(command, [node, npm_cli, "install", "--prefix", str(stage),
                                      "--global=false", "--workspaces=false", "--save-exact",
                                      "--package-lock=true", "--ignore-scripts", "--engine-strict",
                                      "--no-audit", "--no-fund", "--omit=dev", "--registry",
                                      self.REGISTRY, "mcporter@" + version])
            self.assertTrue(options["check"])
            self.assertFalse(options["shell"])
            self.assertEqual(options["cwd"], str(stage))
            env = options["env"]
            for key in poison:
                self.assertNotIn(key, env)
            self.assertEqual(env["npm_config_userconfig"], str(stage / "npm-user.conf"))
            self.assertEqual(env["npm_config_globalconfig"], str(stage / "npm-global.conf"))
            self.assertEqual(env["npm_config_cache"], str(stage / "npm-cache"))
            for name in (".npmrc", "npm-user.conf", "npm-global.conf"):
                self.assertEqual((stage / name).read_bytes(), b"")
            marker = json.loads((stage / installer.MARKER_NAME).read_text(encoding="utf-8"))
            self.assertEqual(marker["registry"], self.REGISTRY)
            self.assertFalse(marker["installScripts"])
            self.assertEqual(marker["version"], version)


class SemverSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("node"):
            raise unittest.SkipTest("Existing Node/npm required; never installed by tests")
        cls.node, cls.version = installer.resolve_node()
        try:
            cls.npm = installer.resolve_npm_cli(cls.node)
        except RuntimeError as error:
            raise unittest.SkipTest(str(error))

    def helper(self, versions, node_version=None):
        return subprocess.run([self.node, str(SCRIPTS / "runtime_versions.cjs"), "--npm-cli", self.npm, "select"], input=json.dumps({"nodeVersion": node_version or self.version, "versions": versions}), capture_output=True, text=True, env=installer.safe_env(self.node), timeout=30)

    def test_highest_stable_compatible_non_deprecated(self):
        major = int(self.version.lstrip("v").split(".")[0])
        def package(version, engines, **extra):
            return {"name": "mcporter", "version": version, "engines": {"node": engines}, **extra}
        versions = {
            "0.8.0": package("0.8.0", "*"),
            "0.9.0": package("0.9.0", "*"),
            "0.10.0": package("0.10.0", f">={major}.0.0 <{major + 1}.0.0 || >=99.0.0"),
            "0.11.0": package("0.11.0", "*", deprecated="fixture"),
            "0.12.0": package("0.12.0", ">=99.0.0"),
            "0.13.0-beta.1": package("0.13.0-beta.1", "*"),
            "0.14.0": package("0.14.0", "not a range"),
        }
        result = self.helper(versions)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["version"], "0.10.0")

    def test_false_node_version_rejected(self):
        result = self.helper({}, "v99.0.0")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("nodeVersion differs", result.stderr)

    def test_no_compatible_version_fails_without_upgrade(self):
        result = self.helper({"0.9.0": {"name": "mcporter", "version": "0.9.0", "engines": {"node": "<0.1.0"}}})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Node will not be upgraded", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
