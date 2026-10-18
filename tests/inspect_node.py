"""Read-only Node identity diagnostics; prints no credentials or process argv."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--skill', required=True, type=Path, help='Existing deployed skill directory; read-only')
args = parser.parse_args()
if not args.skill.is_absolute() or not args.skill.is_dir():
    parser.error('--skill must be an existing absolute directory')
SKILL = args.skill

def version(executable):
    try:
        env = {key: value for key, value in os.environ.items() if not key.upper().startswith(('NODE_', 'NPM_', 'COREPACK_'))}
        return subprocess.run([str(executable), '--version'], env=env, capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return 'unavailable'

report = {'hostname': os.uname().nodename, 'uid': os.getuid(), 'cwd': os.getcwd(), 'shellPATH': os.environ.get('PATH'), 'shellNode': shutil.which('node'), 'nodeCandidates': [], 'serviceProcesses': []}
marker = SKILL / 'scripts/.runtime/mcporter/skill-install.json'
candidates = [Path(part) / 'node' for part in os.environ.get('PATH', '').split(os.pathsep) if part]
try:
    data = json.loads(marker.read_text())
    report['installedMarker'] = {key: data.get(key) for key in ('version', 'nodeVersion', 'nodeExecutable', 'npmCli', 'installedAt')}
    if data.get('nodeExecutable'):
        candidates.append(Path(data['nodeExecutable']))
except (OSError, ValueError):
    report['installedMarker'] = 'unavailable'
seen = set()
for item in candidates:
    if not item.is_file():
        continue
    real = str(item.resolve())
    if real in seen:
        continue
    seen.add(real)
    report['nodeCandidates'].append({'path': str(item), 'realpath': real, 'version': version(real)})
for proc in Path('/proc').iterdir():
    if not proc.name.isdigit():
        continue
    try:
        comm = (proc / 'comm').read_text().strip()
        if not any(name in comm.lower() for name in ('node', 'openclaw', 'amoo')):
            continue
        executable = str((proc / 'exe').resolve(strict=True))
        selected = {'pid': int(proc.name), 'name': comm, 'executable': executable, 'cwd': str((proc / 'cwd').resolve()), 'uid': proc.stat().st_uid}
        # /proc/<pid>/environ cannot expose one key without reading other
        # values. Deliberately do not open it, even just to extract PATH.
        report['serviceProcesses'].append(selected)
    except (OSError, ValueError):
        continue
print(json.dumps(report, indent=2))
