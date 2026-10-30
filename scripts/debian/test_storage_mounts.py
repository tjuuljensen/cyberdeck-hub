"""Test disk mount state and safe worker dispatch without changing any real disks."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location('storage_mount_helper', Path(__file__).with_name('storage-helper.py'))
helper = importlib.util.module_from_spec(spec)
try:
    import grp
    spec.loader.exec_module(helper)
except ModuleNotFoundError:
    with patch.dict(sys.modules, {'grp': SimpleNamespace()}):
        spec.loader.exec_module(helper)


class StorageMountTests(unittest.TestCase):
    def test_ram_and_loop_devices_are_hidden_while_unnamed_physical_disks_remain(self):
        rows = [
            {'name': '/dev/zram0', 'kname': '/dev/zram0', 'type': 'disk',
             'size': 2147483648, 'fstype': 'swap', 'mountpoints': ['[SWAP]']},
            {'name': '/dev/ram0', 'kname': '/dev/ram0', 'type': 'disk'},
            {'name': '/dev/loop0', 'type': 'loop'},
            {'name': '/dev/mmcblk0', 'type': 'disk', 'tran': 'mmc'},
            {'name': '/dev/sdb', 'type': 'disk', 'model': 'Ultra Fit', 'tran': 'usb'},
            {'name': '/dev/sdc', 'type': 'disk'},
        ]
        with patch.object(helper, 'disk_id_for', return_value=None), \
                patch.object(helper, 'has_signatures', return_value=False) as signatures:
            disks = helper.flatten_disks(rows)
        self.assertEqual([disk['device'] for disk in disks], ['/dev/mmcblk0', '/dev/sdb', '/dev/sdc'])
        self.assertEqual(signatures.call_count, 3)
        self.assertEqual(disks[-1]['model'], 'Unknown disk')

    def setUp(self):
        self.stable_id = 'usb-test-disk'
        self.uuid = '12345678-1234-1234-1234-123456789abc'
        self.mount = str(helper.MOUNT_ROOT / self.uuid)
        # resolve_disk returns these raw records, without list_disks UI flags.
        self.disk = {'stable_id': self.stable_id, 'device': '/dev/sdb',
                     'capacity_bytes': 64000000000, 'transport': 'usb', 'adoptable': True,
                     'mounts': [], 'partitions': [{'device': '/dev/sdb1', 'size_bytes': 63000000000,
                         'filesystem': 'ext4', 'uuid': self.uuid, 'mounts': [self.mount]}]}
        self.state = {'version': 1, 'disks': {self.stable_id: {
            'inventory_fingerprint': helper.disk_fingerprint(self.disk), 'mount': self.mount}}}
        self.payload = {'stable_id': self.stable_id}
        self.patches = [patch.object(helper, 'resolve_disk', return_value=self.disk),
                        patch.object(helper, 'adopted_state', return_value=self.state),
                        patch.object(helper, 'public_migration_status', return_value={'status': 'idle'})]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def test_unmount_succeeds_with_raw_record_and_checks_the_result(self):
        with patch.object(helper.os.path, 'ismount', side_effect=[True, False]), \
                patch.object(helper, 'run') as run:
            result = helper.unmount_adopted(self.payload)
        self.assertTrue(result['unmounted'])
        run.assert_called_once_with(['/usr/bin/umount', '--', self.mount], timeout=30)
        with patch.object(helper.os.path, 'ismount', return_value=True), \
                patch.object(helper, 'run'):
            with self.assertRaisesRegex(ValueError, 'still mounted'):
                helper.unmount_adopted(self.payload)

    def test_mount_uses_saved_configuration_without_formatting_or_fstab_writes(self):
        self.disk['partitions'][0]['mounts'] = []
        entry = f'UUID={self.uuid} {self.mount} ext4 defaults,nofail 0 2 # cyberdeck-storage:{self.uuid}'
        with patch.object(helper, 'fstab_lines', return_value=[entry]), \
                patch.object(helper.os.path, 'ismount', return_value=True), \
                patch.object(helper, 'run') as run, \
                patch.object(helper, 'update_fstab') as update:
            self.assertTrue(helper.mount_adopted(self.payload)['mounted'])
        run.assert_called_once_with(['/usr/bin/mount', '--', self.mount], timeout=30)
        update.assert_not_called()

    def test_mount_refuses_missing_configuration_and_changed_adoption(self):
        self.disk['partitions'][0]['mounts'] = []
        with patch.object(helper, 'fstab_lines', return_value=[]), patch.object(helper, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'configuration no longer matches'):
                helper.mount_adopted(self.payload)
        run.assert_not_called()
        self.disk['partitions'][0]['uuid'] = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        with self.assertRaisesRegex(ValueError, 'changed since adoption'):
            helper.unmount_adopted(self.payload)

    def test_other_mounted_partitions_prevent_unmount(self):
        self.disk['mounts'] = ['/another-mount']
        with patch.object(helper, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'other mounted partitions'):
                helper.unmount_adopted(self.payload)
        run.assert_not_called()

    def test_resolver_protects_system_and_active_library_disks(self):
        self.patches[0].stop()
        with patch.object(helper, 'flatten_disks', return_value=[self.disk]), \
                patch.object(helper, 'block_inventory', return_value=[]), \
                patch.object(helper, 'root_disk_paths', return_value={
                    helper.os.path.realpath(self.disk['device'])}):
            with self.assertRaisesRegex(ValueError, 'system disk'):
                helper.resolve_disk(self.stable_id)
        with patch.object(helper, 'flatten_disks', return_value=[self.disk]), \
                patch.object(helper, 'block_inventory', return_value=[]), \
                patch.object(helper, 'root_disk_paths', return_value=set()), \
                patch.object(helper, 'environment_data_root', return_value='/library'), \
                patch.object(helper.os, 'stat', return_value=SimpleNamespace(st_dev=55)), \
                patch.object(helper.os.path, 'exists', return_value=True):
            with self.assertRaisesRegex(ValueError, 'active library data root'):
                helper.resolve_disk(self.stable_id)

    def test_unmounted_disk_retains_only_its_saved_mount_location(self):
        self.disk['partitions'][0]['mounts'] = []
        with patch.object(helper, 'flatten_disks', return_value=[self.disk]), \
                patch.object(helper, 'block_inventory', return_value=[]), \
                patch.object(helper, 'root_disk_paths', return_value=set()), \
                patch.object(helper, 'environment_data_root', return_value='/library'), \
                patch.object(helper.os, 'stat', return_value=SimpleNamespace(st_dev=55)), \
                patch.object(helper.Path, 'exists', return_value=False), \
                patch.object(helper, 'read_json', return_value={}):
            disk = helper.list_disks()['disks'][0]
        self.assertIsNone(disk['mount'])
        self.assertEqual(disk['managed_mount'], self.mount)
        self.assertTrue(disk['adopted'])

    def test_web_action_queues_host_worker_instead_of_unmounting_in_sandbox(self):
        with patch.object(helper, 'read_json', return_value={}), \
                patch.object(helper, 'write_json') as write, \
                patch.object(helper, 'write_initialization_status'), \
                patch.object(helper, 'run') as run:
            self.assertEqual(helper.start_mount_action(self.payload, 'unmount')['status'], 'queued')
        write.assert_called_once_with(helper.INITIALIZE_REQUEST,
                                      {'operation': 'unmount', 'stable_id': self.stable_id}, mode=0o600)
        run.assert_called_once_with(['/usr/bin/systemctl', 'start', '--no-block',
                                    helper.EXISTING_STORAGE_UNIT], timeout=15)

    def test_busy_storage_action_is_not_replaced(self):
        with patch.object(helper, 'read_json', return_value={'status': 'initializing'}), \
                patch.object(helper, 'write_json') as write:
            with self.assertRaisesRegex(ValueError, 'Wait for the disk operation'):
                helper.start_mount_action(self.payload, 'unmount')
        write.assert_not_called()

    def test_host_worker_reports_unmount_completion_and_failure(self):
        for failure in (False, True):
            with self.subTest(failure=failure), \
                    patch.object(helper, 'read_json', return_value={**self.payload, 'operation': 'unmount'}), \
                    patch.object(helper, 'write_initialization_status') as status, \
                    patch.object(helper, 'unmount_adopted', return_value={'mount': self.mount},
                                 side_effect=ValueError('busy disk') if failure else None) as unmount:
                if failure:
                    with self.assertRaisesRegex(ValueError, 'busy disk'):
                        helper.existing_storage_worker()
                    self.assertEqual(status.call_args.args[0], 'failed')
                else:
                    helper.existing_storage_worker()
                    self.assertEqual(status.call_args.args[0], 'completed')
                unmount.assert_called_once()
                self.assertEqual(status.call_args.kwargs['operation'], 'unmount')

    def test_inventory_uses_host_mounts_even_when_service_has_stale_mount(self):
        for mounted in (False, True):
            with self.subTest(mounted=mounted):
                device = {'name': '/dev/sdb', 'maj:min': '8:16', 'children': [{
                    'name': '/dev/sdb1', 'maj:min': '8:17', 'mountpoints': ['/stale-service-mount']}]}
                host = [{'maj:min': '8:17', 'target': self.mount}] if mounted else []
                with patch.object(helper, 'run_as_json', side_effect=[
                        {'blockdevices': [device]}, {'filesystems': host}]) as run:
                    rows = helper.block_inventory()
                self.assertEqual(rows[0]['children'][0]['mountpoints'], [self.mount] if mounted else [])
                self.assertIn('--task', run.call_args.args[0])
                self.assertIn('1', run.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
