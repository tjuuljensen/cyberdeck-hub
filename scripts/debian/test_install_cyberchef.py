"""Safety tests for the pinned, opt-in CyberChef module installer."""
import json
from pathlib import Path
import stat
import importlib.util
import contextlib
import io
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock
import zipfile

_installer_path = Path(__file__).with_name('install-cyberchef.py')
_spec = importlib.util.spec_from_file_location('install_cyberchef', _installer_path)
install_cyberchef = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(install_cyberchef)


class CyberChefInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def make_archive(self, path, entries):
        with zipfile.ZipFile(path, 'w') as archive:
            for name, data in entries:
                info = zipfile.ZipInfo(name)
                if isinstance(data, tuple):
                    info.external_attr = data[0] << 16
                    data = data[1]
                archive.writestr(info, data)
        return path

    def test_extract_writes_pinned_marker_and_regular_files(self):
        source = self.make_archive(self.root / 'cyberchef.zip', [
            ('index.html', '<title>CyberChef</title>'),
            ('assets/main.js', 'self-contained fixture'),
        ])
        destination = self.root / 'stage'
        destination.mkdir()
        install_cyberchef.extract_archive(source, destination)
        marker = json.loads((destination / 'cyberdeck-module.json').read_text(encoding='utf-8'))
        self.assertEqual(marker['name'], 'cyberchef')
        self.assertEqual(marker['build'], install_cyberchef.BUILD)
        self.assertEqual(marker['archive_sha256'], install_cyberchef.ARCHIVE_SHA256)
        self.assertEqual((destination / 'assets/main.js').read_text(encoding='utf-8'),
                         'self-contained fixture')

    def test_extract_rejects_traversal_before_writing_outside_stage(self):
        source = self.make_archive(self.root / 'unsafe.zip', [
            ('../outside.txt', 'not written'),
        ])
        destination = self.root / 'stage'
        destination.mkdir()
        with self.assertRaises(SystemExit):
            install_cyberchef.extract_archive(source, destination)
        self.assertFalse((self.root / 'outside.txt').exists())

    def test_extract_rejects_symlink_entries(self):
        source = self.make_archive(self.root / 'symlink.zip', [
            ('index.html', '<title>CyberChef</title>'),
            ('assets/payload', (stat.S_IFLNK | 0o777, '../outside')),
        ])
        destination = self.root / 'stage'
        destination.mkdir()
        with self.assertRaises(SystemExit):
            install_cyberchef.extract_archive(source, destination)
        self.assertFalse((self.root / 'outside').exists())

    def test_extract_requires_root_index(self):
        source = self.make_archive(self.root / 'missing-entry.zip', [
            ('README.txt', 'No application entry point'),
        ])
        destination = self.root / 'stage'
        destination.mkdir()
        with self.assertRaises(SystemExit):
            install_cyberchef.extract_archive(source, destination)

    def test_check_host_rejects_non_full_install_before_network_checks(self):
        environment = self.root / 'environment'
        environment.write_text('CYBERDECK_RUNTIME_MODE=container\n', encoding='utf-8')
        with patch.object(install_cyberchef, 'ENVIRONMENT', environment), \
                patch.object(install_cyberchef.subprocess, 'run') as commands:
            with self.assertRaises(SystemExit):
                install_cyberchef.check_host('cyberdeck.local')
            commands.assert_not_called()

    def test_check_host_uses_hub_hostname_and_existing_certificate(self):
        environment = self.root / 'environment'
        environment.write_text(
            'CYBERDECK_RUNTIME_MODE=headless\n'
            'CYBERDECK_HOSTNAME=cyberdeck.local\n',
            encoding='utf-8')
        with patch.object(install_cyberchef, 'ENVIRONMENT', environment), \
                patch.object(install_cyberchef.subprocess, 'run', side_effect=[
                    Mock(returncode=0), Mock(returncode=0),
                ]) as run:
            install_cyberchef.check_host('cyberdeck.local')
            self.assertEqual(run.call_count, 2)
            self.assertIn('cyberdeck.local', run.call_args_list[0].args[0])
            self.assertIn('cyberdeck.local', run.call_args_list[1].args[0])

    def test_check_host_rejects_hostname_different_from_hub_name(self):
        environment = self.root / 'environment'
        environment.write_text(
            'CYBERDECK_RUNTIME_MODE=headless\n'
            'CYBERDECK_HOSTNAME=cyberdeck.local\n',
            encoding='utf-8')
        with patch.object(install_cyberchef, 'ENVIRONMENT', environment), \
                patch.object(install_cyberchef.subprocess, 'run') as commands:
            with self.assertRaises(SystemExit):
                install_cyberchef.check_host('chef.cyberdeck.local')
            commands.assert_not_called()

    def test_port_conflict_is_rejected_before_replacing_module_files(self):
        with patch.object(install_cyberchef.subprocess, 'run', side_effect=[
                Mock(returncode=0, stdout='LISTEN 0 128 0.0.0.0:8445 0.0.0.0:*\n'),
                Mock(returncode=1, stdout='', stderr='')]) as commands:
            with self.assertRaises(SystemExit):
                install_cyberchef.check_port_available()
        self.assertEqual(commands.call_count, 2)
        self.assertEqual(commands.call_args_list[0].args[0],
                         ['ss', '-ltnH', '( sport = :8445 )'])

    def test_existing_cyberchef_service_may_restart_on_its_port(self):
        with patch.object(install_cyberchef.subprocess, 'run', side_effect=[
                Mock(returncode=0, stdout='LISTEN 0 128 0.0.0.0:8445 0.0.0.0:*\n'),
                Mock(returncode=0, stdout='', stderr='')]) as commands:
            install_cyberchef.check_port_available()
        self.assertEqual(commands.call_count, 2)

    def test_remove_previews_by_default_and_requires_apply(self):
        module_root = self.root / 'cyberchef'
        module_root.mkdir()
        (module_root / 'cyberdeck-module.json').write_text(json.dumps({
            'name': 'cyberchef', 'build': install_cyberchef.BUILD,
            'archive_sha256': install_cyberchef.ARCHIVE_SHA256,
        }), encoding='utf-8')
        output = io.StringIO()
        with patch.object(install_cyberchef, 'MODULE_ROOT', module_root), \
                patch.object(sys, 'argv', ['install-cyberchef.py', '--remove']), \
                contextlib.redirect_stdout(output):
            self.assertEqual(install_cyberchef.main(), 0)
        self.assertTrue(module_root.is_dir())
        self.assertIn('PREVIEW ONLY', output.getvalue())

        with patch.object(install_cyberchef, 'MODULE_ROOT', module_root), \
                patch.object(install_cyberchef, 'SERVICE_DESTINATION', self.root / 'service'), \
                patch.object(install_cyberchef, 'SERVER_DESTINATION', self.root / 'server'), \
                patch.object(install_cyberchef, 'is_root', return_value=True), \
                patch.object(install_cyberchef.subprocess, 'run', return_value=Mock(returncode=0)), \
                patch.object(sys, 'argv', ['install-cyberchef.py', '--remove', '--apply']):
            self.assertEqual(install_cyberchef.main(), 0)
        self.assertFalse(module_root.exists())


if __name__ == '__main__':
    unittest.main()
