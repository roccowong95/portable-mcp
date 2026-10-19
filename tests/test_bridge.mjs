// Deterministic unit tests only: no installed mcporter, CLI, network, OAuth,
// subprocess, or server is used. Sync into an isolated Linux validation directory.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { BridgeError, executeBridge, parseArguments } from '../src/skills/portable-mcp/scripts/mcp_bridge.mjs';

const VERSIONS = ['0.9.0', '0.15.0'];
const TIMEOUT = 1234;
const TOOL = Object.freeze({
  name: 'exact_tool',
  description: 'Read a literal [value]',
  inputSchema: { type: 'object', properties: { value: { type: 'string' } }, required: ['value'] },
  outputSchema: { type: 'object', properties: { accepted: { type: 'boolean' } } },
});
const RESULT = Object.freeze({
  content: [{ type: 'text', text: 'raw MCP result' }, { type: 'image', data: 'AA==', mimeType: 'image/png' }],
  structuredContent: { accepted: true },
  _meta: { marker: 'preserve' },
  isError: false,
});
const PRIVATE_ERROR = 'Bearer NEVER_PRINT_THIS; https://private.invalid/?token=SECRET';

function isCode(code) {
  return (error) => {
    assert.ok(error instanceof BridgeError);
    assert.equal(error.code, code);
    assert.ok(!error.message.includes('NEVER_PRINT_THIS'));
    assert.ok(!error.message.includes('SECRET'));
    return true;
  };
}

async function fixture(t, options = {}) {
  // Temporary configuration is deliberately outside the checkout and is removed
  // even on assertion failure. Production state/home and process.env are untouched.
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'portable-mcp-bridge-test-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const configPath = path.join(root, 'mcporter.json');
  const definitions = options.definitions ?? [Object.freeze({
    name: 'example', command: Object.freeze({ kind: 'stdio', command: 'never-spawn' }),
    lifecycle: Object.freeze({ mode: 'ephemeral' }),
  })];
  const rawServers = options.rawServers ?? Object.fromEntries(definitions.map(({ name }) => [name, {
    command: 'never-spawn', lifecycle: 'ephemeral',
  }]));
  await fs.writeFile(configPath, JSON.stringify(options.config ?? { mcpServers: rawServers, imports: [] }));
  const events = [];
  const record = (name, args) => events.push({ name, args });
  let page = 0;
  const close = (name) => async () => {
    record(name, []);
    if (options.closeThrows) throw new Error(PRIVATE_ERROR);
  };
  const invoke = async (name, args) => {
    record(name, args);
    if (options.callThrows) throw new Error(PRIVATE_ERROR);
    return Object.hasOwn(options, 'result') ? options.result : RESULT;
  };
  const context = {
    client: {
      listTools: async (...args) => {
        record('client.listTools', args);
        if (options.listThrows) throw new Error(PRIVATE_ERROR);
        if (options.legacyPage) return options.legacyPage(page++, args);
        return { tools: options.tools ?? [TOOL] };
      },
      callTool: (...args) => invoke('client.callTool', args),
      close: close('client.close'),
    },
    transport: { close: close('transport.close') },
    oauthSession: { close: close('oauthSession.close') },
  };
  const runtime = {
    connect: async (...args) => {
      record('connect', args);
      if (options.connectThrows) throw new Error(PRIVATE_ERROR);
      return context;
    },
    listTools: async (...args) => {
      record('listTools', args);
      if (options.listThrows) throw new Error(PRIVATE_ERROR);
      return options.tools ?? [TOOL];
    },
    callTool: (...args) => invoke('callTool', args),
    close: close('runtime.close'),
  };
  const api = {
    loadServerDefinitions: async (...args) => {
      record('load', args);
      if (options.loadThrows) throw new Error(PRIVATE_ERROR);
      return definitions;
    },
    createRuntime: async (...args) => {
      record('create', args);
      return runtime;
    },
  };
  const calls = (name) => events.filter((event) => event.name === name).map((event) => event.args);
  const run = (request = {}, execution = {}) => executeBridge(api, {
    configPath, operation: 'call', server: 'example', tool: TOOL.name, timeoutMs: TIMEOUT, ...request,
  }, { version: options.version ?? '0.9.0', args: { value: 'payload' }, ...execution });
  return { root, configPath, definitions, api, calls, events, run };
}

