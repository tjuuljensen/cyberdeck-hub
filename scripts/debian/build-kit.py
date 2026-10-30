"""Build a source-only Debian install kit; this does not install or contact a host."""
from __future__ import annotations

import argparse
import ast
import gzip
import hashlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import tarfile
import tempfile


REPO_ROOT = Path(__file__).resolve().parents[2]
KIT_FILES = (
    'LICENSE',
    'README.md',
    'docs/runbooks/bootstrap-install.md',
    'docs/runbooks/debian-install.md',
    'scripts/debian/configure-deploy-cache.sh',
    'scripts/debian/build-kit.py',
    'scripts/debian/verify-runtime.py',
    'scripts/debian/install.sh',
    'scripts/debian/install-cyberchef.py',
    'scripts/debian/deploy-helper.py',
    'scripts/debian/storage-helper.py',
    'scripts/debian/admin-helper.py',
    'scripts/debian/wifi-diagnostics.py',
    'scripts/debian/host_identity.py',
    'scripts/debian/http-redirect.py',
    'scripts/debian/configure-gnome-power.py',
)
KIT_DIRECTORIES = (
    'assets/hub',
    'config/debian',
    'app',
)
INSTALLER_REQUIRED_SOURCES = (
    'config/debian/library-manifest.json',
    'config/debian/starter.json',
    'config/debian/systemd/cyberdeck-web.service',
    'config/debian/systemd/cyberdeck-redirect.service',
    'config/debian/systemd/cyberdeck-kiwix.service',
    'config/debian/systemd/cyberdeck-storage-migration.service',
    'config/debian/systemd/cyberdeck-storage-initialize.service',
    'config/debian/systemd/cyberdeck-storage-existing.service',
    'config/debian/systemd/cyberdeck-storage-recovery.service',
    'config/debian/systemd/cyberdeck-storage-boot-recovery.service',
    'config/debian/systemd/cyberdeck-firewall.service',
    'config/debian/systemd/sleep.conf.d/90-cyberdeck.conf',
    'config/debian/systemd/logind.conf.d/90-cyberdeck.conf',
    'scripts/debian/storage-helper.py',
    'scripts/debian/wifi-diagnostics.py',
    'scripts/debian/http-redirect.py',
    'scripts/debian/configure-gnome-power.py',
)


def collect_files(repo_root: Path) -> list[tuple[Path, str]]:
    """Return regular source files with stable kit-relative names, rejecting links."""
    files: list[tuple[Path, str]] = []
    for relative in KIT_FILES:
        source = repo_root / relative
        if source.is_symlink() or not source.is_file():
            raise ValueError(f'Required kit source is missing or unsafe: {relative}')
        files.append((source, relative))

    for relative in KIT_DIRECTORIES:
        base = repo_root / relative
        if base.is_symlink() or not base.is_dir():
            raise ValueError(f'Required kit directory is missing or unsafe: {relative}')
        for current, directories, filenames in os.walk(base, followlinks=False):
            current_path = Path(current)
            for name in directories:
                if (current_path / name).is_symlink():
                    raise ValueError(f'Refusing symlink in install kit: {current_path / name}')
            directories[:] = sorted(name for name in directories if name != '__pycache__')
            for name in sorted(filenames):
                source = current_path / name
                if name.endswith(('.pyc', '.pyo')):
                    continue
                if source.is_symlink() or not source.is_file():
                    raise ValueError(f'Refusing non-regular install-kit source: {source}')
                files.append((source, source.relative_to(repo_root).as_posix()))

    included_paths = {relative for _, relative in files}
    missing = sorted(set(INSTALLER_REQUIRED_SOURCES) - included_paths)
    if missing:
        raise ValueError(f'Debian install kit is missing installer-required sources: {", ".join(missing)}')
    validate_profile_sources(repo_root, included_paths)
    validate_runtime_sources(repo_root)
    return sorted(files, key=lambda item: item[1])


def validate_runtime_sources(repo_root: Path) -> None:
    """Reject an app kit whose helper, sudo policy, or firewall unit is stale."""
    helper = ast.parse((repo_root / 'scripts/debian/admin-helper.py').read_text(encoding='utf-8'))
    actions = set()
    for node in ast.walk(helper):
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict)
                and any(isinstance(target, ast.Name) and target.id == 'allowed'
                        for target in node.targets)):
            actions.update(key.value for key in node.value.keys
                           if isinstance(key, ast.Constant) and isinstance(key.value, str))
    required = {'firewall-status', 'firewall-enable', 'firewall-disable',
                'firewall-load', 'firewall-remove'}
    missing = sorted(required - actions)
    if missing:
        raise ValueError('Outdated admin helper; missing actions: ' + ', '.join(missing))
    installer = (repo_root / 'scripts/debian/install.sh').read_text(encoding='utf-8')
    policy = re.search(r"(?m)^\s*'cyberdeck ALL=\(root\) NOPASSWD: ([^'\n]+)'", installer)
    grants = set(policy.group(1).split(', ')) if policy else set()
    for action in ('firewall-status', 'firewall-enable', 'firewall-disable'):
        if '/usr/local/lib/cyberdeck/admin-helper.py ' + action not in grants:
            raise ValueError('Installer sudoers policy is missing ' + action)
    unit = (repo_root / 'config/debian/systemd/cyberdeck-firewall.service').read_text(encoding='utf-8')
    for directive, action in (('ExecStart', 'firewall-load'), ('ExecStop', 'firewall-remove')):
        if f'{directive}=/usr/local/lib/cyberdeck/admin-helper.py {action}' not in unit.splitlines():
            raise ValueError('Firewall service is missing ' + directive + ' for ' + action)


