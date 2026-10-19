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
        self.assertEqual(config, self.root / 'account/.portable-mcp/config/mcporter.json')
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
                self.assertFalse((self.root / 'account/.portable-mcp/home/.mcporter').exists())


class CapabilityIndexTests(unittest.TestCase):
    def test_index_lifecycle_only_changes_description(self):
        with tempfile.TemporaryDirectory(prefix='pmcp-index-test-') as temporary:
            root = Path(temporary)
            (root / 'scripts').mkdir()
            shutil.copyfile(SCRIPTS / 'pmcp-ctl', root / 'scripts/pmcp-ctl')
            skill = root / 'SKILL.md'
            skill.write_bytes((SCRIPTS.parent / 'SKILL.md').read_bytes())
            before = skill.read_text(encoding='utf-8')

            def run(*args):
                result = subprocess.run([sys.executable, str(root / 'scripts/pmcp-ctl'), *args],
                                        capture_output=True, text=True, encoding='utf-8', timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)

            self.assertEqual(run('meta-list')['capabilities'], {})
            self.assertFalse(run('meta-add', 'demo', '发现测试工具', '--dry-run')['written'])
            self.assertEqual(skill.read_text(encoding='utf-8'), before)
            self.assertTrue(run('meta-add', 'demo', '发现测试工具')['written'])
            manifest = root / 'capabilities.json'
            manifest.write_text(json.dumps({'second':'读取测试状态'}), encoding='utf-8')
            self.assertEqual(set(run('meta-sync', '--input', str(manifest))['capabilities']), {'demo','second'})
            run('meta-rm', 'demo')
            run('meta-rm', 'second')
            self.assertEqual(skill.read_text(encoding='utf-8'), before)
            self.assertEqual(sorted(p.name for p in root.iterdir()), ['SKILL.md','capabilities.json','scripts'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
