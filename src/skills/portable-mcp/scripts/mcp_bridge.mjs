#!/usr/bin/env node
// Private portable-mcp process boundary, public backend API. No native CLI calls, guessed
// tool names, retry-on-error, OAuth browser flows, daemon, or module patching.
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const MAX_PAGES = 100;
const MAX_INPUT_BYTES = 16 * 1024 * 1024;
const DEFAULT_TIMEOUT_MS = 60_000;
const noop = () => {};
const QUIET_LOGGER = Object.freeze({ debug: noop, info: noop, warn: noop, error: noop });
const MESSAGES = Object.freeze({
  INVALID_ARGUMENTS: 'Invalid bridge arguments.',
  INVALID_INPUT: 'Call input must be a JSON object.',
  INVALID_CONFIG: 'The isolated portable-mcp configuration is invalid or unsupported.',
  INVALID_PACKAGE: 'The installed runtime package is unavailable or unsupported.',
  UNSUPPORTED_RUNTIME: 'The installed runtime API is unsupported.',
  UNKNOWN_SERVER: 'The exact configured server name was not found.',
  UNKNOWN_TOOL: 'The exact permitted tool name was not found.',
  UNSUPPORTED_LIFECYCLE: 'Keep-alive is unsupported; configure lifecycle ephemeral explicitly.',
  UNSUPPORTED_AUTH: 'This authentication configuration is unsupported by the non-interactive bridge.',
  INVALID_TOOL_LIST: 'The server returned an invalid or ambiguous tool list.',
  TOOL_LIST_LIMIT: 'The server tool list exceeded the pagination limit.',
  TRANSPORT_FAILED: 'The MCP operation failed; no tool call was retried. OAuth may require explicit authorization.',
  BRIDGE_FAILED: 'The bridge could not complete the operation.',
});

export class BridgeError extends Error {
  constructor(code) {
    super(MESSAGES[code] ?? MESSAGES.BRIDGE_FAILED);
    this.name = 'BridgeError';
    this.code = Object.hasOwn(MESSAGES, code) ? code : 'BRIDGE_FAILED';
  }
}

function fail(code) {
  throw new BridgeError(code);
}

