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
Node-identity checks. Bridge coverage is defined by the named Node test cases.

`test_pipeline.py` additionally checks the real `pmcp.py` → Node bridge process
boundary against fake public backend exports for the 0.9 and 0.15 API branches:
init, version, servers, doctor, tools, schema, successful/error raw calls, exact-name
rejection and JSON type/Unicode preservation. OS-account home and runtime paths
are patched only in its temporary test driver, never through a production switch.
It also exercises the capability-index add/sync/remove lifecycle on a copied skill.
These tests do not prove that either real backend version or its transport works.

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