function assertClosed(f, version, connected = true) {
  assert.equal(f.calls('runtime.close').length, 1);
  for (const name of ['client.close', 'transport.close', 'oauthSession.close']) {
    assert.equal(f.calls(name).length, version === '0.9.0' && connected ? 1 : 0, name);
  }
}

for (const version of VERSIONS) {
  const modern = version === '0.15.0';
  const callName = modern ? 'callTool' : 'client.callTool';

  test(`${version}: exact invocation once, correct no-OAuth signatures and raw result`, async (t) => {
    const f = await fixture(t, { version });
    const args = { value: 'literal', nested: { untouched: true } };
    const outcome = await f.run({}, { args });
    assert.equal(outcome.output, RESULT);
    assert.equal(outcome.exitCode, 0);
    assert.deepEqual(f.calls('load'), [[{ configPath: f.configPath }]]);
    assert.equal(f.calls('create').length, 1);
    const createOptions = f.calls('create')[0][0];
    assert.equal(createOptions.configPath, f.configPath);
    assert.deepEqual(createOptions.servers, f.definitions);
    for (const method of ['debug', 'info', 'warn', 'error']) {
      assert.equal(typeof createOptions.logger[method], 'function');
      assert.equal(createOptions.logger[method](PRIVATE_ERROR), undefined);
    }
    if (modern) {
      assert.deepEqual(f.calls('listTools'), [['example', {
        includeSchema: true, autoAuthorize: false, disableOAuth: true,
        allowCachedAuth: true, timeoutMs: TIMEOUT,
      }]]);
      assert.deepEqual(f.calls(callName), [['example', TOOL.name, { args, timeoutMs: TIMEOUT, disableOAuth: true }]]);
      assert.equal(f.calls('connect').length, 0);
      assert.equal(f.calls('client.callTool').length, 0);
    } else {
      assert.deepEqual(f.calls('connect'), [['example', { maxOAuthAttempts: 0, skipCache: true, allowCachedAuth: true }]]);
      assert.deepEqual(f.calls('client.listTools'), [[undefined, { timeout: TIMEOUT, maxTotalTimeout: TIMEOUT }]]);
      assert.deepEqual(f.calls(callName), [[{ name: TOOL.name, arguments: args }, undefined, {
        timeout: TIMEOUT, maxTotalTimeout: TIMEOUT,
      }]]);
      assert.equal(f.calls('listTools').length, 0);
      assert.equal(f.calls('callTool').length, 0);
    }
    assert.ok(f.events.findIndex(({ name }) => name.includes('listTools')) <
      f.events.findIndex(({ name }) => name === callName));
    assertClosed(f, version);
  });

  test(`${version}: MCP isError retains the entire envelope and exits 2, even if cleanup fails`, async (t) => {
    const result = { ...RESULT, isError: true, content: [{ type: 'text', text: 'application failure' }] };
    const f = await fixture(t, { version, result, closeThrows: true });
    assert.deepEqual(await f.run(), { output: result, exitCode: 2 });
    assert.equal(f.calls(callName).length, 1);
    assertClosed(f, version);
  });

  test(`${version}: thrown call is sanitized and never retried or autocorrected`, async (t) => {
    const f = await fixture(t, { version, callThrows: true, closeThrows: true });
    await assert.rejects(f.run(), isCode('TRANSPORT_FAILED'));
    assert.equal(f.calls(callName).length, 1);
    assertClosed(f, version);
  });

  test(`${version}: malformed call result fails once without retry`, async (t) => {
    const f = await fixture(t, { version, result: null });
    await assert.rejects(f.run(), isCode('TRANSPORT_FAILED'));
    assert.equal(f.calls(callName).length, 1);
    assertClosed(f, version);
  });

  test(`${version}: discovery failures close resources without dispatching`, async (t) => {
    const f = await fixture(t, { version, listThrows: true });
    await assert.rejects(f.run(), isCode('TRANSPORT_FAILED'));
    assert.equal(f.calls(callName).length, 0);
    assertClosed(f, version);
  });

  test(`${version}: typo, case change and fuzzy tool aliases fail without a call`, async (t) => {
    for (const tool of ['exact_too', 'EXACT_TOOL', 'example.exact_tool', 'exact_tool ']) {
      const f = await fixture(t, { version });
      await assert.rejects(f.run({ tool }), isCode('UNKNOWN_TOOL'));
      assert.equal(f.calls(callName).length, 0);
      assertClosed(f, version);
    }
  });

  test(`${version}: URL and fuzzy server aliases cannot create a runtime`, async (t) => {
    for (const server of ['https://example.invalid/mcp', 'Example', 'example ', 'exampl']) {
      const f = await fixture(t, { version });
      await assert.rejects(f.run({ server }), isCode('UNKNOWN_SERVER'));
      assert.equal(f.calls('create').length, 0);
    }
  });

  test(`${version}: normalized allow/block filters apply to tools, schema and calls`, async (t) => {
    for (const filters of [{ allowedTools: [] }, { blockedTools: [TOOL.name] }]) {
      const definitions = [{ name: 'example', command: { kind: 'stdio' }, ...filters }];
      for (const operation of ['call', 'schema', 'tools']) {
        const f = await fixture(t, { version, definitions });
        if (operation === 'tools') {
          assert.deepEqual(await f.run({ operation }), { output: { server: 'example', tools: [] }, exitCode: 0 });
        } else {
          await assert.rejects(f.run({ operation }), isCode('UNKNOWN_TOOL'));
        }
        assert.equal(f.calls(callName).length, 0);
        assertClosed(f, version);
      }
    }
  });

  test(`${version}: tools query is literal, case insensitive; schema returns the API object`, async (t) => {
    const f = await fixture(t, { version });
    assert.deepEqual(await f.run({ operation: 'tools', query: '[VALUE]' }), {
      output: { server: 'example', tools: [TOOL] }, exitCode: 0,
    });
    const schema = await f.run({ operation: 'schema' });
    assert.equal(schema.output.tool, TOOL);
    assert.equal(schema.exitCode, 0);
    assert.equal(f.calls(callName).length, 0);
    // Modern metadata is only what runtime.listTools returns. This fake does
    // not claim to exercise upstream's metadata projection.
  });

  test(`${version}: invalid or ambiguous discovery fails closed`, async (t) => {
    for (const tools of [[TOOL, TOOL], [{ name: '' }], [{ name: 7 }]]) {
      const f = await fixture(t, { version, tools });
      await assert.rejects(f.run(), isCode('INVALID_TOOL_LIST'));
      assert.equal(f.calls(callName).length, 0);
      assertClosed(f, version);
    }
  });

  test(`${version}: restores raw stdio cwd without mutating loader objects`, async (t) => {
    const cwd = os.tmpdir();
    const f = await fixture(t, { version, rawServers: { example: {
      command: 'never-spawn', lifecycle: 'ephemeral', cwd,
    } } });
    await f.run();
    const restored = f.calls('create')[0][0].servers[0];
    assert.equal(restored.command.cwd, cwd);
    assert.notEqual(restored, f.definitions[0]);
    assert.notEqual(restored.command, f.definitions[0].command);
    assert.equal(f.definitions[0].command.cwd, undefined);
  });

  test(`${version}: servers and doctor never create a runtime`, async (t) => {
    const f = await fixture(t, { version, definitions: [
      { name: 'zeta', command: { kind: 'http' }, lifecycle: { mode: 'ephemeral' } },
      { name: 'alpha', command: { kind: 'stdio' }, lifecycle: { mode: 'ephemeral' } },
    ] });
    assert.deepEqual(await f.run({ operation: 'servers' }), { output: { servers: ['alpha', 'zeta'] }, exitCode: 0 });
    const doctor = await f.run({ operation: 'doctor' });
    assert.equal(doctor.exitCode, 0);
    assert.equal(doctor.output.ok, true);
    assert.deepEqual(doctor.output.backend, { package: 'mcporter', version });
    assert.equal(doctor.output.nodeVersion, process.version);
    assert.deepEqual(doctor.output.servers, ['alpha', 'zeta']);
    assert.deepEqual(doctor.output.unsupportedServers, []);
    assert.deepEqual(doctor.output.features, {
      lifecycle: 'ephemeral', interactiveOAuth: false, cachedOAuth: true, toolRetries: false,
      toolMetadata: modern ? 'runtime-name-description-input-output-schema' : 'raw-mcp-tool',
    });
    assert.equal(f.calls('create').length, 0);
  });
}

