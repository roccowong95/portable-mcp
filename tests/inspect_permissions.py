"""Read-only bounded permission and ownership probe; no configs or credentials."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('paths', nargs='+', type=Path)
args = parser.parse_args()
print(json.dumps({'uid': os.getuid(), 'gid': os.getgid(), 'groups': os.getgroups()}))
for target in args.paths:
    if not target.is_absolute():
        parser.error('Use absolute paths')
    result = {'target': str(target), 'ancestors': []}
    for path in reversed([target, *target.parents]):
        item = {'path': str(path)}
        try:
            info = path.lstat()
            item.update({'uid': info.st_uid, 'gid': info.st_gid, 'mode': oct(stat.S_IMODE(info.st_mode)), 'type': 'symlink' if path.is_symlink() else 'dir' if path.is_dir() else 'file', 'readable': os.access(path, os.R_OK), 'traversableOrExecutable': os.access(path, os.X_OK)})
            if path.is_symlink():
                item['linkTarget'] = os.readlink(path)
            if path == target and path.suffix in ('.py', '.mjs', '.cjs') and path.is_file():
                item['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
            # File capabilities/ACL presence only, never xattr values.
            item['hasPosixACL'] = 'system.posix_acl_access' in os.listxattr(path, follow_symlinks=False)
        except OSError as error:
            item['errorType'] = type(error).__name__
        result['ancestors'].append(item)
    print(json.dumps(result))
for pid in (4288, 4289, 4311):
    proc = Path('/proc') / str(pid)
    try:
        selected = {}
        for line in (proc / 'status').read_text().splitlines():
            key, _, value = line.partition(':')
            if key in ('Name', 'Uid', 'Gid', 'Groups', 'NoNewPrivs', 'Seccomp'):
                selected[key] = value.strip()
        print(json.dumps({'pid': pid, 'identity': selected, 'startTicks': (proc / 'stat').read_text().rsplit(')', 1)[1].split()[19], 'exe': str((proc / 'exe').resolve()), 'root': str((proc / 'root').resolve())}))
    except OSError:
        print(json.dumps({'pid': pid, 'status': 'unavailable'}))
