#!/usr/bin/env python3
"""Install or replace the pinned static CyberChef module on a Debian Hub host."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

VERSION = 'v11.5.0'
BUILD = '8cd426dd4f40f1423912d5fad91b578a86a65112'
ARCHIVE_URL = f'https://github.com/gchq/CyberChef/releases/download/{VERSION}/CyberChef_{BUILD}.zip'
ARCHIVE_SHA256 = 'f6478925d3eaa16ec08626a85f5b85eed10d531a5e18700615fed7ecb024cccf'
ENVIRONMENT = Path('/etc/cyberdeck/environment')
CERTIFICATE = Path('/etc/cyberdeck/tls/server.crt')
CA_CERTIFICATE = Path('/etc/cyberdeck/tls/ca.crt')
MODULES_ROOT = Path('/opt/cyberdeck/modules')
MODULE_ROOT = MODULES_ROOT / 'cyberchef'
REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_SOURCE = REPO_ROOT / 'app/cyberchef_server.py'
SERVICE_SOURCE = REPO_ROOT / 'config/debian/systemd/cyberdeck-cyberchef.service'
SERVER_DESTINATION = Path('/usr/local/lib/cyberdeck/app/cyberchef_server.py')
SERVICE_DESTINATION = Path('/etc/systemd/system/cyberdeck-cyberchef.service')
PORT = 8445
MAX_ARCHIVE_BYTES = 256 * 1024**2
MAX_EXPANDED_BYTES = 1024 * 1024**2
MAX_ARCHIVE_FILES = 20_000


def fail(message: str) -> None:
    raise SystemExit(f'ERROR: {message}')


def is_root() -> bool:
    """Return whether this process has root privileges on a Unix host."""
    get_euid = getattr(os, 'geteuid', None)
    return get_euid is not None and get_euid() == 0


def read_environment() -> dict[str, str]:
    if ENVIRONMENT.is_symlink():
        fail(f'Refusing symlinked Hub environment file: {ENVIRONMENT}')
    try:
        lines = ENVIRONMENT.read_text(encoding='utf-8').splitlines()
    except OSError as error:
        fail(f'Cannot read {ENVIRONMENT}: {error}')
    values = {}
    for line in lines:
        if not line or line.lstrip().startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        values[key] = value
    return values


def check_host(hostname: str) -> None:
    settings = read_environment()
    if settings.get('CYBERDECK_RUNTIME_MODE') not in {'debian', 'headless'}:
        fail('CyberChef is available only on a full Debian/headless installation.')
    configured = settings.get('CYBERDECK_HOSTNAME', '').strip().lower().rstrip('.')
    if hostname != configured:
        fail('CyberChef must use the configured Hub hostname and its existing TLS certificate.')
    if (not hostname or not hostname.isascii() or len(hostname) > 253 or not all(
            part and len(part) <= 63 and part[0].isalnum() and part[-1].isalnum() and
            all(char.isalnum() or char == '-' for char in part)
            for part in hostname.split('.'))):
        fail('The configured Hub hostname is not valid for TLS verification.')
    for command in (
            ['openssl', 'verify', '-CAfile', str(CA_CERTIFICATE),
             '-verify_hostname', hostname, str(CERTIFICATE)],
            ['openssl', 'x509', '-in', str(CERTIFICATE), '-noout', '-checkhost', hostname]):
        result = subprocess.run(command, text=True, capture_output=True, timeout=10)
        if result.returncode:
            fail(f'The Hub TLS certificate does not cover {hostname}; repair the Hub certificate before installing CyberChef.')


def check_port_available() -> None:
    """Refuse to replace files if another service owns the CyberChef port."""
    result = subprocess.run(['ss', '-ltnH', '( sport = :8445 )'],
                            text=True, capture_output=True, timeout=10)
    if result.returncode:
        fail(result.stderr.strip() or 'Unable to check whether HTTPS port 8445 is available.')
    if not result.stdout.strip():
        return
    service = subprocess.run(['systemctl', 'is-active', '--quiet',
                              'cyberdeck-cyberchef.service'],
                             text=True, capture_output=True, timeout=10)
    if service.returncode:
        fail('HTTPS port 8445 is already used by another service; refusing to replace CyberChef files.')


def download_archive(destination: Path) -> None:
    request = urllib.request.Request(ARCHIVE_URL, headers={'User-Agent': 'Cyberdeck-Hub-module-installer/1'})
    try:
        with urllib.request.urlopen(request, timeout=45) as response, destination.open('wb') as output:
            total = 0
            while block := response.read(1024 * 1024):
                total += len(block)
                if total > MAX_ARCHIVE_BYTES:
                    fail('Upstream archive exceeds the configured download limit.')
                output.write(block)
    except OSError as error:
        fail(f'Unable to download the pinned CyberChef archive: {error}')


def check_archive(path: Path) -> None:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    if digest.hexdigest() != ARCHIVE_SHA256:
        fail('CyberChef archive SHA-256 does not match the pinned upstream value.')


def extract_archive(path: Path, destination: Path) -> None:
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as error:
        fail(f'CyberChef archive is not a readable ZIP file: {error}')
    with archive:
        entries = archive.infolist()
        if len(entries) > MAX_ARCHIVE_FILES:
            fail('CyberChef archive contains too many files.')
        expanded = 0
        normalized = []
        for entry in entries:
            name = entry.filename
            relative = PurePosixPath(name)
            if (not name or name.startswith('/') or '\\' in name or
                    any(part in {'', '.', '..'} for part in relative.parts)):
                fail(f'Unsafe path in CyberChef archive: {name!r}')
            mode = entry.external_attr >> 16
            if stat.S_ISLNK(mode):
                fail(f'Symlinks are not allowed in the CyberChef archive: {name!r}')
            expanded += entry.file_size
            if expanded > MAX_EXPANDED_BYTES:
                fail('CyberChef archive expands beyond the configured size limit.')
            normalized.append((entry, relative.parts))

        # The upstream ZIP may package its web root inside wrapper folders.
        # Accept that layout, and the older standalone CyberChef*.html name,
        # while rejecting ambiguous or mixed-root archives.
        html_entries = [(entry, parts) for entry, parts in normalized
                        if not entry.is_dir() and parts[-1].lower() == 'index.html']
        rename_index = False
        if not html_entries:
            html_entries = [(entry, parts) for entry, parts in normalized
                            if not entry.is_dir() and
                            parts[-1].lower().startswith('cyberchef') and
                            parts[-1].lower().endswith('.html')]
            rename_index = True
        if not html_entries:
            fail('CyberChef archive must contain one index.html or standalone CyberChef HTML file.')
        shallowest = min(len(parts) for _, parts in html_entries)
        html_entries = [(entry, parts) for entry, parts in html_entries
                        if len(parts) == shallowest]
        if len(html_entries) != 1:
            fail('CyberChef archive has multiple equally shallow application entry pages.')
        index_parts = html_entries[0][1]
        wrapper = index_parts[:-1]
        normalized_paths = set()
        for entry, parts in normalized:
            if wrapper:
                if parts[:len(wrapper)] != wrapper:
                    if entry.is_dir() and wrapper[:len(parts)] == parts:
                        continue
                    fail('CyberChef archive mixes files outside its web-root folder.')
                parts = parts[len(wrapper):]
                if not parts:
                    continue
            if rename_index and entry.filename and PurePosixPath(entry.filename).parts == index_parts:
                parts = ('index.html',)
            elif not rename_index and parts[-1].lower() == 'index.html':
                # ZIPs produced on case-insensitive systems may retain an
                # uppercase spelling. The Hub serves the canonical lowercase
                # path, so normalize it while extracting.
                parts = (*parts[:-1], 'index.html')
            if not parts:
                fail(f'Unsafe empty path in CyberChef archive: {entry.filename!r}')
            if parts in normalized_paths:
                fail(f'CyberChef archive has duplicate paths after unpacking: {entry.filename!r}')
            normalized_paths.add(parts)
            target = destination.joinpath(*parts)
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entry) as source, target.open('xb') as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            target.chmod(0o644)
        index = destination / 'index.html'
        if not index.is_file():
            root_entries = ', '.join(sorted(child.name for child in destination.iterdir())[:12])
            fail('The extracted CyberChef web root has no index.html; '
                 f'top-level entries: {root_entries or "(empty)"}.')
        (destination / 'cyberdeck-module.json').write_text(json.dumps({
            'name': 'cyberchef', 'build': BUILD, 'archive_sha256': ARCHIVE_SHA256,
            'source': ARCHIVE_URL,
        }, indent=2) + '\n', encoding='utf-8')


def install(archive_arg: Path | None, replace: bool, enable: bool = False) -> None:
    if not is_root():
        fail('Run --apply with sudo on the Debian Hub host.')
    if archive_arg is not None:
        if archive_arg.is_symlink() or not archive_arg.is_file():
            fail('--archive must name a regular, non-symlink ZIP file.')
        try:
            source = archive_arg.resolve(strict=True)
        except OSError as error:
            fail(f'Cannot resolve --archive: {error}')
    else:
        source = None
    hostname = read_environment().get('CYBERDECK_HOSTNAME', '')
    if not hostname:
        fail('Run the Debian Hub installer first so CyberChef can use its hostname and TLS certificate.')
    check_host(hostname)
    if any(path.is_symlink() for path in
           (Path('/opt/cyberdeck'), MODULES_ROOT, MODULE_ROOT, SERVER_SOURCE,
            SERVICE_SOURCE, SERVER_DESTINATION, SERVICE_DESTINATION)):
        fail('Refusing symlinked CyberChef installation paths.')
    for path in (SERVER_DESTINATION.parent, SERVICE_DESTINATION.parent):
        if path.is_symlink():
            fail(f'Refusing symlinked CyberChef destination directory: {path}')
    if not SERVER_SOURCE.is_file() or not SERVICE_SOURCE.is_file():
        fail('The CyberChef HTTPS server and systemd service sources are missing.')
    check_port_available()
    for directory in (Path('/opt/cyberdeck'), MODULES_ROOT):
        directory.mkdir(parents=True, exist_ok=True, mode=0o755)
        os.chown(directory, 0, 0)
        directory.chmod(0o755)
    MODULES_ROOT.mkdir(parents=True, exist_ok=True)
    previous = MODULES_ROOT / 'cyberchef.previous'
    if MODULE_ROOT.exists() and not replace:
        fail(f'{MODULE_ROOT} already exists; use --replace to preserve it as cyberchef.previous.')
    if previous.exists():
        fail(f'{previous} already exists; move it aside before replacing the module.')
    with tempfile.TemporaryDirectory(prefix='.cyberchef-stage-', dir=MODULES_ROOT) as temporary:
        stage = Path(temporary) / 'cyberchef'
        stage.mkdir(mode=0o755)
        archive_path = source
        if archive_path is None:
            archive_path = Path(temporary) / 'cyberchef.zip'
            download_archive(archive_path)
        if archive_path.stat().st_size > MAX_ARCHIVE_BYTES:
            fail('CyberChef archive exceeds the configured download limit.')
        check_archive(archive_path)
        extract_archive(archive_path, stage)
        for folder, dirs, files in os.walk(stage):
            Path(folder).chmod(0o755)
            for filename in files:
                (Path(folder) / filename).chmod(0o644)
        if MODULE_ROOT.exists():
            MODULE_ROOT.rename(previous)
        try:
            stage.rename(MODULE_ROOT)
        except OSError:
            if previous.exists() and not MODULE_ROOT.exists():
                previous.rename(MODULE_ROOT)
            raise
    SERVER_DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SERVER_SOURCE, SERVER_DESTINATION)
    SERVER_DESTINATION.chmod(0o644)
    shutil.copyfile(SERVICE_SOURCE, SERVICE_DESTINATION)
    SERVICE_DESTINATION.chmod(0o644)
    result = subprocess.run(['systemctl', 'daemon-reload'], capture_output=True,
                            text=True, timeout=20)
    if result.returncode:
        fail(result.stderr.strip() or 'systemd could not reload the CyberChef service.')
    state_args = ['enable', '--now'] if enable else ['disable', '--now']
    result = subprocess.run(['systemctl', *state_args, 'cyberdeck-cyberchef.service'],
                            capture_output=True, text=True, timeout=30)
    if result.returncode:
        fail(result.stderr.strip() or 'The CyberChef service could not be left in the requested state.')
    print(f'CyberChef {BUILD} installed at {MODULE_ROOT}.')
    if enable:
        print(f'Open https://{hostname}:{PORT}/ from a client that trusts the Cyberdeck CA.')
    else:
        print('CyberChef is installed but disabled. Enable it in Admin when needed.')


def remove() -> None:
    if not is_root():
        fail('Run --remove --apply with sudo on the Debian Hub host.')
    if any(path.is_symlink() for path in
           (Path('/opt/cyberdeck'), MODULES_ROOT, MODULE_ROOT)):
        fail('Refusing to remove a symlinked CyberChef path.')
    marker = MODULE_ROOT / 'cyberdeck-module.json'
    if not marker.is_file() or marker.is_symlink():
        fail('Refusing to remove a directory without the Cyberdeck CyberChef marker.')
    try:
        metadata = json.loads(marker.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        fail(f'Cannot validate the installed CyberChef marker: {error}')
    if (not isinstance(metadata, dict) or metadata.get('name') != 'cyberchef' or
            metadata.get('build') != BUILD or metadata.get('archive_sha256') != ARCHIVE_SHA256):
        fail('Installed CyberChef marker does not match this installer; refusing removal.')
    subprocess.run(['systemctl', 'disable', '--now', 'cyberdeck-cyberchef.service'],
                   capture_output=True, text=True, timeout=30, check=False)
    shutil.rmtree(MODULE_ROOT)
    for path in (SERVICE_DESTINATION, SERVER_DESTINATION):
        if path.is_symlink():
            fail(f'Refusing symlinked CyberChef service file: {path}')
        path.unlink(missing_ok=True)
    subprocess.run(['systemctl', 'daemon-reload'], capture_output=True,
                   text=True, timeout=20, check=False)
    print('CyberChef static files and its service were removed. The Hub hostname and certificate are unchanged.')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Install the pinned release; preview is the default.')
    parser.add_argument('--archive', type=Path, help='Use a local copy of the pinned ZIP for offline installation.')
    parser.add_argument('--replace', action='store_true', help='Keep the current installation as cyberchef.previous when replacing it.')
    parser.add_argument('--enable', action='store_true', help='Start the service after installing; default is installed but disabled.')
    parser.add_argument('--remove', action='store_true', help='Preview removal; add --apply to remove the matching module files.')
    args = parser.parse_args()
    if args.remove:
        if args.archive or args.replace or args.enable:
            parser.error('--remove cannot be combined with --archive, --replace, or --enable.')
        if not args.apply:
            print('PREVIEW ONLY — no changes made.')
            print(f'Would remove the CyberChef module at {MODULE_ROOT} after validating its marker.')
            return 0
        remove()
        return 0
    if not args.apply:
        print('PREVIEW ONLY — no changes made.')
        print(f'Pinned release: {VERSION} ({BUILD})')
        print(f'Archive SHA-256: {ARCHIVE_SHA256}')
        print(f'Install path: {MODULE_ROOT}')
        print('Uses the Hub hostname and existing certificate on isolated HTTPS port 8445; no extra DNS record or certificate SAN is needed.')
        print('Default install state: module present, service disabled; Admin can enable it later.')
        print('The module is available only in full Debian/headless mode; container deployments use an operator-managed upstream image.')
        return 0
    install(args.archive, args.replace, args.enable)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
