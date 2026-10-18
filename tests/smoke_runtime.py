"""Smoke-test an EXISTING mcporter package with a disposable local stdio fixture.

No install, OAuth, HTTP connection or production config/vault is used. Deployment
paths are accepted here only because this is a development test, not a skill API.
"""
import argparse
import json
import os
import signal
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / 'src/skills/portable-mcp/scripts/mcporter_bridge.mjs'
FIXTURE = r'''
import json, sys
from pathlib import Path
log = Path(sys.argv[1])
for line in sys.stdin:
    request = json.loads(line)
    if 'id' not in request:
        continue
    method = request.get('method')
    if method == 'initialize':
        result = {'protocolVersion': request['params']['protocolVersion'], 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'portable-local-fixture', 'version': '1.0.0'}}
    elif method == 'ping':
        result = {}
    elif method == 'tools/list':
        result = {'tools': [{'name': 'echo_fixture', 'description': 'Local deterministic fixture', 'inputSchema': {'type': 'object', 'properties': {'fail': {'type': 'boolean'}}}, 'annotations': {'readOnlyHint': True}}]}
    elif method == 'tools/call':
        with log.open('a') as stream:
            stream.write(json.dumps({'name': request['params']['name']}) + '\n')
        failed = request['params'].get('arguments', {}).get('fail', False)
        result = {'content': [{'type': 'text', 'text': 'fixture-error' if failed else 'fixture-ok'}], 'isError': failed, '_meta': {'fixture': True}}
    else:
        print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'error': {'code': -32601, 'message': 'Unknown fixture method'}}), flush=True)
        continue
    print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)
'''


def run_case(command, payload, env):
    # The fixture stays in this new session/process group. Always reap the
    # bridge and kill remaining group members, including on timeout/interrupt.
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, env=env,
                               start_new_session=True)
    try:
        stdout, stderr = process.communicate(json.dumps(payload), timeout=15)
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', required=True)
    parser.add_argument('--package', required=True)
    args = parser.parse_args()
    if os.name != 'posix':
        parser.error('This isolated process-group smoke test targets Linux/POSIX')
    node = Path(args.node)
    package = Path(args.package)
    if not node.is_absolute() or not node.is_file() or not package.is_absolute() or not (package / 'package.json').is_file():
        parser.error('Existing absolute Node and mcporter package paths required')
    with tempfile.TemporaryDirectory(prefix='pmcp-runtime-smoke-') as temporary:
        temp = Path(temporary)
        os.chmod(temp, 0o700)
        server = temp / 'server.py'
        server.write_text(FIXTURE, encoding='utf-8')
        log = temp / 'dispatch.jsonl'
        config = temp / 'mcporter.json'
        config.write_text(json.dumps({'imports': [], 'mcpServers': {'fixture': {'command': sys.executable, 'args': [str(server), str(log)], 'cwd': str(temp), 'lifecycle': 'ephemeral'}}}), encoding='utf-8')
        env = {key: value for key, value in os.environ.items() if not key.upper().startswith(('NODE_', 'NPM_', 'COREPACK_', 'MCPORTER_', 'MCPC_', 'PMCP_', 'PORTABLE_MCP_', 'XDG_'))}
        for kind in ('home', 'config', 'data', 'cache', 'state', 'broker'):
            (temp / kind).mkdir(mode=0o700)
        env.update({'HOME': str(temp / 'home'), 'USERPROFILE': str(temp / 'home'), 'XDG_CONFIG_HOME': str(temp / 'config'), 'XDG_DATA_HOME': str(temp / 'data'), 'XDG_CACHE_HOME': str(temp / 'cache'), 'XDG_STATE_HOME': str(temp / 'state'), 'MCPORTER_CONFIG': str(config), 'MCPORTER_DAEMON_DIR': str(temp / 'broker'), 'MCPORTER_DISABLE_KEEPALIVE': '*', 'PYTHONDONTWRITEBYTECODE': '1'})
        cases = [('tools', None, {}, 0), ('schema', 'echo_fixture', {}, 0), ('call', 'echo_fixture', {}, 0), ('call', 'echo_fixture', {'fail': True}, 2), ('call', 'echo_fixtur', {}, 1)]
        for operation, tool, payload, expected in cases:
            command = [str(node), str(BRIDGE), str(package), str(config), operation, 'fixture']
            if tool:
                command.append(tool)
            command += ['--timeout', '5000']
            result = run_case(command, payload, env)
            assert result.returncode == expected, (operation, tool, result.returncode, result.stdout, result.stderr)
            output = json.loads(result.stdout)
            assert result.stderr == '', 'Unexpected stderr from isolated bridge'
            if operation == 'call' and expected in (0, 2):
                assert output['_meta'] == {'fixture': True}, output
                assert output['isError'] == (expected == 2), output
            elif expected == 1:
                assert output['error']['code'] == 'UNKNOWN_TOOL', output
            elif operation == 'tools':
                assert output['tools'][0]['name'] == 'echo_fixture', output
            elif operation == 'schema':
                assert output['tool']['inputSchema']['type'] == 'object', output
            print(json.dumps({'operation': operation, 'tool': tool, 'exit': result.returncode, 'passed': True}), flush=True)
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        assert calls == [{'name': 'echo_fixture'}, {'name': 'echo_fixture'}], calls
        assert not (temp / 'home/.mcporter/credentials.json').exists(), 'Unexpected OAuth vault'
        assert not (temp / 'data/mcporter/credentials.json').exists(), 'Unexpected OAuth vault'
        print(json.dumps({'toolDispatches': len(calls), 'unexpectedToolDispatches': 0, 'oauthVaultCreated': False, 'passed': True}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
