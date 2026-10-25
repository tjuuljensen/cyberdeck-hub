#!/usr/bin/env python3
"""Bounded content acquisition and verified recovery copies; Python standard library only."""
import argparse
import datetime as dt
import hashlib
import html
from html.parser import HTMLParser
import http.client
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import ssl
import subprocess
import sys
import urllib.parse
import urllib.request

APP_ROOT = Path(__file__).resolve().parent
DEFAULT_SOURCE_ROOT = APP_ROOT.parent
REPO = Path(os.environ.get('CYBERDECK_SOURCE_ROOT', DEFAULT_SOURCE_ROOT)).resolve()
KIWIX_FIRST_PARTY_MIRROR = 'mirror.download.kiwix.org'
KIWIX_DOWNLOAD_HOSTS = {'download.kiwix.org', 'lb.download.kiwix.org', KIWIX_FIRST_PARTY_MIRROR}
TRANSFER_FIELDS = ('path', 'url', 'source_file', 'max_bytes', 'expected_bytes', 'sha256', 'url_resolver')


def safe_path(root, name):
    p = PurePosixPath(name)
    if not name or p.is_absolute() or '..' in p.parts or '\\' in name or ':' in name:
        raise ValueError(f'Unsafe relative path: {name}')
    root = Path(root).resolve()
    dest = root.joinpath(*p.parts)
    for part in [dest, *dest.parents]:
        if part == root:
            break
        if part.is_symlink():
            raise ValueError(f'Symlink refused: {part}')
    if not dest.resolve().is_relative_to(root):
        raise ValueError('Path escaped destination')
    return dest


def same_transfer_identity(previous, updated):
    """Allow labels/provenance to change while keeping payload identity pinned."""
    return all(previous.get(field) == updated.get(field) for field in TRANSFER_FIELDS)


