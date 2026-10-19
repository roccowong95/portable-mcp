# Offline Linux regression checks

These tests exercise the private entry and bridge with temporary fixture data and
fake public mcporter APIs. They do not install packages, contact MCP services,
read an account's real credential vault, or bypass host authorization controls.
They are **technical regression evidence**, not Amoo, OAuth, token refresh, or
real-service acceptance.

Prerequisites: existing Python 3.9+, Node and npm. The version-selection tests use
npm's existing semver implementation and the actual Node executable. No Node
version is changed. No package downloads are necessary.

Develop locally and sync the current source/tests into an independent directory
on the approved Linux verification host. This host also runs the actual service:
do not modify the deployed plugin, account configuration, credentials or Node.
Direct SSH technical checks do not require a commit/push or an Amoo session.
From the synchronized repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py' -v
node --test tests/test_bridge.mjs
```

Python coverage: fixed account-home state, ambient control stripping, explicit
configuration imports/lifecycle, unsafe auth/cache/environment rejection,
absolute stdio cwd, POSIX modes/links, corrupt-vault preservation, profile lock,
removed deployment flags, offline install reuse, real npm semver selection and
Node-identity checks. State expectations use the real OS account home under
`.pmcp/config/mcp.json`; legacy `.portable-mcp` state is not automatically migrated.
Bridge coverage is defined by the named Node test cases.

`test_entry.py` also tests `config-add` with mocked runtime discovery and a native
staged-output fixture: exact target/auth-only argv, quiet execution, HTTP/OAuth and
stdio options, environment-only placeholders (including `Bearer ${VAR}` headers),
explicit ephemeral lifecycle, preserved sibling fields/cwd, init requirement,
no same-name overwrite, atomic replacement, failed replacement/native generation,
malformed/duplicate output, external modification detection, dry-run preservation
and staging cleanup. Approved query URLs (including placeholder token values,
encoded/repeated/empty parameters and a trailing `?`) are forwarded and saved
verbatim; dry-run and native failure leave canonical configuration unchanged.
The process fixture deliberately echoes the placeholder URL from native stdout
and stderr to verify that quiet execution does not expose it in entry output.
Invalid input and isolation overrides must fail before runtime discovery. These semantic cases run on Windows too, with only the Windows
ACL inspector mocked; they are **not Windows ACL-policy evidence**. Existing
POSIX permission/account-home and real process-pipeline suites skip on Windows.

`test_pipeline.py` additionally checks the real `pmcp.py` → Node bridge process
boundary against fake public backend exports for the 0.9 and 0.15 API branches:
init, version, servers, doctor, tools, schema, successful/error raw calls, exact-name
rejection and JSON type/Unicode preservation. Its fake `dist/cli.js` implements
native config add through the actual Python → Node subprocess boundary, checking
HTTP/stdio adds and dry-run without server spawns, connection/call receipts or a
credential vault; ordinary discovery and calls then work with the added server. OS-account home and runtime paths
are patched only in its temporary test driver, never through a production switch.
The capability-index cases call `pmcp.py meta-*` on a copied skill without Node,
runtime, init or account-state access. They cover validation, dry-run/merge/replace,
idempotency, writer locks and unchanged surrounding metadata. Installer cases use
mocked registry/npm boundaries to assert the fixed npmmirror URL without downloading
or installing packages. These tests do not prove real package installation or that
either real backend version or its transport works.

All fixtures are created in OS temporary directories and removed by the tests.
No test entry point creates the production runtime or authenticates an account.

## Existing-runtime smoke test

`smoke_runtime.py` uses an already installed mcporter package with a temporary
Python stdio MCP server. It checks real discovery, schema, successful and failed
raw results, and exact-name rejection. Its two `tools/call` dispatches only append
to a temporary fixture log. It isolates HOME, XDG and broker directories, does not
install anything, and does not use the deployed configuration or credential vault.
Only the bridge is exercised: this is not an end-to-end test of the fixed-home
Python entry, nor an Amoo or OAuth test.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 tests/smoke_runtime.py \
  --node /absolute/path/to/existing/node \
  --package /absolute/path/to/existing/node_modules/mcporter
```

## Read-only environment diagnostic

`inspect_node.py` reports the current account, SSH PATH and Node candidates,
selected installation-record fields, and Node/OpenClaw/Amoo process identities.
It does not open process environment files or read process arguments,
configuration contents or tokens. Use it only on the approved validation host.
It does execute existing Node candidates with `--version` (with Node controls
removed), and does not install or update packages.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 tests/inspect_node.py \
  --skill /absolute/path/to/existing/portable-mcp
```

Observed results and evidence boundaries are recorded in
[the Linux validation report](validation-linux.md).
