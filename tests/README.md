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
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_entry.py' -v
node --test tests/test_bridge.mjs
```

Python coverage: fixed account-home state, ambient control stripping, explicit
configuration imports/lifecycle, unsafe auth/cache/environment rejection,
absolute stdio cwd, POSIX modes/links, corrupt-vault preservation, profile lock,
removed deployment flags, offline install reuse, real npm semver selection and
Node-identity checks. Bridge coverage is defined by the named Node test cases.

All fixtures are created in OS temporary directories and removed by the tests.
No test entry point creates the production runtime or authenticates an account.
