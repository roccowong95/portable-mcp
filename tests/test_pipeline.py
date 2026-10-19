"""No-download process regression: real Python/Node entry, fake public backend API.

Only the test process patches the OS-home lookup and runtime location to temp
fixtures. The published entry gains no test switch or alternate-state option.
No real backend transport, account state, package install or OAuth is used.
"""
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

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src/skills/portable-mcp/scripts"
sys.path.insert(0, str(SCRIPTS))
import install_runtime as installer

FAKE_API = r'''
import fs from 'node:fs/promises';
export async function loadServerDefinitions({configPath}) {
  const config = JSON.parse(await fs.readFile(configPath, 'utf8'));
  return Object.entries(config.mcpServers).map(([name, value]) => ({
    name, command: {kind: 'stdio'}, lifecycle: {mode: value.lifecycle},
  }));
}
export async function createRuntime() {
  const tools = [{name:'echo_fixture', description:'Literal [echo]',
    inputSchema:{type:'object'}, outputSchema:{type:'object'}}];
  async function call(name, args) {
    if (name !== 'echo_fixture') throw Error('unexpected call');
    await fs.appendFile(process.env.FIXTURE_RECEIPT, JSON.stringify(args)+'\n');
    return {content:[{type:'text',text:'fixture'}],structuredContent:args,
      isError:args.fail === true,_meta:{fixture:true}};
  }
  return {
    connect: async () => ({client:{listTools:async()=>({tools}),
      callTool:async({name,arguments:args})=>call(name,args),close:async()=>{}},
      transport:{close:async()=>{}}}),
    listTools:async()=>tools,
    callTool:async(_server,name,{args})=>call(name,args),
    close:async()=>{},
  };
}
'''

FAKE_CLI = r'''
import fs from 'node:fs/promises';
// A deliberately finite native-add contract: never load a transport or spawn a
// command, and reject every wrapper-only flag accidentally forwarded to native.
const argv = process.argv.slice(2);
if (argv.length !== 7 && argv.length !== 9) throw Error('unexpected native argv');
if (argv[0] !== '--config' || argv[2] !== 'config' || argv[3] !== 'add') {
  throw Error('unexpected native operation');
}
if (!['--url', '--command'].includes(argv[5])) throw Error('unexpected target');
if (argv.length === 9 && (argv[7] !== '--auth' || argv[8] !== 'oauth')) {
  throw Error('unexpected auth');
}
const target = {[argv[5] === '--url' ? 'baseUrl' : 'command']: argv[6]};
if (argv.length === 9) target.auth = 'oauth';
const before = JSON.parse(await fs.readFile(argv[1], 'utf8'));
if (Object.keys(before.mcpServers).length || before.imports.length) {
  throw Error('native add received canonical siblings');
}
await fs.writeFile(argv[1], JSON.stringify({mcpServers:{[argv[4]]:target}, imports:[]}));
// Noise must stay suppressed by execute(quiet=True), never become JSON output.
console.log('native fixture output, not wrapper JSON');
console.error('native fixture diagnostic');
'''

DRIVER = r'''
import importlib.util, json, pathlib, sys
from unittest.mock import patch
scripts, root, version, operation = sys.argv[1:5]
sys.path.insert(0, scripts)
spec = importlib.util.spec_from_file_location('pipeline_entry', pathlib.Path(scripts)/'pmcp.py')
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)
root = pathlib.Path(root)
with patch.object(entry, 'account_home', return_value=root/'account'), \
     patch.object(entry, 'RUNTIME', root/'runtime'), \
     patch.object(entry, 'PACKAGE', root/'runtime/node_modules/mcporter'), \
     patch.object(entry, 'install_lock', return_value=entry.nullcontext()), \
     patch.object(sys, 'argv', ['pmcp.py', operation, *sys.argv[5:]]):
    sys.exit(entry.main())
'''