test('legacy: cursor pages preserve full Tool metadata and SDK1 request options', async (t) => {
  const extended = { ...TOOL, title: 'Full metadata', annotations: { readOnlyHint: true }, _meta: { marker: 1 } };
  const f = await fixture(t, { legacyPage: (page) => page === 0
    ? { tools: [], nextCursor: 'page-two' } : { tools: [extended] } });
  const result = await f.run({ operation: 'schema' });
  assert.equal(result.output.tool, extended);
  assert.deepEqual(f.calls('client.listTools'), [
    [undefined, { timeout: TIMEOUT, maxTotalTimeout: TIMEOUT }],
    [{ cursor: 'page-two' }, { timeout: TIMEOUT, maxTotalTimeout: TIMEOUT }],
  ]);
  assert.equal(f.calls('client.callTool').length, 0);
  assertClosed(f, '0.9.0');
});

test('legacy: repeated cursors are rejected before invocation and context is closed', async (t) => {
  const f = await fixture(t, { legacyPage: () => ({ tools: [], nextCursor: 'same' }) });
  await assert.rejects(f.run(), isCode('TOOL_LIST_LIMIT'));
  assert.equal(f.calls('client.listTools').length, 2);
  assert.equal(f.calls('client.callTool').length, 0);
  assertClosed(f, '0.9.0');
});

