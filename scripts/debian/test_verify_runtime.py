"""Check deployment verification failures without sudo, namespaces, or host changes."""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location('verify_runtime', Path(__file__).with_name('verify-runtime.py'))
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


class VerifyRuntimeTests(unittest.TestCase):
    def check_status(self, status, denied=False):
        def run(*args):
            if args[:2] == ('systemctl', 'show'):
                return '1234'
            if args[-1] == 'firewall-status':
                return json.dumps(status)
            if denied and args[-1] == 'firewall-enable':
                raise RuntimeError('sudo: a password is required')
            return ''
        with patch.object(verifier.os, 'geteuid', return_value=0, create=True), \
                patch.object(verifier.socket, 'gethostname', return_value='test-hub'), \
                patch.object(verifier, 'run', side_effect=run) as calls:
            result = verifier.verify('test-hub')
        return result, calls

    def test_checks_status_and_change_authorization_in_live_mount_namespace(self):
        status = {'available': True, 'enabled': True, 'active': True}
        result, calls = self.check_status(status)
        self.assertEqual(result, status)
        calls.assert_any_call('nsenter', '--target', '1234', '--mount', '--',
                              'runuser', '-u', 'cyberdeck', '--', 'sudo', '-n',
                              verifier.HELPER, 'firewall-status')
        calls.assert_any_call('nsenter', '--target', '1234', '--mount', '--',
                              'runuser', '-u', 'cyberdeck', '--', 'sudo', '-n',
                              '-l', '--', verifier.HELPER, 'firewall-enable')

    def test_missing_rules_fail_even_when_the_service_is_active(self):
        with self.assertRaisesRegex(RuntimeError, 'no active rules'):
            self.check_status({'available': True, 'enabled': True, 'active': False})

    def test_missing_change_permission_fails_without_toggling_the_firewall(self):
        with self.assertRaisesRegex(RuntimeError, 'password is required'):
            self.check_status({'available': True, 'enabled': True, 'active': True}, denied=True)

    def test_disabled_module_is_verified_without_enabling_it(self):
        _, calls = self.check_status({'available': True, 'enabled': False, 'active': False})
        self.assertFalse(any(call.args[:2] == ('systemctl', 'is-enabled')
                             for call in calls.call_args_list))


if __name__ == '__main__':
    unittest.main()
