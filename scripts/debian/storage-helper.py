#!/usr/bin/python3
"""Allowlisted root helper for Cyberdeck disk adoption and library migration."""
import hashlib
import grp
import json
import os
from pathlib import Path
import re
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request

ADOPTIONS = Path('/etc/cyberdeck/storage-adoptions.json')
ENVIRONMENT = Path('/etc/cyberdeck/environment')
FSTAB = Path('/etc/fstab')
RUN_ROOT = Path('/run/cyberdeck-storage')
REQUEST = RUN_ROOT / 'storage-migration-request.json'
STATUS = RUN_ROOT / 'storage-migration-status.json'
INITIALIZE_REQUEST = RUN_ROOT / 'storage-initialize-request.json'
INITIALIZE_STATUS = RUN_ROOT / 'storage-initialize-status.json'
JOURNAL = Path('/etc/cyberdeck/storage-migration-journal.json')
DATA_ROOT_DEFAULT = Path('/srv/cyberdeck')
MOUNT_ROOT = Path('/mnt/cyberdeck-disks')
UNITS = ('cyberdeck-web.service', 'cyberdeck-kiwix.service')
STORAGE_UNIT = 'cyberdeck-storage-migration.service'
INITIALIZE_UNIT = 'cyberdeck-storage-initialize.service'
EXISTING_STORAGE_UNIT = 'cyberdeck-storage-existing.service'
MAX_REQUEST = 4096
PUBLIC_STATUS_FIELDS = {
    'status', 'updated_at', 'stable_id', 'source', 'destination',
    'target_id', 'target_mount', 'data_root', 'error', 'recovered', 'backup_retained',
}
PUBLIC_INITIALIZATION_FIELDS = {'status', 'operation', 'stable_id', 'phase', 'mount', 'error', 'updated_at'}


def run(args, *, check=True, timeout=60):
    return subprocess.run(args, check=check, text=True, capture_output=True,
                          timeout=timeout, env={**os.environ, 'LC_ALL': 'C'})


def read_json(path, default):
    try:
        if path.is_symlink():
            raise ValueError(f'Refusing symlink: {path}')
        value = json.loads(path.read_text(encoding='utf-8'))
        return value
    except FileNotFoundError:
        return default


def write_json(path, value, mode=0o600):
    if path.is_symlink():
        raise ValueError(f'Refusing symlink: {path}')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    if path.parent == RUN_ROOT:
        os.chmod(RUN_ROOT, 0o750)
        os.chown(RUN_ROOT, 0, grp.getgrnam('cyberdeck').gr_gid)
    temporary = path.with_name(path.name + '.' + str(os.getpid()) + '.tmp')
    temporary.write_text(json.dumps(value, sort_keys=True) + '\n', encoding='utf-8')
    public_status = path in {STATUS, INITIALIZE_STATUS}
    temporary.chmod(0o640 if public_status else mode)
    if public_status:
        os.chown(temporary, 0, grp.getgrnam('cyberdeck').gr_gid)
    os.replace(temporary, path)


def run_as_json(args):
    result = run(args)
    return json.loads(result.stdout)


def block_inventory():
    result = run_as_json([
        '/usr/bin/lsblk', '--json', '--bytes', '--paths', '--output',
        'NAME,KNAME,TYPE,SIZE,MODEL,SERIAL,WWN,TRAN,RO,FSTYPE,UUID,MAJ:MIN',
    ])
    # lsblk in the web service sees its private mount namespace. Read the
    # host's mount table explicitly so completed host workers cannot leave
    # the disk card showing a stale mount from the service sandbox.
    mounts = run_as_json(['/usr/bin/findmnt', '--json', '--list', '--task', '1',
                          '--output', 'MAJ:MIN,TARGET']).get('filesystems', [])
    by_device = {}
    for mount in mounts:
        if mount.get('maj:min') and mount.get('target'):
            by_device.setdefault(mount['maj:min'], []).append(mount['target'])

    def apply_mounts(rows):
        for row in rows:
            row['mountpoints'] = sorted(set(by_device.get(row.get('maj:min'), [])))
            apply_mounts(row.get('children') or [])

    rows = result.get('blockdevices', [])
    apply_mounts(rows)
    return rows


def has_signatures(device):
    result = run(['/usr/sbin/wipefs', '--no-act', '--json', '--output', 'TYPE', device],
                 check=False, timeout=15)
    if result.returncode:
        return True
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return True
    return bool(data.get('signatures'))


def disk_id_for(device):
    device = os.path.realpath(device)
    links = Path('/dev/disk/by-id')
    if links.is_dir():
        for link in sorted(links.iterdir()):
            if link.is_symlink() and os.path.realpath(link) == device:
                name = link.name
                if (name.startswith(('wwn-', 'usb-', 'ata-', 'nvme-')) and
                        re.fullmatch(r'[A-Za-z0-9_.+:-]{3,180}', name)):
                    return name
    return None


