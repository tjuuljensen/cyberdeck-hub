"""Host identity transactions tested without network, services or real host writes."""
from contextlib import ExitStack, nullcontext
from pathlib import Path
from types import SimpleNamespace
import json
import tempfile
import unittest
from unittest.mock import patch

import host_identity as identity


class HostIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.stack = ExitStack()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.stack.close)
        paths = {'ENVIRONMENT': 'environment', 'DNS_CONFIG': 'dns/cyberdeck.conf',
                 'PROFILE': 'profile', 'TLS': 'tls', 'HOSTS': 'hosts',
                 'STATE': 'state.json', 'BACKUPS': 'backups'}
        for attribute, relative in paths.items():
            self.stack.enter_context(patch.object(identity, attribute, self.root / relative))
        identity.TLS.mkdir()
        identity.DNS_CONFIG.parent.mkdir()
        identity.ENVIRONMENT.write_text(
            'KEEP=this\nCYBERDECK_HOSTNAME=cyberdeck-test-1.lan\nCYBERDECK_RUNTIME_MODE=headless\n')
        identity.HOSTS.write_text('127.0.0.1 localhost\n127.0.1.1 cyberdeck-test-1 extra # keep\n::1 localhost\n')
        identity.PROFILE.write_text('[connection]\ninterface-name=wlan1\n')
        identity.DNS_CONFIG.write_text('# previous DNS\n')
        for name in ('ca.key', 'ca.crt', 'server.key', 'server.crt'):
            (identity.TLS / name).write_text('old-' + name)
        self.host = 'cyberdeck-test-1'
        self.calls = []
        self.fail_restart = False
        self.fail_recovery = False
        self.stack.enter_context(patch.object(identity, 'change_lock', side_effect=nullcontext))
        self.stack.enter_context(patch.object(identity.os, 'chown', create=True))
        self.stack.enter_context(patch.object(identity, 'require_host', side_effect=lambda expected=None: self.host))
        self.stack.enter_context(patch.object(identity, 'check_rename_tools'))
        self.stack.enter_context(patch.object(identity.shutil, 'which', return_value='/usr/bin/nmcli'))
        self.stack.enter_context(patch.object(identity.time, 'sleep'))
        self.stack.enter_context(patch.object(identity, 'run', side_effect=self.fake_run))

    def fake_run(self, args, **kwargs):
        self.calls.append(args)
        if 'ResolveHostName' in args:
            return SimpleNamespace(returncode=1, stdout='', stderr='not found')
        if args[:2] == ['systemctl', 'is-active'] and 'cyberdeck-hostname-' in args[-1]:
            return SimpleNamespace(returncode=0, stdout='active', stderr='')
        if args[0] == 'hostnamectl':
            if self.fail_recovery and args[-1] == 'cyberdeck-test-1':
                raise OSError('simulated recovery failure')
            self.host = args[-1]
        if args[:2] == ['systemctl', 'restart'] and args[-1] == 'cyberdeck-web.service' and self.fail_restart:
            self.fail_restart = False
            raise OSError('simulated restart failure')
        if 'GetHostNameFqdn' in args:
            return SimpleNamespace(returncode=0, stdout=f's "{self.host}.local"', stderr='')
        if args[:4] == ['nmcli', '-t', '-f', 'NAME']:
            return SimpleNamespace(returncode=0, stdout='cyberdeck-hotspot\n', stderr='')
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    def certificate(self, directory, hostname):
        key, cert = directory / 'new.key', directory / 'new.crt'
        key.write_text('new-key-for-' + hostname)
        cert.write_text('new-certificate-for-' + hostname)
        return key, cert

    def schedule(self):
        result = identity.request_hostname({'hostname': 'family-library', 'confirm': 'family-library'})
        self.assertEqual(result['url'], 'https://family-library.local/')
        self.assertEqual(self.host, 'cyberdeck-test-1')
        return identity.state_read()['id']

    def test_invalid_names_never_schedule_or_write(self):
        for name in ('', 'localhost', '-bad', 'bad-', 'bad.name', 'bad\nname', 'UPPER', 'a' * 64, '1test', None):
            with self.subTest(name=name), self.assertRaises(ValueError):
                identity.request_hostname({'hostname': name, 'confirm': name})
        self.assertFalse(identity.STATE.exists())
        self.assertEqual(self.calls, [])

    def test_confirmation_and_existing_name_rejected(self):
        for payload in ({'hostname': 'family-library'}, {'hostname': self.host, 'confirm': self.host}):
            with self.assertRaises(ValueError):
                identity.request_hostname(payload)
        with patch.object(identity, 'run', return_value=SimpleNamespace(returncode=0)):
            with self.assertRaisesRegex(ValueError, 'already in use'):
                identity.request_hostname({'hostname': 'family-library', 'confirm': 'family-library'})
        self.assertFalse(identity.STATE.exists())

    def test_duplicate_and_interrupted_requests_are_not_replayed(self):
        change_id = self.schedule()
        with self.assertRaisesRegex(ValueError, 'already in progress'):
            self.schedule()
        with patch.object(identity, 'run', return_value=SimpleNamespace(returncode=1)):
            with self.assertRaisesRegex(ValueError, 'local recovery'):
                self.schedule()
        self.assertEqual(identity.state_read()['id'], change_id)

    def test_dns_follows_adapter_and_validates_before_replacing(self):
        identity.prepare_dns('wlan1')
        text = identity.DNS_CONFIG.read_text()
        self.assertIn('interface-name=cyberdeck-test-1.lan,wlan1/4', text)
        self.assertNotIn('10.42.0.1', text)
        self.assertNotIn('.local,', text)  # .local belongs to mDNS, not unicast DNS.
        identity.prepare_dns('wlan2')
        self.assertNotIn('wlan1', identity.DNS_CONFIG.read_text())
        before = identity.DNS_CONFIG.read_bytes()
        with patch.object(identity, 'run', return_value=SimpleNamespace(returncode=1)):
            with self.assertRaisesRegex(ValueError, 'DNS validation failed'):
                identity.prepare_dns('wlan3')
        self.assertEqual(identity.DNS_CONFIG.read_bytes(), before)
        self.assertEqual(list(identity.DNS_CONFIG.parent.iterdir()), [identity.DNS_CONFIG])

    def test_dns_rejects_interface_injection_and_symlinks(self):
        for device in ('wlan0\naddress=/#/1.2.3.4', 'wlan*', '../wlan', ''):
            with self.assertRaises(ValueError):
                identity.dns_text('family-library', device)
        with patch.object(Path, 'is_symlink', side_effect=lambda: True):
            with self.assertRaisesRegex(ValueError, 'symlink'):
                identity.prepare_dns('wlan1')

    def test_success_updates_identity_and_certificate_but_preserves_ca(self):
        change_id = self.schedule()
        ca = {name: (identity.TLS / name).read_bytes() for name in ('ca.key', 'ca.crt')}
        with patch.object(identity, 'make_certificate', side_effect=self.certificate):
            identity.apply_hostname(change_id)
        self.assertEqual(identity.state_read()['status'], 'complete')
        self.assertEqual(self.host, 'family-library')
        self.assertEqual(identity.environment_host(), 'family-library.local')
        self.assertIn('KEEP=this', identity.ENVIRONMENT.read_text())
        self.assertIn('family-library.lan,wlan1/4', identity.DNS_CONFIG.read_text())
        self.assertIn('family-library family-library.local family-library.lan extra # keep', identity.HOSTS.read_text())
        self.assertIn('::1 localhost', identity.HOSTS.read_text())
        for name, data in ca.items():
            self.assertEqual((identity.TLS / name).read_bytes(), data)
        self.assertIn(['nmcli', 'connection', 'down', 'id', 'cyberdeck-hotspot'], self.calls)
        self.assertIn(['systemctl', 'restart', 'cyberdeck-redirect.service',
                       'cyberdeck-web.service'], self.calls)
        with self.assertRaisesRegex(ValueError, 'No matching'):
            identity.apply_hostname(change_id)

    def test_failure_restores_hostname_files_and_services(self):
        before = {path: path.read_bytes() for path in
                  (identity.ENVIRONMENT, identity.HOSTS, identity.TLS / 'server.key',
                   identity.TLS / 'server.crt', identity.DNS_CONFIG)}
        change_id = self.schedule()
        self.fail_restart = True
        with patch.object(identity, 'make_certificate', side_effect=self.certificate):
            with self.assertRaisesRegex(ValueError, 'Previous settings'):
                identity.apply_hostname(change_id)
        self.assertEqual(identity.state_read()['status'], 'failed')
        self.assertEqual(self.host, 'cyberdeck-test-1')
        for path, data in before.items():
            self.assertEqual(path.read_bytes(), data)
        self.assertIn(['systemctl', 'restart', *identity.DEBIAN_SERVICES], self.calls)

    def test_recovery_failure_is_not_reported_as_restored(self):
        change_id = self.schedule()
        self.fail_restart = self.fail_recovery = True
        with patch.object(identity, 'make_certificate', side_effect=self.certificate):
            with self.assertRaisesRegex(ValueError, 'local recovery'):
                identity.apply_hostname(change_id)
        self.assertEqual(identity.state_read()['status'], 'recovery-required')

    def test_preflight_failure_does_not_change_hostname_or_certificate(self):
        change_id = self.schedule()
        with patch.object(identity, 'make_certificate', side_effect=OSError('fixture failure')):
            with self.assertRaises(ValueError):
                identity.apply_hostname(change_id)
        self.assertEqual(self.host, 'cyberdeck-test-1')
        self.assertEqual((identity.TLS / 'server.key').read_text(), 'old-server.key')
        self.assertFalse(any(call[0] == 'hostnamectl' for call in self.calls))

    def test_certificate_includes_both_domains_and_keeps_ca_serial_untouched(self):
        directory = self.root / 'certificate'
        directory.mkdir()
        (directory / 'new.key').touch()
        identity.make_certificate(directory, 'family-library')
        extensions = (directory / 'server.ext').read_text()
        self.assertIn('DNS:family-library.lan,DNS:family-library.local', extensions)
        signing = next(call for call in self.calls if call[:3] == ['openssl', 'x509', '-req'])
        self.assertIn('-set_serial', signing)
        self.assertNotIn('-CAcreateserial', signing)
        self.assertIn(str(identity.TLS / 'ca.key'), signing)

    def test_explicit_recovery_restores_only_the_latest_record(self):
        change_id = self.schedule()
        with patch.object(identity, 'make_certificate', side_effect=self.certificate):
            identity.apply_hostname(change_id)
        with patch.object(identity, 'require_platform') as require:
            identity.restore_hostname(change_id, 'family-library')
            require.assert_called_once_with('family-library')
        self.assertEqual(self.host, 'cyberdeck-test-1')
        self.assertEqual(identity.environment_host(), 'cyberdeck-test-1.lan')
        self.assertEqual(identity.state_read()['status'], 'restored')
        with patch.object(identity, 'require_platform'):
            with self.assertRaisesRegex(ValueError, 'latest'):
                identity.restore_hostname('a' * 32, self.host)

    def test_recovery_rejects_modified_destination_before_file_writes(self):
        change_id = self.schedule()
        with patch.object(identity, 'make_certificate', side_effect=self.certificate):
            identity.apply_hostname(change_id)
        metadata = identity.BACKUPS / change_id / 'state.json'
        record = json.loads(metadata.read_text())
        record['files'][0]['path'] = '/etc/shadow'
        metadata.write_text(json.dumps(record))
        with patch.object(identity, 'require_platform'), patch.object(identity, 'restore_files') as restore:
            with self.assertRaisesRegex(ValueError, 'Unexpected path'):
                identity.restore_hostname(change_id, 'family-library')
            restore.assert_not_called()
        record['files'][0]['path'] = str(identity.ENVIRONMENT)
        metadata.write_text(json.dumps(record))
        (metadata.parent / 'file-0').write_text('corrupted backup')
        with patch.object(identity, 'require_platform'), patch.object(identity, 'restore_files') as restore:
            with self.assertRaisesRegex(ValueError, 'checksum'):
                identity.restore_hostname(change_id, 'family-library')
            restore.assert_not_called()

    def test_host_preflight_requires_root_debian_and_matching_identity(self):
        # Exercise the real guard, separately from the mocked transaction fixtures.
        self.stack.close()
        with patch.object(identity.os, 'geteuid', return_value=1, create=True):
            with self.assertRaisesRegex(ValueError, 'requires root'):
                identity.require_platform()
        with patch.object(identity.os, 'geteuid', return_value=0, create=True), \
                patch.object(identity.platform, 'freedesktop_os_release', return_value={'ID': 'debian', 'VERSION_ID': '13'}), \
                patch.object(identity.socket, 'gethostname', return_value='family-library'), \
                patch.object(identity, 'environment_host', return_value='old-name.lan'):
            with self.assertRaisesRegex(ValueError, 'does not match'):
                identity.require_host()
            with self.assertRaisesRegex(ValueError, 'changed since'):
                identity.require_platform('old-name')
        with patch.object(identity.os, 'geteuid', return_value=0, create=True), \
                patch.object(identity.platform, 'freedesktop_os_release', return_value={'ID': 'ubuntu'}):
            with self.assertRaisesRegex(ValueError, 'Debian 13'):
                identity.require_platform()


if __name__ == '__main__':
    unittest.main()
