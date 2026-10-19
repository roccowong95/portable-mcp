"""Offline safety regressions. No package installation, MCP server or real vault."""
import importlib.util
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
        self.config = self.state / "config" / "mcporter.json"

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
            self.assertEqual(entry.prepare_state(), self.home / ".portable-mcp")
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
