"""Tests for read-only Wi-Fi radio, rfkill, and firmware diagnostics."""
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


DIAGNOSTICS_PATH = Path(__file__).with_name('wifi-diagnostics.py')
REPO_ROOT = DIAGNOSTICS_PATH.parents[2]
SPEC = importlib.util.spec_from_file_location('wifi_diagnostics', DIAGNOSTICS_PATH)
wifi = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wifi)


class NetworkManagerRadioTests(unittest.TestCase):
    def test_reports_wifi_disabled_separately_from_hardware_radio(self):
        completed = SimpleNamespace(returncode=0, stdout='enabled:disabled\n', stderr='')
        with patch.object(wifi.shutil, 'which', return_value='/usr/bin/nmcli'), \
                patch.object(wifi, 'run', return_value=completed) as run:
            status = wifi.networkmanager_radio_status()
        self.assertEqual(status, {'hardware': 'enabled', 'wifi': 'disabled'})
        run.assert_called_once_with(['/usr/bin/nmcli', '-t', '-f', 'WIFI-HW,WIFI', 'radio'])

    def test_unavailable_nmcli_state_is_not_reported_as_enabled(self):
        completed = SimpleNamespace(returncode=1, stdout='', stderr='NetworkManager unavailable')
        with patch.object(wifi.shutil, 'which', return_value='/usr/bin/nmcli'), \
                patch.object(wifi, 'run', return_value=completed):
            self.assertIsNone(wifi.networkmanager_radio_status())

    def test_disabled_radio_guidance_suggests_explicit_enable_command(self):
        messages = wifi.radio_guidance({'hardware': 'enabled', 'wifi': 'disabled'})
        self.assertIn('sudo nmcli radio wifi on', '\n'.join(messages))


class RfkillTests(unittest.TestCase):
    def test_reads_soft_and_hard_blocks_without_rfkill_executable(self):
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as directory:
            root = Path(directory)
            radio = root / 'rfkill0'
            radio.mkdir()
            (radio / 'name').write_text('phy0', encoding='utf-8')
            (radio / 'type').write_text('wlan', encoding='utf-8')
            (radio / 'soft').write_text('1', encoding='ascii')
            (radio / 'hard').write_text('0', encoding='ascii')
            self.assertEqual(wifi.rfkill_status(root), [{
                'name': 'phy0', 'type': 'wlan',
                'soft_blocked': 'yes', 'hard_blocked': 'no',
            }])


if __name__ == '__main__':
    unittest.main()
