#!/usr/bin/python3
"""Lock GNOME idle suspend off through the system dconf database."""
from pathlib import Path
import os
import re
import subprocess
import tempfile

PROFILE = Path('/etc/dconf/profile/user')
DATABASE = Path('/etc/dconf/db/local.d/90-cyberdeck-power')
LOCKS = Path('/etc/dconf/db/local.d/locks/90-cyberdeck-power')
VALUES = {
    'sleep-inactive-ac-type': "'nothing'",
    'sleep-inactive-ac-timeout': '0',
    'sleep-inactive-battery-type': "'nothing'",
    'sleep-inactive-battery-timeout': '0',
}


def atomic_write(path, content, mode=0o644):
    if path.is_symlink():
        raise ValueError(f'Refusing dconf symlink: {path}')
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(content)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run as root on the target host.')
    if PROFILE.is_symlink():
        raise SystemExit(f'ERROR: Refusing dconf profile symlink: {PROFILE}')
    profile = PROFILE.read_text(encoding='utf-8') if PROFILE.exists() else 'user-db:user\n'
    if not re.search(r'^\s*system-db:local\s*$', profile, re.M):
        profile = profile.rstrip() + '\nsystem-db:local\n'
    atomic_write(PROFILE, profile)
    values = '[org/gnome/settings-daemon/plugins/power]\n' + ''.join(
        f'{key}={value}\n' for key, value in VALUES.items())
    locks = ''.join(f'/org/gnome/settings-daemon/plugins/power/{key}\n' for key in VALUES)
    atomic_write(DATABASE, values)
    atomic_write(LOCKS, locks)
    subprocess.run(['dconf', 'update'], check=True, timeout=30)
    print('Locked GNOME idle suspend off for AC and battery power; dconf database rebuilt.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit(f'ERROR: {error}')