def sha256(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def write_json(path, value):
    path = Path(path)
    tmp = path.with_name(path.name + '.tmp')
    if tmp.is_symlink() or path.is_symlink():
        raise ValueError('Refusing JSON symlink')
    tmp.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    os.replace(tmp, path)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def external_root(path):
    raw = Path(path).absolute()
    if raw.is_symlink():
        raise ValueError('Root must not be a symlink')
    root = raw.resolve()
    if root == Path(root.anchor) or root.is_relative_to(REPO):
        raise ValueError('Payload/recovery root must be outside the checkout and not filesystem root')
    return root


def validate_asset(asset):
    name = asset['path']
    if not re.fullmatch(r'(zim|public)/[A-Za-z0-9][A-Za-z0-9._-]*', name):
        raise ValueError(f'Expected flat public/ or zim/ filename: {name}')
    if type(asset['max_bytes']) is not int or asset['max_bytes'] <= 0:
        raise ValueError('Invalid per-file size ceiling')
    if 'expected_bytes' in asset and (type(asset['expected_bytes']) is not int or
                                      not 0 < asset['expected_bytes'] <= asset['max_bytes']):
        raise ValueError('Invalid expected byte count')
    digest = asset.get('sha256')
    if digest is not None and not re.fullmatch('[0-9a-fA-F]{64}', digest):
        raise ValueError('Invalid expected SHA-256')
    sources = int('url' in asset) + int('source_file' in asset) + int(asset.get('local_payload') is True)
    if sources != 1:
        raise ValueError('Specify exactly one URL, source file, or already-imported local payload')
    if 'url' in asset and urllib.parse.urlparse(asset['url']).scheme != 'https':
        raise ValueError('Downloads must use HTTPS')
    search_terms = asset.get('search_terms', '')
    if (not isinstance(search_terms, str) or len(search_terms) > 1000 or
            any(ord(char) < 32 and char not in '\t\r\n' for char in search_terms)):
        raise ValueError('Search terms must be at most 1000 characters of text')
    if 'url_resolver' in asset:
        page = urllib.parse.urlparse(asset.get('url', ''))
        if (asset['url_resolver'] != 'mediafire' or page.netloc != 'www.mediafire.com' or
                not re.fullmatch(r'/file/[a-z0-9]+/[^/]+/file', page.path) or
                page.query or page.fragment or not digest or not name.endswith('.pdf')):
            raise ValueError('MediaFire resolver requires a canonical HTTPS file page and pinned PDF hash')
    if 'source_file' in asset:
        src = safe_path(REPO, asset['source_file'])
        if not src.is_relative_to(REPO / 'assets'):
            raise ValueError('Local content must be under assets/')


class MediaFireLinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'a' and attrs.get('id') == 'downloadButton':
            self.links.append(attrs.get('href', ''))


def validate_resolved_url(asset, url):
    if asset.get('url_resolver') == 'mediafire':
        parsed = urllib.parse.urlparse(url)
        file_id = urllib.parse.urlparse(asset['url']).path.split('/')[2]
        if (parsed.scheme != 'https' or
                not re.fullmatch(r'download[0-9]+\.mediafire\.com', parsed.netloc) or
                f'/{file_id}/' not in parsed.path):
            raise ValueError('Refusing download outside the selected MediaFire file')


def download_url(asset):
    """Resolve the author's stable MediaFire page without saving expiring URLs."""
    if 'url_resolver' in asset:
        validate_asset(asset)
        request = urllib.request.Request(asset['url'], headers={'User-Agent': 'cyberdeck-library/1'})
        with urllib.request.urlopen(request, timeout=60) as response:
            if response.geturl() != asset['url']:
                raise ValueError('Unexpected MediaFire landing-page redirect')
            page = response.read(2_000_001)
        if len(page) > 2_000_000:
            raise ValueError('MediaFire landing page exceeds size ceiling')
        parser = MediaFireLinkParser()
        parser.feed(page.decode('utf-8'))
        if len(parser.links) != 1:
            raise ValueError('MediaFire download button missing or ambiguous; review publisher link')
        url = parser.links[0]
        validate_resolved_url(asset, url)
        return url
    parsed = urllib.parse.urlparse(asset['url'])
    if asset['path'].endswith('.zim') and parsed.hostname in KIWIX_DOWNLOAD_HOSTS:
        # Keep the manifest's acquisition identity stable while avoiding Kiwix's
        # load-balancer redirect to community mirrors. This is Kiwix's own mirror.
        return urllib.parse.urlunparse(parsed._replace(netloc=KIWIX_FIRST_PARTY_MIRROR))
    return asset['url']


def stream_download(asset, destination, cancel_check=None):
    if resumable(asset):
        resume_download(asset, destination, cancel_check=cancel_check)
        validate_payload(asset, destination)
        return
    limit = asset['max_bytes']
    if 'url' in asset:
        request = urllib.request.Request(download_url(asset), headers={'User-Agent': 'cyberdeck-library/1'})
        source = urllib.request.urlopen(request, timeout=60)
        final_url = urllib.parse.urlparse(source.geturl())
        original_url = urllib.parse.urlparse(asset['url'])
        if final_url.scheme != 'https':
            source.close()
            raise ValueError('Refusing non-HTTPS final download URL')
        try:
            validate_resolved_url(asset, source.geturl())
        except ValueError:
            source.close()
            raise
        if asset['path'].endswith('.zim') and original_url.hostname in KIWIX_DOWNLOAD_HOSTS:
            if final_url.hostname not in KIWIX_DOWNLOAD_HOSTS | {KIWIX_FIRST_PARTY_MIRROR}:
                source.close()
                raise ValueError('Refusing ZIM redirect outside the official Kiwix download domain')
    else:
        source = safe_path(REPO, asset['source_file']).open('rb')
    total = 0
    with source, destination.open('xb') as output:
        while True:
            if cancel_check and cancel_check():
                raise AcquisitionCancelled('Download canceled by administrator')
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise ValueError('Download exceeds configured size ceiling')
            output.write(chunk)
    validate_payload(asset, destination)


def validate_payload(asset, destination):
    total = destination.stat().st_size
    if total == 0:
        raise ValueError('Empty content file')
    if 'expected_bytes' in asset and total != asset['expected_bytes']:
        raise ValueError('Download differs from expected byte count')
    with destination.open('rb') as handle:
        magic = handle.read(8)
    if asset['path'].endswith('.zim') and magic[:4] != b'ZIM\x04':
        raise ValueError('Response is not a ZIM archive')
    if asset['path'].endswith('.pdf') and not magic.startswith(b'%PDF-'):
        raise ValueError('Response is not a PDF')


def resumable(asset):
    # Pinned bytes are essential: a mirror can change even without an ETag.
    return 'url' in asset and bool(asset.get('sha256')) and 'expected_bytes' in asset


def resume_state(asset, partial):
    metadata = partial.with_name(partial.name + '.json')
    if partial.is_symlink() or metadata.is_symlink():
        raise ValueError('Refusing resume symlink')
    state = None
    if metadata.exists():
        state = read_json(metadata)
        if not isinstance(state, dict) or state.get('version') != 1 or state.get('asset') != asset:
            raise ValueError(f'Resume metadata differs from manifest: {metadata}; preserve and inspect both partial files')
        etag = state.get('etag')
        if etag is not None and (not isinstance(etag, str) or not re.fullmatch(r'"[\x21\x23-\x7e]*"', etag)):
            raise ValueError('Invalid saved strong ETag')
    if partial.exists():
        if state is None or not partial.is_file():
            raise ValueError(f'Untracked partial: {partial}; no matching resume metadata')
        size = partial.stat().st_size
        if size > asset['expected_bytes']:
            raise ValueError(f'Partial exceeds expected size: {partial}')
        return size, state
    return 0, state


def resume_download(asset, partial, cancel_check=None):
    offset, state = resume_state(asset, partial)
    size = asset['expected_bytes']
    if offset == size:
        print('Complete partial found; verifying without network.', flush=True)
        return
    headers = {'User-Agent': 'cyberdeck-library/1', 'Accept-Encoding': 'identity'}
    if offset:
        headers['Range'] = f'bytes={offset}-'
        if state.get('etag'):
            headers['If-Range'] = state['etag']
        print(f'Resuming at {offset:,} of {size:,} bytes.', flush=True)
    request = urllib.request.Request(download_url(asset), headers=headers)
    with urllib.request.urlopen(request, timeout=60) as source:
        final_url = urllib.parse.urlparse(source.geturl())
        original_url = urllib.parse.urlparse(asset['url'])
        if final_url.scheme != 'https':
            raise ValueError('Refusing non-HTTPS final download URL')
        validate_resolved_url(asset, source.geturl())
        if asset['path'].endswith('.zim') and original_url.hostname in KIWIX_DOWNLOAD_HOSTS:
            if final_url.hostname not in KIWIX_DOWNLOAD_HOSTS | {KIWIX_FIRST_PARTY_MIRROR}:
                raise ValueError('Refusing ZIM redirect outside the official Kiwix download domain')
        if source.headers.get('Content-Encoding', 'identity').lower() != 'identity':
            raise ValueError('Encoded response cannot be resumed safely')
        if offset:
            if source.status != 206:
                raise ValueError('Server did not honor resume range; partial preserved, no automatic restart')
            match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', source.headers.get('Content-Range', ''))
            if not match or tuple(map(int, match.groups())) != (offset, size - 1, size):
                raise ValueError('Unexpected Content-Range; partial preserved')
        elif source.status != 200 or source.headers.get('Content-Range'):
            raise ValueError('Expected a complete HTTP 200 response for initial download')
        length = source.headers.get('Content-Length')
        if length is not None and (not length.isdigit() or int(length) != size - offset):
            raise ValueError('Unexpected Content-Length; partial preserved')
        etag = source.headers.get('ETag')
        strong = etag if etag and re.fullmatch(r'"[\x21\x23-\x7e]*"', etag) else None
        if offset and state.get('etag') and etag is not None and etag != state['etag']:
            raise ValueError('Remote ETag changed; partial preserved')
        if not offset:
            # Commit identity before the first byte; missing/changed metadata is never guessed.
            write_json(partial.with_name(partial.name + '.json'),
                       {'version': 1, 'asset': asset, 'etag': strong})
        mode = 'r+b' if partial.exists() else 'xb'
        with partial.open(mode) as output:
            output.seek(offset)
            total = offset
            while True:
                if cancel_check and cancel_check():
                    raise AcquisitionCancelled('Download canceled by administrator')
                chunk = source.read(min(1024 * 1024, size - total + 1))
                if not chunk:
                    break
                if total + len(chunk) > size:
                    raise ValueError('Response exceeds expected byte count; partial preserved')
                output.write(chunk)
                total += len(chunk)
            output.flush()
            os.fsync(output.fileno())
        if total != size:
            raise OSError(f'Interrupted download: {total:,} of {size:,} bytes retained; rerun the same command')


def partial_credit(root, asset):
    partial = safe_path(root, asset['path'] + '.part')
    if resumable(asset):
        return resume_state(asset, partial)[0]
    if partial.exists():
        raise ValueError(f'Old non-resumable partial exists: {partial}; inspect it explicitly')
    return 0


def verify_content(root, recover_missing=None, only=None):
    lock = read_json(safe_path(root, 'acquired.json'))
    if not lock:
        raise ValueError('Empty acquisition manifest')
    for name, record in lock.items():
        if only is not None and name not in only:
            continue
        path = safe_path(root, name)
        if (not path.exists() and recover_missing and name in recover_missing and
                same_transfer_identity(record.get('asset', {}), recover_missing[name])):
            continue
        if not path.is_file() or path.stat().st_size != record['bytes'] or sha256(path) != record['sha256']:
            raise ValueError(f'Content integrity failure: {name}')
    archive = safe_path(root, 'manifests')
    if archive.exists():
        for path in archive.iterdir():
            safe_path(root, 'manifests/' + path.name)
            if not path.is_file() or not re.fullmatch('[0-9a-f]{64}\\.json', path.name):
                raise ValueError('Unexpected acquisition manifest archive entry')
            if sha256(path) != path.stem:
                raise ValueError(f'Acquisition manifest integrity failure: {path.name}')
    return lock


def load_manifest(manifest):
    raw = Path(manifest).read_bytes()
    document = json.loads(raw)
    reserve = document.get('reserve_bytes', 1_000_000_000)
    if type(reserve) is not int or reserve < 1_000_000_000:
        raise ValueError('Reserve must be at least 1 GB')
    assets = document['assets']
    if not assets or len({a['path'] for a in assets}) != len(assets):
        raise ValueError('Empty or duplicate content paths')
    for asset in assets:
        validate_asset(asset)
    return raw, assets


def plan(manifest):
    """Read only the local manifest; no network, payload access or writes."""
    raw, assets = load_manifest(manifest)
    total = 0
    for asset in assets:
        size = asset.get('expected_bytes', asset['max_bytes'])
        total += size
        kind = 'expected' if 'expected_bytes' in asset else 'ceiling'
        print(f'{asset["title"]}: {size:,} bytes ({size / 1e9:.2f} GB; '
              f'{size / 2**30:.2f} GiB), {kind}')
    reserve = json.loads(raw).get('reserve_bytes', 1_000_000_000)
    required = sum(a['max_bytes'] for a in assets) + reserve
    print(f'Pack total: {total:,} bytes ({total / 1e9:.2f} GB; {total / 2**30:.2f} GiB).')
    print(f'Fresh install free-space gate: {required:,} bytes including reserve.')
    print('Backup needs all installed library data plus package cache and recovery source.')
    print('Preview only. No network requests, downloads or changes.')


def verify_manifest(root, manifest, missing_only=False):
    _, assets = load_manifest(manifest)
    requested = {asset['path'] for asset in assets} if missing_only else None
    lock = verify_content(root, only=requested)
    for asset in assets:
        if lock.get(asset['path'], {}).get('asset') != asset:
            raise ValueError(f'Manifest asset missing or changed: {asset["path"]}')
    return lock


class AcquisitionCancelled(Exception):
    """Signal a cooperative stop requested for one acquisition asset."""


def fetch(root, manifest, missing_only=False, continue_on_error=False, status_callback=None,
          cancel_check=None):
    def report_status(name, state, error=''):
        if status_callback:
            try:
                status_callback(name, state, error)
            except (OSError, ValueError, KeyError, json.JSONDecodeError) as status_error:
                print(f'Could not persist acquisition status for {name}: '
                      f'{type(status_error).__name__}', flush=True)

    root = external_root(root)
    raw, assets = load_manifest(manifest)
    root.mkdir(parents=True, exist_ok=True)
    lock_path = safe_path(root, 'acquired.json')
    manifest_assets = {asset['path']: asset for asset in assets}
    requested = set(manifest_assets) if missing_only else None
    lock = verify_content(root, recover_missing=manifest_assets, only=requested) if lock_path.exists() else {}
    metadata_changed = False
    acquisition_errors = []
    for asset in assets:
        name = asset['path']
        if name not in lock or lock[name]['asset'] == asset:
            continue
        if not same_transfer_identity(lock[name].get('asset', {}), asset):
            raise ValueError(f'Manifest changed file identity for {name}; use a new edition/path or preserve the old lock first')
        lock[name]['asset'] = asset
        metadata_changed = True
    if metadata_changed:
        write_json(lock_path, lock)
    if missing_only:
        print('Integrity scope: requested manifest only; unrelated library files were not scanned.', flush=True)
    missing_locked = {name for name in manifest_assets if name in lock and
                      not safe_path(root, name).exists()}
    missing = []
    for asset in assets:
        name = asset['path']
        if name in lock:
            if lock[name]['asset'] != asset:
                raise ValueError(f'Manifest changed for {name}; use a new edition/path or preserve the old lock first')
            if name not in missing_locked:
                report_status(name, 'downloaded')
                continue
            if asset.get('local_payload') is not True:
                print(f'Recorded content file is missing; reacquiring: {name}', flush=True)
            missing.append(asset)
            continue
        if safe_path(root, name).exists():
            dest = safe_path(root, name)
            partial = safe_path(root, name + '.part')
            metadata = safe_path(root, name + '.part.json')
            # Recover a crash between the verified rename and acquisition-record write.
            if not resumable(asset) or partial.exists() or not metadata.exists():
                raise ValueError(f'Untracked destination exists: {name}; inspect it before proceeding')
            resume_state(asset, partial)
            validate_payload(asset, dest)
            digest = sha256(dest)
            if digest.lower() != asset['sha256'].lower():
                raise ValueError(f'Untracked destination hash mismatch: {name}; preserved')
            dest.chmod(0o644)
            lock[name] = acquisition_record(asset, dest, digest)
            write_json(lock_path, lock)
            metadata.unlink()
            report_status(name, 'downloaded')
        else:
            missing.append(asset)
    unavailable = [asset['path'] for asset in missing if asset.get('local_payload') is True]
    if unavailable:
        raise ValueError('Imported local payload is missing and has no download source: ' + ', '.join(unavailable))
    reserve = json.loads(raw).get('reserve_bytes', 1_000_000_000)
    required = sum(a['max_bytes'] - partial_credit(root, a) for a in missing) + reserve
    if missing and shutil.disk_usage(root).free < required:
        raise ValueError(f'Insufficient free space for all missing assets plus reserve: {required:,} bytes required')
    # Preserve the exact requested manifest, including user-supplied external ones.
    # A saved request is provenance, not a marker that every download succeeded.
    snapshot = safe_path(root, 'manifests/' + hashlib.sha256(raw).hexdigest() + '.json')
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    if snapshot.exists():
        if snapshot.read_bytes() != raw:
            raise ValueError('Acquisition manifest snapshot differs from its hash')
    else:
        with snapshot.open('xb') as handle:
            handle.write(raw)
    for asset in assets:
        name = asset['path']
        dest = safe_path(root, name)
        expected = asset.get('sha256')
        if cancel_check and cancel_check(name):
            partial = safe_path(root, name + '.part')
            partial.unlink(missing_ok=True)
            partial.with_name(partial.name + '.json').unlink(missing_ok=True)
            report_status(name, 'canceled')
            continue
        if name in lock and name not in missing_locked:
            if lock[name]['asset'] != asset:
                raise ValueError(f'Manifest changed for {name}; use a new edition/path or preserve the old lock first')
            print(f'Already verified: {name}')
            continue
        if dest.exists():
            raise ValueError(f'Untracked destination exists: {name}; inspect it before proceeding')
        # Require headroom based on the configured bound, before writing anything large.
        if shutil.disk_usage(root).free < asset['max_bytes'] - partial_credit(root, asset) + reserve:
            raise ValueError('Insufficient free space for remaining file bytes plus reserve')
        dest.parent.mkdir(parents=True, exist_ok=True)
        partial = safe_path(root, name + '.part')
        can_resume = resumable(asset)
        try:
            report_status(name, 'downloading')
            print(f'Acquiring: {name}', flush=True)
            stream_download(asset, partial, cancel_check=(
                (lambda: cancel_check(name)) if cancel_check else None))
            if cancel_check and cancel_check(name):
                raise AcquisitionCancelled('Download canceled by administrator')
            digest = sha256(partial)
            if expected and digest.lower() != expected.lower():
                raise ValueError(f'Expected SHA-256 mismatch: {name}; inspect partial before retrying')
            os.replace(partial, dest)
            dest.chmod(0o644)
        except AcquisitionCancelled:
            partial.unlink(missing_ok=True)
            partial.with_name(partial.name + '.json').unlink(missing_ok=True)
            report_status(name, 'canceled')
            print(f'Canceled: {name}', flush=True)
            continue
        except (OSError, ValueError) as error:
            if not continue_on_error:
                raise
            acquisition_errors.append((name, str(error)))
            report_status(name, 'failed', str(error)[:500])
            print(f'Acquisition failed: {name}: {error}', flush=True)
            continue
        finally:
            if partial.exists() and not can_resume:
                partial.unlink()
        lock[name] = acquisition_record(asset, dest, digest)
        write_json(lock_path, lock)
        report_status(name, 'downloaded')
        metadata = safe_path(root, name + '.part.json')
        if can_resume and metadata.exists():
            metadata.unlink()
    links = ''.join(f'<li><a href="{html.escape(name.removeprefix("public/"))}">'
                    f'{html.escape(rec["asset"]["title"])}</a></li>'
                    for name, rec in lock.items() if name.startswith('public/'))
    index = safe_path(root, 'public/index.html')
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text('<!doctype html><html lang="en"><meta charset="utf-8">'
                     '<title>Cyberdeck library</title><h1>Cyberdeck library</h1>'
                     '<p><a id="kiwix" href="http://127.0.0.1:8080/">Open Kiwix</a></p>'
                     '<script>document.getElementById("kiwix").href = '
                     'location.protocol + "//" + location.hostname + ":8080/";</script>'
                     '<ul>' + links + '</ul><p>Public reference shelf on a trusted local network. '
                     'Search ZIMs in Kiwix; use PDF reader search for manuals.</p></html>\n', encoding='utf-8')
    if acquisition_errors:
        print(f'Acquisition finished with {len(acquisition_errors)} failed asset(s):', flush=True)
        for name, error in acquisition_errors:
            print(f'  {name}: {error}', flush=True)
    else:
        print('Acquisition complete. Saved hashes verify future copies, not publisher authenticity.')


def acquisition_record(asset, path, digest):
    return {'asset': asset, 'bytes': path.stat().st_size, 'sha256': digest,
            'acquired_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
            'verification': 'matched expected SHA-256' if asset.get('sha256') else
            'locally computed SHA-256; publisher checksum not verified'}


def tree_hashes(root):
    result = {}
    for p in sorted(Path(root).rglob('*')):
        if p.is_symlink():
            raise ValueError(f'Symlink refused in bundle: {p}')
        if p.is_file() and p != Path(root) / 'checksums.json':
            result[p.relative_to(root).as_posix()] = sha256(p)
    return result


def verify_bundle(bundle):
    bundle = Path(bundle)
    expected = read_json(bundle / 'checksums.json')
    if not expected:
        raise ValueError('Empty backup inventory')
    for name in expected:
        safe_path(bundle, name)
    if tree_hashes(bundle) != expected:
        raise ValueError('Backup has missing, changed or unexpected files')
    verify_content(bundle / 'data')


def physical_disks(path):
    source = subprocess.check_output(['findmnt', '-n', '-o', 'SOURCE', '-T', str(path)], text=True).strip()
    rows = subprocess.check_output(['lsblk', '-s', '-n', '-r', '-o', 'TYPE,MAJ:MIN', source], text=True)
    return {row.split()[1] for row in rows.splitlines() if row.split()[0] == 'disk'}


def backup(root, mount):
    if sys.platform != 'linux':
        raise ValueError('Backup requires Linux mount/device checks on the Debian host')
    root, mount = external_root(root), external_root(mount)
    subprocess.run(['mountpoint', '-q', str(mount)], check=True)
    origin, target = physical_disks(root), physical_disks(mount)
    if not origin or not target or origin & target:
        raise ValueError('Backup must be on an identifiable, separate physical disk')
    verify_content(root)
    if not (root / 'recovery-packages/COMPLETE').is_file():
        raise ValueError('Cache the installed packages successfully before making a recovery bundle')
    files = tree_hashes(root)  # Reject symlinks before copying, including public documents.
    required = sum(safe_path(root, name).stat().st_size for name in files) + 1_000_000_000
    if shutil.disk_usage(mount).free < required:
        raise ValueError(f'Insufficient backup space: {required:,} bytes required including 1 GB source/reserve allowance')
    bundle = mount / ('cyberdeck-' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    bundle.mkdir()
    shutil.copytree(root, bundle / 'data')
    source = bundle / 'source'
    for name in ['app', 'tests', 'scripts/debian', 'config/debian', 'assets/hub',
                 'docs/runbooks/debian-install.md']:
        src, dest = safe_path(REPO, name), safe_path(source, name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dest, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        else:
            shutil.copy2(src, dest)
    (bundle / 'README.txt').write_text('Canonical Debian recovery: source/docs/runbooks/debian-install.md\n'
                                      'Keep the verified Debian installation media separately with this backup.\n',
                                      encoding='utf-8')
    write_json(bundle / 'checksums.json', tree_hashes(bundle))
    verify_bundle(bundle)
    print(f'Backup copied and read-back verified: {bundle}')
    print('Still required: retain installation media and perform a disconnected recovery rehearsal.')


def restore(bundle, destination):
    destination = external_root(destination)
    if destination.exists():
        raise ValueError('Restore destination must not exist; preserve the working copy first')
    verify_bundle(bundle)
    shutil.copytree(Path(bundle) / 'data', destination)
    verify_content(destination)
    print(f'Restored and verified: {destination}. Package/service restore is a separate step.')


def check(root, host):
    if host != 'localhost':
        ip = ipaddress.ip_address(host)
        if ip.version != 4 or not (ip.is_private or ip.is_loopback):
            raise ValueError('Use a private/loopback IPv4 address, not public DNS')
    lock = verify_content(root)
    # Ignore proxies. Confirm the pre-trust guide is served directly on HTTP port 80.
    bootstrap_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with bootstrap_opener.open(f'http://{host}/', timeout=10) as response:
        if response.status != 200 or response.geturl() != f'http://{host}/':
            raise ValueError('HTTP certificate bootstrap probe failed')
        bootstrap = response.read(262144)
        if b'Set up a trusted connection' not in bootstrap or b'/?lang=da' not in bootstrap:
            raise ValueError('HTTP certificate bootstrap page is incomplete')
    ca_file = Path('/etc/cyberdeck/tls/ca.crt')
    context = ssl.create_default_context(cafile=str(ca_file)) if ca_file.is_file() else ssl.create_default_context()
    secure_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
    for url in [f'http://{host}:8080/', f'https://{host}/',
                *[f'https://{host}/library/{urllib.parse.quote(n.removeprefix("public/"))}'
                  for n in lock if n.startswith('public/')]]:
        with secure_opener.open(url, timeout=10) as response:
            if response.status != 200:
                raise ValueError('Local service probe failed')
    print('PASS: content hashes, HTTP bootstrap/redirect, trusted HTTPS app, and Kiwix endpoints. NOT a proof of offline/search/recovery acceptance.')
    print('Now perform disconnected cold boot, browser search, second-client and restore checks in the guide.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    cmd = sub.add_parser('plan', help='Print local manifest sizes; no network or changes')
    cmd.add_argument('--manifest', type=Path, required=True)
    for action in ['fetch', 'verify', 'check', 'backup']:
        cmd = sub.add_parser(action)
        cmd.add_argument('--root', type=Path, default=Path('/srv/cyberdeck'))
        if action == 'fetch':
            cmd.add_argument('--manifest', type=Path, default=REPO / 'config/debian/starter.json')
            cmd.add_argument('--missing-only', action='store_true',
                             help='Verify only files listed in the requested manifest')
        if action == 'verify':
            cmd.add_argument('--manifest', type=Path, help='Also require all assets in this pack to be acquired unchanged')
            cmd.add_argument('--missing-only', action='store_true',
                             help='With --manifest, verify only files listed in that manifest')
        if action == 'check':
            cmd.add_argument('--host', default='127.0.0.1')
        if action == 'backup':
            cmd.add_argument('--mount', type=Path, required=True)
    cmd = sub.add_parser('restore')
    cmd.add_argument('--bundle', type=Path, required=True)
    cmd.add_argument('--destination', type=Path, required=True)
    cmd = sub.add_parser('verify-bundle')
    cmd.add_argument('--bundle', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == 'plan':
            plan(args.manifest)
        elif args.action == 'fetch':
            fetch(args.root, args.manifest, missing_only=args.missing_only)
        elif args.action == 'verify':
            if args.manifest:
                verify_manifest(args.root, args.manifest, missing_only=args.missing_only)
            elif args.missing_only:
                raise ValueError('--missing-only requires --manifest for verify')
            else:
                verify_content(args.root)
            print('Content integrity passed.')
        elif args.action == 'check':
            check(args.root, args.host)
        elif args.action == 'backup':
            backup(args.root, args.mount)
        elif args.action == 'restore':
            restore(args.bundle, args.destination)
        else:
            verify_bundle(args.bundle)
            print('Backup integrity passed.')
    except (OSError, ValueError, KeyError, http.client.HTTPException, subprocess.CalledProcessError) as error:
        parser.exit(1, f'ERROR: {error}\n')
    except KeyboardInterrupt:
        parser.exit(130, 'Interrupted. Pinned resumable downloads retain their partial files; rerun the same command.\n')


if __name__ == '__main__':
    main()
