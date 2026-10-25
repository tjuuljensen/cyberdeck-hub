#!/usr/bin/env python3
"""Root-only hostname, certificate and hotspot DNS maintenance for Cyberdeck."""
import argparse
import configparser
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import secrets
import shutil
import socket
import stat
import subprocess
import tempfile
import time
import uuid

ENVIRONMENT = Path('/etc/cyberdeck/environment')
DNS_CONFIG = Path('/etc/NetworkManager/dnsmasq-shared.d/cyberdeck.conf')
PROFILE = Path('/etc/NetworkManager/system-connections/cyberdeck-hotspot.nmconnection')
TLS = Path('/etc/cyberdeck/tls')
HOSTS = Path('/etc/hosts')
STATE = Path('/etc/cyberdeck/hostname-change.json')
BACKUPS = Path('/etc/cyberdeck/hostname-changes')
SCRIPT = '/usr/local/lib/cyberdeck/host_identity.py'
DNSMASQ = '/usr/sbin/dnsmasq'
SERVICES = ('avahi-daemon.service', 'cyberdeck-redirect.service', 'cyberdeck-kiwix-https.service',
            'cyberdeck-legacy-https.service', 'cyberdeck-web.service')
DEBIAN_SERVICES = ('avahi-daemon.service', 'cyberdeck-redirect.service', 'cyberdeck-web.service')
NAME_RE = re.compile(r'[a-z][a-z0-9-]{0,61}[a-z0-9]|[a-z]')


def run(args, *, check=True, timeout=25):
    return subprocess.run(args, check=check, text=True, capture_output=True, timeout=timeout)


def valid_name(value):
    if not isinstance(value, str) or not NAME_RE.fullmatch(value) or value in {'localhost', 'localhost-localdomain'}:
        raise ValueError('Use 1-63 lowercase letters, digits or hyphens; start with a letter and end with a letter or digit.')
    return value


def safe_path(path):
    for candidate in (path, *path.parents):
        if candidate.is_symlink():
            raise ValueError('Refusing a symlink in a host configuration path')
    if path.exists() and not path.is_file():
        raise ValueError('Host configuration must be a regular file')


def environment_host():
    safe_path(ENVIRONMENT)
    values = [line.partition('=')[2] for line in ENVIRONMENT.read_text(encoding='utf-8').splitlines()
              if line.startswith('CYBERDECK_HOSTNAME=')]
    if len(values) != 1:
        raise ValueError('The installed Cyberdeck environment must contain one hostname')
    return values[0]


def runtime_services():
    """Select the restart set for the installed Hub service layout."""
    safe_path(ENVIRONMENT)
    modes = [line.partition('=')[2].strip().lower()
             for line in ENVIRONMENT.read_text(encoding='utf-8').splitlines()
             if line.startswith('CYBERDECK_RUNTIME_MODE=')]
    if len(modes) > 1:
        raise ValueError('The installed Cyberdeck environment has ambiguous runtime mode')
    return DEBIAN_SERVICES if modes and modes[0] in {'debian', 'headless'} else SERVICES


def require_platform(expected=None):
    if not hasattr(os, 'geteuid') or os.geteuid() != 0:
        raise ValueError('Host configuration requires root on the Cyberdeck server')
    release = platform.freedesktop_os_release()
    if release.get('ID') != 'debian' or release.get('VERSION_ID') != '13':
        raise ValueError('Host configuration requires Debian 13')
    current = valid_name(socket.gethostname().split('.')[0])
    if expected is not None and current != expected:
        raise ValueError('The hostname changed since this operation was requested')
    return current


def require_host(expected=None):
    current = require_platform(expected)
    if environment_host() not in {current + '.lan', current + '.local'}:
        raise ValueError('The running hostname does not match the installed Cyberdeck environment')
    return current