test('legacy: pagination is bounded to 100 unique cursors', async (t) => {
  const f = await fixture(t, { legacyPage: (page) => ({ tools: [], nextCursor: `cursor-${page}` }) });
  await assert.rejects(f.run(), isCode('TOOL_LIST_LIMIT'));
  assert.equal(f.calls('client.listTools').length, 100);
  assert.equal(f.calls('client.callTool').length, 0);
  assertClosed(f, '0.9.0');
});

test('legacy: connect failure closes runtime without assuming a returned context', async (t) => {
  const f = await fixture(t, { connectThrows: true });
  await assert.rejects(f.run(), isCode('TRANSPORT_FAILED'));
  assert.equal(f.calls('connect').length, 1);
  assert.equal(f.calls('client.callTool').length, 0);
  assertClosed(f, '0.9.0', false);
});

test('doctor reports unsupported lifecycle/auth offline; ordinary operations reject them', async (t) => {
  const definitions = [
    { name: 'keeper', command: { kind: 'stdio' }, lifecycle: { mode: 'keep-alive' } },
    { name: 'refresh', command: { kind: 'http' }, auth: 'refreshable_bearer' },
  ];
  const f = await fixture(t, { definitions });
  const result = await f.run({ operation: 'doctor' });
  assert.equal(result.exitCode, 1);
  assert.equal(result.output.ok, false);
  assert.deepEqual(result.output.unsupportedServers, [
    { server: 'keeper', code: 'UNSUPPORTED_LIFECYCLE' },
    { server: 'refresh', code: 'UNSUPPORTED_AUTH' },
  ]);
  await assert.rejects(f.run({ server: 'keeper' }), isCode('UNSUPPORTED_LIFECYCLE'));
  await assert.rejects(f.run({ server: 'refresh' }), isCode('UNSUPPORTED_AUTH'));
  assert.equal(f.calls('create').length, 0);
});

