"""Prepare a Rufus overlay or remastered Debian installer ISO payload."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

REPO_ROOT = Path(__file__).resolve().parents[2]
BOOT_PARAMETER = 'file=/cdrom/preseed.cfg'
PRESEED_HEADER = '#_preseed_V1'
OVERLAY_FILES = (
    'config/debian/preseed.cfg',
    'scripts/debian/cyberdeck-firstboot-install.sh',
    'scripts/debian/cyberdeck-firstboot-profile.sh',
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def sha512(path: Path) -> str:
    digest = hashlib.sha512()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def validate_preseed(path: Path) -> None:
    """Reject media input that Debian Installer cannot identify as a preseed."""
    try:
        with path.open('r', encoding='utf-8') as source:
            first_line = source.readline().rstrip('\r\n')
    except (OSError, UnicodeError) as error:
        raise ValueError(f'Cannot read Debian preseed file {path}: {error}') from error
    if first_line != PRESEED_HEADER:
        raise ValueError(f'{path} must start with the Debian preseed marker {PRESEED_HEADER}.')


def clear_previous_outputs(output_dir: Path, stage: Path) -> None:
    """Remove only media outputs identified by this builder's manifest."""
    manifest_path = output_dir / 'cyberdeck-media-manifest.json'
    stage_manifest_path = stage / 'cyberdeck-media-manifest.json'
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError('Cannot overwrite output safely without this builder\'s media manifest.')
    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if not isinstance(manifest, dict):
            raise ValueError('The existing media manifest is not a JSON object.')
        if (manifest.get('format') != 1 or
                manifest.get('overlay_zip') != 'cyberdeck-preseed-overlay.zip'):
            raise ValueError('The existing media manifest does not identify generated Cyberdeck media.')
        if stage.is_symlink():
            raise ValueError('Refusing to overwrite a symlink in place of the generated overlay directory.')
        if stage.exists():
            if stage.is_symlink() or not stage.is_dir() or stage_manifest_path.is_symlink() or not stage_manifest_path.is_file():
                raise ValueError('Cannot overwrite an unsafe or unrecognized overlay directory.')
            staged_manifest = json.loads(stage_manifest_path.read_text(encoding='utf-8'))
            if not isinstance(staged_manifest, dict):
                raise ValueError('The overlay manifest is not a JSON object.')
            if (staged_manifest.get('format') != 1 or
                    staged_manifest.get('source_revision') != manifest.get('source_revision')):
                raise ValueError('The overlay directory does not match the existing media manifest.')
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f'Cannot read the existing Cyberdeck media manifest: {error}') from error

    output_files = [output_dir / name for name in
                    ('cyberdeck-install-kit.tar.gz', 'cyberdeck-preseed-overlay.zip',
                     'cyberdeck-media-manifest.json')]
    for path in output_files:
        if path.is_symlink():
            raise ValueError(f'Refusing to overwrite a symlink: {path}')
        if path.exists():
            if not path.is_file():
                raise ValueError(f'Refusing to overwrite a non-file media output: {path}')
    if stage.exists():
        shutil.rmtree(stage)
    for path in output_files:
        if path.exists():
            path.unlink()


