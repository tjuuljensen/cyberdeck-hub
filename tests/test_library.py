"""Offline regression checks; no package installs, real downloads or service changes."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location('library', Path(__file__).resolve().parents[1] / 'app' / 'library.py')
lib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lib)


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='cyberdeck-test-')
        self.base = Path(self.temp.name)
        self.root = self.base / 'content'
        self.manifest = self.base / 'manifest.json'
        self.asset = {'path': 'public/sample.pdf', 'url': 'https://example.invalid/sample.pdf',
                      'max_bytes': 10000, 'sha256': None, 'title': 'Sample', 'rights': 'Test fixture'}
        self.save_manifest()

    def tearDown(self):
        self.temp.cleanup()

    def save_manifest(self):
        self.manifest.write_text(json.dumps({'assets': [self.asset]}), encoding='utf-8')

    def acquire(self):
        with patch.object(lib, 'stream_download', side_effect=lambda a, p: p.write_bytes(b'%PDF-test')) as call:
            lib.fetch(self.root, self.manifest)
        return call

    def bundle(self):
        self.acquire()
        bundle = self.base / 'bundle'
        lib.shutil.copytree(self.root, bundle / 'data')
        lib.write_json(bundle / 'checksums.json', lib.tree_hashes(bundle))
        return bundle

    def test_rerun_skips_download_and_preserves_bytes(self):
        self.acquire()
        with patch.object(lib, 'stream_download', side_effect=AssertionError('must not download')):
            lib.fetch(self.root, self.manifest)
        self.assertEqual((self.root / 'public/sample.pdf').read_bytes(), b'%PDF-test')

    def test_fetch_reports_each_pdf_download_outcome(self):
        events = []
        with patch.object(lib, 'stream_download', side_effect=OSError('publisher unavailable')), \
             redirect_stdout(io.StringIO()):
            lib.fetch(self.root, self.manifest, continue_on_error=True,
                      status_callback=lambda *event: events.append(event))
        self.assertEqual(events, [('public/sample.pdf', 'downloading', ''),
                                  ('public/sample.pdf', 'failed', 'publisher unavailable')])

        events.clear()
        with patch.object(lib, 'stream_download', side_effect=lambda _asset, path: path.write_bytes(b'%PDF-test')), \
             redirect_stdout(io.StringIO()):
            lib.fetch(self.root, self.manifest, status_callback=lambda *event: events.append(event))
        self.assertEqual([event[1] for event in events], ['downloading', 'downloaded'])

    def test_imported_local_payload_is_verified_and_reused(self):
        asset = {'path': 'public/imported.pdf', 'local_payload': True,
                 'max_bytes': 10000, 'title': 'Imported PDF'}
        self.manifest.write_text(json.dumps({'assets': [asset]}), encoding='utf-8')
        payload = self.root / asset['path']
        payload.parent.mkdir(parents=True)
        payload.write_bytes(b'%PDF-imported')
        digest = lib.sha256(payload)
        lib.write_json(self.root / 'acquired.json', {
            asset['path']: lib.acquisition_record(asset, payload, digest)})
        with patch.object(lib, 'stream_download', side_effect=AssertionError('must not download')):
            lib.fetch(self.root, self.manifest)
        lib.verify_manifest(self.root, self.manifest)

    def test_missing_imported_local_payload_fails_before_download(self):
        asset = {'path': 'public/imported.pdf', 'local_payload': True,
                 'max_bytes': 10000, 'title': 'Imported PDF'}
        self.manifest.write_text(json.dumps({'assets': [asset]}), encoding='utf-8')
        payload = self.root / asset['path']
        payload.parent.mkdir(parents=True)
        payload.write_bytes(b'%PDF-imported')
        lib.write_json(self.root / 'acquired.json', {
            asset['path']: lib.acquisition_record(asset, payload, lib.sha256(payload))})
        payload.unlink()
        with patch.object(lib, 'stream_download', side_effect=AssertionError('must not download')):
            with self.assertRaisesRegex(ValueError, 'has no download source'):
                lib.fetch(self.root, self.manifest)

    def test_metadata_only_manifest_changes_refresh_without_redownload(self):
        self.acquire()
        self.asset['title'] = 'Updated sample title'
        self.asset['rights'] = 'Updated attribution note'
        self.save_manifest()
        with patch.object(lib, 'stream_download', side_effect=AssertionError('must not redownload')):
            lib.fetch(self.root, self.manifest)
        record = lib.read_json(self.root / 'acquired.json')['public/sample.pdf']
        self.assertEqual(record['asset']['title'], 'Updated sample title')
        self.assertEqual(record['asset']['rights'], 'Updated attribution note')

    def test_manifest_payload_identity_change_is_rejected(self):
        self.acquire()
        self.asset['url'] = 'https://example.invalid/another-file.pdf'
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'changed file identity'):
            lib.fetch(self.root, self.manifest)

    def test_missing_locked_content_is_reacquired_from_the_same_manifest(self):
        self.acquire()
        (self.root / 'public/sample.pdf').unlink()
        with patch.object(lib, 'stream_download', side_effect=lambda _asset, path: path.write_bytes(b'%PDF-restored')) as call:
            lib.fetch(self.root, self.manifest)
        self.assertEqual(call.call_count, 1)
        self.assertEqual((self.root / 'public/sample.pdf').read_bytes(), b'%PDF-restored')
        lib.verify_manifest(self.root, self.manifest)

    def test_missing_only_skips_unrelated_payloads_but_checks_requested_integrity(self):
        self.acquire()
        lock = lib.read_json(self.root / 'acquired.json')
        other_asset = dict(self.asset, path='public/unrelated.pdf', title='Unrelated')
        other_path = self.root / other_asset['path']
        other_path.parent.mkdir(parents=True, exist_ok=True)
        other_path.write_bytes(b'%PDF-original')
        lock[other_asset['path']] = lib.acquisition_record(
            other_asset, other_path, lib.hashlib.sha256(other_path.read_bytes()).hexdigest())
        lib.write_json(self.root / 'acquired.json', lock)
        other_path.write_bytes(b'%PDF-corrupted')
        with patch.object(lib, 'stream_download', side_effect=AssertionError('must not redownload')):
            lib.fetch(self.root, self.manifest, missing_only=True)
            lib.verify_manifest(self.root, self.manifest, missing_only=True)
        with self.assertRaisesRegex(ValueError, 'integrity failure: public/unrelated.pdf'):
            lib.verify_content(self.root)

    def test_missing_only_still_rejects_corrupt_requested_file(self):
        self.acquire()
        (self.root / 'public/sample.pdf').write_bytes(b'%PDF-corrupt')
        with self.assertRaisesRegex(ValueError, 'integrity failure: public/sample.pdf'):
            lib.fetch(self.root, self.manifest, missing_only=True)

    def test_preview_is_read_only_and_has_exact_total(self):
        output = io.StringIO()
        with patch.object(lib.urllib.request, 'urlopen', side_effect=AssertionError('no network')), \
             patch.object(Path, 'mkdir', side_effect=AssertionError('no writes')), \
             redirect_stdout(output):
            lib.plan(self.manifest)
        self.assertIn('Sample: 10,000 bytes', output.getvalue())
        self.assertIn('Fresh install free-space gate: 1,000,010,000 bytes', output.getvalue())

    def test_zim_manifest_keeps_identity_and_uses_first_party_mirror(self):
        zim = {'path': 'zim/reference_en_all_maxi_2026-08.zim',
               'url': 'https://download.kiwix.org/zim/reference/reference_en_all_maxi_2026-08.zim',
               'max_bytes': 10000, 'title': 'Reference', 'rights': 'Test fixture'}
        manifest = self.base / 'zim-manifest.json'
        manifest.write_text(json.dumps({'assets': [zim]}), encoding='utf-8')
        _, assets = lib.load_manifest(manifest)
        zim = assets[0]
        self.assertEqual(lib.urllib.parse.urlparse(zim['url']).hostname, 'download.kiwix.org')
        self.assertEqual(lib.urllib.parse.urlparse(lib.download_url(zim)).hostname,
                         'mirror.download.kiwix.org')

    def test_kiwix_load_balancer_and_mirror_urls_use_first_party_mirror(self):
        for host in ('download.kiwix.org', 'lb.download.kiwix.org',
                     'mirror.download.kiwix.org'):
            asset = {'path': 'zim/maps_en_nordics_2026-08a.zim',
                     'url': f'https://{host}/zim/maps/maps_en_nordics_2026-08a.zim'}
            self.assertEqual(lib.urllib.parse.urlparse(lib.download_url(asset)).hostname,
                             'mirror.download.kiwix.org')

    def test_aggregate_space_failure_precedes_download(self):
        extra = dict(self.asset, path='public/extra.pdf')
        self.manifest.write_text(json.dumps({'assets': [self.asset, extra]}))
        with patch.object(lib.shutil, 'disk_usage', return_value=SimpleNamespace(free=1_000_015_000)), \
             patch.object(lib, 'stream_download') as download:
            with self.assertRaisesRegex(ValueError, 'all missing assets'):
                lib.fetch(self.root, self.manifest)
        download.assert_not_called()
        self.assertFalse((self.root / 'acquired.json').exists())

    def test_zim_only_pack_gets_index_and_skips_completed_files(self):
        payload = b'ZIM\x04fixture'
        self.asset.update(path='zim/sample.zim', expected_bytes=len(payload),
                          sha256=lib.hashlib.sha256(payload).hexdigest())
        self.save_manifest()
        with patch.object(lib, 'stream_download', side_effect=lambda a, p: p.write_bytes(payload)):
            lib.fetch(self.root, self.manifest)
        self.assertTrue((self.root / 'public/index.html').is_file())
        with patch.object(lib.shutil, 'disk_usage', return_value=SimpleNamespace(free=0)), \
             patch.object(lib, 'stream_download', side_effect=AssertionError('already acquired')):
            lib.fetch(self.root, self.manifest)
        lib.verify_manifest(self.root, self.manifest)

    def test_stream_checks_zim_magic_and_exact_size(self):
        source = self.base / 'fixture.zim'
        local = dict(self.asset, path='zim/sample.zim', source_file='fixture.zim', expected_bytes=8)
        del local['url']
        with patch.object(lib, 'REPO', self.base):
            source.write_bytes(b'ZIM\x04oops!')
            with self.assertRaisesRegex(ValueError, 'byte count'):
                lib.stream_download(local, self.base / 'length.part')
            source.write_bytes(b'not-zim!')
            with self.assertRaisesRegex(ValueError, 'not a ZIM'):
                lib.stream_download(local, self.base / 'magic.part')
            source.write_bytes(b'ZIM\x04test')
            lib.stream_download(local, self.base / 'good.part')

    def test_backup_space_failure_does_not_start_copy(self):
        self.acquire()
        cache = self.root / 'recovery-packages'
        cache.mkdir()
        (cache / 'COMPLETE').write_text('fixture')
        mount = self.base / 'mount'
        mount.mkdir()
        with patch.object(lib.sys, 'platform', 'linux'), \
             patch.object(lib.subprocess, 'run'), \
             patch.object(lib, 'physical_disks', side_effect=[{'8:0'}, {'8:16'}]), \
             patch.object(lib.shutil, 'disk_usage', return_value=SimpleNamespace(free=1)), \
             patch.object(lib.shutil, 'copytree') as copy:
            with self.assertRaisesRegex(ValueError, 'backup space'):
                lib.backup(self.root, mount)
        copy.assert_not_called()
        self.assertEqual(list(mount.iterdir()), [])

    def test_additive_pack_preserves_starter_and_archives_exact_manifests(self):
        self.acquire()
        original = self.manifest.read_bytes()
        extra = dict(self.asset, path='public/extra.pdf', title='Extra')
        self.manifest.write_text(json.dumps({'id': 'extra', 'assets': [extra]}), encoding='utf-8')
        with patch.object(lib, 'stream_download', side_effect=lambda a, p: p.write_bytes(b'%PDF-extra')):
            lib.fetch(self.root, self.manifest)
        lock = lib.verify_manifest(self.root, self.manifest)
        self.assertEqual(set(lock), {'public/sample.pdf', 'public/extra.pdf'})
        snapshots = {p.read_bytes() for p in (self.root / 'manifests').iterdir()}
        self.assertEqual(snapshots, {original, self.manifest.read_bytes()})
        index = (self.root / 'public/index.html').read_text()
        self.assertIn('sample.pdf', index)
        self.assertIn('extra.pdf', index)

    def test_saved_request_does_not_claim_a_failed_pack_is_complete(self):
        self.acquire()
        extra = dict(self.asset, path='public/missing.pdf')
        self.manifest.write_text(json.dumps({'assets': [extra]}), encoding='utf-8')
        with patch.object(lib, 'stream_download', side_effect=OSError('offline')):
            with self.assertRaises(OSError):
                lib.fetch(self.root, self.manifest)
        self.assertEqual(len(list((self.root / 'manifests').iterdir())), 2)
        with self.assertRaisesRegex(ValueError, 'missing or changed'):
            lib.verify_manifest(self.root, self.manifest)
        self.assertEqual((self.root / 'public/sample.pdf').read_bytes(), b'%PDF-test')

    def test_corrupt_saved_manifest_blocks_content_verification(self):
        self.acquire()
        next((self.root / 'manifests').iterdir()).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'manifest integrity'):
            lib.verify_content(self.root)

    def test_legacy_content_without_manifest_archive_still_verifies(self):
        self.acquire()
        lib.shutil.rmtree(self.root / 'manifests')
        lib.verify_content(self.root)

    def test_offline_pack_verification_detects_changed_manifest(self):
        self.acquire()
        self.asset['title'] = 'Different revision'
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'missing or changed'):
            lib.verify_manifest(self.root, self.manifest)

    def test_corruption_blocks_reuse(self):
        self.acquire()
        (self.root / 'public/sample.pdf').write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'integrity failure'):
            lib.fetch(self.root, self.manifest)

    def test_expected_hash_mismatch_never_promotes(self):
        self.asset['sha256'] = '0' * 64
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'mismatch'):
            self.acquire()
        self.assertFalse((self.root / self.asset['path']).exists())
        self.assertFalse((self.root / (self.asset['path'] + '.part')).exists())

    def test_changed_source_cannot_overwrite(self):
        self.acquire()
        self.asset['url'] = 'https://example.invalid/changed.pdf'
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'Manifest changed'):
            lib.fetch(self.root, self.manifest)

    def test_partial_failure_never_promotes(self):
        def fail(asset, path):
            path.write_bytes(b'partial')
            raise OSError('connection lost')
        with patch.object(lib, 'stream_download', side_effect=fail):
            with self.assertRaises(OSError):
                lib.fetch(self.root, self.manifest)
        self.assertFalse((self.root / self.asset['path']).exists())
        self.assertFalse((self.root / (self.asset['path'] + '.part')).exists())

    def test_path_traversal_is_rejected(self):
        for path in ['../escape', '/absolute', 'data/../../escape', 'C:\\escape', 'data\\escape']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                lib.safe_path(self.base, path)

    def test_no_untracked_overwrite(self):
        (self.root / 'public').mkdir(parents=True)
        (self.root / self.asset['path']).write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError, 'Untracked'):
            lib.fetch(self.root, self.manifest)
        self.assertEqual((self.root / self.asset['path']).read_bytes(), b'keep')

    def test_stream_size_bound_and_format(self):
        source = self.base / 'fixture.pdf'
        source.write_bytes(b'not a PDF')
        with patch.object(lib, 'REPO', self.base):
            local = dict(self.asset, source_file='fixture.pdf')
            del local['url']
            with self.assertRaisesRegex(ValueError, 'not a PDF'):
                lib.stream_download(local, self.base / 'wrong.part')
            local['max_bytes'] = 2
            with self.assertRaisesRegex(ValueError, 'ceiling'):
                lib.stream_download(local, self.base / 'large.part')

    def test_restore_and_refuse_existing_destination(self):
        bundle = self.bundle()
        dest = self.base / 'restored'
        lib.restore(bundle, dest)
        self.assertEqual(lib.verify_content(dest), lib.verify_content(self.root))
        with self.assertRaisesRegex(ValueError, 'must not exist'):
            lib.restore(bundle, dest)

    def test_corrupt_backup_is_rejected_before_restore(self):
        bundle = self.bundle()
        (bundle / 'data/public/sample.pdf').write_bytes(b'bad')
        dest = self.base / 'restored'
        with self.assertRaisesRegex(ValueError, 'missing, changed'):
            lib.restore(bundle, dest)
        self.assertFalse(dest.exists())

    def test_extra_backup_file_and_malicious_manifest_rejected(self):
        bundle = self.bundle()
        (bundle / 'unexpected.txt').write_text('unexpected')
        with self.assertRaises(ValueError):
            lib.verify_bundle(bundle)
        lib.write_json(bundle / 'checksums.json', {'../outside': '0' * 64})
        with self.assertRaises(ValueError):
            lib.verify_bundle(bundle)

    def test_same_physical_disk_backup_rejected(self):
        with patch.object(lib.sys, 'platform', 'linux'), \
             patch.object(lib.subprocess, 'run'), \
             patch.object(lib, 'physical_disks', return_value={'8:0'}):
            with self.assertRaisesRegex(ValueError, 'separate physical disk'):
                lib.backup(self.root, self.base / 'mount')

    def test_bundle_contains_recovery_source_and_validates(self):
        self.acquire()
        cache = self.root / 'recovery-packages'
        cache.mkdir()
        (cache / 'COMPLETE').write_text('fixture')
        mount = self.base / 'mount'
        mount.mkdir()
        with patch.object(lib.sys, 'platform', 'linux'), \
             patch.object(lib.subprocess, 'run'), \
             patch.object(lib, 'physical_disks', side_effect=[{'8:0'}, {'8:16'}]):
            lib.backup(self.root, mount)
        bundle = next(mount.iterdir())
        lib.verify_bundle(bundle)
        saved_pdf = bundle / 'data' / 'public' / 'sample.pdf'
        self.assertEqual(saved_pdf.read_bytes(), b'%PDF-test')
        saved_record = lib.read_json(bundle / 'data' / 'acquired.json')['public/sample.pdf']
        self.assertEqual(saved_record['sha256'], lib.sha256(saved_pdf))
        self.assertTrue((bundle / 'source/scripts/debian/install.sh').is_file())
        self.assertTrue((bundle / 'source/scripts/debian/deploy-helper.py').is_file())
        self.assertTrue((bundle / 'source/config/debian/systemd/sleep.conf.d/90-cyberdeck.conf').is_file())
        self.assertTrue((bundle / 'source/docs/runbooks/debian-install.md').is_file())
        self.assertTrue((bundle / 'source/app/webapp.py').is_file())
        self.assertTrue((bundle / 'source/scripts/debian/admin-helper.py').is_file())
        destination = self.base / 'restored-pack'
        with patch.object(lib.urllib.request, 'urlopen', side_effect=AssertionError('no network during restore')):
            lib.restore(bundle, destination)
            lib.verify_manifest(destination, self.manifest)
        saved = next((destination / 'manifests').iterdir())
        self.assertEqual(saved.read_bytes(), self.manifest.read_bytes())


if __name__ == '__main__':
    unittest.main()