test('cwd rejects relative/non-string values and HTTP placement before runtime creation', async (t) => {
  for (const cwd of ['relative', '', null, 17]) {
    const f = await fixture(t, { rawServers: { example: { command: 'never-spawn', cwd } } });
    await assert.rejects(f.run(), isCode('INVALID_CONFIG'));
    assert.equal(f.calls('create').length, 0);
  }
  const f = await fixture(t, {
    rawServers: { example: { url: 'https://never-connect.invalid/mcp', cwd: os.tmpdir() } },
    definitions: [{ name: 'example', command: { kind: 'http' } }],
  });
  await assert.rejects(f.run(), isCode('INVALID_CONFIG'));
  assert.equal(f.calls('create').length, 0);
});

test('isolated config rejects imports, refresh/cache overrides, and arbitrary top-level keys', async (t) => {
  for (const config of [
    { mcpServers: {}, imports: ['external'] },
    { mcpServers: {} },
    { mcpServers: {}, imports: [], extra: true },
    ...['tokenCacheDir', 'token_cache_dir', 'refresh'].map((key) => ({
      mcpServers: { example: { [key]: 'private' } }, imports: [],
    })),
    { mcpServers: { example: { auth: 'refreshable_bearer' } }, imports: [] },
  ]) {
    const f = await fixture(t, { config });
    await assert.rejects(f.run(), isCode('INVALID_CONFIG'));
    assert.equal(f.calls('load').length, 0);
    assert.equal(f.calls('create').length, 0);
  }
});

test('loader exceptions are sanitized and cannot start a runtime', async (t) => {
  const f = await fixture(t, { loadThrows: true });
  await assert.rejects(f.run(), isCode('INVALID_CONFIG'));
  assert.equal(f.calls('create').length, 0);
});

test('call arguments must be a JSON object before config loading or dispatch', async (t) => {
  for (const args of [null, [], 'text', 9, true]) {
    const f = await fixture(t);
    await assert.rejects(f.run({}, { args }), isCode('INVALID_INPUT'));
    assert.equal(f.calls('load').length, 0);
    assert.equal(f.calls('create').length, 0);
  }
});

test('parseArguments accepts the documented positional interface and explicit timeout/query', () => {
  const packagePath = path.join(os.tmpdir(), 'fake-package');
  const configPath = path.join(os.tmpdir(), 'fake-config.json');
  assert.deepEqual(parseArguments([packagePath, configPath, 'call', 'example', TOOL.name]), {
    packagePath, configPath, operation: 'call', server: 'example', tool: TOOL.name,
    query: undefined, timeoutMs: 60_000,
  });
  assert.deepEqual(parseArguments([packagePath, configPath, 'tools', 'example', '--query', '[VALUE]', '--timeout', '1234']), {
    packagePath, configPath, operation: 'tools', server: 'example', tool: undefined,
    query: '[VALUE]', timeoutMs: TIMEOUT,
  });
});

test('parseArguments rejects unsupported flags, wrong arity and unsafe timeouts', () => {
  const packagePath = path.join(os.tmpdir(), 'fake-package');
  const configPath = path.join(os.tmpdir(), 'fake-config.json');
  const base = [packagePath, configPath];
  for (const argv of [
    [], ['relative', configPath, 'servers'], [packagePath, 'relative', 'servers'],
    [...base, 'unknown'], [...base, 'servers', 'unexpected'], [...base, 'call', 'example'],
    [...base, 'call', 'example', TOOL.name, '--query', 'text'],
    [...base, 'tools', 'example', '--query'], [...base, 'tools', 'example', '--query', 'x', '--query', 'y'],
    [...base, 'tools', 'example', '--args', '-'], [...base, 'tools', 'example', '--timeout', '1', '--timeout', '2'],
    [...base, 'tools', ' example'],
    ...['0', '-1', '1.5', 'NaN', '2147483648', '9007199254740993'].map((timeout) =>
      [...base, 'tools', 'example', '--timeout', timeout]),
  ]) {
    assert.throws(() => parseArguments(argv), isCode('INVALID_ARGUMENTS'));
  }
});
