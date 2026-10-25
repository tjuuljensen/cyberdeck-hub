"""Tests for the source-only Debian kit builder; no archive is installed or run."""
import importlib.util
import os
from pathlib import Path
import tempfile
import tarfile
import unittest


_builder_path = Path(__file__).with_name('build-kit.py')
_spec = importlib.util.spec_from_file_location('build_kit', _builder_path)
build_kit_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_kit_module)


class BuildKitTests(unittest.TestCase):
    def test_kit_contains_installer_app_profile_and_runbook_without_tests(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'cyberdeck-hub-debian-kit.tar.gz'
            count = build_kit_module.build_kit(build_kit_module.REPO_ROOT, output)
            with tarfile.open(output, 'r:gz') as archive:
                names = set(archive.getnames())

        self.assertGreater(count, 20)
        self.assertTrue({
            'scripts/debian/install.sh',
            'scripts/debian/install-cyberchef.py',
            'scripts/debian/deploy-helper.py',
            'config/debian/starter.json',
            'config/debian/systemd/cyberdeck-cyberchef.service',
            'config/debian/systemd/cyberdeck-web.service',
            'config/debian/systemd/sleep.conf.d/90-cyberdeck.conf',
            'config/debian/systemd/logind.conf.d/90-cyberdeck.conf',
            'scripts/debian/admin-helper.py',
            'scripts/debian/host_identity.py',
            'scripts/debian/http-redirect.py',
            'scripts/debian/configure-gnome-power.py',
            'app/cyberchef_server.py',
            'app/webapp.py',
            'app/static/admin.js',
            'app/translations/da.json',
            'assets/hub/library-startup.html',
            'docs/runbooks/debian-install.md',
        }.issubset(names))
        self.assertFalse(any('/tests/' in name for name in names))
        self.assertFalse(any('__pycache__' in name or name.endswith('.pyc') for name in names))

    def test_repeated_builds_ignore_checkout_timestamps_and_are_byte_identical(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'source'
            root.mkdir()
            for source, relative in build_kit_module.collect_files(build_kit_module.REPO_ROOT):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
            first = Path(temp) / 'first.tar.gz'
            second = Path(temp) / 'second.tar.gz'
            build_kit_module.build_kit(root, first)
            for target in root.rglob('*'):
                if target.is_file():
                    os.utime(target, (1_234_567_890, 1_234_567_890))
            build_kit_module.build_kit(root, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with tarfile.open(first, 'r:gz') as archive:
                self.assertTrue(all(member.mtime == 0 and member.mode == 0o644
                                    for member in archive.getmembers()))

    def test_profile_source_must_be_a_regular_included_assets_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            profile = root / 'config' / 'debian' / 'starter.json'
            profile.parent.mkdir(parents=True)
            profile.write_text('{"assets":[{"source_file":"assets/hub/card.html",'
                                '"expected_bytes":4,"sha256":"9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"}]}',
                               encoding='utf-8')
            included = {'config/debian/starter.json'}
            with self.assertRaisesRegex(ValueError, 'missing from the install kit'):
                build_kit_module.validate_profile_sources(root, set())

            asset = root / 'assets' / 'hub' / 'card.html'
            asset.parent.mkdir(parents=True)
            asset.write_text('test', encoding='utf-8')
            included.add('assets/hub/card.html')
            build_kit_module.validate_profile_sources(root, included)

            profile.write_text('{"assets":[{"source_file":"assets/hub/card.html",'
                                '"expected_bytes":3}]}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'size does not match its profile'):
                build_kit_module.validate_profile_sources(root, included)

            profile.write_text('{"assets":[{"source_file":"assets/hub/card.html",'
                                '"sha256":"' + '0' * 64 + '"}]}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'hash does not match its profile'):
                build_kit_module.validate_profile_sources(root, included)

            profile.write_text('{"assets":[{"source_file":"assets/../secret"}]}',
                               encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Unsafe generic Debian starter profile source_file'):
                build_kit_module.validate_profile_sources(root, included)

    def test_additional_profile_sources_are_validated_and_packaged(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            starter = root / 'config/debian/starter.json'
            extra = root / 'config/debian/profiles/danmark.json'
            starter.parent.mkdir(parents=True)
            extra.parent.mkdir(parents=True)
            starter.write_text('{"assets":[]}', encoding='utf-8')
            extra.write_text('{"assets":[{"source_file":"assets/hub/card.html"}]}',
                             encoding='utf-8')
            asset = root / 'assets/hub/card.html'
            asset.parent.mkdir(parents=True)
            asset.write_text('card', encoding='utf-8')
            included = {'config/debian/starter.json', 'config/debian/profiles/danmark.json'}
            with self.assertRaisesRegex(ValueError, 'profile.*source_file is missing'):
                build_kit_module.validate_profile_sources(root, included)
            included.add('assets/hub/card.html')
            build_kit_module.validate_profile_sources(root, included)

    def test_output_inside_packaged_source_is_rejected_without_writing(self):
        output = build_kit_module.REPO_ROOT / 'app/install-kit.tar.gz'
        with self.assertRaisesRegex(ValueError, 'inside its source'):
            build_kit_module.build_kit(build_kit_module.REPO_ROOT, output)
        self.assertFalse(output.exists())

    def test_missing_source_is_rejected_without_replacing_existing_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'source'
            root.mkdir()
            output = Path(temp) / 'existing.tar.gz'
            output.write_bytes(b'keep')
            with self.assertRaises(ValueError):
                build_kit_module.build_kit(root, output)
            self.assertEqual(output.read_bytes(), b'keep')


if __name__ == '__main__':
    unittest.main()