@unittest.skipUnless(os.name == 'posix', 'Linux process-boundary verification')
class ProcessPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('node'):
            raise unittest.SkipTest('Existing Node required; never installed by tests')
        cls.node, cls.node_version = installer.resolve_node()
        try:
            cls.npm = installer.resolve_npm_cli(cls.node)
        except RuntimeError as error:
            raise unittest.SkipTest(str(error))

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='pmcp-process-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / 'account').mkdir(mode=0o700)
        self.package = self.root / 'runtime/node_modules/mcporter'
        (self.package / 'dist').mkdir(parents=True)
        (self.package / 'dist/index.js').write_text(FAKE_API, encoding='utf-8')
        (self.package / 'dist/cli.js').write_text(FAKE_CLI, encoding='utf-8')
        self.driver = self.root / 'driver.py'
        self.driver.write_text(DRIVER, encoding='utf-8')
        self.receipt = self.root / 'receipt.jsonl'
        self.env = os.environ.copy()
        self.env.update({'FIXTURE_RECEIPT': str(self.receipt), 'PYTHONDONTWRITEBYTECODE': '1'})

    def provision(self, version):
        (self.package / 'package.json').write_text(json.dumps({
            'name':'mcporter', 'version':version, 'type':'module', 'engines':{'node':'*'},
        }), encoding='utf-8')
        (self.root / 'runtime/skill-install.json').write_text(json.dumps({
            'schemaVersion':1, 'package':'mcporter', 'version':version,
            'nodeVersion':self.node_version, 'cli':'node_modules/mcporter/dist/cli.js',
        }), encoding='utf-8')
        result = self.run_entry(version, 'init')
        self.assertEqual(result.returncode, 0, result.stderr)
        config = Path(json.loads(result.stdout)['config'])
        self.assertEqual(config, self.root / 'account/.pmcp/config/mcp.json')
        config.write_text(json.dumps({'imports':[], 'mcpServers':{
            'fixture':{'command':'never-spawn', 'lifecycle':'ephemeral'},
        }}), encoding='utf-8')
        return config

    def run_entry(self, version, operation, *args, payload=None):
        return subprocess.run([sys.executable, str(self.driver), str(SCRIPTS),
                               str(self.root), version, operation, *args],
                              input=json.dumps(payload, ensure_ascii=False) if payload is not None else '',
                              capture_output=True, text=True, encoding='utf-8',
                              env=self.env, timeout=15)

    def test_native_add_http_and_stdio_then_ordinary_pipeline_without_spawning(self):
        for version in ('0.9.0', '0.15.0'):
            with self.subTest(version=version):
                config = self.provision(version)
                # Reset only this test's isolated config, not real account state.
                config.write_text('{"imports":[],"mcpServers":{}}', encoding='utf-8')
                before = config.read_bytes()
                preview = self.run_entry(version, 'config-add', 'preview', '--command',
                                         'must-never-be-spawned', '--dry-run')
                self.assertEqual(preview.returncode, 0, preview.stderr)
                self.assertFalse(json.loads(preview.stdout)['written'])
                self.assertEqual(config.read_bytes(), before)
                web = self.run_entry(version, 'config-add', 'web', '--url',
                                     'https://example.invalid/mcp', '--oauth', '--header',
                                     'Authorization=Bearer ${FIXTURE_TOKEN}')
                self.assertEqual(web.returncode, 0, web.stderr)
                self.assertEqual(web.stderr, '')
                self.assertFalse(json.loads(web.stdout)['connected'])
                local = self.run_entry(version, 'config-add', 'local', '--command',
                                       'must-never-be-spawned', '--arg=--config', '--arg',
                                       'child.json', '--arg=--root', '--arg', 'child-root',
                                       '--cwd', str(self.root), '--env', 'TOKEN=${FIXTURE_TOKEN}')
                self.assertEqual(local.returncode, 0, local.stderr)
                self.assertEqual(local.stderr, '')
                self.assertTrue(json.loads(local.stdout)['written'])
                data = json.loads(config.read_text(encoding='utf-8'))
                self.assertEqual(data, {'imports': [], 'mcpServers': {
                    'web': {'baseUrl': 'https://example.invalid/mcp', 'auth': 'oauth',
                            'headers': {'Authorization': 'Bearer ${FIXTURE_TOKEN}'}, 'lifecycle': 'ephemeral'},
                    'local': {'command': 'must-never-be-spawned', 'args': ['--config', 'child.json', '--root', 'child-root'],
                              'cwd': str(self.root), 'env': {'TOKEN': '${FIXTURE_TOKEN}'}, 'lifecycle': 'ephemeral'}}})
                self.assertFalse(self.receipt.exists())
                self.assertEqual(list(config.parent.glob('.pmcp-add-*')), [])
                self.assertFalse((self.root / 'account/.pmcp/home/.mcporter').exists())
                servers = self.run_entry(version, 'servers')
                self.assertEqual(servers.returncode, 0, servers.stderr)
                self.assertEqual(json.loads(servers.stdout)['servers'], ['local', 'web'])
                tools = self.run_entry(version, 'tools', 'local')
                self.assertEqual(tools.returncode, 0, tools.stderr)
                self.assertEqual(json.loads(tools.stdout)['tools'][0]['name'], 'echo_fixture')
                self.assertFalse(self.receipt.exists())
                call = self.run_entry(version, 'call', 'local', 'echo_fixture', payload={'afterAdd': True})
                self.assertEqual(call.returncode, 0, call.stderr)
                self.assertEqual(json.loads(call.stdout)['structuredContent'], {'afterAdd': True})
                self.assertEqual(self.receipt.read_text().splitlines(), ['{"afterAdd":true}'])
                self.receipt.unlink()  # Verified receipt in this test's temporary root.

    def test_entry_to_node_pipeline_and_input_types(self):
        for version in ('0.9.0', '0.15.0'):
            with self.subTest(version=version):
                self.provision(version)
                cases = [('version', (), {'backend':{'package':'mcporter','version':version}}),
                         ('servers', (), {'servers':['fixture']}),
                         ('doctor', (), {'ok':True, 'backend':{'package':'mcporter','version':version}})]
                for operation, args, expected in cases:
                    result = self.run_entry(version, operation, *args)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    value = json.loads(result.stdout)
                    for key, wanted in expected.items():
                        self.assertEqual(value[key], wanted)
                self.assertFalse(self.receipt.exists())
                tools = self.run_entry(version, 'tools', 'fixture', '--query', '[ECHO]')
                self.assertEqual(tools.returncode, 0, tools.stderr)
                self.assertEqual(json.loads(tools.stdout)['tools'][0]['name'], 'echo_fixture')
                schema = self.run_entry(version, 'schema', 'fixture', 'echo_fixture')
                self.assertEqual(schema.returncode, 0, schema.stderr)
                self.assertEqual(json.loads(schema.stdout)['tool']['inputSchema'], {'type':'object'})
                for fail in (False, True):
                    payload = {'id':'00123', 'text':'中文 🧪', 'empty':'', 'nested':[None, True, {'n':3}], 'fail':fail}
                    result = self.run_entry(version, 'call', 'fixture', 'echo_fixture', payload=payload)
                    self.assertEqual(result.returncode, 2 if fail else 0, result.stderr)
                    value = json.loads(result.stdout)
                    self.assertEqual(value['structuredContent'], payload)
                    self.assertEqual(value['_meta'], {'fixture':True})
                    self.assertEqual(value['isError'], fail)
                    self.assertEqual(result.stderr, '')
                typo = self.run_entry(version, 'call', 'fixture', 'echo_fixtur', payload={})
                self.assertEqual(typo.returncode, 1)
                self.assertEqual(json.loads(typo.stdout)['error']['code'], 'UNKNOWN_TOOL')
                invalid = self.run_entry(version, 'call', 'fixture', 'echo_fixture', payload=[])
                self.assertEqual(invalid.returncode, 1)
                self.assertEqual(json.loads(invalid.stdout)['error']['code'], 'INVALID_INPUT')
                self.assertEqual(len(self.receipt.read_text().splitlines()), 2)
                self.receipt.unlink()  # Only this fixture's receipt; temp root above is known.
                self.assertFalse((self.root / 'account/.pmcp/home/.mcporter').exists())