def disk_fingerprint(disk):
    partitions = [{'size_bytes': part['size_bytes'],
                   'filesystem': part['filesystem'], 'uuid': part['uuid']}
                  for part in disk['partitions']]
    inventory = {
        'capacity_bytes': disk['capacity_bytes'],
        'transport': disk['transport'],
        'partitions': sorted(partitions, key=lambda part: json.dumps(part, sort_keys=True)),
    }
    encoded = json.dumps(inventory, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def flatten_disks(rows):
    result = []
    for row in rows:
        kernel_name = Path(row.get('kname') or row.get('name') or '').name
        # zram reports TYPE=disk, but RAM-backed devices are OS resources,
        # not physical storage candidates for Admin's disk management.
        if row.get('type') != 'disk' or re.fullmatch(r'(?:zram|ram)\d+', kernel_name):
            continue
        children = row.get('children') or []
        partitions = []
        for part in children:
            mountpoints = sorted(set(p for p in (part.get('mountpoints') or []) if p))
            partitions.append({
                'device': part.get('name'), 'size_bytes': part.get('size'),
                'filesystem': part.get('fstype'), 'uuid': part.get('uuid'),
                'mounts': mountpoints,
            })
        device = row.get('name') or ''
        stable_id = disk_id_for(device)
        signatures = has_signatures(device) if device else True
        mounts = sorted(set(p for p in (row.get('mountpoints') or []) if p))
        result.append({
            'stable_id': stable_id,
            'device': device,
            'model': (row.get('model') or '').strip() or 'Unknown disk',
            'capacity_bytes': row.get('size'),
            'transport': row.get('tran'),
            'read_only': str(row.get('ro', '0')) == '1',
            'partitions': partitions,
            'mounts': mounts,
            'clean': not partitions and not row.get('fstype') and not mounts and not signatures,
            'adoptable': bool(stable_id) and not str(row.get('ro', '0')) == '1',
        })
    return result


def adopted_state():
    state = read_json(ADOPTIONS, {'version': 1, 'disks': {}})
    if not isinstance(state, dict) or state.get('version') != 1 or not isinstance(state.get('disks'), dict):
        raise ValueError('Disk adoption state is invalid')
    return state


def public_migration_status():
    record = read_json(STATUS, None)
    if record is None:
        record = read_json(JOURNAL, {'status': 'idle'})
    return {key: value for key, value in record.items() if key in PUBLIC_STATUS_FIELDS}


def list_disks():
    state = adopted_state()['disks']
    system_paths = root_disk_paths()
    disks = flatten_disks(block_inventory())
    for disk in disks:
        members = {os.path.realpath(disk['device'])}
        members.update(os.path.realpath(part['device']) for part in disk['partitions']
                       if part.get('device'))
        disk['system_disk'] = bool(members & system_paths)
        if disk['system_disk']:
            disk['adoptable'] = False
        data_device = os.stat(environment_data_root()).st_dev
        block_devices = [disk['device']] + [part['device'] for part in disk['partitions']]
        disk['active_data_disk'] = any(
            os.stat(device).st_rdev == data_device
            for device in block_devices if device and Path(device).exists())
        if disk['active_data_disk']:
            disk['adoptable'] = False
        adoption = state.get(disk['stable_id']) if disk['stable_id'] else None
        disk['adopted'] = adoption is not None
        disk['adoption_stale'] = bool(
            adoption and adoption.get('inventory_fingerprint') != disk_fingerprint(disk))
        disk['mount'] = None
        disk['managed_mount'] = adoption.get('mount') if adoption else None
        disk['initialized'] = False
        for part in disk['partitions']:
            if part['mounts']:
                disk['mount'] = part['mounts'][0]
            if part['filesystem'] and part['uuid']:
                disk['initialized'] = True
    initialization = read_json(INITIALIZE_STATUS, {})
    return {'disks': disks, 'migration': public_migration_status(),
            'initialization': {key: value for key, value in initialization.items()
                               if key in PUBLIC_INITIALIZATION_FIELDS}}


def resolve_disk(stable_id):
    if not isinstance(stable_id, str) or not re.fullmatch(r'[A-Za-z0-9_.+:-]{3,180}', stable_id):
        raise ValueError('Select a disk with a stable device identity')
    disks = {disk['stable_id']: disk for disk in flatten_disks(block_inventory())
             if disk['stable_id']}
    disk = disks.get(stable_id)
    if not disk:
        raise ValueError('The selected disk is no longer connected; refresh the disk list')
    if not disk['adoptable']:
        raise ValueError('The selected disk is read-only or has no stable identity')
    members = {os.path.realpath(disk['device'])}
    members.update(os.path.realpath(part['device']) for part in disk['partitions']
                   if part.get('device'))
    if members & root_disk_paths():
        raise ValueError('The system disk cannot be managed as Cyberdeck storage')
    data_device = os.stat(environment_data_root()).st_dev
    mounts = disk['mounts'] + [mount for part in disk['partitions'] for mount in part['mounts']]
    if any(os.path.exists(mount) and os.stat(mount).st_dev == data_device for mount in mounts):
        raise ValueError('The disk containing the active library data root cannot be selected')
    return disk


def save_adoption(stable_id, disk):
    state = adopted_state()
    state['disks'][stable_id] = {
        'device': disk['device'], 'model': disk['model'],
        'capacity_bytes': disk['capacity_bytes'], 'adopted_at': int(time.time()),
        'inventory_fingerprint': disk_fingerprint(disk),
    }
    write_json(ADOPTIONS, state)


def require_current_adoption(stable_id, disk, state=None):
    state = state if state is not None else adopted_state()['disks']
    adoption = state.get(stable_id)
    if adoption is None:
        raise ValueError('Adopt this disk before using it for Cyberdeck storage')
    if adoption.get('inventory_fingerprint') != disk_fingerprint(disk):
        raise ValueError('Disk contents or partition layout changed since adoption; refresh the disk adoption in Admin')


def require_writable_host_configuration():
    """Require host /etc to be writable; call only from a host-namespace worker."""
    options = run(['/usr/bin/findmnt', '--noheadings', '--output', 'OPTIONS',
                   '--target', '/etc']).stdout.strip().split(',')
    if 'rw' not in options:
        raise ValueError('The host configuration filesystem is read-only; repair it before changing disk settings')


def mount_options(mount):
    return run(['/usr/bin/findmnt', '--noheadings', '--output', 'OPTIONS',
                '--target', mount]).stdout.strip().split(',')


def adopt(payload):
    stable_id = payload.get('stable_id')
    disk = resolve_disk(stable_id)
    save_adoption(stable_id, disk)
    return {'adopted': True, 'disk': next(item for item in list_disks()['disks']
                                           if item['stable_id'] == stable_id)}


def adopted_mount_plan(payload):
    """Resolve a current adoption to its UUID-bound managed mount path."""
    stable_id = payload.get('stable_id')
    disk = resolve_disk(stable_id)
    adoptions = adopted_state()['disks']
    require_current_adoption(stable_id, disk, adoptions)
    adoption = adoptions[stable_id]
    # resolve_disk already rejects the system and active library disks. Its
    # records do not contain the presentation flags added by list_disks.
    migration_status = public_migration_status().get('status', 'idle')
    if migration_status in {'queued', 'copying', 'quiescing', 'verifying', 'switching', 'pending-health'}:
        raise ValueError('Wait for the library storage operation to finish before changing this disk mount')
    mount = adoption.get('mount')
    managed_mounts = {str(MOUNT_ROOT / part['uuid']) for part in disk['partitions']
                      if isinstance(part.get('uuid'), str) and re.fullmatch(r'[A-Fa-f0-9-]{16,64}', part['uuid'])}
    if not isinstance(mount, str) or mount not in managed_mounts:
        raise ValueError('This adopted disk has no Cyberdeck-managed mount')
    if MOUNT_ROOT.is_symlink() or Path(mount).is_symlink():
        raise ValueError('Refusing a symlink at the storage mount path')
    mounted_paths = set(disk['mounts'])
    mounted_paths.update(path for part in disk['partitions'] for path in part['mounts'])
    if mounted_paths - {mount}:
        raise ValueError('Unmount other mounted partitions before safely disconnecting this disk')
    return stable_id, disk, mount, mounted_paths


def unmount_adopted(payload):
    _stable_id, _disk, mount, mounted_paths = adopted_mount_plan(payload)
    if mounted_paths != {mount} or not os.path.ismount(mount):
        raise ValueError('The adopted disk is not mounted at its expected Cyberdeck path')
    run(['/usr/bin/umount', '--', mount], timeout=30)
    if os.path.ismount(mount):
        raise ValueError('The adopted disk is still mounted; close files using it and retry')
    return {'unmounted': True, 'mount': mount}


def mount_adopted(payload):
    _stable_id, disk, mount, mounted_paths = adopted_mount_plan(payload)
    partition = next(part for part in disk['partitions']
                     if str(MOUNT_ROOT / str(part.get('uuid'))) == mount)
    if partition['filesystem'] != 'ext4':
        raise ValueError('The managed filesystem is no longer ext4; inspect the disk before mounting it')
    marker = f'# cyberdeck-storage:{partition["uuid"]}'
    configured = any(
        len(fields := line.split()) >= 4 and fields[0] == 'UUID=' + partition['uuid']
        and fields[1] == mount and fields[2] == 'ext4' and marker in line
        for line in fstab_lines())
    if not configured:
        raise ValueError('The managed mount configuration no longer matches this adopted disk')
    if not mounted_paths:
        run(['/usr/bin/mount', '--', mount], timeout=30)
    if not os.path.ismount(mount):
        raise ValueError('The adopted disk did not mount at its expected Cyberdeck path')
    return {'mounted': True, 'mount': mount}


def start_mount_action(payload, operation):
    if operation not in {'mount', 'unmount'}:
        raise ValueError('Unsupported disk mount action')
    stable_id, _disk, _mount, mounts = adopted_mount_plan(payload)
    if operation == 'unmount' and not mounts:
        raise ValueError('The adopted disk is already unmounted')
    if read_json(INITIALIZE_STATUS, {}).get('status') in {'queued', 'initializing'}:
        raise ValueError('Wait for the disk operation to finish before changing its mount state')
    write_json(INITIALIZE_REQUEST, {'operation': operation, 'stable_id': stable_id}, mode=0o600)
    write_initialization_status('queued', operation=operation, stable_id=stable_id, phase='queued')
    try:
        # Reuse the existing root worker, which runs in the host mount
        # namespace. Mount changes made inside the web sandbox stay private.
        run(['/usr/bin/systemctl', 'start', '--no-block', EXISTING_STORAGE_UNIT], timeout=15)
    except (OSError, subprocess.SubprocessError) as error:
        write_initialization_status('failed', operation=operation, stable_id=stable_id,
                                    phase='failed', error=str(error))
        raise
    return {'status': 'queued', 'stable_id': stable_id}


def root_disk_paths():
    source = run(['/usr/bin/findmnt', '--noheadings', '--output', 'SOURCE', '--target', '/']).stdout.strip()
    if not source.startswith('/dev/'):
        return set()
    result = run(['/usr/bin/lsblk', '--inverse', '--noheadings', '--paths', '--output', 'NAME', source], check=False)
    return {os.path.realpath(line.strip()) for line in result.stdout.splitlines() if line.strip().startswith('/dev/')}


def require_unused_disk(disk):
    members = {os.path.realpath(disk['device'])}
    members.update(os.path.realpath(part['device']) for part in disk['partitions'] if part.get('device'))
    if members & root_disk_paths():
        raise ValueError('The system disk cannot be initialized')
    try:
        swap_devices = {os.path.realpath(line.split()[0])
                        for line in Path('/proc/swaps').read_text(encoding='ascii').splitlines()[1:]
                        if line.split() and line.split()[0].startswith('/dev/')}
    except OSError:
        swap_devices = set()
    if members & swap_devices:
        raise ValueError('A disk used for swap cannot be initialized')
    if disk['mounts'] or any(part['mounts'] for part in disk['partitions']):
        raise ValueError('Unmount the selected disk safely before initialization')
    for device in members:
        device_name = Path(device).name
        holders = Path('/sys/class/block') / device_name / 'holders'
        if holders.is_dir() and any(holders.iterdir()):
            raise ValueError('The selected disk is in use by another block device')


def fstab_lines():
    if FSTAB.is_symlink():
        raise ValueError('Refusing a symlink at /etc/fstab')
    return FSTAB.read_text(encoding='utf-8').splitlines() if FSTAB.exists() else []


def update_fstab(marker, entries):
    lines = [line for line in fstab_lines() if marker not in line]
    lines.extend(entries)
    temporary = FSTAB.with_name('fstab.cyberdeck.tmp')
    temporary.write_text('\n'.join(lines).rstrip() + '\n', encoding='utf-8')
    temporary.chmod(0o644)
    os.replace(temporary, FSTAB)


def restore_fstab(lines):
    if FSTAB.is_symlink():
        raise ValueError('Refusing a symlink at /etc/fstab')
    temporary = FSTAB.with_name('fstab.cyberdeck.tmp')
    temporary.write_text('\n'.join(lines).rstrip() + '\n', encoding='utf-8')
    temporary.chmod(0o644)
    os.replace(temporary, FSTAB)


def validate_initialization(payload):
    stable_id = payload.get('stable_id')
    if payload.get('confirm') != stable_id:
        raise ValueError('Confirmation must exactly match the selected disk identity')
    disk = resolve_disk(stable_id)
    adoptions = adopted_state()['disks']
    adoption = adoptions.get(stable_id)
    if adoption is None:
        raise ValueError('Adopt this disk before initializing it')
    require_current_adoption(stable_id, disk, adoptions)
    require_unused_disk(disk)
    if disk['capacity_bytes'] is None or disk['capacity_bytes'] < 1_000_000_000:
        raise ValueError('The selected disk is too small or its capacity is unknown')
    device = os.path.realpath(disk['device'])
    if disk_id_for(device) != stable_id:
        raise ValueError('Disk identity changed; refresh and preview again')
    return stable_id, disk, device


def write_initialization_status(status, **values):
    write_json(INITIALIZE_STATUS, {'status': status, 'updated_at': int(time.time()), **values}, mode=0o640)


def start_initialization(payload):
    stable_id, _disk, _device = validate_initialization(payload)
    if read_json(INITIALIZE_STATUS, {}).get('status') in {'queued', 'initializing'}:
        raise ValueError('A disk initialization is already in progress')
    write_json(INITIALIZE_REQUEST, {'operation': 'initialize', 'stable_id': stable_id,
                                    'confirm': stable_id}, mode=0o600)
    write_initialization_status('queued', operation='initialize', stable_id=stable_id, phase='queued')
    try:
        run(['/usr/bin/systemctl', 'start', '--no-block', INITIALIZE_UNIT], timeout=15)
    except (OSError, subprocess.SubprocessError) as error:
        write_initialization_status('failed', operation='initialize', stable_id=stable_id,
                                    phase='failed', error=str(error))
        raise
    return {'status': 'queued', 'stable_id': stable_id}


def initialize_disk(payload):
    stable_id, disk, device = validate_initialization(payload)
    require_writable_host_configuration()
    write_initialization_status('initializing', operation='initialize', stable_id=stable_id, phase='wiping')
    run(['/usr/sbin/wipefs', '--all', device], timeout=120)
    write_initialization_status('initializing', operation='initialize', stable_id=stable_id, phase='partitioning')
    run(['/usr/sbin/parted', '--script', device, 'mklabel', 'gpt'], timeout=120)
    run(['/usr/sbin/parted', '--script', device, 'mkpart', 'primary', 'ext4', '1MiB', '100%'], timeout=120)
    run(['/usr/sbin/partprobe', device], check=False, timeout=20)
    run(['/usr/bin/udevadm', 'settle'], timeout=30)
    updated = next((row for row in flatten_disks(block_inventory())
                    if row['stable_id'] == stable_id), None)
    if not updated or len(updated['partitions']) != 1:
        raise ValueError('Could not verify the new partition; disk needs operator recovery')
    partition = os.path.realpath(updated['partitions'][0]['device'])
    write_initialization_status('initializing', operation='initialize', stable_id=stable_id, phase='formatting')
    run(['/usr/sbin/mkfs.ext4', '-F', '-L', 'CYBERDECK', partition], timeout=180)
    # Debian 13's util-linux package installs blkid under /usr/sbin.
    uuid = run(['/usr/sbin/blkid', '-s', 'UUID', '-o', 'value', partition]).stdout.strip()
    if not re.fullmatch(r'[A-Fa-f0-9-]{16,64}', uuid):
        raise ValueError('Could not verify the new filesystem UUID')
    mount = MOUNT_ROOT / uuid
    if MOUNT_ROOT.is_symlink() or mount.is_symlink():
        raise ValueError('Refusing a symlink at the storage mount path')
    mount.mkdir(parents=True, exist_ok=True)
    marker = f'# cyberdeck-storage:{uuid}'
    write_initialization_status('initializing', operation='initialize', stable_id=stable_id,
                                phase='mounting', mount=str(mount))
    old_fstab = fstab_lines()
    fstab_changed = False
    mounted = False
    try:
        update_fstab(marker, [f'UUID={uuid} {mount} ext4 defaults,nofail,x-systemd.device-timeout=5s 0 2 {marker}'])
        fstab_changed = True
        run(['/usr/bin/systemctl', 'daemon-reload'], timeout=30)
        run(['/usr/bin/mount', str(mount)], timeout=30)
        mounted = True
        if not os.path.ismount(mount):
            raise ValueError('The initialized filesystem did not mount at its assigned path')
        final_disk = next((row for row in flatten_disks(block_inventory())
                           if row['stable_id'] == stable_id), None)
        final_partition = next((part for part in final_disk['partitions']
                                if os.path.realpath(part['device']) == partition), None) if final_disk else None
        if (not final_partition or final_partition['filesystem'] != 'ext4' or
                final_partition['uuid'] != uuid or str(mount) not in final_partition['mounts']):
            raise ValueError('Mounted filesystem verification failed; the disk is not ready for library data')
        state = adopted_state()
        state['disks'][stable_id]['initialized_uuid'] = uuid
        state['disks'][stable_id]['mount'] = str(mount)
        state['disks'][stable_id]['inventory_fingerprint'] = disk_fingerprint(final_disk)
        write_json(ADOPTIONS, state)
    except Exception:
        if mounted:
            run(['/usr/bin/umount', str(mount)], check=False, timeout=30)
        if fstab_changed:
            restore_fstab(old_fstab)
            run(['/usr/bin/systemctl', 'daemon-reload'], check=False, timeout=30)
        raise
    write_initialization_status('completed', operation='initialize', stable_id=stable_id,
                                phase='completed', mount=str(mount))
    return {'initialized': True, 'filesystem': 'ext4', 'uuid': uuid, 'mount': str(mount)}


def initialize_worker():
    request = read_json(INITIALIZE_REQUEST, {})
    stable_id = request.get('stable_id')
    try:
        write_initialization_status('initializing', operation='initialize',
                                    stable_id=stable_id, phase='checking')
        initialize_disk(request)
    except Exception as error:
        write_initialization_status('failed', operation='initialize', stable_id=stable_id,
                                    phase='failed', error=str(error))
        raise


def existing_filesystem_plan(payload):
    stable_id = payload.get('stable_id')
    disk = resolve_disk(stable_id)
    state = adopted_state()
    require_current_adoption(stable_id, disk, state['disks'])
    partitions = [part for part in disk['partitions'] if part['filesystem'] and part['uuid']]
    if len(partitions) != 1 or partitions[0]['filesystem'] != 'ext4':
        raise ValueError('Use existing storage requires exactly one ext4 filesystem with a UUID')
    part = partitions[0]
    marker = f'# cyberdeck-storage:{part["uuid"]}'
    if part['mounts']:
        mount = part['mounts'][0]
        if 'rw' not in mount_options(mount):
            raise ValueError('The existing filesystem is mounted read-only; repair or remount it read-write on the host before using it')
        persistent = any(
            len(fields := line.split()) >= 3 and fields[1] == mount and
            (fields[0] == 'UUID=' + part['uuid'] or
             fields[0] == '/dev/disk/by-uuid/' + part['uuid'] or
             (fields[0].startswith('/dev/') and
              os.path.realpath(fields[0]) == os.path.realpath(part['device']))) and
            (len(fields) < 4 or 'noauto' not in fields[3].split(','))
            for line in fstab_lines())
        if not persistent:
            raise ValueError('This mounted filesystem is not configured for persistent startup; configure it on the host first')
        already_mounted = True
    else:
        mount = str(MOUNT_ROOT / part['uuid'])
        if MOUNT_ROOT.is_symlink() or Path(mount).is_symlink():
            raise ValueError('Refusing a symlink at the storage mount path')
        for line in fstab_lines():
            fields = line.split()
            if len(fields) >= 3 and fields[0] in {
                    'UUID=' + part['uuid'], '/dev/disk/by-uuid/' + part['uuid']} and fields[1] != mount:
                raise ValueError('This filesystem UUID is already assigned to a different persistent mount')
        already_mounted = False
    return stable_id, disk, part, mount, marker, already_mounted


def start_existing_storage(payload):
    stable_id, _disk, _part, _mount, _marker, _mounted = existing_filesystem_plan(payload)
    if read_json(INITIALIZE_STATUS, {}).get('status') in {'queued', 'initializing'}:
        raise ValueError('A storage operation is already in progress')
    write_json(INITIALIZE_REQUEST, {'operation': 'use-existing', 'stable_id': stable_id}, mode=0o600)
    write_initialization_status('queued', operation='use-existing', stable_id=stable_id,
                                phase='queued')
    try:
        run(['/usr/bin/systemctl', 'start', '--no-block', EXISTING_STORAGE_UNIT], timeout=15)
    except (OSError, subprocess.SubprocessError) as error:
        write_initialization_status('failed', operation='use-existing', stable_id=stable_id,
                                    phase='failed', error=str(error))
        raise
    return {'status': 'queued', 'stable_id': stable_id}


def use_existing_filesystem(payload):
    stable_id, disk, part, mount, marker, already_mounted = existing_filesystem_plan(payload)
    require_writable_host_configuration()
    if not already_mounted:
        old_fstab = fstab_lines()
        Path(mount).mkdir(parents=True, exist_ok=True)
        update_fstab(marker, [f'UUID={part["uuid"]} {mount} ext4 defaults,nofail,x-systemd.device-timeout=5s 0 2 {marker}'])
    else:
        old_fstab = None
    mounted_here = False
    try:
        if not already_mounted:
            run(['/usr/bin/systemctl', 'daemon-reload'], timeout=30)
            run(['/usr/bin/mount', mount], timeout=30)
            mounted_here = True
        if 'rw' not in mount_options(mount):
            raise ValueError('The existing filesystem mounted read-only; repair it on the host before using it')
        updated = next((row for row in flatten_disks(block_inventory())
                        if row['stable_id'] == stable_id), None)
        mounted_part = next((item for item in updated['partitions']
                             if item['uuid'] == part['uuid']), None) if updated else None
        if not mounted_part or mount not in mounted_part['mounts']:
            raise ValueError('The existing filesystem did not appear at its configured mount; inspect the disk before retrying')
        state = adopted_state()
        require_current_adoption(stable_id, disk, state['disks'])
        state['disks'][stable_id]['filesystem_uuid'] = part['uuid']
        state['disks'][stable_id]['mount'] = mount
        state['disks'][stable_id]['inventory_fingerprint'] = disk_fingerprint(updated)
        write_json(ADOPTIONS, state)
    except Exception:
        if mounted_here:
            run(['/usr/bin/umount', mount], check=False, timeout=30)
        if old_fstab is not None:
            restore_fstab(old_fstab)
            run(['/usr/bin/systemctl', 'daemon-reload'], check=False, timeout=30)
        raise
    return {'mounted': True, 'filesystem': 'ext4', 'uuid': part['uuid'], 'mount': mount}


def existing_storage_worker():
    request = read_json(INITIALIZE_REQUEST, {})
    stable_id = request.get('stable_id')
    operation = request.get('operation', 'use-existing')
    try:
        operations = {'mount': mount_adopted, 'unmount': unmount_adopted,
                      'use-existing': use_existing_filesystem}
        if operation not in operations:
            raise ValueError('Unsupported existing-storage operation')
        write_initialization_status('initializing', operation=operation,
                                    stable_id=stable_id, phase=operation)
        result = operations[operation](request)
        write_initialization_status('completed', operation=operation, stable_id=stable_id,
                                    phase='completed', mount=result['mount'])
    except Exception as error:
        write_initialization_status('failed', operation=operation, stable_id=stable_id,
                                    phase='failed', error=str(error))
        raise


def environment_data_root():
    for line in ENVIRONMENT.read_text(encoding='utf-8').splitlines():
        if line.startswith('CYBERDECK_ROOT='):
            value = line.split('=', 1)[1]
            candidate = Path(value)
            if (not value.startswith('/') or
                    not re.fullmatch(r'/[A-Za-z0-9_./-]+', value) or
                    candidate.resolve() != candidate):
                raise ValueError('Configured data root is invalid')
            return candidate
    return DATA_ROOT_DEFAULT


def environment_home_mount():
    for line in ENVIRONMENT.read_text(encoding='utf-8').splitlines():
        if line.startswith('CYBERDECK_HOME_MOUNT='):
            value = line.split('=', 1)[1]
            if value == '':
                return None
            if value != '/home':
                raise ValueError('Configured home filesystem mount is invalid')
            return value
    return None


def findmnt_record(path):
    result = run_as_json(['/usr/bin/findmnt', '--json', '--target', str(path),
                          '--output', 'TARGET,SOURCE,FSROOT,FSTYPE,OPTIONS'])
    rows = result.get('filesystems') or []
    return rows[0] if rows else None


def mount_records_at(path):
    result = run(['/usr/bin/findmnt', '--json', '--mountpoint', str(path),
                  '--output', 'TARGET,SOURCE,FSROOT,FSTYPE,OPTIONS'], check=False)
    if result.returncode == 1:
        return []
    if result.returncode:
        raise subprocess.CalledProcessError(
            result.returncode, result.args, output=result.stdout, stderr=result.stderr)
    return (json.loads(result.stdout or '{}').get('filesystems') or [])


def cyberdeck_library_alias_mounts(path, active_root):
    """Return stacked Cyberdeck library aliases safe to detach during migration."""
    records = mount_records_at(path)
    if not records:
        return 0
    if any(fields[1] == str(path) for line in fstab_lines()
           if len(fields := line.split()) >= 2 and not fields[0].startswith('#')):
        raise ValueError('The destination path has a persistent mount entry; review it before migration')
    if any(record.get('target') != str(path) or record.get('fstype') != 'ext4' or
           record.get('fsroot') != '/.cyberdeck-library' for record in records):
        raise ValueError('Refusing a mount at the data destination that is not a Cyberdeck library alias')
    if os.stat(path).st_dev != os.stat(active_root).st_dev:
        raise ValueError('The mounted destination is not on the active library filesystem')
    return len(records)


def restore_destination_alias(path, active_root, count):
    if count <= 0:
        return
    existing = len(mount_records_at(path))
    if existing > count:
        raise ValueError('Destination has more mounted layers than its migration journal allows')
    for _ in range(count - existing):
        run(['/usr/bin/mount', '--bind', str(active_root), str(path)], timeout=30)


def filesystem_target(target_mount):
    if (not isinstance(target_mount, str) or not target_mount.startswith('/') or
            str(Path(target_mount)) != target_mount or '\x00' in target_mount):
        raise ValueError('Select a valid approved storage folder')
    state = adopted_state()['disks']
    home_mount = environment_home_mount()
    disk = None
    if target_mount != '/' and target_mount != home_mount:
        for candidate in flatten_disks(block_inventory()):
            if not any(target_mount in part['mounts'] for part in candidate['partitions']):
                continue
            if not candidate['stable_id']:
                continue
            require_current_adoption(candidate['stable_id'], candidate, state)
            disk = candidate
            break
        if disk is None:
            raise ValueError('Only the system root, a separate /home filesystem, or an adopted mounted disk can hold library data')

    fstab_entry = next((fields for line in fstab_lines()
                        if len(fields := line.split()) >= 4 and fields[1] == target_mount and
                        not fields[0].startswith('#')), None)
    if not fstab_entry or 'noauto' in fstab_entry[3].split(','):
        raise ValueError('The selected filesystem is not configured for persistent startup')
    source, _mount, filesystem, raw_options = fstab_entry[:4]
    if filesystem != 'ext4':
        raise ValueError('Library data migration currently requires an ext4 destination')
    options = raw_options.split(',')
    if 'ro' in options:
        raise ValueError('The selected filesystem is configured read-only')
    if source.startswith('UUID='):
        uuid = source[5:]
        device = '/dev/disk/by-uuid/' + uuid
    elif source.startswith('/dev/disk/by-uuid/'):
        device = source
        uuid = Path(source).name
    elif source.startswith('/dev/'):
        device = os.path.realpath(source)
        uuid = run(['/usr/sbin/blkid', '-s', 'UUID', '-o', 'value', device]).stdout.strip()
    else:
        raise ValueError('The selected filesystem does not have a supported block-device identity')
    if not re.fullmatch(r'[A-Fa-f0-9-]{16,64}', uuid) or not Path(device).exists():
        raise ValueError('The selected filesystem identity could not be verified')

    inspect_path = target_mount
    mounted = findmnt_record(inspect_path)
    device_stat = os.stat(device)
    mounted_device_matches = False
    if mounted:
        try:
            mounted_device_matches = os.stat(inspect_path).st_dev == device_stat.st_rdev
        except OSError:
            pass
    if (not mounted or mounted.get('fstype') != filesystem or not mounted_device_matches):
        home_probe = Path('/home/.cyberdeck-storage-probe')
        if target_mount != home_mount or not home_probe.exists():
            raise ValueError('The selected filesystem is not mounted at its approved folder')
        mounted = findmnt_record(home_probe)
        inspect_path = str(home_probe)
        if not mounted or mounted.get('fstype') != filesystem:
            raise ValueError('The separate /home filesystem is not visible to Cyberdeck')
        if os.stat(inspect_path).st_dev != device_stat.st_rdev:
            raise ValueError('The /home probe does not match the selected filesystem identity')
    target_id = hashlib.sha256(
        f'{target_mount}\0{uuid}\0{filesystem}'.encode('utf-8')).hexdigest()
    return {'target_id': target_id, 'target_mount': target_mount,
            'device': device, 'uuid': uuid, 'filesystem': filesystem,
            'model': disk['model'] if disk else Path(os.path.realpath(device)).name,
            'persistent': True, 'writable': True, 'inspect_path': inspect_path,
            'stable_id': disk['stable_id'] if disk else None}


def migration_preview(payload):
    target_mount = payload.get('target_mount')
    target = filesystem_target(target_mount)
    if payload.get('target_id') and payload['target_id'] != target['target_id']:
        raise ValueError('The destination filesystem changed since preview; refresh and review it again')
    data_root = environment_data_root()
    if data_root.is_symlink() or not data_root.is_dir():
        raise ValueError('Configured library data root is missing or unsafe')
    destination = Path(target_mount) / '.cyberdeck-library'
    try:
        root_real = data_root.resolve()
        destination_real = destination.resolve()
        common = os.path.commonpath((str(root_real), str(destination_real)))
        same_directory = destination.exists() and os.path.samefile(data_root, destination)
    except (OSError, ValueError):
        raise ValueError('Could not safely compare the source and destination folders')
    if common in {str(root_real), str(destination_real)}:
        raise ValueError('The library source and destination folders cannot contain one another')
    if same_directory:
        raise ValueError('The selected destination is already the active library data root')
    size = sum(path.stat().st_size for path in data_root.rglob('*') if path.is_file() and not path.is_symlink())
    free = shutil.disk_usage(target['inspect_path']).free
    destination_visible = target['inspect_path'] == target_mount
    destination_empty = None if not destination_visible else not destination.exists() or (
        destination.is_dir() and not destination.is_symlink() and
        not os.path.ismount(destination) and not any(destination.iterdir()))
    return {'target_id': target['target_id'], 'target_mount': target_mount,
            'stable_id': target['stable_id'], 'device': target['device'],
            'model': target['model'],
            'filesystem': target['filesystem'], 'uuid': target['uuid'], 'mount': target_mount,
            'destination': str(destination),
            'data_root': str(data_root), 'copy_bytes': size, 'free_bytes': free,
            'eligible': target['filesystem'] == 'ext4' and target['persistent'] and
                        target['writable'] and free >= size + 1024**3,
            'persistent_mount': target['persistent'], 'destination_empty': destination_empty}


def write_migration_status(status, **values):
    record = read_json(JOURNAL, {})
    if status != 'failed':
        record.pop('error', None)
        record.pop('recovered', None)
    record.update({'status': status, 'updated_at': int(time.time()), **values})
    write_json(JOURNAL, record)
    # The status file is group-readable by the Hub service. Keep the recovery
    # journal's prior fstab contents and block-device metadata root-only.
    write_json(STATUS, {key: value for key, value in record.items()
                        if key in PUBLIC_STATUS_FIELDS}, mode=0o644)


def recover_check():
    """Restore the previous root after an interrupted storage switch."""
    initialization = read_json(INITIALIZE_STATUS, {})
    if initialization.get('status') in {'queued', 'initializing'}:
        write_initialization_status(
            'failed', stable_id=initialization.get('stable_id'), phase='interrupted',
            error='Disk initialization was interrupted. Inspect the disk layout before retrying.')
    journal = read_json(JOURNAL, {'status': 'idle'})
    status = journal.get('status')
    if status not in {'queued', 'copying', 'quiescing', 'verifying', 'switching', 'pending-health'}:
        return {'recovered': False, 'status': status or 'idle'}
    live = read_json(STATUS, {})
    if status == 'queued' and live.get('status') == 'queued':
        try:
            worker = run(['/usr/bin/systemctl', 'is-active', STORAGE_UNIT],
                         check=False, timeout=5)
        except (OSError, subprocess.SubprocessError):
            # If systemd cannot be queried, preserve the queued state rather
            # than risk declaring a live migration failed.
            return {'recovered': False, 'status': 'queued'}
        if worker.returncode == 0 and worker.stdout.strip() in {
                'active', 'activating', 'reloading'}:
            return {'recovered': False, 'status': 'queued'}
        write_migration_status(
            'failed', stable_id=journal.get('stable_id'),
            target_id=journal.get('target_id'), target_mount=journal.get('target_mount'),
            error='Storage migration did not start. Check the migration service journal before retrying.')
        return {'recovered': False, 'status': 'failed'}
    if status == 'pending-health' and live.get('status') == 'pending-health':
        return {'recovered': False, 'status': 'pending-health'}
    if status in {'switching', 'pending-health'}:
        root = journal.get('data_root')
        old_fstab = journal.get('old_fstab')
        if not isinstance(root, str) or not root.startswith('/') or not isinstance(old_fstab, str):
            raise ValueError('Storage migration journal is incomplete; services must remain stopped')
        expected_device = journal.get('source_device')
        if not isinstance(expected_device, int) or not Path(root).exists():
            raise ValueError('Could not restore the original data root; services must remain stopped')
        current_device = os.stat(root).st_dev
        if current_device != expected_device:
            run(['/usr/bin/umount', root], timeout=30)
            if os.stat(root).st_dev != expected_device:
                raise ValueError('Could not restore the original data root; services must remain stopped')
        temporary = FSTAB.with_name('fstab.cyberdeck.recovery')
        temporary.write_text(old_fstab, encoding='utf-8')
        temporary.chmod(0o644)
        os.replace(temporary, FSTAB)
        run(['/usr/bin/systemctl', 'daemon-reload'], timeout=30)
    alias_destination = journal.get('detached_destination')
    alias_count = journal.get('detached_mount_count', 0)
    if alias_destination:
        active_root = journal.get('data_root') or journal.get('source')
        if (not isinstance(active_root, str) or not active_root.startswith('/') or
                not isinstance(alias_count, int) or alias_count < 1 or alias_count > 16):
            raise ValueError('Storage migration journal has an invalid destination alias')
        restore_destination_alias(Path(alias_destination), Path(active_root), alias_count)
    write_migration_status('failed', stable_id=journal.get('stable_id'),
                           target_id=journal.get('target_id'), target_mount=journal.get('target_mount'),
                           error='Interrupted storage migration was rolled back to the original data root',
                           recovered=True, detached_destination=None, detached_mount_count=0)
    return {'recovered': True, 'status': 'failed'}


def recover_after_failure():
    if STATUS.is_symlink():
        raise ValueError('Refusing a symlink at the runtime migration status')
    result = recover_check()
    if result.get('recovered'):
        run(['/usr/bin/systemctl', 'start', *UNITS], timeout=90)
    return result


def migrate_worker():
    request = read_json(REQUEST, {})
    target_id = request.get('target_id')
    target_mount = request.get('target_mount')
    stable_id = None
    stopped = False
    fstab_changed = False
    bind_mounted = False
    destination_alias_count = 0
    destination_alias_detached = False
    destination = None
    root = None
    old_fstab = None
    try:
        preview = migration_preview({'target_id': target_id, 'target_mount': target_mount})
        if not preview['eligible']:
            required = preview.get('copy_bytes', 0) + 1024**3
            available = preview.get('free_bytes', 0)
            if available < required:
                raise ValueError(
                    f'Destination needs {required} bytes including reserve, '
                    f'but only {available} bytes are free')
            raise ValueError('Destination filesystem is not eligible for library storage')
        root = Path(preview['data_root'])
        mount = Path(preview['target_mount'])
        stable_id = preview.get('stable_id')
        if mount.is_symlink() or not mount.is_dir() or not os.path.ismount(mount):
            raise ValueError('Selected destination is no longer a mounted filesystem')
        if 'rw' not in mount_options(str(mount)):
            raise ValueError('Selected destination is mounted read-only')
        destination = Path(preview['destination'])
        if destination.is_symlink():
            raise ValueError('Refusing a symlink or nested mount at the data destination')
        destination_alias_count = cyberdeck_library_alias_mounts(destination, root)
        if os.path.ismount(destination) and not destination_alias_count:
            raise ValueError('Refusing a symlink or nested mount at the data destination')
        if destination.exists() and any(destination.iterdir()):
            existing = run([
                '/usr/bin/rsync', '-aHAXn', '--checksum', '--delete', '--itemize-changes',
                '--numeric-ids', '--', str(root) + '/', str(destination) + '/'], timeout=86400)
            if existing.stdout.strip():
                raise ValueError(
                    f'Destination already contains data that differs from the active library: '
                    f'{destination}. No existing files were changed.')
        root_stat = root.stat()
        if not destination_alias_count:
            destination.mkdir(mode=0o750, exist_ok=True)
            os.chown(destination, root_stat.st_uid, root_stat.st_gid)
            shutil.copystat(root, destination, follow_symlinks=False)
        write_migration_status('copying', stable_id=stable_id, target_id=target_id,
                               target_mount=str(mount), source=str(root), destination=str(destination))
        if not destination_alias_count:
            run(['/usr/bin/rsync', '-aHAX', '--numeric-ids', '--', str(root) + '/', str(destination) + '/'], timeout=86400)
        write_migration_status('quiescing', stable_id=stable_id, target_id=target_id,
                               target_mount=str(mount), source=str(root), destination=str(destination),
                               detached_destination=str(destination) if destination_alias_count else None,
                               detached_mount_count=destination_alias_count)
        run(['/usr/bin/systemctl', 'stop', *UNITS], timeout=90)
        stopped = True
        if destination_alias_count:
            destination_alias_detached = True
            for _ in range(destination_alias_count):
                run(['/usr/bin/umount', str(destination)], timeout=30)
            if mount_records_at(destination):
                raise ValueError('Could not detach the existing Cyberdeck library mounts from the destination')
            if destination.is_symlink() or not destination.is_dir():
                raise ValueError('The underlying destination folder is missing or unsafe')
            if any(destination.iterdir()):
                existing = run([
                    '/usr/bin/rsync', '-aHAXn', '--checksum', '--delete', '--itemize-changes',
                    '--numeric-ids', '--', str(root) + '/', str(destination) + '/'], timeout=86400)
                if existing.stdout.strip():
                    raise ValueError(
                        f'The underlying destination already contains different data: {destination}. '
                        'No existing files were changed.')
            else:
                run(['/usr/bin/rsync', '-aHAX', '--numeric-ids', '--',
                     str(root) + '/', str(destination) + '/'], timeout=86400)
            os.chown(destination, root_stat.st_uid, root_stat.st_gid)
            shutil.copystat(root, destination, follow_symlinks=False)
        # Capture writes made during the initial copy only after both writers stop.
        run(['/usr/bin/rsync', '-aHAX', '--numeric-ids', '--delete', '--',
             str(root) + '/', str(destination) + '/'], timeout=86400)
        os.chown(destination, root_stat.st_uid, root_stat.st_gid)
        shutil.copystat(root, destination, follow_symlinks=False)
        write_migration_status('verifying', stable_id=stable_id, target_id=target_id,
                               target_mount=str(mount), source=str(root), destination=str(destination))
        verify = run(['/usr/bin/rsync', '-aHAXn', '--checksum', '--delete', '--itemize-changes',
                      '--numeric-ids', '--', str(root) + '/', str(destination) + '/'], timeout=86400)
        if verify.stdout.strip():
            raise ValueError('Destination verification found differences')
        if root.is_symlink() or not root.is_absolute():
            raise ValueError('Configured data root is not a safe absolute path')
        data_root = root.resolve()
        # Preserve all existing files and install a durable bind mount only after verification.
        marker = '# cyberdeck-storage-root'
        old_fstab = FSTAB.read_text(encoding='utf-8')
        write_migration_status('switching', stable_id=stable_id, target_id=target_id,
                               target_mount=str(mount), source=str(root),
                               destination=str(destination), data_root=str(data_root),
                               source_device=os.stat(data_root).st_dev, old_fstab=old_fstab)
        entries = [f'{destination} {data_root} none bind,nofail,x-systemd.device-timeout=5s 0 0 {marker}']
        update_fstab(marker, entries)
        fstab_changed = True
        run(['/usr/bin/mount', '--bind', str(destination), str(data_root)], timeout=30)
        bind_mounted = True
        run(['/usr/bin/systemctl', 'daemon-reload'], timeout=30)
        write_migration_status('pending-health', stable_id=stable_id, target_id=target_id,
                               target_mount=str(mount), source=str(root),
                               destination=str(destination), data_root=str(data_root))
        run(['/usr/bin/systemctl', 'start', *UNITS], timeout=90)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        zim_directory = data_root / 'zim'
        kiwix_required = zim_directory.is_dir() and any(zim_directory.glob('*.zim'))
        for _ in range(30):
            web_active = run(['/usr/bin/systemctl', 'is-active', UNITS[0]],
                             check=False).stdout.strip() == 'active'
            kiwix_active = run(['/usr/bin/systemctl', 'is-active', UNITS[1]],
                               check=False).stdout.strip() == 'active'
            if web_active and (kiwix_active or not kiwix_required):
                try:
                    with urllib.request.urlopen('https://127.0.0.1/', timeout=4,
                                                context=context) as response:
                        if response.status == 200:
                            break
                except (OSError, urllib.error.URLError):
                    pass
            time.sleep(1)
        else:
            raise ValueError('Services did not pass post-migration health checks')
        state = adopted_state()
        for record in state['disks'].values():
            record.pop('data_root', None)
            record.pop('destination', None)
        if stable_id in state['disks']:
            state['disks'][stable_id]['data_root'] = str(data_root)
            state['disks'][stable_id]['destination'] = str(destination)
            write_json(ADOPTIONS, state)
        write_migration_status('committed', stable_id=stable_id, target_id=target_id,
                               target_mount=str(mount), source=str(root),
                               destination=str(destination), backup_retained=True,
                               detached_destination=None, detached_mount_count=0)
    except Exception as error:
        if stopped:
            run(['/usr/bin/systemctl', 'stop', *UNITS], check=False, timeout=90)
            if bind_mounted:
                run(['/usr/bin/umount', str(data_root)], timeout=30)
                if os.stat(data_root).st_dev != os.stat(root).st_dev:
                    raise ValueError('Could not restore the original data root; services remain stopped') from error
            if fstab_changed and old_fstab is not None:
                temporary = FSTAB.with_name('fstab.cyberdeck.rollback')
                temporary.write_text(old_fstab, encoding='utf-8')
                temporary.chmod(0o644)
                os.replace(temporary, FSTAB)
            run(['/usr/bin/systemctl', 'daemon-reload'], check=False, timeout=30)
            if destination_alias_detached:
                restore_destination_alias(destination, root, destination_alias_count)
            run(['/usr/bin/systemctl', 'start', *UNITS], check=False, timeout=90)
        write_migration_status('failed', stable_id=stable_id, target_id=target_id,
                               target_mount=target_mount, error=str(error),
                               detached_destination=None, detached_mount_count=0)
        raise


def start_migration(payload):
    target_id = payload.get('target_id')
    target_mount = payload.get('target_mount')
    preview = migration_preview({'target_mount': target_mount, 'target_id': target_id})
    if not preview['eligible']:
        raise ValueError('Destination is not eligible for migration')
    if payload.get('confirm') != target_id:
        raise ValueError('Confirmation must exactly match the selected filesystem identity')
    if read_json(STATUS, {'status': 'idle'}).get('status') in {
            'queued', 'copying', 'quiescing', 'verifying', 'switching', 'pending-health'}:
        raise ValueError('A storage migration is already in progress')
    write_json(REQUEST, {'target_id': target_id, 'target_mount': target_mount}, mode=0o600)
    write_migration_status('queued', stable_id=preview.get('stable_id'),
                            target_id=target_id, target_mount=target_mount,
                            detached_destination=None, detached_mount_count=0)
    try:
        run(['/usr/bin/systemctl', 'start', '--no-block', STORAGE_UNIT], timeout=15)
    except (OSError, subprocess.SubprocessError) as error:
        write_migration_status('failed', stable_id=preview.get('stable_id'),
                               target_id=target_id, target_mount=target_mount, error=str(error))
        raise
    return {'status': 'queued'}


def main():
    if os.geteuid() != 0:
        raise ValueError('Storage helper must run as root')
    action = sys.argv[1] if len(sys.argv) == 2 else ''
    raw = sys.stdin.read(MAX_REQUEST + 1) if action in {
        'adopt', 'mount', 'unmount', 'initialize', 'use-existing', 'migration-preview', 'migrate'} else '{}'
    if len(raw) > MAX_REQUEST:
        raise ValueError('Storage request is too large')
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError('Expected a JSON object')
    allowed = {
        'list': list_disks,
        'adopt': lambda: adopt(payload),
        'mount': lambda: start_mount_action(payload, 'mount'),
        'unmount': lambda: start_mount_action(payload, 'unmount'),
        'initialize': lambda: start_initialization(payload),
        'initialize-worker': initialize_worker,
        'use-existing': lambda: start_existing_storage(payload),
        'use-existing-worker': existing_storage_worker,
        'migration-preview': lambda: migration_preview(payload),
        'migrate': lambda: start_migration(payload),
        'migration-status': public_migration_status,
        'migrate-worker': migrate_worker,
        'recover-check': recover_check,
        'recover-after-failure': recover_after_failure,
    }
    if action not in allowed:
        raise ValueError('Unsupported storage operation')
    result = allowed[action]()
    print(json.dumps(result))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
