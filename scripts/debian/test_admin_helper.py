"""Focused tests for hotspot adapter selection and NetworkManager errors."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('admin_helper', Path(__file__).with_name('admin-helper.py'))
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class HotspotHelperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.profile = Path(self.temp.name) / 'cyberdeck-hotspot.nmconnection'
        self.upstreams = Path(self.temp.name) / 'upstreams.json'
        self.redundancy = Path(self.temp.name) / 'redundancy-minutes'
        self.fallback_state = Path(self.temp.name) / 'hotspot-fallback.json'
        self.module_disabled = Path(self.temp.name) / 'hotspot-module-disabled'
        self.profile_patcher = patch.object(helper, 'PROFILE', self.profile)
        self.profile_patcher.start()
        self.upstreams_patcher = patch.object(helper, 'UPSTREAMS', self.upstreams)
        self.upstreams_patcher.start()
        self.redundancy_patcher = patch.object(helper, 'REDUNDANCY_MINUTES', self.redundancy)
        self.redundancy_patcher.start()
        self.fallback_state_patcher = patch.object(helper, 'FALLBACK_STATE', self.fallback_state)
        self.fallback_state_patcher.start()
        self.module_disabled_patcher = patch.object(helper, 'HOTSPOT_MODULE_DISABLED', self.module_disabled)
        self.module_disabled_patcher.start()

    def tearDown(self):
        self.profile_patcher.stop()
        self.upstreams_patcher.stop()
        self.redundancy_patcher.stop()
        self.fallback_state_patcher.stop()
        self.module_disabled_patcher.stop()
        self.temp.cleanup()

    def test_web_service_sandbox_allows_root_helper_networkmanager_writes(self):
        service = Path(__file__).parents[2] / 'config/debian/systemd/cyberdeck-web.service'
        contents = service.read_text(encoding='utf-8')
        self.assertIn('BindPaths=@CYBERDECK_ROOT@', contents)
        self.assertIn('ReadWritePaths=/etc/cyberdeck /run/cyberdeck-storage /run/cyberdeck-web', contents)
        self.assertIn('ReadWritePaths=-/etc/NetworkManager/system-connections -/etc/NetworkManager/dnsmasq-shared.d', contents)
        self.assertIn('/run/cyberdeck-storage', contents)
        tmpfiles = Path(__file__).parents[2] / 'config/debian/tmpfiles.d/cyberdeck-storage.conf'
        self.assertIn('d /run/cyberdeck-storage 0750 root cyberdeck -',
                      tmpfiles.read_text(encoding='utf-8'))

    def test_cyberchef_status_requires_verified_marker_and_reports_service_state(self):
        root = Path(self.temp.name) / 'cyberchef'
        root.mkdir()
        (root / 'index.html').write_text('CyberChef', encoding='utf-8')
        (root / 'cyberdeck-module.json').write_text(
            '{"name":"cyberchef","build":"' + 'a' * 40 +
            '","archive_sha256":"' + 'b' * 64 + '"}', encoding='utf-8')
        with patch.object(helper, 'CYBERCHEF_ROOT', root), patch.object(helper, 'run',
                side_effect=[SimpleNamespace(returncode=1), SimpleNamespace(returncode=0)]) as run:
            self.assertEqual(helper.cyberchef_status(),
                             {'installed': True, 'enabled': False, 'active': True})
        self.assertEqual(run.call_args_list[0].args[0],
                         ['systemctl', 'is-enabled', '--quiet', helper.CYBERCHEF_SERVICE])
        self.assertEqual(run.call_args_list[1].args[0],
                         ['systemctl', 'is-active', '--quiet', helper.CYBERCHEF_SERVICE])

    def test_cyberchef_toggle_uses_only_fixed_service_actions(self):
        root = Path(self.temp.name) / 'cyberchef'
        root.mkdir()
        (root / 'index.html').write_text('CyberChef', encoding='utf-8')
        (root / 'cyberdeck-module.json').write_text(
            '{"name":"cyberchef","build":"' + 'a' * 40 +
            '","archive_sha256":"' + 'b' * 64 + '"}', encoding='utf-8')
        with patch.object(helper, 'CYBERCHEF_ROOT', root), patch.object(helper, 'run',
                side_effect=[SimpleNamespace(returncode=0), SimpleNamespace(returncode=0),
                             SimpleNamespace(returncode=0)]) as run:
            state = helper.cyberchef_set_enabled(True)
        self.assertTrue(state['enabled'] and state['active'])
        self.assertEqual(run.call_args_list[0].args[0],
                         ['systemctl', 'enable', '--now', helper.CYBERCHEF_SERVICE])
        with patch.object(helper, 'CYBERCHEF_ROOT', root), patch.object(helper, 'run',
                side_effect=[SimpleNamespace(returncode=0), SimpleNamespace(returncode=0),
                             SimpleNamespace(returncode=0)]) as run:
            helper.cyberchef_set_enabled(False)
        self.assertEqual(run.call_args_list[0].args[0],
                         ['systemctl', 'disable', '--now', helper.CYBERCHEF_SERVICE])

    def test_status_does_not_report_off_when_networkmanager_fails(self):
        with patch.object(helper, 'wifi_devices', return_value=[]), \
                patch.object(helper, 'run', return_value=SimpleNamespace(returncode=1, stdout='')):
            with self.assertRaisesRegex(ValueError, 'status unavailable'):
                helper.status()

    def test_status_requires_exact_hotspot_connection_name(self):
        with patch.object(helper, 'wifi_devices', return_value=[]), \
                patch.object(helper, 'available_upstreams', return_value=([], False)), \
                patch.object(helper, 'ethernet_carrier', return_value=False), \
                patch.object(helper, 'run') as run:
            run.return_value = SimpleNamespace(returncode=0, stdout='old-cyberdeck-hotspot\n')
            self.assertFalse(helper.status()['active'])
            run.return_value = SimpleNamespace(returncode=0, stdout='cyberdeck-hotspot\n')
            self.assertTrue(helper.status()['active'])

    def test_start_requires_saved_profile(self):
        with patch.object(helper, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'Save an SSID and password first'):
                helper.hotspot_up()
        run.assert_not_called()

    def test_saved_hotspot_password_is_read_from_the_root_profile(self):
        self.profile.write_text('[wifi-security]\nkey-mgmt=wpa-psk\npsk=secret-pass-8\n', encoding='utf-8')
        self.assertEqual(helper.hotspot_password(), 'secret-pass-8')

    def test_status_exposes_saved_ssid_but_not_the_password(self):
        self.profile.write_text('[connection]\ninterface-name=wlan1\n\n[wifi]\nssid=Home Cyberdeck\n'
                                '\n[wifi-security]\npsk=secret-pass-8\n', encoding='utf-8')
        with patch.object(helper, 'wifi_devices', return_value=[]), \
                patch.object(helper, 'ethernet_carrier', return_value=False), \
                patch.object(helper, 'available_upstreams', return_value=([], False)), \
                patch.object(helper, 'run', return_value=SimpleNamespace(returncode=0, stdout='')):
            result = helper.status()
        self.assertEqual(result['ssid'], 'Home Cyberdeck')
        self.assertNotIn('password', result)

    def test_saved_hotspot_password_refuses_missing_profile(self):
        with self.assertRaisesRegex(ValueError, 'not configured'):
            helper.hotspot_password()

    def test_start_reports_networkmanager_activation_error(self):
        self.profile.write_text('[connection]\ninterface-name=wlan1\n', encoding='utf-8')
        with patch.object(helper, 'wifi_devices', return_value=[{'device': 'wlan1'}]), \
                patch.object(helper.host_identity, 'prepare_dns'), \
                patch.object(helper, 'ap_supported', return_value=True), \
                patch.object(helper, 'run', return_value=SimpleNamespace(returncode=10, stderr='No such connection')):
            with self.assertRaisesRegex(ValueError, 'No such connection'):
                helper.hotspot_up()

    def test_start_explains_unavailable_networkmanager_adapter(self):
        device = 'wlx00147c670659'
        self.profile.touch()
        with patch.object(helper, 'selected_device', return_value=device), \
                patch.object(helper, 'wifi_devices', return_value=[{'device': device, 'state': 'unavailable'}]), \
                patch.object(helper, 'ap_supported', return_value=True), \
                patch.object(helper, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'is unavailable in NetworkManager'):
                helper.hotspot_up()
        run.assert_not_called()

    def test_start_runs_profile_on_selected_adapter(self):
        device = 'wlan1'
        self.profile.write_text(f'[connection]\ninterface-name={device}\n', encoding='utf-8')
        with patch.object(helper, 'wifi_devices', return_value=[{'device': device}]), \
                patch.object(helper.host_identity, 'prepare_dns') as dns, \
                patch.object(helper, 'ap_supported', return_value=True), \
                patch.object(helper, 'run', return_value=SimpleNamespace(returncode=0, stderr='', stdout='activated')) as run:
            self.assertEqual(helper.hotspot_up(), 'activated')
        run.assert_called_once_with(['nmcli', 'connection', 'up', 'id', 'cyberdeck-hotspot', 'ifname', device], check=False)
        dns.assert_called_once_with(device)

    def test_dns_failure_prevents_hotspot_activation(self):
        self.profile.write_text('[connection]\ninterface-name=wlan1\n', encoding='utf-8')
        with patch.object(helper, 'wifi_devices', return_value=[{'device': 'wlan1'}]), \
                patch.object(helper, 'ap_supported', return_value=True), \
                patch.object(helper.host_identity, 'prepare_dns', side_effect=ValueError('DNS validation failed')), \
                patch.object(helper, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'DNS validation failed'):
                helper.hotspot_up()
        run.assert_not_called()

    def test_configure_binds_profile_to_selected_adapter(self):
        autostart = Path(self.temp.name) / 'autostart'
        with patch.object(helper, 'AUTOSTART', autostart), \
                patch.object(helper, 'wifi_devices', return_value=[{'device': 'wlan0'}, {'device': 'wlan1'}]), \
                patch.object(helper, 'ap_supported', side_effect=lambda device: device == 'wlan1'), \
                patch.object(helper, 'run'):
            result = helper.configure({'ssid': 'Offline Library', 'password': 'secret-pass-8', 'device': 'wlan1',
                                       'upstream_ssids': ['Home Wi-Fi', 'Guest Wi-Fi']})
        self.assertTrue(result['saved'])
        self.assertIn('interface-name=wlan1', self.profile.read_text(encoding='utf-8'))
        self.assertEqual(helper.configured_upstreams(), ['Home Wi-Fi', 'Guest Wi-Fi'])

    def test_configure_rejects_adapter_without_ap_support(self):
        with patch.object(helper, 'wifi_devices', return_value=[{'device': 'wlan0'}]), \
                patch.object(helper, 'ap_supported', return_value=False):
            with self.assertRaisesRegex(ValueError, 'selected Wi-Fi adapter does not report'):
                helper.configure({'ssid': 'Offline Library', 'password': 'secret-pass-8', 'device': 'wlan0'})

    def test_configured_ssid_availability_suppresses_hotspot_fallback(self):
        self.profile.touch()
        with patch.object(helper, 'AUTOSTART') as autostart, \
                patch.object(helper, 'AUTOSTART_PAUSED') as paused, \
                patch.object(helper, 'available_upstreams', return_value=(['Home Wi-Fi'], False)), \
                patch.object(helper, 'run', return_value=SimpleNamespace(stdout='')) as run:
            autostart.exists.return_value = True
            paused.exists.return_value = False
            result = helper.hotspot_autostart()
        self.assertFalse(result['active'])
        self.assertIn('Home Wi-Fi', result['reason'])
        run.assert_called_once_with(['nmcli', '-t', '-f', 'NAME', 'connection', 'show', '--active'], check=False)

    def test_no_upstream_starts_hotspot_automatically(self):
        self.profile.touch()
        with patch.object(helper, 'AUTOSTART') as autostart, \
                patch.object(helper, 'AUTOSTART_PAUSED') as paused, \
                patch.object(helper, 'run', return_value=SimpleNamespace(stdout='')), \
                patch.object(helper, 'available_upstreams', return_value=([], False)), \
                patch.object(helper, 'hotspot_up', return_value='activated') as start:
            autostart.exists.return_value = True
            paused.exists.return_value = False
            result = helper.hotspot_autostart()
        self.assertTrue(result['active'])
        start.assert_called_once_with()

    def test_upstream_scan_failure_fails_closed(self):
        self.profile.touch()
        with patch.object(helper, 'AUTOSTART') as autostart, \
                patch.object(helper, 'AUTOSTART_PAUSED') as paused, \
                patch.object(helper, 'run', return_value=SimpleNamespace(stdout='')), \
                patch.object(helper, 'available_upstreams', return_value=([], True)), \
                patch.object(helper, 'hotspot_up') as start:
            autostart.exists.return_value = True
            paused.exists.return_value = False
            result = helper.hotspot_autostart()
        self.assertFalse(result['active'])
        self.assertIn('scan failed', result['reason'])
        start.assert_not_called()

    def test_manual_stop_pauses_automatic_restart(self):
        autostart = Path(self.temp.name) / 'autostart'
        paused = Path(self.temp.name) / 'paused'
        autostart.touch()
        with patch.object(helper, 'AUTOSTART', autostart), \
                patch.object(helper, 'AUTOSTART_PAUSED', paused), \
                patch.object(helper, 'run', return_value=SimpleNamespace(returncode=0)):
            result = helper.hotspot_stop()
        self.assertTrue(result['stopped'])
        self.assertTrue(paused.exists())

    def test_hotspot_module_disable_keeps_profile_and_autostart_dormant(self):
        autostart = Path(self.temp.name) / 'autostart'
        autostart.touch()
        self.profile.touch()
        with patch.object(helper, 'AUTOSTART', autostart), \
                patch.object(helper, 'run', return_value=SimpleNamespace(returncode=0)):
            disabled = helper.hotspot_module_set_enabled(False)
            self.assertTrue(self.module_disabled.exists())
            self.assertTrue(autostart.exists())
            self.assertTrue(self.profile.exists())
            result = helper.hotspot_autostart()
            self.assertIn('module is disabled', result['reason'])
            enabled = helper.hotspot_module_set_enabled(True)
        self.assertFalse(self.module_disabled.exists())
        self.assertTrue(autostart.exists())
        self.assertTrue(disabled['stopped'])
        self.assertTrue(enabled['enabled'])

    def test_only_configured_and_saved_wifi_networks_count_as_upstreams(self):
        responses = [
            SimpleNamespace(returncode=0, stdout='wifi-uuid:802-11-wireless\n'),
            SimpleNamespace(returncode=0, stdout=''),
            SimpleNamespace(returncode=0, stdout='yes\nHome Wi-Fi\n'),
            SimpleNamespace(returncode=0, stdout='Home Wi-Fi\nOther Network\n'),
        ]
        with patch.object(helper, 'ethernet_carrier', return_value=False), \
                patch.object(helper, 'configured_upstreams', return_value=['Home Wi-Fi']), \
                patch.object(helper, 'wifi_devices', return_value=[{'device': 'wlan0', 'state': 'disconnected'}]), \
                patch.object(helper, 'run', side_effect=responses):
            available, unknown = helper.available_upstreams()
        self.assertEqual(available, ['Home Wi-Fi'])
        self.assertFalse(unknown)


if __name__ == '__main__':
    unittest.main()
