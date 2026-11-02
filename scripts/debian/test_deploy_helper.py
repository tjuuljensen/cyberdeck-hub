"""Exercise software snapshots with disposable files and mocked systemd calls."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


_helper_path = Path(__file__).with_name('deploy-helper.py')
_spec = importlib.util.spec_from_file_location('deploy_helper', _helper_path)
helper = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(helper)


class DeployHelperTests(unittest.TestCase):
    def test_snapshot_restores_managed_files_and_service_state(self):
        self.exercise_snapshot_restore(legacy=False)

    def test_legacy_snapshot_restores_desktop_settings(self):
        self.exercise_snapshot_restore(legacy=True)

    def exercise_snapshot_restore(self, legacy):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = root / 'usr/local/lib/cyberdeck'
            app.mkdir(parents=True)
            app_file = app / 'webapp.py'
            app_file.write_text('old application', encoding='utf-8')
            config = root / 'etc/cyberdeck/environment'
            config.parent.mkdir(parents=True)
            config.write_text('old configuration', encoding='utf-8')
            absent = root / 'etc/systemd/system/cyberdeck-web.service'
            desktop = root / 'etc/dconf/db/local'
            desktop.parent.mkdir(parents=True)
            desktop.write_text('old desktop configuration', encoding='utf-8')
            current_trees = (app, config.parent)
            with patch.object(helper, 'BACKUP_ROOT', root / 'backups'), \
                    patch.object(helper, 'TREE_PATHS', current_trees), \
                    patch.object(helper, 'FILE_PATHS', (absent,)), \
                    patch.object(helper, 'LEGACY_DESKTOP_PATHS', (desktop,)), \
                    patch.object(helper, 'SERVICE_NAMES', ('cyberdeck-web.service', 'cyberdeck-firewall.service')), \
                    patch.object(helper, 'require_root'), \
                    patch.object(helper, 'service_state', return_value={'enabled': 'enabled', 'active': 'active'}), \
                    patch.object(helper.os, 'chown', create=True), \
                    patch.object(helper.shutil, 'which', return_value='/usr/bin/dconf'), \
                    patch.object(helper, 'run') as run, \
                    redirect_stdout(io.StringIO()):
                snapshot_trees = (*current_trees, desktop) if legacy else current_trees
                with patch.object(helper, 'TREE_PATHS', snapshot_trees):
                    deployment_id = helper.snapshot('family-library')
                state = json.loads((root / 'backups' / deployment_id / 'state.json').read_text())
                self.assertEqual(str(desktop) in {row['path'] for row in state['assets']}, legacy)
                desktop.write_text('new desktop configuration', encoding='utf-8')
                app_file.write_text('new application', encoding='utf-8')
                config.write_text('new configuration', encoding='utf-8')
                absent.parent.mkdir(parents=True)
                absent.write_text('created during deployment', encoding='utf-8')
                helper.restore('family-library', deployment_id)

            self.assertEqual(app_file.read_text(encoding='utf-8'), 'old application')
            self.assertEqual(config.read_text(encoding='utf-8'), 'old configuration')
            self.assertFalse(absent.exists())
            run.assert_any_call('systemctl', 'daemon-reload')
            if legacy:
                self.assertEqual(desktop.read_text(encoding='utf-8'), 'old desktop configuration')
                run.assert_any_call('dconf', 'update')
            else:
                self.assertEqual(desktop.read_text(encoding='utf-8'), 'new desktop configuration')
                self.assertFalse(any(call.args[0] == 'dconf' for call in run.call_args_list))
            run.assert_any_call('systemctl', 'enable', 'cyberdeck-web.service', check=False)
            run.assert_any_call('systemctl', 'restart', 'cyberdeck-web.service', check=False)
            run.assert_any_call('systemctl', 'enable', 'cyberdeck-firewall.service', check=False)
            run.assert_any_call('systemctl', 'restart', 'cyberdeck-firewall.service', check=False)

    def test_snapshot_rejects_symlinks_in_managed_tree(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = root / 'app'
            app.mkdir()
            link = app / 'unexpected-link'
            link.symlink_to(root / 'target')
            with patch.object(helper, 'BACKUP_ROOT', root / 'backups'), \
                    patch.object(helper, 'TREE_PATHS', (app,)), \
                    patch.object(helper, 'FILE_PATHS', ()), \
                    patch.object(helper, 'SERVICE_NAMES', ()), \
                    patch.object(helper, 'require_root'), \
                    patch.object(helper.os, 'chown', create=True):
                with self.assertRaisesRegex(RuntimeError, 'symlink'):
                    helper.snapshot('family-library')


if __name__ == '__main__':
    unittest.main()