def atomic_write(path, data, mode=0o600, owner=None):
    safe_path(path)
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(mode)
        if owner is not None:
            os.chown(temporary, *owner)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def dns_text(hostname, device):
    valid_name(hostname)
    if not isinstance(device, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,15}', device):
        raise ValueError('Invalid hotspot adapter')
    return ('# Managed by Cyberdeck; addresses follow the selected hotspot adapter.\n'
            f'interface-name={hostname}.lan,{device}/4\n'
            f'interface-name={hostname},{device}/4\n')


def prepare_dns(device):
    hostname = require_host()
    safe_path(DNS_CONFIG)
    if not DNS_CONFIG.parent.is_dir():
        raise ValueError('Deploy the hotspot DNS configuration before starting the hotspot')
    content = dns_text(hostname, device).encode('ascii')
    # Hidden temporary files are ignored by dnsmasq's conf-dir loader.
    fd, name = tempfile.mkstemp(prefix='.cyberdeck-test-', dir=DNS_CONFIG.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
        result = run([DNSMASQ, '--test', '--no-hosts', '--conf-file=' + str(temporary)], check=False)
        if result.returncode:
            raise ValueError('Hotspot DNS validation failed; the hotspot was not started')
        atomic_write(DNS_CONFIG, content, 0o644)
    finally:
        temporary.unlink(missing_ok=True)


def saved_adapter():
    safe_path(PROFILE)
    if not PROFILE.exists():
        return None
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(PROFILE, encoding='utf-8')
    device = parser.get('connection', 'interface-name', fallback='')
    dns_text('validation', device)
    return device


def hotspot_active():
    if (not shutil.which('nmcli') or
            run(['systemctl', 'is-active', '--quiet', 'NetworkManager.service'], check=False).returncode):
        return False
    names = run(['nmcli', '-t', '-f', 'NAME', 'connection', 'show', '--active']).stdout.splitlines()
    return 'cyberdeck-hotspot' in names


def state_read():
    safe_path(STATE)
    return json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {}


def state_write(record):
    atomic_write(STATE, (json.dumps(record) + '\n').encode('utf-8'))


@contextmanager
def change_lock():
    import fcntl  # Only host-side operations use Linux locking.
    path = STATE.with_suffix('.lock')
    safe_path(path)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('A hostname change is already in progress') from exc
        yield
    finally:
        os.close(fd)


def hostname_status():
    current = require_host()
    record = state_read()
    return {'hostname': current, 'url': f'https://{environment_host()}/',
            'change': {key: record[key] for key in ('status', 'hostname', 'previous', 'error', 'id') if key in record}}


def check_rename_tools():
    commands = ['openssl', 'hostnamectl', 'systemd-run', 'busctl']
    if PROFILE.exists() and not shutil.which('nmcli'):
        raise ValueError('NetworkManager is required to preserve the configured hotspot during a hostname change')
    if shutil.which('nmcli'):
        commands.append('nmcli')
    for command in commands:
        if not shutil.which(command):
            raise ValueError('Hostname changes require the updated setup package (including Avahi)')
    if not Path(DNSMASQ).is_file():
        raise ValueError('Install dnsmasq-base with the updated setup package')
    for service in runtime_services():
        if run(['systemctl', 'is-active', service], check=False).returncode:
            raise ValueError('Library services and local name discovery must be running; complete server setup first')


def request_hostname(payload):
    hostname = valid_name(payload.get('hostname'))
    if payload.get('confirm') != hostname:
        raise ValueError('Confirm the new hostname before applying it')
    current = require_host()
    if hostname == current:
        raise ValueError('Choose a different hostname')
    with change_lock():
        previous = state_read()
        if previous.get('status') == 'recovery-required':
            raise ValueError('The previous hostname change needs local recovery before retrying')
        if previous.get('status') in {'scheduled', 'applying'}:
            unit = 'cyberdeck-hostname-' + previous['id']
            if any(run(['systemctl', 'is-active', unit + suffix], check=False).returncode == 0
                   for suffix in ('.timer', '.service')):
                raise ValueError('A hostname change is already in progress')
            raise ValueError('An interrupted hostname change needs local recovery before retrying')
        check_rename_tools()
        # An existing name must not be stolen from another device.
        collision = run(['busctl', '--system', '--timeout=8s', '--', 'call', 'org.freedesktop.Avahi', '/',
                         'org.freedesktop.Avahi.Server', 'ResolveHostName', 'iisiu',
                         '-1', '-1', hostname + '.local', '-1', '0'], check=False, timeout=10)
        if collision.returncode == 0:
            raise ValueError('That name is already in use on this network; choose another')
        change_id = uuid.uuid4().hex
        record = {'id': change_id, 'hostname': hostname, 'previous': current, 'status': 'scheduled'}
        state_write(record)
        try:
            run(['systemd-run', '--unit=cyberdeck-hostname-' + change_id, '--on-active=5s',
                 '--timer-property=AccuracySec=1s', '/usr/bin/python3', SCRIPT, '--apply', change_id])
        except Exception:
            record.update(status='failed', error='Could not schedule the change; the hostname was not changed')
            state_write(record)
            raise
    return {'scheduled': True, 'hostname': hostname, 'url': f'https://{hostname}.local/',
            'previous_url': f'https://{environment_host()}/'}


def replacement_environment(text, hostname):
    if sum(line.startswith('CYBERDECK_HOSTNAME=') for line in text.splitlines()) != 1:
        raise ValueError('Expected exactly one configured hostname')
    return '\n'.join('CYBERDECK_HOSTNAME=' + hostname + '.local' if line.startswith('CYBERDECK_HOSTNAME=')
                     else line for line in text.splitlines()) + '\n'


def replacement_hosts(text, previous, hostname):
    lines, found = [], False
    old_names = {previous, previous + '.lan', previous + '.local'}
    for line in text.splitlines():
        body, marker, comment = line.partition('#')
        fields = body.split()
        if fields and fields[0] == '127.0.1.1' and old_names.intersection(fields[1:]):
            aliases = [name for name in fields[1:] if name not in old_names]
            line = '127.0.1.1\t' + ' '.join([hostname, hostname + '.local', hostname + '.lan', *aliases])
            if marker:
                line += ' #' + comment
            found = True
        lines.append(line)
    if not found:
        lines.append(f'127.0.1.1\t{hostname} {hostname}.local {hostname}.lan')
    return '\n'.join(lines) + '\n'


def make_certificate(directory, hostname):
    key, csr, cert, extensions = (directory / name for name in ('new.key', 'new.csr', 'new.crt', 'server.ext'))
    extensions.write_text(f'subjectAltName=DNS:{hostname},DNS:{hostname}.lan,DNS:{hostname}.local,IP:127.0.0.1\n'
                          'extendedKeyUsage=serverAuth\n', encoding='ascii')
    run(['openssl', 'req', '-new', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(key),
         '-out', str(csr), '-subj', '/CN=' + hostname])
    key.chmod(0o600)
    run(['openssl', 'x509', '-req', '-in', str(csr), '-CA', str(TLS / 'ca.crt'),
         '-CAkey', str(TLS / 'ca.key'), '-set_serial', '0x' + secrets.token_hex(16),
         '-out', str(cert), '-days', '825', '-sha256', '-extfile', str(extensions)])
    run(['openssl', 'verify', '-CAfile', str(TLS / 'ca.crt'), '-verify_hostname', hostname + '.local', str(cert)])
    return key, cert


def restart_hotspot(device):
    run(['nmcli', 'connection', 'down', 'id', 'cyberdeck-hotspot'], check=False)
    run(['nmcli', 'connection', 'up', 'id', 'cyberdeck-hotspot', 'ifname', device])


def snapshot(directory):
    records = []
    for index, path in enumerate((ENVIRONMENT, HOSTS, TLS / 'server.key', TLS / 'server.crt', DNS_CONFIG)):
        safe_path(path)
        if not path.is_file():
            raise ValueError('Complete server setup and DNS deployment before changing the hostname')
        metadata = path.stat()
        backup = directory / f'file-{index}'
        backup.write_bytes(path.read_bytes())
        backup.chmod(0o600)
        records.append({'path': str(path), 'backup': backup.name, 'mode': stat.S_IMODE(metadata.st_mode),
                        'uid': metadata.st_uid, 'gid': metadata.st_gid,
                        'sha256': hashlib.sha256(backup.read_bytes()).hexdigest()})
    return records


def restore_files(directory, records):
    for record in records:
        atomic_write(Path(record['path']), (directory / record['backup']).read_bytes(), record['mode'],
                     (record['uid'], record['gid']))


def apply_hostname(change_id):
    if not re.fullmatch(r'[0-9a-f]{32}', change_id):
        raise ValueError('Invalid hostname change identifier')
    with change_lock():
        record = state_read()
        if record.get('id') != change_id or record.get('status') != 'scheduled':
            raise ValueError('No matching scheduled hostname change')
        records, changed, directory = [], False, BACKUPS / change_id
        phase = 'preflight'
        try:
            current = require_host(record['previous'])
            hostname = valid_name(record['hostname'])
            check_rename_tools()
            for path in (TLS / 'ca.key', TLS / 'ca.crt', directory / 'state.json'):
                safe_path(path)
            directory.mkdir(parents=True, mode=0o700)
            BACKUPS.chmod(0o700)
            records = snapshot(directory)
            device = saved_adapter()
            was_active = hotspot_active()
            if was_active and not device:
                raise ValueError('The active hotspot has no saved adapter')
            atomic_write(directory / 'state.json', (json.dumps({'previous': current, 'hostname': hostname,
                'hotspot_active': was_active, 'device': device, 'files': records}) + '\n').encode('utf-8'))
            record.update(status='applying')
            state_write(record)
            phase = 'certificate preparation'
            key, cert = make_certificate(directory, hostname)
            environment = replacement_environment(ENVIRONMENT.read_text(encoding='utf-8'), hostname)
            hosts = replacement_hosts(HOSTS.read_text(encoding='utf-8'), current, hostname)
            changed = True
            phase = 'hostname and DNS update'
            for path, data in ((ENVIRONMENT, environment.encode()), (HOSTS, hosts.encode()),
                               (TLS / 'server.key', key.read_bytes()), (TLS / 'server.crt', cert.read_bytes())):
                info = next(item for item in records if item['path'] == str(path))
                atomic_write(path, data, info['mode'], (info['uid'], info['gid']))
            run(['hostnamectl', '--static', '--transient', 'set-hostname', hostname])
            if device:
                prepare_dns(device)
            else:
                atomic_write(DNS_CONFIG, b'# No saved hotspot adapter; generated on hotspot start.\n', 0o644)
            phase = 'local name discovery'
            run(['systemctl', 'restart', 'avahi-daemon.service'])
            time.sleep(2)  # Let mDNS probing detect name collisions before committing.
            published = run(['busctl', '--system', 'call', 'org.freedesktop.Avahi', '/',
                             'org.freedesktop.Avahi.Server', 'GetHostNameFqdn']).stdout.strip()
            if published != 's "' + hostname + '.local"':
                raise ValueError('Local name discovery did not publish the requested hostname')
            if was_active:
                phase = 'hotspot reconnection'
                restart_hotspot(device)
            phase = 'library service restart'
            services = runtime_services()
            run(['systemctl', 'restart', *services[1:]])
            for service in services:
                run(['systemctl', 'is-active', service])
            record.update(status='complete')
            state_write(record)
        except Exception:
            recovery_failed = False
            if changed:
                try:
                    restore_files(directory, records)
                    run(['hostnamectl', '--static', '--transient', 'set-hostname', record['previous']])
                    if was_active:
                        restart_hotspot(device)
                    run(['systemctl', 'restart', *runtime_services()])
                except Exception:
                    recovery_failed = True
            record.update(status='recovery-required' if recovery_failed else 'failed',
                          error=f'Hostname change failed during {phase}. ' + ('Use the local recovery record.' if recovery_failed else
                                'Previous settings were retained or restored; reconnect using the previous address.'))
            state_write(record)
            # Do not copy subprocess output (which may include sensitive paths) into the API or journal.
            raise ValueError(record['error']) from None


def restore_hostname(change_id, expected_host):
    """Explicit local recovery, including a power loss halfway through a rename."""
    if not re.fullmatch(r'[0-9a-f]{32}', change_id):
        raise ValueError('Invalid hostname change identifier')
    require_platform(valid_name(expected_host))
    with change_lock():
        record = state_read()
        if record.get('id') != change_id:
            raise ValueError('Only the latest hostname change can be restored')
        directory = BACKUPS / change_id
        metadata = directory / 'state.json'
        safe_path(metadata)
        unit = 'cyberdeck-hostname-' + change_id
        run(['systemctl', 'stop', unit + '.timer', unit + '.service'], check=False)
        if record.get('status') == 'scheduled' and not metadata.exists():
            record.update(status='cancelled')
            state_write(record)
            return
        saved = json.loads(metadata.read_text(encoding='utf-8'))
        previous = valid_name(saved['previous'])
        if previous != record['previous'] or saved['hostname'] != record['hostname']:
            raise ValueError('Recovery record does not match the requested change')
        paths = (ENVIRONMENT, HOSTS, TLS / 'server.key', TLS / 'server.crt', DNS_CONFIG)
        records = saved['files']
        if not isinstance(records, list) or len(records) != len(paths):
            raise ValueError('Incomplete hostname recovery record')
        for index, (entry, path) in enumerate(zip(records, paths)):
            if entry.get('path') != str(path) or entry.get('backup') != f'file-{index}':
                raise ValueError('Unexpected path in hostname recovery record')
            if any(type(entry.get(key)) is not int or entry[key] < 0 for key in ('mode', 'uid', 'gid')):
                raise ValueError('Invalid file metadata in hostname recovery record')
            safe_path(path)
            safe_path(directory / entry['backup'])
            if not (directory / entry['backup']).is_file():
                raise ValueError('Missing hostname recovery file')
            if hashlib.sha256((directory / entry['backup']).read_bytes()).hexdigest() != entry.get('sha256'):
                raise ValueError('Hostname recovery file failed its checksum')
        device = saved.get('device')
        if device:
            dns_text(previous, device)
        active = hotspot_active()
        if (active or saved.get('hotspot_active')) and not device:
            raise ValueError('Recovery needs the recorded hotspot adapter')
        restore_files(directory, records)
        run(['hostnamectl', '--static', '--transient', 'set-hostname', previous])
        if active or saved.get('hotspot_active'):
            restart_hotspot(device)
        run(['systemctl', 'restart', *runtime_services()])
        record.update(status='restored')
        record.pop('error', None)
        state_write(record)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    operations = parser.add_mutually_exclusive_group()
    operations.add_argument('--apply', metavar='CHANGE-ID')
    operations.add_argument('--restore', metavar='CHANGE-ID')
    parser.add_argument('--expected-host', help='Required for explicit local recovery')
    args = parser.parse_args()
    if args.restore and not args.expected_host:
        parser.error('--restore requires --expected-host')
    if args.apply or args.restore:
        try:
            if args.restore:
                restore_hostname(args.restore, args.expected_host)
            else:
                apply_hostname(args.apply)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            parser.exit(1, str(error) + '\n')
    else:
        print('Preview only: hostname changes are requested through Library management > System.')