class CapabilityIndexTests(unittest.TestCase):
    """Real unified CLI, copied skill and import-only installer; no Node on PATH."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='pmcp-index-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.scripts = self.root / 'scripts'
        self.scripts.mkdir()
        for name in ('pmcp.py', 'install_runtime.py'):
            shutil.copyfile(SCRIPTS / name, self.scripts / name)
        self.skill = self.root / 'SKILL.md'
        self.before = (SCRIPTS.parent / 'SKILL.md').read_bytes()
        self.skill.write_bytes(self.before)
        self.manifest = self.root / 'capabilities.json'
        self.env = os.environ.copy()
        self.env.update({'PATH': '', 'PYTHONDONTWRITEBYTECODE': '1',
                         'HOME': str(self.root / 'unused-home'),
                         'USERPROFILE': str(self.root / 'unused-home')})

    def run_meta(self, *args, success=True):
        result = subprocess.run([sys.executable, str(self.scripts / 'pmcp.py'), *args],
                                cwd=self.root, env=self.env, capture_output=True,
                                text=True, encoding='utf-8', timeout=10)
        self.assertFalse((self.scripts / '.runtime').exists())
        self.assertFalse((self.root / '.pmcp').exists())
        self.assertFalse((self.root / '.portable-mcp').exists())
        self.assertFalse((self.root / 'unused-home').exists())
        self.assertEqual(sorted(p.name for p in self.scripts.iterdir()),
                         ['install_runtime.py', 'pmcp.py'])
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, '')
            return json.loads(result.stdout)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertIn('PMCP_META_FAILED:', result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        return result

    def write_manifest(self, value):
        self.manifest.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        return str(self.manifest)

    def snapshot(self):
        info = self.skill.stat()
        return self.skill.read_bytes(), info.st_ino, info.st_mtime_ns, info.st_mode

    def assert_only_index_changed(self, before):
        def mask(raw):
            lines = raw.splitlines(keepends=True)
            return b''.join(b'  PMCP_CAPABILITIES=<INDEX>\n'
                            if line.startswith(b'  PMCP_CAPABILITIES=') else line
                            for line in lines)
        self.assertEqual(mask(self.skill.read_bytes()), mask(before))

    def test_index_lifecycle_only_changes_description_without_node(self):
        self.assertIsNone(shutil.which('node', path=self.env['PATH']))
        self.assertEqual(self.run_meta('meta-list')['capabilities'], {})
        self.assertFalse(self.run_meta('meta-add', 'demo', '发现测试工具', '--dry-run')['written'])
        self.assertEqual(self.skill.read_bytes(), self.before)
        self.assertTrue(self.run_meta('meta-add', 'demo', '发现测试工具')['written'])
        self.assert_only_index_changed(self.before)
        manifest = self.write_manifest({'second': '读取测试状态'})
        self.assertEqual(set(self.run_meta('meta-sync', '--input', manifest)['capabilities']),
                         {'demo', 'second'})
        self.run_meta('meta-rm', 'demo')
        self.run_meta('meta-rm', 'second')
        self.assertEqual(self.skill.read_bytes(), self.before)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()),
                         ['SKILL.md', 'capabilities.json', 'scripts'])

    def test_sync_merge_replace_dry_run_and_idempotence(self):
        self.run_meta('meta-add', 'old', '旧服务')
        self.run_meta('meta-add', 'same', '不变服务')
        manifest = self.write_manifest([{'name': 'same', 'summary': '不变服务'},
                                        {'name': 'new', 'summary': '新服务'}])
        before = self.snapshot()
        preview = self.run_meta('meta-sync', '--input', manifest, '--replace', '--dry-run')
        self.assertEqual(preview['capabilities'], {'same': '不变服务', 'new': '新服务'})
        self.assertEqual(preview['diff'], {'added': ['new'], 'updated': [],
                                         'removed': ['old'], 'unchanged': ['same']})
        self.assertTrue(preview['changed'])
        self.assertFalse(preview['written'])
        self.assertTrue(preview['dryRun'])
        self.assertEqual(self.snapshot(), before)
        merged = self.run_meta('meta-sync', '--input', manifest)
        self.assertEqual(set(merged['capabilities']), {'old', 'same', 'new'})
        self.assertEqual(merged['diff']['removed'], [])
        replaced = self.run_meta('meta-sync', '--input', manifest, '--replace')
        self.assertEqual(replaced['diff']['removed'], ['old'])
        self.assertTrue(replaced['written'])
        before = self.snapshot()
        again = self.run_meta('meta-sync', '--input', manifest, '--replace')
        self.assertFalse(again['written'])
        self.assertFalse(again['changed'])
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.run_meta('meta-add', 'same', '不变服务')['changed'])
        self.assertFalse(self.run_meta('meta-rm', 'absent')['changed'])
        self.assertEqual(self.snapshot(), before)
        self.write_manifest({'same': '更新服务'})
        updated = self.run_meta('meta-sync', '--input', manifest)
        self.assertEqual(updated['diff']['updated'], ['same'])
        self.assertEqual(updated['capabilities']['new'], '新服务')
        self.assert_only_index_changed(self.before)

    def test_malicious_summaries_rejected_without_rewriting(self):
        for value in ('', ' leading', 'trailing ', 'x' * 161, 'a\nname: injected',
                      'a\rb', 'a\tb', 'a\u202eb', 'a\u200bb', 'a\u2028b', 'a\u2029b',
                      'PMCP_CAPABILITIES={"other":"injected"}'):
            with self.subTest(value=repr(value)):
                self.run_meta('meta-add', 'demo', value, success=False)
                self.assertEqual(self.skill.read_bytes(), self.before)
        # Quotes/YAML-looking text are data inside JSON, not executable metadata.
        summary = '读取 "quoted": {value} --- [service]'
        self.assertEqual(self.run_meta('meta-add', 'demo', summary)['capabilities'],
                         {'demo': summary})
        self.assert_only_index_changed(self.before)

    def test_invalid_names_limits_and_nonfinite_lock_timeout(self):
        for name in ('../demo', '.demo', '服务', 'x' * 65):
            with self.subTest(name=name):
                self.run_meta('meta-add', name, 'summary', success=False)
        for value in ('nan', 'inf', '-1', '61'):
            with self.subTest(timeout=value):
                self.run_meta('meta-list', '--lock-timeout=' + value, success=False)
        for manifest in ({f's{i}': 'summary' for i in range(25)},
                         {f's{i}': '测' * 160 for i in range(10)}):
            with self.subTest(entries=len(manifest)):
                self.run_meta('meta-sync', '--input', self.write_manifest(manifest), success=False)
        self.assertEqual(self.skill.read_bytes(), self.before)

    def test_duplicate_json_and_invalid_manifests_are_rejected(self):
        inputs = ('{"demo":"first","demo":"second"}',
                  '[{"name":"demo","summary":"first"},{"name":"demo","summary":"second"}]',
                  '[{"name":"demo","summary":"first","summary":"second"}]',
                  '[{"name":"demo","summary":"first","secret":"do-not-echo"}]',
                  '[{"name":"demo","summary":null}]', '[] trailing-do-not-echo', 'null')
        for text in inputs:
            with self.subTest(text=text):
                self.manifest.write_text(text, encoding='utf-8')
                result = self.run_meta('meta-sync', '--input', str(self.manifest), success=False)
                self.assertNotIn('do-not-echo', result.stderr)
                self.assertEqual(self.skill.read_bytes(), self.before)
        self.manifest.write_bytes(b'\xffdo-not-echo')
        result = self.run_meta('meta-sync', '--input', str(self.manifest), success=False)
        self.assertNotIn('do-not-echo', result.stderr)

    def test_ambiguous_frontmatter_or_index_is_preserved(self):
        text = self.before.decode('utf-8')
        variants = (text.replace('PMCP_CAPABILITIES={}',
                                 'PMCP_CAPABILITIES={"demo":"one","demo":"two"}', 1),
                    text.replace('description: >-', 'description: ignored\ndescription: >-', 1),
                    text.replace('description: >-', '"description": ignored\ndescription: >-', 1),
                    text.replace('PMCP_CAPABILITIES={}',
                                 'PMCP_CAPABILITIES={}\n  PMCP_CAPABILITIES={}', 1),
                    text.replace('description: >-', 'description: |', 1))
        for malformed in variants:
            with self.subTest(frontmatter=malformed[:100]):
                self.assertNotEqual(malformed, text)
                self.skill.write_text(malformed, encoding='utf-8')
                before = self.snapshot()
                self.run_meta('meta-add', 'demo', 'summary', success=False)
                self.assertEqual(self.snapshot(), before)
                self.assertFalse((self.root / '.pmcp-meta.lock').exists())

    def test_writer_lock_busy_but_list_and_dry_run_do_not_lock(self):
        lock = self.root / '.pmcp-meta.lock'
        lock.mkdir()
        before = self.snapshot()
        result = self.run_meta('meta-add', 'demo', 'summary', '--lock-timeout', '0', success=False)
        self.assertIn('lock is busy', result.stderr)
        self.assertTrue(lock.is_dir())
        self.assertEqual(self.run_meta('meta-list')['capabilities'], {})
        preview = self.run_meta('meta-add', 'demo', 'summary', '--dry-run', '--lock-timeout', '0')
        self.assertTrue(preview['changed'])
        self.assertFalse(preview['written'])
        manifest = self.write_manifest({'demo': 'summary'})
        self.assertFalse(self.run_meta('meta-sync', '--input', manifest, '--replace', '--dry-run')['written'])
        self.assertEqual(self.snapshot(), before)
        lock.rmdir()  # Known empty lock in this test's temporary root only.
        self.assertTrue(self.run_meta('meta-add', 'demo', 'summary')['written'])
        self.assertFalse(lock.exists())

    def test_crlf_mode_and_other_metadata_are_preserved(self):
        crlf = self.before.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
        self.skill.write_bytes(crlf)
        if os.name == 'posix':
            self.skill.chmod(0o640)
        mode = self.skill.stat().st_mode
        self.run_meta('meta-add', 'demo', 'summary')
        self.assert_only_index_changed(crlf)
        self.assertNotIn(b'\n', self.skill.read_bytes().replace(b'\r\n', b''))
        self.assertEqual(self.skill.stat().st_mode, mode)
        self.run_meta('meta-rm', 'demo')
        self.assertEqual(self.skill.read_bytes(), crlf)


if __name__ == '__main__':
    unittest.main(verbosity=2)
