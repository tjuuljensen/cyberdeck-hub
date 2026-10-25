"""Verify installer syntax and its no-host-change default preview."""
import os
from pathlib import Path
import shutil
import subprocess
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALLER_RELATIVE = Path('scripts') / 'debian' / 'install.sh'


def find_bash():
    """Find Bash without assuming a particular platform package layout."""
    if os.name == 'nt':
        program_files = Path(os.environ.get('ProgramFiles', r'C:\Program Files'))
        program_w6432 = Path(os.environ.get('ProgramW6432', str(program_files)))
        candidates = [
            str(program_w6432 / 'Git' / 'bin' / 'bash.exe'),
            str(program_files / 'Git' / 'bin' / 'bash.exe'),
            shutil.which('bash'),
        ]
    else:
        candidates = [shutil.which('bash')]
    for candidate in candidates:
        if not candidate or not Path(candidate).is_file():
            continue
        try:
            probe = subprocess.run([candidate, '--version'], capture_output=True,
                                   text=True, timeout=5, check=False)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if probe.returncode == 0:
            return candidate
    return None


class DebianInstallerScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bash = find_bash()
        if cls.bash is None:
            raise unittest.SkipTest('Runnable Bash is unavailable; the OS may block its startup')

    def run_installer(self, *arguments, input_data='knowledge-hub\n'):
        return subprocess.run(
            [self.bash, INSTALLER_RELATIVE.as_posix(), *arguments], cwd=REPO_ROOT,
            input=input_data, capture_output=True, text=True, timeout=20, check=False)

    def test_installer_passes_bash_syntax_check(self):
        result = subprocess.run(
            [self.bash, '-n', INSTALLER_RELATIVE.as_posix()], cwd=REPO_ROOT,
            capture_output=True, text=True, timeout=20, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cli_configuration_is_preview_only(self):
        result = self.run_installer('--hostname', 'knowledge-hub')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('PREVIEW ONLY', result.stdout)
        self.assertIn('no changes made.', result.stdout)
        self.assertIn('https://knowledge-hub.local/', result.stdout)
        self.assertIn('Persistent library data: /srv/cyberdeck', result.stdout)
        self.assertIn('Data filesystem capacity:', result.stdout)
        self.assertIn('allowlisted reboot and poweroff controls are available', result.stdout)
        self.assertIn('disable system sleep and logind idle suspend', result.stdout)
        self.assertIn('isolated HTTPS port 8445', result.stdout)
        self.assertIn('leaves the service disabled', result.stdout)

    def test_missing_options_prompt_for_server_name_without_module_prompt(self):
        result = self.run_installer(input_data='knowledge-hub\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('CyberChef hostname?', result.stderr)
        self.assertIn('https://knowledge-hub.local/', result.stdout)


if __name__ == '__main__':
    unittest.main()
