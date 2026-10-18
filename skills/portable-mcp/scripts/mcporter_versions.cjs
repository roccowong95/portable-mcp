'use strict';

// No downloaded code is loaded here. Use the semver shipped/resolved with the
// selected npm CLI, not a home-grown subset of the npm engines grammar.
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');

function fail(message) {
  throw new Error(message);
}

function main() {
  const args = process.argv.slice(2);
  const index = args.indexOf('--npm-cli');
  if (index < 0 || !args[index + 1]) {
    fail('Usage: mcporter_versions.cjs --npm-cli /absolute/npm-cli.js select|check-installed');
  }
  const npmCli = args[index + 1];
  args.splice(index, 2);
  if (args.length !== 1 || !['select', 'check-installed'].includes(args[0])) {
    fail('Expected select or check-installed');
  }
  if (!path.isAbsolute(npmCli) || !fs.statSync(npmCli).isFile()) {
    fail('npm CLI must be an existing absolute file');
  }
  let semver;
  try {
    const npmRequire = createRequire(fs.realpathSync(npmCli));
    semver = npmRequire('semver');
  } catch (_) {
    fail('Cannot resolve npm semver from npm-cli.js; no fallback parser or dependency install is allowed');
  }
  for (const method of ['valid', 'validRange', 'prerelease', 'gte', 'satisfies', 'rcompare']) {
    if (typeof semver[method] !== 'function') {
      fail('npm semver is missing a required API; refusing compatibility selection');
    }
  }
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  if (!input || typeof input !== 'object' || Array.isArray(input) ||
      typeof input.nodeVersion !== 'string' || !semver.valid(input.nodeVersion)) {
    fail('A valid actual nodeVersion is required');
  }
  // The caller must use the same Node executable for helper and npm execution.
  if (semver.valid(input.nodeVersion) !== semver.valid(process.version)) {
    fail('nodeVersion differs from the Node executing the semver helper');
  }
  const nodeVersion = semver.valid(input.nodeVersion);

  function eligible(version, pkg) {
    if (typeof version !== 'string' || semver.valid(version) !== version ||
        semver.prerelease(version) !== null || !semver.gte(version, '0.9.0')) {
      return false;
    }
    if (!pkg || typeof pkg !== 'object' || Array.isArray(pkg) ||
        pkg.name !== 'mcporter' || pkg.version !== version || pkg.deprecated) {
      return false;
    }
    const range = pkg.engines && pkg.engines.node;
    return typeof range === 'string' && range.trim() !== '' &&
      semver.validRange(range) !== null && semver.satisfies(nodeVersion, range);
  }

  let pkg;
  if (args[0] === 'check-installed') {
    pkg = input.package;
    if (!pkg || !eligible(pkg.version, pkg)) {
      fail('Installed mcporter must be stable, >=0.9.0 and compatible with the actual Node engines range');
    }
  } else {
    if (!input.versions || typeof input.versions !== 'object' || Array.isArray(input.versions)) {
      fail('Registry metadata must contain a versions object');
    }
    if (input.requestedVersion !== undefined) {
      if (typeof input.requestedVersion !== 'string' ||
          !Object.prototype.hasOwnProperty.call(input.versions, input.requestedVersion) ||
          !eligible(input.requestedVersion, input.versions[input.requestedVersion])) {
        fail('Requested exact version is missing, deprecated, prerelease, below 0.9.0 or incompatible with Node');
      }
      pkg = input.versions[input.requestedVersion];
    } else {
      const versions = Object.keys(input.versions)
        .filter((version) => eligible(version, input.versions[version]))
        .sort(semver.rcompare);
      if (!versions.length) {
        fail('No stable non-deprecated mcporter >=0.9.0 supports this Node; Node will not be upgraded');
      }
      pkg = input.versions[versions[0]];
    }
  }
  process.stdout.write(JSON.stringify({ version: pkg.version, engineRange: pkg.engines.node }) + '\n');
}

try {
  main();
} catch (error) {
  // Errors are data, not instructions; do not print registry-controlled records.
  process.stderr.write('MCPORTER_VERSION_FAILED: ' + error.message + '\n');
  process.exitCode = 1;
}