def validate_profile_sources(repo_root: Path, included_paths: set[str]) -> None:
    """Ensure every bundled profile's local payload is present in the kit."""
    starter = repo_root / 'config/debian/starter.json'
    profile_paths = [starter]
    extra_profiles = repo_root / 'config/debian/profiles'
    if extra_profiles.is_symlink():
        raise ValueError('Refusing symlink profile directory: config/debian/profiles')
    if extra_profiles.exists():
        if not extra_profiles.is_dir():
            raise ValueError('Expected config/debian/profiles to be a directory')
        profile_paths.extend(sorted(extra_profiles.glob('*.json')))
    for profile_path in profile_paths:
        relative_profile = profile_path.relative_to(repo_root).as_posix()
        label = 'generic Debian starter profile' if profile_path == starter else f'profile {relative_profile}'
        try:
            if profile_path.is_symlink() or relative_profile not in included_paths:
                raise ValueError('profile file is missing from the install kit or is a symlink')
            profile = json.loads(profile_path.read_text(encoding='utf-8'))
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            raise ValueError(f'Cannot read {label}: {error}') from error
        if not isinstance(profile, dict) or not isinstance(profile.get('assets'), list):
            raise ValueError(f'The {label} must contain an assets list')
        for asset in profile['assets']:
            if not isinstance(asset, dict):
                raise ValueError(f'The {label} contains a non-object asset')
            source_name = asset.get('source_file')
            if source_name is None:
                continue
            if not isinstance(source_name, str):
                raise ValueError(f'A {label} source_file must be a relative assets path')
            relative = PurePosixPath(source_name)
            if (not source_name or relative.is_absolute() or '\\' in source_name or ':' in source_name or
                    '..' in relative.parts or not relative.parts or relative.parts[0] != 'assets'):
                raise ValueError(f'Unsafe {label} source_file: {source_name!r}')
            source = repo_root.joinpath(*relative.parts)
            if (source_name not in included_paths or source.is_symlink() or not source.is_file()):
                raise ValueError(f'{label} source_file is missing from the install kit: {source_name}')
            size = source.stat().st_size
            expected_bytes = asset.get('expected_bytes')
            if expected_bytes is not None and (type(expected_bytes) is not int or expected_bytes != size):
                raise ValueError(f'{label} source_file size does not match its profile: {source_name}')
            expected_hash = asset.get('sha256')
            if expected_hash is not None:
                if (not isinstance(expected_hash, str) or
                        not re.fullmatch(r'[0-9a-fA-F]{64}', expected_hash)):
                    raise ValueError(f'{label} source_file hash is invalid: {source_name}')
                with source.open('rb') as handle:
                    digest = hashlib.file_digest(handle, 'sha256').hexdigest()
                if digest.lower() != expected_hash.lower():
                    raise ValueError(f'{label} source_file hash does not match its profile: {source_name}')


def build_kit(repo_root: Path, output: Path) -> int:
    """Write an atomic gzip tarball and return its source-file count."""
    repo_root = repo_root.resolve(strict=True)
    output = output.absolute()
    if not output.parent.is_dir():
        raise ValueError('The install-kit output directory must already exist')
    if output.is_symlink() or (output.exists() and not output.is_file()):
        raise ValueError('The install-kit output must be a regular file path')
    files = collect_files(repo_root)
    for relative in (*KIT_FILES, *KIT_DIRECTORIES):
        source = (repo_root / relative).resolve(strict=True)
        candidate = output.resolve(strict=False)
        if candidate == source or (source.is_dir() and candidate.is_relative_to(source)):
            raise ValueError('The install-kit output cannot be inside its source files')

    descriptor, temporary_name = tempfile.mkstemp(prefix='.cyberdeck-hub-debian-kit-', suffix='.tmp',
                                                    dir=output.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        # Normalize gzip and tar metadata so the same source tree yields the
        # same checksum across repeated builds and checkout times.
        with temporary.open('wb') as raw_archive:
            with gzip.GzipFile(filename='', mode='wb', fileobj=raw_archive,
                               mtime=0, compresslevel=9) as compressed:
                with tarfile.open(fileobj=compressed, mode='w',
                                  format=tarfile.PAX_FORMAT) as archive:
                    for source, relative in files:
                        info = tarfile.TarInfo(relative)
                        info.size = source.stat().st_size
                        info.mode = 0o644
                        info.mtime = 0
                        with source.open('rb') as content:
                            archive.addfile(info, content)
        os.replace(temporary, output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return len(files)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument('--output', type=Path,
                        help='destination .tar.gz path; its parent directory must exist')
    operation.add_argument('--validate-only', action='store_true',
                           help='validate the complete source kit without writing or installing it')
    parser.add_argument('--source-root', type=Path, default=REPO_ROOT,
                        help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if args.validate_only:
            count = len(collect_files(args.source_root))
            print(f'Validated {count} source files, helper actions, sudoers grants, and firewall unit.')
            return 0
        count = build_kit(args.source_root, args.output)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(f'Created {args.output} with {count} source files.')
    print('Transfer it to Debian, extract it, review docs/runbooks/debian-install.md, and run install.sh in preview mode first.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