function object(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function versionParts(version) {
  const match = typeof version === 'string' && /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.exec(version);
  if (!match) fail('INVALID_PACKAGE');
  const parts = match.slice(1).map(Number);
  if (!parts.every(Number.isSafeInteger) || (parts[0] === 0 && parts[1] < 9)) fail('INVALID_PACKAGE');
  return parts;
}

export function parseArguments(argv) {
  if (!Array.isArray(argv) || argv.length < 3) fail('INVALID_ARGUMENTS');
  const [packagePath, configPath, operation, ...rest] = argv;
  if (!path.isAbsolute(packagePath) || !path.isAbsolute(configPath) ||
      !['servers', 'tools', 'schema', 'call', 'doctor'].includes(operation)) fail('INVALID_ARGUMENTS');
  const positional = [];
  const seen = new Set();
  let query;
  let timeoutMs = DEFAULT_TIMEOUT_MS;
  for (let i = 0; i < rest.length; i += 1) {
    const token = rest[i];
    if (token.startsWith('--')) {
      if (!['--query', '--timeout'].includes(token) || seen.has(token)) fail('INVALID_ARGUMENTS');
      seen.add(token);
      const value = rest[++i];
      if (value === undefined || value.startsWith('--')) fail('INVALID_ARGUMENTS');
      if (token === '--query') {
        if (operation !== 'tools') fail('INVALID_ARGUMENTS');
        query = value;
      } else {
        if (!/^[1-9]\d*$/.test(value)) fail('INVALID_ARGUMENTS');
        timeoutMs = Number(value);
        if (!Number.isSafeInteger(timeoutMs) || timeoutMs > 2_147_483_647) fail('INVALID_ARGUMENTS');
      }
    } else {
      positional.push(token);
    }
  }
  const count = { servers: 0, doctor: 0, tools: 1, schema: 2, call: 2 }[operation];
  if (positional.length !== count || positional.some((value) => !value || value.trim() !== value)) {
    fail('INVALID_ARGUMENTS');
  }
  return { packagePath, configPath, operation, server: positional[0], tool: positional[1], query, timeoutMs };
}

function validateDefinition(definition) {
  if (!object(definition) || typeof definition.name !== 'string' || !definition.name ||
      definition.name.trim() !== definition.name || !object(definition.command) ||
      !['http', 'stdio'].includes(definition.command.kind)) fail('INVALID_CONFIG');
  for (const field of ['allowedTools', 'blockedTools']) {
    const values = definition[field];
    if (values !== undefined && (!Array.isArray(values) || values.some((value) => typeof value !== 'string'))) {
      fail('INVALID_CONFIG');
    }
  }
  if (definition.allowedTools !== undefined && definition.blockedTools !== undefined) fail('INVALID_CONFIG');
}

function checkSupportedDefinition(definition) {
  if (definition.lifecycle?.mode === 'keep-alive') fail('UNSUPPORTED_LIFECYCLE');
  // No implicit refresh commands or cross-profile token-cache overrides.
  if (definition.auth === 'refreshable_bearer' || definition.refresh !== undefined ||
      definition.tokenCacheDir !== undefined) fail('UNSUPPORTED_AUTH');
}

function allowed(tool, definition) {
  if (definition.allowedTools !== undefined) return definition.allowedTools.includes(tool.name);
  if (definition.blockedTools !== undefined) return !definition.blockedTools.includes(tool.name);
  return true;
}

function validateTools(tools) {
  if (!Array.isArray(tools)) fail('INVALID_TOOL_LIST');
  const names = new Set();
  for (const tool of tools) {
    if (!object(tool) || typeof tool.name !== 'string' || !tool.name || names.has(tool.name)) {
      fail('INVALID_TOOL_LIST');
    }
    names.add(tool.name);
  }
  return tools;
}

async function listLegacyTools(context, timeoutMs) {
  const tools = [];
  const cursors = new Set();
  let cursor;
  for (let page = 0; page < MAX_PAGES; page += 1) {
    const response = await context.client.listTools(cursor === undefined ? undefined : { cursor }, {
      timeout: timeoutMs,
      maxTotalTimeout: timeoutMs,
    });
    if (!object(response) || !Array.isArray(response.tools)) fail('INVALID_TOOL_LIST');
    tools.push(...response.tools);
    cursor = response.nextCursor;
    if (cursor === undefined || cursor === null || cursor === '') return tools;
    if (typeof cursor !== 'string') fail('INVALID_TOOL_LIST');
    if (cursors.has(cursor)) fail('TOOL_LIST_LIMIT');
    cursors.add(cursor);
  }
  fail('TOOL_LIST_LIMIT');
}

async function closeLegacyContext(context) {
  if (!context) return;
  // This context is deliberately uncached: runtime.close() alone is a no-op.
  // Use the context's close methods, not private transport/process internals.
  for (const resource of [context.client, context.transport, context.oauthSession]) {
    try {
      await resource?.close?.();
    } catch {
      // Cleanup must never replace a raw tool result with an exception message.
    }
  }
}

// Injectable public API seam: callers can supply fake backend exports without
// importing a real package, spawning a server, or changing process streams.
// Resolves {output, exitCode}; the CLI below is the only JSON/stdout writer.
export async function executeBridge(api, request, { version, args = {} } = {}) {
  const [major, minor] = versionParts(version);
  // 0.9–0.11 have SDK1 and no public callTool disableOAuth option. 0.12
  // introduces the public suppression option; 0.13 switches SDK1 to SDK2.
  // Keeping SDK calls only in the legacy branch avoids signature guessing.
  const modern = major > 0 || minor >= 12;
  if (typeof api?.createRuntime !== 'function' || typeof api?.loadServerDefinitions !== 'function') {
    fail('UNSUPPORTED_RUNTIME');
  }
  if (request.operation === 'call' && !object(args)) fail('INVALID_INPUT');
  const config = await validateConfig(request.configPath);
  let definitions;
  try {
    definitions = await api.loadServerDefinitions({ configPath: request.configPath });
  } catch {
    fail('INVALID_CONFIG');
  }
  if (!Array.isArray(definitions)) fail('INVALID_CONFIG');
  const names = new Set();
  definitions = definitions.map((definition) => {
    validateDefinition(definition);
    if (names.has(definition.name)) fail('INVALID_CONFIG');
    names.add(definition.name);
    const raw = Object.hasOwn(config.mcpServers, definition.name) ? config.mcpServers[definition.name] : undefined;
    if (!raw) fail('INVALID_CONFIG');
    if (raw.cwd === undefined) return definition;
    if (definition.command.kind !== 'stdio') fail('INVALID_CONFIG');
    // 0.9 drops raw cwd while normalizing. Restore it on private copies so
    // createRuntime receives the explicit directory without mutating API data.
    return { ...definition, command: { ...definition.command, cwd: raw.cwd } };
  });
  const servers = [...names].sort();
  if (request.operation === 'servers') return { output: { servers }, exitCode: 0 };
  if (request.operation === 'doctor') {
    const unsupportedServers = [];
    for (const definition of definitions) {
      try {
        checkSupportedDefinition(definition);
      } catch (error) {
        if (!(error instanceof BridgeError)) throw error;
        unsupportedServers.push({ server: definition.name, code: error.code });
      }
    }
    return {
      output: {
        ok: unsupportedServers.length === 0,
        backend: { package: 'mcporter', version },
        nodeVersion: process.version,
        servers,
        features: {
          lifecycle: 'ephemeral',
          interactiveOAuth: false,
          cachedOAuth: true,
          toolRetries: false,
          toolMetadata: modern ? 'runtime-name-description-input-output-schema' : 'raw-mcp-tool',
        },
        unsupportedServers,
      },
      exitCode: unsupportedServers.length ? 1 : 0,
    };
  }
  // Definition names only: never accept an ad-hoc URL, fuzzy alias, or trim.
  const definition = definitions.find((entry) => entry.name === request.server);
  if (!definition) fail('UNKNOWN_SERVER');
  checkSupportedDefinition(definition);
  let runtime;
  let context;
  try {
    runtime = await api.createRuntime({
      configPath: request.configPath,
      servers: definitions,
      logger: QUIET_LOGGER,
    });
    if (typeof runtime?.close !== 'function' ||
        (modern && (typeof runtime.listTools !== 'function' || typeof runtime.callTool !== 'function')) ||
        (!modern && typeof runtime.connect !== 'function')) fail('UNSUPPORTED_RUNTIME');
    let tools;
    if (modern) {
      tools = await runtime.listTools(request.server, {
        includeSchema: true,
        autoAuthorize: false,
        disableOAuth: true,
        allowCachedAuth: true,
        timeoutMs: request.timeoutMs,
      });
      // 0.12's public listTools handles cursor iteration itself; the Python
      // process-group deadline bounds it. 0.13+ SDK2 has listMaxPages: 100.
    } else {
      context = await runtime.connect(request.server, {
        maxOAuthAttempts: 0,
        skipCache: true,
        allowCachedAuth: true,
      });
      tools = await listLegacyTools(context, request.timeoutMs);
    }
    tools = validateTools(tools).filter((tool) => allowed(tool, definition));
    if (request.operation === 'tools') {
      const query = request.query?.toLowerCase();
      if (query !== undefined) {
        tools = tools.filter((tool) => `${tool.name}\n${typeof tool.description === 'string' ? tool.description : ''}`
          .toLowerCase().includes(query));
      }
      return { output: { server: request.server, tools }, exitCode: 0 };
    }
    const tool = tools.find((entry) => entry.name === request.tool);
    if (!tool) fail('UNKNOWN_TOOL');
    if (request.operation === 'schema') {
      return { output: { server: request.server, tool }, exitCode: 0 };
    }
    if (request.operation !== 'call') fail('INVALID_ARGUMENTS');
    // Exactly one invocation, after exact discovery and config-filter checks.
    const result = modern
      ? await runtime.callTool(request.server, request.tool, {
        args,
        timeoutMs: request.timeoutMs,
        disableOAuth: true,
      })
      : await context.client.callTool({ name: request.tool, arguments: args }, undefined, {
        timeout: request.timeoutMs,
        maxTotalTimeout: request.timeoutMs,
      });
    if (!object(result)) fail('TRANSPORT_FAILED');
    return { output: result, exitCode: result.isError === true ? 2 : 0 };
  } catch (error) {
    if (error instanceof BridgeError) throw error;
    // Do not reflect arbitrary server messages, URLs, headers, args or stacks.
    fail('TRANSPORT_FAILED');
  } finally {
    await closeLegacyContext(context);
    try {
      await runtime?.close?.();
    } catch {
      // As above, no upstream cleanup details and no retry after a result.
    }
  }
}

async function readCallInput(stream) {
  const chunks = [];
  let size = 0;
  for await (const chunk of stream) {
    size += Buffer.byteLength(chunk);
    if (size > MAX_INPUT_BYTES) fail('INVALID_INPUT');
    chunks.push(Buffer.from(chunk));
  }
  try {
    const value = JSON.parse(Buffer.concat(chunks).toString('utf8'));
    if (!object(value)) fail('INVALID_INPUT');
    return value;
  } catch {
    fail('INVALID_INPUT');
  }
}

async function validateConfig(configPath) {
  try {
    const config = JSON.parse(await fs.readFile(configPath, 'utf8'));
    if (!object(config) || !object(config.mcpServers) || !Array.isArray(config.imports) ||
        config.imports.length !== 0 || Object.keys(config).some((key) => !['mcpServers', 'imports'].includes(key))) {
      fail('INVALID_CONFIG');
    }
    for (const entry of Object.values(config.mcpServers)) {
      if (!object(entry) || entry.tokenCacheDir !== undefined || entry.token_cache_dir !== undefined ||
          entry.refresh !== undefined || entry.auth?.toLowerCase?.() === 'refreshable_bearer') fail('INVALID_CONFIG');
      if (entry.cwd !== undefined && (typeof entry.cwd !== 'string' || !path.isAbsolute(entry.cwd))) {
        fail('INVALID_CONFIG');
      }
    }
    return config;
  } catch {
    fail('INVALID_CONFIG');
  }
}

function isolateOutput() {
  // mcporter 0.9's bundled SDK patches auto-print server stderr on nonzero
  // exit, bypassing the supplied logger. Silence this process boundary before
  // import; do not import or patch mcporter private modules to change it.
  const write = process.stdout.write.bind(process.stdout);
  const discard = (_chunk, encoding, callback) => {
    const done = typeof encoding === 'function' ? encoding : callback;
    if (typeof done === 'function') queueMicrotask(done);
    return true;
  };
  process.stdout.write = discard;
  process.stderr.write = discard;
  for (const name of ['log', 'info', 'warn', 'error', 'debug', 'trace']) console[name] = noop;
  // These are captured during module evaluation; never let ambient debugging,
  // recording or replay leak credentials or replace a real operation.
  for (const key of Object.keys(process.env)) {
    if (/^MCPORTER_(?:RECORD|REPLAY|STDIO_(?:TRACE|LOGS))(?:_|$)/.test(key)) delete process.env[key];
  }
  return write;
}

async function main() {
  const write = isolateOutput();
  let outcome;
  try {
    const request = parseArguments(process.argv.slice(2));
    await validateConfig(request.configPath);
    let metadata;
    let api;
    try {
      metadata = JSON.parse(await fs.readFile(path.join(request.packagePath, 'package.json'), 'utf8'));
      if (metadata.name !== 'mcporter') fail('INVALID_PACKAGE');
      versionParts(metadata.version);
      api = await import(pathToFileURL(path.join(request.packagePath, 'dist', 'index.js')).href);
    } catch {
      fail('INVALID_PACKAGE');
    }
    const args = request.operation === 'call' ? await readCallInput(process.stdin) : {};
    outcome = await executeBridge(api, request, { version: metadata.version, args });
  } catch (error) {
    const safe = error instanceof BridgeError ? error : new BridgeError('BRIDGE_FAILED');
    outcome = { output: { error: { code: safe.code, message: safe.message } }, exitCode: 1 };
  }
  let output;
  try {
    output = JSON.stringify(outcome.output) + '\n';
  } catch {
    output = JSON.stringify({ error: { code: 'BRIDGE_FAILED', message: MESSAGES.BRIDGE_FAILED } }) + '\n';
    outcome.exitCode = 1;
  }
  process.exitCode = outcome.exitCode;
  write(output);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await main();
}