def patch_boot_config(source: Path, destination: Path, directives: tuple[str, ...]) -> int:
    """Add the preseed argument to every GRUB linux or ISOLINUX append line."""
    try:
        lines = source.read_text(encoding='utf-8').splitlines(keepends=True)
    except (OSError, UnicodeError) as error:
        raise ValueError(f'Cannot read installer boot configuration {source}: {error}') from error
    changed = 0
    matched = 0
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if not any(re.match(rf'^{re.escape(directive)}\s', stripped) for directive in directives):
            continue
        matched += 1
        if BOOT_PARAMETER in line:
            continue
        newline = '\r\n' if line.endswith('\r\n') else '\n' if line.endswith('\n') else ''
        body = line[:-len(newline)] if newline else line
        separator = re.search(r'\s---(?:\s|$)', body)
        if separator:
            body = body[:separator.start()] + ' ' + BOOT_PARAMETER + body[separator.start():]
        else:
            body += ' ' + BOOT_PARAMETER
        lines[index] = body + newline
        changed += 1
    if matched == 0:
        raise ValueError(f'No installer boot entries found in {source}; ISO layout may have changed.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('w', encoding='utf-8', newline='') as output:
        output.write(''.join(lines))
    return changed


def git_state(repo_root: Path) -> tuple[str, bool]:
    try:
        revision = subprocess.run(['git', '-C', str(repo_root), 'rev-parse', 'HEAD'],
                                  check=True, capture_output=True, text=True).stdout.strip()
        dirty = bool(subprocess.run(['git', '-C', str(repo_root), 'status', '--porcelain'],
                                    check=True, capture_output=True, text=True).stdout.strip())
        return revision, dirty
    except (OSError, subprocess.CalledProcessError):
        return 'unavailable', True


def prepare_overlay(repo_root: Path, iso: Path, grub: Path, isolinux: Path,
                    output_dir: Path, overwrite: bool = False) -> dict[str, object]:
    repo_root = repo_root.resolve(strict=True)
    iso = iso.resolve(strict=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_dir = output_dir.resolve(strict=True)
    stage = output_dir / 'overlay'
    existing = [path.name for path in (stage, output_dir / 'cyberdeck-install-kit.tar.gz',
                                       output_dir / 'cyberdeck-preseed-overlay.zip',
                                       output_dir / 'cyberdeck-media-manifest.json')
                if path.exists() or path.is_symlink()]
    if existing:
        if not overwrite:
            raise ValueError(
                f"Refusing to overwrite existing media outputs: {', '.join(existing)}. "
                'Use --overwrite to replace a prior output created by this builder, or choose a new output directory.')
    validate_preseed(repo_root / 'config/debian/preseed.cfg')
    if existing and overwrite:
        with tempfile.TemporaryDirectory(prefix='.cyberdeck-media-rebuild-', dir=output_dir.parent) as temporary:
            staged_output = Path(temporary)
            manifest = prepare_overlay(repo_root, iso, grub, isolinux, staged_output)
            clear_previous_outputs(output_dir, stage)
            for name in ('overlay', 'cyberdeck-install-kit.tar.gz',
                         'cyberdeck-preseed-overlay.zip', 'cyberdeck-media-manifest.json'):
                (staged_output / name).replace(output_dir / name)
            return manifest
    stage.mkdir()

    kit = output_dir / 'cyberdeck-install-kit.tar.gz'
    build_script = repo_root / 'scripts/debian/build-kit.py'
    subprocess.run([sys.executable, str(build_script), '--output', str(kit)],
                   check=True, cwd=repo_root)

    for relative in OVERLAY_FILES:
        source = repo_root / relative
        if source.is_symlink() or not source.is_file():
            raise ValueError(f'Required USB source is missing or unsafe: {relative}')
        if relative == 'config/debian/preseed.cfg':
            destination = stage / 'preseed.cfg'
        else:
            destination = stage / Path(relative).name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
    (stage / 'cyberdeck-install-kit.tar.gz').write_bytes(kit.read_bytes())
    patch_boot_config(grub, stage / 'boot/grub/grub.cfg', ('linux', 'linuxefi'))
    patch_boot_config(isolinux, stage / 'isolinux/txt.cfg', ('append',))

    revision, dirty = git_state(repo_root)
    embedded_manifest = {
        'format': 1,
        'source_revision': revision,
        'source_worktree_dirty': dirty,
        'base_iso': iso.name,
        'base_iso_sha512': sha512(iso),
        'install_kit_sha256': sha256(kit),
        'preseed_sha256': sha256(stage / 'preseed.cfg'),
        'boot_parameter': BOOT_PARAMETER,
        'created_utc': datetime.now(timezone.utc).isoformat(),
    }
    manifest = stage / 'cyberdeck-media-manifest.json'
    with manifest.open('w', encoding='utf-8', newline='') as output:
        output.write(json.dumps(embedded_manifest, indent=2) + '\n')
    overlay_zip = output_dir / 'cyberdeck-preseed-overlay.zip'
    if overlay_zip.exists():
        raise ValueError(f'Refusing to overwrite existing overlay archive: {overlay_zip}')
    with zipfile.ZipFile(overlay_zip, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(stage.rglob('*')):
            if path.is_file():
                archive.write(path, path.relative_to(stage).as_posix())
    final_manifest = dict(embedded_manifest)
    final_manifest.update({
        'overlay_zip': overlay_zip.name,
        'overlay_zip_sha256': sha256(overlay_zip),
    })
    with (output_dir / 'cyberdeck-media-manifest.json').open(
            'w', encoding='utf-8', newline='') as output:
        output.write(json.dumps(final_manifest, indent=2) + '\n')
    return final_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, default=REPO_ROOT)
    parser.add_argument('--iso', type=Path, required=True)
    parser.add_argument('--grub-config', type=Path, required=True)
    parser.add_argument('--isolinux-config', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--overwrite', action='store_true',
                        help='replace prior outputs only when this builder\'s manifest validates them')
    args = parser.parse_args()
    try:
        manifest = prepare_overlay(args.repo_root, args.iso, args.grub_config,
                                   args.isolinux_config, args.output_dir, args.overwrite)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.error(str(error))
    print(f"Prepared {args.output_dir / manifest['overlay_zip']}")
    print(f"Overlay SHA-256: {manifest['overlay_zip_sha256']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
