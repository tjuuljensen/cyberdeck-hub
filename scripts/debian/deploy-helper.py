#!/usr/bin/env python3
"""Create protected software snapshots and restore a Debian deployment."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import socket
import stat
import subprocess
import sys
import uuid


BACKUP_ROOT = Path('/var/backups/cyberdeck/deployments')
TREE_PATHS = (
    Path('/usr/local/lib/cyberdeck'),
    Path('/etc/cyberdeck'),
    Path('/etc/dconf/db/local'),
    Path('/opt/cyberdeck/modules/cyberchef'),
    Path('/opt/cyberdeck/modules/cyberchef.previous'),
)
FILE_PATHS = (
    Path('/etc/systemd/system/cyberdeck-web.service'),
    Path('/etc/systemd/system/cyberdeck-kiwix.service'),
    Path('/etc/systemd/system/cyberdeck-redirect.service'),
    Path('/etc/systemd/system/cyberdeck-cyberchef.service'),
    Path('/etc/systemd/system/cyberdeck-storage-migration.service'),
    Path('/etc/systemd/system/cyberdeck-storage-initialize.service'),
    Path('/etc/systemd/system/cyberdeck-storage-existing.service'),
    Path('/etc/systemd/system/cyberdeck-storage-recovery.service'),
    Path('/etc/systemd/system/cyberdeck-storage-boot-recovery.service'),
    Path('/etc/systemd/system/cyberdeck-firewall.service'),
    Path('/etc/systemd/system/cyberdeck-hotspot-autostart.service'),
    Path('/etc/systemd/system/cyberdeck-hotspot-autostart.timer'),
    Path('/etc/tmpfiles.d/cyberdeck-storage.conf'),
    Path('/etc/sudoers.d/cyberdeck-web'),
    Path('/etc/NetworkManager/dnsmasq-shared.d/cyberdeck.conf'),
    Path('/etc/systemd/sleep.conf.d/90-cyberdeck.conf'),
    Path('/etc/systemd/logind.conf.d/90-cyberdeck.conf'),
    Path('/etc/dconf/profile/user'),
    Path('/etc/dconf/db/local.d/90-cyberdeck-power'),
    Path('/etc/dconf/db/local.d/locks/90-cyberdeck-power'),
)
SERVICE_NAMES = (
    'cyberdeck-web.service', 'cyberdeck-kiwix.service',
    'cyberdeck-redirect.service', 'cyberdeck-cyberchef.service',
    'cyberdeck-storage-migration.service', 'cyberdeck-storage-initialize.service',
    'cyberdeck-storage-existing.service', 'cyberdeck-storage-recovery.service',
    'cyberdeck-storage-boot-recovery.service',
    'cyberdeck-firewall.service',
    'cyberdeck-hotspot-autostart.timer',
    'sleep.target', 'suspend.target', 'hibernate.target', 'hybrid-sleep.target',
)
DEPLOY_ID_RE = re.compile(r'^[0-9a-f]{32}$')


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=check, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT)


def require_root(expected_host: str) -> None:
    if os.geteuid() != 0:
        raise RuntimeError('Snapshot and rollback operations must run as root.')
    if (not re.fullmatch(r'[a-z][a-z0-9-]{0,61}[a-z0-9]|[a-z]', expected_host)
            or socket.gethostname().split('.')[0] != expected_host):
        raise RuntimeError(f'Refusing operation: expected host {expected_host!r}.')


def reject_symlink_path(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            raise RuntimeError(f'Refusing symlink in managed path: {current}')


def copy_node(source: Path, destination: Path) -> None:
    info = source.lstat()
    if stat.S_ISLNK(info.st_mode):
        raise RuntimeError(f'Refusing symlink in deployment snapshot: {source}')
    if stat.S_ISDIR(info.st_mode):
        destination.mkdir(mode=stat.S_IMODE(info.st_mode), parents=True)
        os.chown(destination, info.st_uid, info.st_gid)
        for child in sorted(source.iterdir()):
            copy_node(child, destination / child.name)
        os.chmod(destination, stat.S_IMODE(info.st_mode))
    elif stat.S_ISREG(info.st_mode):
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        os.chown(destination, info.st_uid, info.st_gid)
        os.chmod(destination, stat.S_IMODE(info.st_mode))
    else:
        raise RuntimeError(f'Refusing non-regular managed path: {source}')


def remove_node(path: Path) -> None:
    reject_symlink_path(path)
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def service_state(unit: str) -> dict[str, str]:
    enabled = run('systemctl', 'is-enabled', unit, check=False)
    active = run('systemctl', 'is-active', unit, check=False)
    return {'enabled': enabled.stdout.strip() or 'unknown',
            'active': active.stdout.strip() or 'unknown'}


def snapshot(expected_host: str) -> str:
    require_root(expected_host)
    reject_symlink_path(BACKUP_ROOT)
    BACKUP_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(BACKUP_ROOT, 0o700)
    deployment_id = uuid.uuid4().hex
    directory = BACKUP_ROOT / deployment_id
    directory.mkdir(mode=0o700)
    records = []
    paths = [(path, 'tree') for path in TREE_PATHS] + [(path, 'file') for path in FILE_PATHS]
    try:
        for index, (path, kind) in enumerate(paths):
            reject_symlink_path(path)
            exists = path.exists()
            backup_name = f'asset-{index:02d}' if exists else None
            if exists:
                backup = directory / backup_name
                copy_node(path, backup)
                info = path.lstat()
                records.append({'path': str(path), 'kind': kind, 'exists': True,
                                'backup': backup_name, 'mode': stat.S_IMODE(info.st_mode),
                                'uid': info.st_uid, 'gid': info.st_gid})
            else:
                records.append({'path': str(path), 'kind': kind, 'exists': False,
                                'backup': None, 'mode': None, 'uid': None, 'gid': None})
        states = {unit: service_state(unit) for unit in SERVICE_NAMES}
        state_path = directory / 'state.json'
        state_path.write_text(json.dumps({'id': deployment_id, 'host': expected_host,
                                          'assets': records, 'services': states}, indent=2) + '\n',
                              encoding='utf-8')
        os.chmod(state_path, 0o600)
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    print(deployment_id)
    return deployment_id


def restore(expected_host: str, deployment_id: str) -> None:
    require_root(expected_host)
    if not DEPLOY_ID_RE.fullmatch(deployment_id):
        raise ValueError('Deployment ID must be 32 lowercase hexadecimal characters.')
    directory = BACKUP_ROOT / deployment_id
    reject_symlink_path(directory)
    if not directory.is_dir():
        raise FileNotFoundError(f'No deployment backup found for {deployment_id}.')
    state_path = directory / 'state.json'
    if state_path.is_symlink() or not state_path.is_file():
        raise ValueError('Deployment backup state is missing or unsafe.')
    state = json.loads(state_path.read_text(encoding='utf-8'))
    if state.get('id') != deployment_id or state.get('host') != expected_host:
        raise ValueError('Deployment backup does not match the requested ID and host.')
    records = state.get('assets')
    expected_paths = [str(path) for path in (*TREE_PATHS, *FILE_PATHS)]
    expected = set(expected_paths)
    if (not isinstance(records, list) or len(records) != len(expected_paths)
            or {row.get('path') for row in records} != expected):
        raise ValueError('Deployment backup managed-path set is invalid.')
    services = state.get('services')
    # Older Hub snapshots predate recording the firewall unit state. Preserve
    # their existing compatibility without guessing the omitted state.
    service_sets = (set(SERVICE_NAMES), set(SERVICE_NAMES) - {'cyberdeck-firewall.service'})
    if not isinstance(services, dict) or set(services) not in service_sets:
        raise ValueError('Deployment backup service-state set is invalid.')
    for record in records:
        if (not isinstance(record, dict) or record.get('kind') not in {'tree', 'file'}
                or not isinstance(record.get('exists'), bool)):
            raise ValueError('Deployment backup contains an invalid asset record.')
        if record['exists']:
            backup_name = record.get('backup')
            if not isinstance(backup_name, str) or not re.fullmatch(r'asset-[0-9]{2}', backup_name):
                raise ValueError('Deployment backup contains an invalid asset name.')
            backup = directory / backup_name
            if backup.is_symlink() or not backup.exists():
                raise ValueError(f'Deployment asset is missing or unsafe: {backup_name}')
            copy_node_validation(backup)
    for unit, values in services.items():
        if (not isinstance(values, dict) or values.get('enabled') not in {
                'enabled', 'enabled-runtime', 'disabled', 'static', 'indirect', 'alias',
                'masked', 'masked-runtime', 'generated', 'transient', 'linked',
                'linked-runtime', 'not-found', 'unknown'}
                or values.get('active') not in {
                    'active', 'inactive', 'failed', 'activating', 'deactivating',
                    'reloading', 'unknown'}):
            raise ValueError(f'Deployment backup contains invalid service state: {unit}')
    for record in records:
        path = Path(record['path'])
        if path not in (*TREE_PATHS, *FILE_PATHS):
            raise ValueError(f'Unexpected managed path in snapshot: {path}')
        remove_node(path)
        if record['exists']:
            backup_name = record.get('backup')
            backup = directory / backup_name
            copy_node(backup, path)
    run('systemctl', 'daemon-reload')
    if shutil.which('dconf'):
        run('dconf', 'update')
    for unit, values in services.items():
        enabled_state = values['enabled']
        if enabled_state in {'enabled', 'enabled-runtime', 'linked', 'linked-runtime'}:
            run('systemctl', 'enable', unit, check=False)
        elif enabled_state == 'disabled':
            run('systemctl', 'disable', unit, check=False)
        elif enabled_state in {'masked', 'masked-runtime'}:
            command = ('mask', '--runtime', unit) if enabled_state == 'masked-runtime' else ('mask', unit)
            run('systemctl', *command, check=False)
        else:
            # This also removes links created by the candidate when the saved
            # unit was previously static, disabled, unknown, or not installed.
            run('systemctl', 'disable', unit, check=False)
        if values['active'] in {'active', 'activating', 'reloading'}:
            run('systemctl', 'restart', unit, check=False)
        elif values['active'] in {'inactive', 'failed'}:
            run('systemctl', 'stop', unit, check=False)
    print(f'Rolled back deployment {deployment_id} from {directory}.')


def copy_node_validation(path: Path) -> None:
    """Validate a saved tree before touching any current target files."""
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        raise ValueError(f'Refusing symlink in deployment backup: {path}')
    if stat.S_ISDIR(info.st_mode):
        for child in path.iterdir():
            copy_node_validation(child)
    elif not stat.S_ISREG(info.st_mode):
        raise ValueError(f'Refusing non-regular deployment backup: {path}')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest='action', required=True)
    snapshot_parser = subparsers.add_parser('snapshot')
    snapshot_parser.add_argument('expected_host')
    rollback_parser = subparsers.add_parser('rollback')
    rollback_parser.add_argument('deployment_id')
    rollback_parser.add_argument('expected_host')
    args = parser.parse_args()
    if args.action == 'snapshot':
        snapshot(args.expected_host)
    else:
        restore(args.expected_host, args.deployment_id)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        raise SystemExit(1)
