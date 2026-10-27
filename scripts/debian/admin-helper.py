#!/usr/bin/python3
"""Root-owned allowlist for NetworkManager and host power operations."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid
import configparser
import host_identity

AUTOSTART = Path('/etc/cyberdeck/hotspot-autostart')
AUTOSTART_PAUSED = Path('/etc/cyberdeck/hotspot-autostart-paused')
HOTSPOT_MODULE_DISABLED = Path('/etc/cyberdeck/hotspot-module-disabled')
UPSTREAMS = Path('/etc/cyberdeck/hotspot-upstreams.json')
REDUNDANCY_MINUTES = Path('/etc/cyberdeck/hotspot-redundancy-minutes')
FALLBACK_STATE = Path('/run/cyberdeck-web/hotspot-fallback.json')
PROFILE = Path('/etc/NetworkManager/system-connections/cyberdeck-hotspot.nmconnection')
IW = '/usr/sbin/iw'
DEFAULT_REDUNDANCY_MINUTES = 60
STORAGE_HELPER = Path('/usr/local/lib/cyberdeck/storage-helper.py')
CYBERCHEF_ROOT = Path('/opt/cyberdeck/modules/cyberchef')
CYBERCHEF_SERVICE = 'cyberdeck-cyberchef.service'
FIREWALL_ENABLED = Path('/etc/cyberdeck/firewall-enabled')
FIREWALL_SERVICE = 'cyberdeck-firewall.service'
NFT = '/usr/sbin/nft'


def storage_operation(action, payload):
    """Delegate approved storage actions to the separate, root-owned helper."""
    if not STORAGE_HELPER.is_file() or STORAGE_HELPER.is_symlink():
        raise ValueError('Storage helper is not installed')
    import importlib.util
    spec = importlib.util.spec_from_file_location('cyberdeck_storage_helper', STORAGE_HELPER)
    if not spec or not spec.loader:
        raise ValueError('Could not load storage helper')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    operations = {
        'list': module.list_disks,
        'adopt': lambda: module.adopt(payload),
        'initialize': lambda: module.initialize_disk(payload),
        'use-existing': lambda: module.use_existing_filesystem(payload),
        'migration-preview': lambda: module.migration_preview(payload),
        'migrate': lambda: module.start_migration(payload),
        'migration-status': lambda: module.read_json(module.STATUS, {'status': 'idle'}),
    }
    if action not in operations:
        raise ValueError('Unsupported storage operation')
    return operations[action]()


def run(args, *, check=True):
    return subprocess.run(args, check=check, text=True, capture_output=True, timeout=25)


def ethernet_carrier():
    for path in Path('/sys/class/net').glob('*/carrier'):
        iface = path.parent.name
        if iface == 'lo':
            continue
        try:
            device_type = run(['nmcli', '-g', 'GENERAL.TYPE', 'device', 'show', iface], check=False).stdout.strip()
            if device_type == 'ethernet' and path.read_text().strip() == '1':
                return True
        except (OSError, subprocess.SubprocessError):
            continue
    return False


def wifi_devices():
    result = run(['nmcli', '-t', '-f', 'DEVICE,TYPE,STATE,CONNECTION', 'device', 'status'], check=False)
    devices = []
    for line in result.stdout.splitlines():
        fields = line.split(':', 3)
        if len(fields) != 4 or fields[1] != 'wifi' or not re.fullmatch(r'[A-Za-z0-9_.-]{1,15}', fields[0]):
            continue
        devices.append({'device': fields[0], 'state': fields[2], 'connection': fields[3] or None})
    return devices


def ap_supported(device=None):
    if device is None:
        return any(ap_supported(item['device']) for item in wifi_devices())
    info = run([IW, 'dev', device, 'info'], check=False)
    match = re.search(r'^\s*wiphy\s+(\d+)\s*$', info.stdout, re.M)
    if info.returncode or not match:
        return False
    phy = run([IW, 'phy', 'phy' + match.group(1), 'info'], check=False)
    return phy.returncode == 0 and re.search(r'^\s*\*\s*AP\s*$', phy.stdout, re.M) is not None


def selected_device():
    if not PROFILE.is_file() or PROFILE.is_symlink():
        return None
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(PROFILE, encoding='utf-8')
        device = parser.get('connection', 'interface-name', fallback='')
    except (configparser.Error, OSError):
        return None
    return device if re.fullmatch(r'[A-Za-z0-9_.-]{1,15}', device) else None


def hotspot_ssid():
    if not PROFILE.is_file() or PROFILE.is_symlink():
        return ''
    parser = configparser.ConfigParser(interpolation=None)
    try:
        with PROFILE.open(encoding='utf-8') as stream:
            parser.read_file(stream)
        return parser.get('wifi', 'ssid', fallback='')
    except (configparser.Error, OSError):
        return ''


def hotspot_password():
    if not PROFILE.is_file() or PROFILE.is_symlink():
        raise ValueError('Hotspot is not configured')
    parser = configparser.ConfigParser(interpolation=None)
    try:
        with PROFILE.open(encoding='utf-8') as stream:
            parser.read_file(stream)
        password = parser.get('wifi-security', 'psk')
    except (configparser.Error, OSError) as exc:
        raise ValueError('Could not read the saved hotspot password') from exc
    if not password:
        raise ValueError('No saved hotspot password')
    return password


def configured_upstreams():
    if not UPSTREAMS.exists() or UPSTREAMS.is_symlink():
        return []
    try:
        values = json.loads(UPSTREAMS.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(values, list):
        return []
    return [value for value in values if isinstance(value, str)]


def redundancy_minutes():
    if not REDUNDANCY_MINUTES.is_file() or REDUNDANCY_MINUTES.is_symlink():
        return DEFAULT_REDUNDANCY_MINUTES
    try:
        value = int(REDUNDANCY_MINUTES.read_text(encoding='ascii').strip())
    except (OSError, ValueError):
        return DEFAULT_REDUNDANCY_MINUTES
    return value if 1 <= value <= 1440 else DEFAULT_REDUNDANCY_MINUTES


def fallback_state():
    if not FALLBACK_STATE.is_file() or FALLBACK_STATE.is_symlink():
        return None
    try:
        state = json.loads(FALLBACK_STATE.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(state, dict) or not isinstance(state.get('fallback_started_at'), (int, float)):
        return None
    recovered = state.get('upstream_available_since')
    if recovered is not None and not isinstance(recovered, (int, float)):
        return None
    return {'fallback_started_at': float(state['fallback_started_at']),
            'upstream_available_since': float(recovered) if recovered is not None else None}


def save_fallback_state(state):
    if FALLBACK_STATE.is_symlink():
        raise ValueError('Refusing a symlink at the hotspot fallback state path')
    fd = os.open(FALLBACK_STATE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump(state, stream)
        stream.write('\n')
    FALLBACK_STATE.chmod(0o600)


def clear_fallback_state():
    if FALLBACK_STATE.is_symlink():
        raise ValueError('Refusing a symlink at the hotspot fallback state path')
    FALLBACK_STATE.unlink(missing_ok=True)


def hotspot_clients():
    device = selected_device()
    if not device:
        return None
    result = run([IW, 'dev', device, 'station', 'dump'], check=False)
    if result.returncode:
        return None
    return len(re.findall(r'^Station\s+[0-9a-fA-F:]+\s', result.stdout, re.M))


def unescape_nmcli_field(value):
    output = []
    escaped = False
    replacements = {'n': '\n', 'r': '\r', ':': ':', '\\': '\\'}
    for char in value:
        if escaped:
            output.append(replacements.get(char, char))
            escaped = False
        elif char == '\\':
            escaped = True
        else:
            output.append(char)
    if escaped:
        output.append('\\')
    return ''.join(output)


def available_upstreams(*, hotspot_active=False):
    available = []
    if ethernet_carrier():
        available.append('Ethernet')
    wanted = set(configured_upstreams())
    if not wanted:
        return available, False
    profiles = run(['nmcli', '-t', '-f', 'UUID,TYPE', 'connection', 'show'], check=False)
    active_profiles = run(['nmcli', '-t', '-f', 'UUID,TYPE', 'connection', 'show', '--active'], check=False)
    if profiles.returncode or active_profiles.returncode:
        return available, True
    saved = {}
    for line in profiles.stdout.splitlines():
        fields = line.split(':', 1)
        if len(fields) != 2 or fields[1] != '802-11-wireless':
            continue
        result = run(['nmcli', '-g', 'connection.autoconnect,802-11-wireless.ssid', 'connection', 'show', 'uuid', fields[0]], check=False)
        if result.returncode:
            return available, True
        values = result.stdout.splitlines()
        if len(values) >= 2 and values[1].strip():
            saved[fields[0]] = (values[1].strip(), values[0].strip().lower() in {'yes', 'true', '1'})
    active_uuids = {line.split(':', 1)[0] for line in active_profiles.stdout.splitlines()
                    if line.split(':', 1)[-1] == '802-11-wireless'}
    trusted = {ssid for uuid, (ssid, _) in saved.items() if ssid in wanted and uuid in active_uuids}
    wanted_saved = {ssid for ssid, autoconnect in saved.values() if ssid in wanted and autoconnect}
    if not wanted_saved:
        return available, False
    ap_device = selected_device() if hotspot_active else None
    for item in wifi_devices():
        device = item['device']
        if device == ap_device:
            continue
        if item['state'] == 'unavailable':
            continue
        result = run(['nmcli', '-g', 'SSID', 'device', 'wifi', 'list', '--rescan', 'auto', 'ifname', device], check=False)
        if result.returncode:
            return available, True
        visible = {unescape_nmcli_field(line) for line in result.stdout.splitlines()}
        available.extend(sorted(wanted_saved & visible))
    available.extend(sorted(trusted))
    return list(dict.fromkeys(available)), False


def status():
    devices = wifi_devices()
    for item in devices:
        item['ap_supported'] = ap_supported(item['device'])
    connections = run(['nmcli', '-t', '--escape', 'no', '-f', 'NAME', 'connection', 'show', '--active'], check=False)
    if connections.returncode:
        raise ValueError('Hotspot status unavailable: NetworkManager could not read active connections')
    active = 'cyberdeck-hotspot' in connections.stdout.splitlines()
    upstreams, upstream_scan_unknown = available_upstreams(hotspot_active=active)
    return {'wifi': ', '.join(item['device'] for item in devices) if devices else 'unavailable',
            'wifi_devices': devices, 'selected_device': selected_device(),
            'ssid': hotspot_ssid(),
            'ethernet_carrier': ethernet_carrier(), 'active': active,
            'ap_supported': any(item['ap_supported'] for item in devices), 'configured': PROFILE.is_file() and not PROFILE.is_symlink(),
            'autostart': AUTOSTART.exists() and not AUTOSTART_PAUSED.exists(),
            'redundancy_minutes': redundancy_minutes(),
            'upstream_ssids': configured_upstreams(), 'available_upstreams': upstreams,
            'upstream_scan_unknown': upstream_scan_unknown}


def configure(payload):
    ssid, password = payload.get('ssid', ''), payload.get('password', '')
    device = payload.get('device', '')
    upstream_ssids = payload.get('upstream_ssids', [])
    redundancy = payload.get('redundancy_minutes', DEFAULT_REDUNDANCY_MINUTES)
    if isinstance(redundancy, bool) or not isinstance(redundancy, int) or not 1 <= redundancy <= 1440:
        raise ValueError('Hotspot allowed redundancy time must be between 1 and 1440 minutes')
    if not isinstance(ssid, str) or not re.fullmatch(r'[A-Za-z0-9 _.-]{1,32}', ssid):
        raise ValueError('SSID must use 1–32 letters, digits, spaces, dots, dashes, or underscores')
    if not isinstance(password, str) or not re.fullmatch(r'[A-Za-z0-9._-]{8,63}', password):
        raise ValueError('Password must use 8–63 letters, digits, dots, dashes, or underscores')
    available = {item['device'] for item in wifi_devices()}
    if not isinstance(device, str) or device not in available:
        raise ValueError('Select an available Wi-Fi adapter')
    if not ap_supported(device):
        raise ValueError('The selected Wi-Fi adapter does not report access-point mode support')
    if not isinstance(upstream_ssids, list) or len(upstream_ssids) > 16 or any(
            not isinstance(ssid, str) or not ssid or len(ssid.encode('utf-8')) > 32 or
            any(ord(char) < 32 or ord(char) == 127 for char in ssid)
            for ssid in upstream_ssids):
        raise ValueError('Enter up to 16 upstream Wi-Fi SSIDs, one per line (1–32 bytes, no control characters)')
    upstream_ssids = list(dict.fromkeys(upstream_ssids))
    for path in (PROFILE, UPSTREAMS, REDUNDANCY_MINUTES, AUTOSTART, AUTOSTART_PAUSED):
        if path.is_symlink():
            raise ValueError('Refusing a symlink at a hotspot configuration path')
    PROFILE.parent.mkdir(parents=True, exist_ok=True)
    profile = ('[connection]\nid=cyberdeck-hotspot\nuuid=' + str(uuid.uuid4()) +
               '\ninterface-name=' + device +
               '\ntype=wifi\nautoconnect=false\n\n[wifi]\nmode=ap\nssid=' + ssid +
               '\nband=bg\n\n[wifi-security]\nkey-mgmt=wpa-psk\npsk=' + password +
               '\n\n[ipv4]\nmethod=shared\n\n[ipv6]\nmethod=ignore\n')
    fd = os.open(PROFILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        stream.write(profile)
    PROFILE.chmod(0o600)
    run(['nmcli', 'connection', 'reload'])
    upstream_fd = os.open(UPSTREAMS, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(upstream_fd, 'w', encoding='utf-8') as stream:
        json.dump(upstream_ssids, stream, ensure_ascii=False)
        stream.write('\n')
    UPSTREAMS.chmod(0o600)
    redundancy_fd = os.open(REDUNDANCY_MINUTES, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(redundancy_fd, 'w', encoding='ascii') as stream:
        stream.write(str(redundancy) + '\n')
    REDUNDANCY_MINUTES.chmod(0o600)
    if payload.get('autostart') is True:
        AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
        AUTOSTART.write_text('enabled\n', encoding='ascii')
        AUTOSTART.chmod(0o600)
        AUTOSTART_PAUSED.unlink(missing_ok=True)
    else:
        AUTOSTART.unlink(missing_ok=True)
        AUTOSTART_PAUSED.unlink(missing_ok=True)
    return {'saved': True, 'autostart': AUTOSTART.exists(), 'redundancy_minutes': redundancy}


def hotspot_up():
    if PROFILE.is_symlink():
        raise ValueError('Refusing a symlink at the NetworkManager hotspot profile')
    if not PROFILE.is_file():
        raise ValueError('Hotspot is not configured. Save an SSID and password first.')
    device = selected_device()
    if not device:
        raise ValueError('Hotspot adapter is not set. Save hotspot settings and choose a Wi-Fi adapter first.')
    selected = next((item for item in wifi_devices() if item['device'] == device), None)
    if not selected:
        raise ValueError('The selected Wi-Fi adapter is not available')
    state = selected.get('state', 'unknown').lower()
    if state in {'unavailable', 'unmanaged'}:
        raise ValueError(f"Wi-Fi adapter {device} is {state} in NetworkManager. Check its radio block, driver, and NetworkManager management state.")
    if not ap_supported(device):
        raise ValueError('The selected Wi-Fi adapter does not report access-point mode support')
    host_identity.prepare_dns(device)
    result = run(['nmcli', 'connection', 'up', 'id', 'cyberdeck-hotspot', 'ifname', device], check=False)
    if result.returncode:
        raise ValueError(result.stderr.strip() or 'NetworkManager could not activate the hotspot profile')
    return result.stdout


def hotspot_autostart():
    if HOTSPOT_MODULE_DISABLED.exists():
        return {'active': False, 'reason': 'Hotspot module is disabled'}
    if not PROFILE.is_file() or PROFILE.is_symlink():
        return {'active': False, 'reason': 'hotspot profile is not configured'}
    active = any('cyberdeck-hotspot' in line for line in run(['nmcli', '-t', '-f', 'NAME', 'connection', 'show', '--active'], check=False).stdout.splitlines())
    if not active and (not AUTOSTART.exists() or AUTOSTART_PAUSED.exists()):
        return {'active': False, 'reason': 'automatic start is disabled'}
    state = fallback_state() if active else None
    if active and state is None:
        return {'active': True, 'reason': 'hotspot is already active; no automatic fallback is being timed'}
    upstreams, unknown = available_upstreams(hotspot_active=active)
    if unknown:
        return {'active': active, 'reason': 'upstream scan failed; leaving hotspot state unchanged'}
    if upstreams:
        if not active:
            clear_fallback_state()
            return {'active': False, 'reason': 'upstream available: ' + ', '.join(upstreams)}
        now = time.time()
        if state['upstream_available_since'] is None:
            state['upstream_available_since'] = now
            save_fallback_state(state)
        clients = hotspot_clients()
        elapsed = now - state['upstream_available_since']
        timeout = redundancy_minutes() * 60
        if clients == 0 or elapsed >= timeout:
            result = run(['nmcli', 'connection', 'down', 'id', 'cyberdeck-hotspot'], check=False)
            if result.returncode == 0:
                clear_fallback_state()
                reason = 'upstream available and no hotspot clients remain' if clients == 0 else 'hotspot redundancy time expired'
                return {'active': False, 'reason': reason}
            return {'active': True, 'reason': result.stderr.strip() or 'could not stop hotspot'}
        remaining = max(1, int((timeout - elapsed + 59) // 60))
        return {'active': True, 'reason': f'upstream available; hotspot clients connected; {remaining} redundancy minutes remain'}
    if active:
        if state['upstream_available_since'] is not None:
            state['upstream_available_since'] = None
            save_fallback_state(state)
        return {'active': True, 'reason': 'hotspot is providing fallback while upstreams are unavailable'}
    clear_fallback_state()
    hotspot_up()
    save_fallback_state({'fallback_started_at': time.time(), 'upstream_available_since': None})
    return {'active': True, 'reason': 'all configured upstreams are unavailable; hotspot fallback started'}


def hotspot_stop():
    result = run(['nmcli', 'connection', 'down', 'id', 'cyberdeck-hotspot'], check=False)
    if AUTOSTART.exists():
        AUTOSTART_PAUSED.parent.mkdir(parents=True, exist_ok=True)
        if AUTOSTART_PAUSED.is_symlink():
            raise ValueError('Refusing a symlink at the hotspot auto-start pause setting')
        AUTOSTART_PAUSED.write_text('paused by administrator\n', encoding='ascii')
        AUTOSTART_PAUSED.chmod(0o600)
    clear_fallback_state()
    return {'stopped': result.returncode == 0}


def hotspot_module_set_enabled(enabled):
    if type(enabled) is not bool:
        raise ValueError('Hotspot module state must be a boolean')
    if HOTSPOT_MODULE_DISABLED.is_symlink():
        raise ValueError('Refusing a symlink at the Hotspot module setting')
    if enabled:
        HOTSPOT_MODULE_DISABLED.unlink(missing_ok=True)
        return {'enabled': True}
    HOTSPOT_MODULE_DISABLED.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(HOTSPOT_MODULE_DISABLED, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'w', encoding='ascii') as stream:
        stream.write('disabled\n')
    result = run(['nmcli', 'connection', 'down', 'id', 'cyberdeck-hotspot'], check=False)
    clear_fallback_state()
    return {'enabled': False, 'stopped': result.returncode == 0}


def hotspot_start_manual():
    clear_fallback_state()
    hotspot_up()
    return {'started': True}


def cyberchef_installed():
    """Accept only a marked static module before allowing its service to run."""
    marker = CYBERCHEF_ROOT / 'cyberdeck-module.json'
    if (CYBERCHEF_ROOT.is_symlink() or marker.is_symlink() or
            not CYBERCHEF_ROOT.is_dir() or not (CYBERCHEF_ROOT / 'index.html').is_file() or
            not marker.is_file()):
        return False
    try:
        metadata = json.loads(marker.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return (isinstance(metadata, dict) and metadata.get('name') == 'cyberchef' and
            bool(re.fullmatch(r'[a-f0-9]{40}', str(metadata.get('build', '')))) and
            bool(re.fullmatch(r'[a-f0-9]{64}', str(metadata.get('archive_sha256', '')))))


def cyberchef_status():
    installed = cyberchef_installed()
    if not installed:
        return {'installed': False, 'enabled': False, 'active': False}
    enabled = run(['systemctl', 'is-enabled', '--quiet', CYBERCHEF_SERVICE], check=False).returncode == 0
    active = run(['systemctl', 'is-active', '--quiet', CYBERCHEF_SERVICE], check=False).returncode == 0
    return {'installed': True, 'enabled': enabled, 'active': active}


def cyberchef_set_enabled(enabled):
    if type(enabled) is not bool:
        raise ValueError('CyberChef state must be a boolean')
    if not cyberchef_installed():
        raise ValueError('CyberChef is not installed or its marker is invalid')
    action = ['enable', '--now'] if enabled else ['disable', '--now']
    run(['systemctl', *action, CYBERCHEF_SERVICE])
    return cyberchef_status()


def firewall_conflicts():
    """Find other host firewall managers that would compete with our base chain."""
    conflicts = []
    for unit in ('ufw.service', 'firewalld.service', 'nftables.service'):
        result = run(['systemctl', 'is-active', '--quiet', unit], check=False)
        if result.returncode == 0:
            conflicts.append(unit)
    if Path(NFT).is_file():
        ruleset = run([NFT, 'list', 'ruleset'], check=False).stdout
        other_rules = re.sub(r'(?ms)^table inet cyberdeck \{.*?^\}\s*', '', ruleset)
        if 'hook input' in other_rules and 'nftables.service' not in conflicts:
            conflicts.append('existing nftables input rules')
    return conflicts


def firewall_status():
    conflicts = firewall_conflicts()
    state_unsafe = FIREWALL_ENABLED.is_symlink()
    available = Path(NFT).is_file() and not conflicts and not state_unsafe
    enabled = FIREWALL_ENABLED.is_file() and not FIREWALL_ENABLED.is_symlink()
    active = False
    if Path(NFT).is_file():
        active = run([NFT, 'list', 'table', 'inet', 'cyberdeck'], check=False).returncode == 0
    reason = None
    if not Path(NFT).is_file():
        reason = 'nftables is not installed'
    elif conflicts:
        reason = 'another firewall manager or input ruleset is active: ' + ', '.join(conflicts)
    elif state_unsafe:
        reason = 'Cyberdeck firewall state path is a symlink'
    return {'available': available, 'enabled': enabled, 'active': active,
            'conflicts': conflicts, 'reason': reason}


def firewall_ssh_ports():
    """Preserve active SSH listeners when the managed default-deny chain loads."""
    result = run(['/usr/bin/ss', '-H', '-ltnp'], check=False)
    ports = set()
    for line in result.stdout.splitlines():
        if 'sshd' not in line:
            continue
        fields = line.split()
        if len(fields) < 4:
            continue
        endpoint = fields[3]
        port = endpoint.rsplit(':', 1)[-1]
        if port.isdecimal() and 1 <= int(port) <= 65535:
            ports.add(int(port))
    return ports or {22}


def firewall_load():
    """Apply a dedicated nftables input policy without flushing other tables."""
    if FIREWALL_ENABLED.is_symlink() or not FIREWALL_ENABLED.is_file():
        raise ValueError('Cyberdeck firewall module is not enabled')
    if not Path(NFT).is_file():
        raise ValueError('nftables is not installed')
    conflicts = firewall_conflicts()
    if conflicts:
        raise ValueError('Refusing to replace rules while another firewall manager is active: ' +
                         ', '.join(conflicts))
    run([NFT, 'delete', 'table', 'inet', 'cyberdeck'], check=False)
    tcp_ports = sorted(firewall_ssh_ports() | {80, 443, 8445})
    rules = '\n'.join((
        'add table inet cyberdeck',
        'add chain inet cyberdeck input { type filter hook input priority -10; policy drop; }',
        'add rule inet cyberdeck input iifname "lo" accept',
        'add rule inet cyberdeck input ct state established,related accept',
        'add rule inet cyberdeck input meta l4proto { icmp, ipv6-icmp } accept',
        'add rule inet cyberdeck input tcp dport { ' + ', '.join(map(str, tcp_ports)) + ' } accept',
        'add rule inet cyberdeck input tcp dport 53 accept',
        'add rule inet cyberdeck input udp dport { 53, 67, 68 } accept',
        ''))
    result = subprocess.run([NFT, '-f', '-'], input=rules, check=False,
                            text=True, capture_output=True, timeout=20)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or 'Could not load Cyberdeck nftables rules')
    return firewall_status()


def firewall_remove():
    """Remove only the Cyberdeck-owned nftables table."""
    if not Path(NFT).is_file():
        return {'active': False}
    result = run([NFT, 'delete', 'table', 'inet', 'cyberdeck'], check=False)
    if result.returncode and 'No such file' not in result.stderr:
        raise RuntimeError(result.stderr.strip() or 'Could not remove Cyberdeck firewall rules')
    return {'active': False}


def firewall_set_enabled(enabled):
    if type(enabled) is not bool:
        raise ValueError('Firewall state must be a boolean')
    if FIREWALL_ENABLED.is_symlink():
        raise ValueError('Refusing a symlink at the Cyberdeck firewall state path')
    if enabled:
        status = firewall_status()
        if not status['available']:
            raise ValueError(status['reason'] or 'Cyberdeck firewall is unavailable')
        FIREWALL_ENABLED.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(FIREWALL_ENABLED, os.O_WRONLY | os.O_CREAT | os.O_TRUNC |
                             getattr(os, 'O_NOFOLLOW', 0), 0o600)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, 'w', encoding='ascii') as marker:
            marker.write('enabled\n')
        try:
            run(['systemctl', 'enable', '--now', FIREWALL_SERVICE])
        except (OSError, subprocess.SubprocessError):
            run(['systemctl', 'disable', '--now', FIREWALL_SERVICE], check=False)
            FIREWALL_ENABLED.unlink(missing_ok=True)
            raise
    else:
        run(['systemctl', 'disable', '--now', FIREWALL_SERVICE], check=False)
        firewall_remove()
        FIREWALL_ENABLED.unlink(missing_ok=True)
    return firewall_status()


def main():
    action = sys.argv[1] if len(sys.argv) == 2 else ''
    payload_actions = {'hotspot-configure', 'hostname-configure',
                       'storage-adopt', 'storage-initialize', 'storage-use-existing',
                       'storage-migration-preview', 'storage-migrate'}
    raw = sys.stdin.read(16385) if action in payload_actions else '{}'
    if len(raw) > 16384:
        raise ValueError('Configuration request is too large')
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError('Expected a JSON object')
    allowed = {
        'hotspot-status': lambda: status(),
        'hostname-status': host_identity.hostname_status,
        'hostname-configure': lambda: host_identity.request_hostname(payload),
        'cyberchef-status': cyberchef_status,
        'cyberchef-enable': lambda: cyberchef_set_enabled(True),
        'cyberchef-disable': lambda: cyberchef_set_enabled(False),
        'firewall-status': firewall_status,
        'firewall-enable': lambda: firewall_set_enabled(True),
        'firewall-disable': lambda: firewall_set_enabled(False),
        'firewall-load': firewall_load,
        'firewall-remove': firewall_remove,
        'hotspot-password': lambda: {'password': hotspot_password()},
        'hotspot-configure': lambda: configure(payload),
        'hotspot-start': lambda: hotspot_start_manual(),
        'hotspot-stop': lambda: hotspot_stop(),
        'hotspot-autostart': lambda: hotspot_autostart(),
        'hotspot-module-enable': lambda: hotspot_module_set_enabled(True),
        'hotspot-module-disable': lambda: hotspot_module_set_enabled(False),
        'storage-list': lambda: storage_operation('list', payload),
        'storage-adopt': lambda: storage_operation('adopt', payload),
        'storage-initialize': lambda: storage_operation('initialize', payload),
        'storage-use-existing': lambda: storage_operation('use-existing', payload),
        'storage-migration-preview': lambda: storage_operation('migration-preview', payload),
        'storage-migrate': lambda: storage_operation('migrate', payload),
        'power-reboot': lambda: (run(['systemctl', 'reboot']), {'accepted': True})[1],
        'power-poweroff': lambda: (run(['systemctl', 'poweroff']), {'accepted': True})[1],
    }
    if action not in allowed:
        raise SystemExit('Unsupported operation')
    if action in {'hotspot-configure', 'hotspot-start', 'hotspot-stop', 'hotspot-autostart',
                  'hotspot-module-enable', 'hotspot-module-disable'}:
        with host_identity.change_lock():
            result = allowed[action]()
    elif action in {'firewall-enable', 'firewall-disable'}:
        with host_identity.change_lock():
            result = allowed[action]()
    else:
        result = allowed[action]()
    print(json.dumps(result))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
