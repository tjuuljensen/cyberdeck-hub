"""Focused security and workflow tests for the local library web application."""
import io
import hashlib
import errno
from contextlib import closing
from html.parser import HTMLParser
import json
import re
import ssl
import threading
from pathlib import Path
import sys
import tempfile
import unittest
import warnings
import zipfile
from unittest.mock import patch, Mock, MagicMock

try:
    import flask  # noqa: F401
    HAS_FLASK = True
except ModuleNotFoundError:
    HAS_FLASK = False
if HAS_FLASK:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
    import webapp


class StylesheetTests(unittest.TestCase):
    def test_online_and_rss_home_cards_use_primary_text_gradient(self):
        stylesheet = (Path(__file__).resolve().parents[1] / 'app' / 'static' /
                      'cyberdeck.css').read_text(encoding='utf-8')
        rules = re.findall(r'([^{}]+)\{([^{}]*)\}', stylesheet)
        backgrounds = {selector.strip(): declarations for selector, declarations in rules
                       if selector.strip() in {
                           '.online-cards-group .resource-home-card',
                           '.online-cards-group .resource-home-card:hover'}}
        self.assertEqual(set(backgrounds), {
            '.online-cards-group .resource-home-card',
            '.online-cards-group .resource-home-card:hover'})
        for declarations in backgrounds.values():
            self.assertIn('background:linear-gradient(105deg,color-mix(in srgb,var(--text)',
                          declarations)
        resource_card = [declarations for selector, declarations in rules
                         if selector.strip() == '.resource-home-card']
        self.assertEqual(len(resource_card), 1)
        self.assertIn('border-color:var(--line)', resource_card[0])


@unittest.skipUnless(HAS_FLASK, 'Flask is required for the web application tests')
class WebAppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        webapp.DATA_ROOT = root / 'data'
        webapp.PRIVATE_ROOT = webapp.DATA_ROOT / 'private'
        webapp.DB_PATH = webapp.PRIVATE_ROOT / 'metadata.sqlite3'
        webapp.STARTER_MANIFEST = root / 'starter.json'
        webapp.STARTER_MANIFEST.write_text(json.dumps({'assets': []}), encoding='utf-8')
        webapp.app.secret_key = b'test-only-session-key-that-is-not-used-on-host'
        webapp.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        self.client = webapp.app.test_client()
        with webapp.connect_db() as db:
            db.execute('INSERT INTO admin(username,password_hash) VALUES(?,?)',
                       ('owner', webapp.generate_password_hash('correct horse battery staple')))
            db.execute('INSERT INTO library_subject(id,title,description,display_order) '
                       'VALUES(?,?,?,?)',
                       ('computing-docs', 'Computing and recovery',
                        'Computing documentation and recovery references.', 90))
            db.commit()
        db.close()  # sqlite's transaction context does not close the Windows file handle.
        # Keep worker and host-command subprocesses inert in workstation tests.
        # subprocess.run uses Popen as a context manager, so the fake must expose
        # the process methods that run() expects as well as the worker PID.
        self.fake_process = MagicMock()
        self.fake_process.pid = 123
        self.fake_process.__enter__.return_value = self.fake_process
        self.fake_process.__exit__.return_value = False
        self.fake_process.communicate.return_value = (b'', b'')
        self.fake_process.returncode = 0
        self.fake_process.poll.return_value = 0
        self.fake_process.wait.return_value = 0
        self.pdf_worker_patcher = patch.object(
            webapp.subprocess, 'Popen', return_value=self.fake_process)
        self.pdf_worker_patcher.start()
        self.csrf = self.login()

    def tearDown(self):
        self.pdf_worker_patcher.stop()
        self.temp.cleanup()

    def use_data_root(self, root, include_computing_subject=False):
        webapp.DATA_ROOT = Path(root) / 'data'
        webapp.PRIVATE_ROOT = webapp.DATA_ROOT / 'private'
        webapp.DB_PATH = webapp.PRIVATE_ROOT / 'metadata.sqlite3'
        with closing(webapp.connect_db()) as db:
            db.execute('INSERT OR IGNORE INTO admin(username,password_hash) VALUES(?,?)',
                       ('owner', webapp.generate_password_hash('correct horse battery staple')))
            if include_computing_subject:
                db.execute('INSERT OR IGNORE INTO library_subject(id,title,description,display_order) '
                           'VALUES(?,?,?,?)',
                           ('computing-docs', 'Computing and recovery',
                            'Computing documentation and recovery references.', 90))
            db.commit()

    def login(self):
        response = self.client.get('/login', base_url='https://localhost')
        self.assertEqual(response.status_code, 200)
        with self.client.session_transaction(base_url='https://localhost') as saved:
            token = saved['csrf']
        response = self.client.post('/login', data={'username': 'owner',
                                'password': 'correct horse battery staple', 'csrf_token': token},
                                base_url='https://localhost')
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction(base_url='https://localhost') as saved:
            return saved['csrf']  # Login rotates the token.

    def test_cli_registers_admin_and_worker_commands(self):
        admin = webapp.build_cli().parse_args(['create-admin', 'admin'])
        worker = webapp.build_cli().parse_args(['fetch-zim', 'request-id'])
        pdf_worker = webapp.build_cli().parse_args(['fetch-import-pdfs', '--request-id', 'a' * 32])
        self.assertEqual((admin.command, admin.username), ('create-admin', 'admin'))
        self.assertEqual((worker.command, worker.zim_id), ('fetch-zim', 'request-id'))
        self.assertEqual((pdf_worker.command, pdf_worker.request_id), ('fetch-import-pdfs', 'a' * 32))

    def test_local_search_matches_catalogue_metadata_and_bounds_query(self):
        db = webapp.connect_db()
        try:
            db.execute('INSERT INTO item(id,title,description,subject) VALUES(?,?,?,?)',
                       ('water-guide', 'Water storage guide', 'Household drinking water', 'preparedness'))
            db.execute('INSERT INTO attachment(id,item_id,filename,stored_path,kind) VALUES(?,?,?,?,?)',
                       ('water-pdf', 'water-guide', 'water-storage.pdf',
                        'private/water-storage.pdf', 'pdf'))
            db.commit()
        finally:
            db.close()
        result = self.client.get('/search?q=water', base_url='https://localhost')
        self.assertEqual(result.status_code, 200)
        self.assertIn(b'Water storage guide', result.data)
        self.assertIn(b'Preparedness', result.data)
        self.assertIn(b'water-storage.pdf', result.data)

        short = self.client.get('/search?q=w', base_url='https://localhost')
        self.assertIn(b'Enter at least two characters', short.data)
        long = self.client.get('/search?q=' + ('x' * 121), base_url='https://localhost')
        self.assertEqual(long.status_code, 400)

    def test_local_search_returns_subject_matches(self):
        result = self.client.get('/search?q=preparedness', base_url='https://localhost')
        self.assertEqual(result.status_code, 200)
        self.assertIn(b'href="/subjects/preparedness"', result.data)
        self.assertIn(b'Preparedness', result.data)

    def test_pdf_import_status_is_admin_visible_and_retry_resets_only_failures(self):
        request_id = 'a' * 32
        manifest, status_path, _log = webapp.pdf_import_paths(request_id)
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({'assets': []}), encoding='utf-8')
        webapp.library.write_json(status_path, {
            'id': request_id, 'created_at': 1, 'updated_at': 1,
            'files': [
                {'path': 'public/good.pdf', 'title': 'Good PDF', 'status': 'downloaded', 'error': ''},
                {'path': 'public/bad.pdf', 'title': 'Bad PDF', 'status': 'failed', 'error': 'HTTP 403'},
            ]})
        listing = self.client.get('/api/admin/import/pdf', base_url='https://localhost')
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.get_json()['imports'][0]['files'][1]['status'], 'failed')
        with patch.object(webapp, 'start_pdf_import_worker') as start:
            response = self.client.post(f'/api/admin/import/pdf/{request_id}/retry',
                                        headers={'X-CSRF-Token': self.csrf},
                                        base_url='https://localhost')
        self.assertEqual(response.status_code, 200)
        start.assert_called_once_with(request_id)
        refreshed = webapp.read_pdf_import_status(request_id)['files']
        self.assertEqual([item['status'] for item in refreshed], ['downloaded', 'queued'])
        self.assertEqual(refreshed[1]['error'], '')

    def test_pdf_import_status_marks_interrupted_worker_as_failed(self):
        request_id = 'b' * 32
        _manifest, status_path, _log = webapp.pdf_import_paths(request_id)
        status_path.parent.mkdir(parents=True)
        webapp.library.write_json(status_path, {
            'id': request_id, 'created_at': 1, 'updated_at': 1, 'worker_pid': 999999999,
            'files': [{'path': 'public/guide.pdf', 'title': 'Guide',
                       'status': 'downloading', 'error': ''}],
        })
        status = webapp.refresh_pdf_import_liveness(webapp.read_pdf_import_status(request_id))
        self.assertEqual(status['files'][0]['status'], 'failed')
        self.assertIn('retry is available', status['files'][0]['error'])

    def test_cyberchef_links_to_separate_port_only_for_full_install(self):
        root = Path(self.temp.name) / 'cyberchef'
        root.mkdir()
        (root / 'index.html').write_text('<!doctype html><title>CyberChef fixture</title>',
                                         encoding='utf-8')
        (root / 'cyberdeck-module.json').write_text(json.dumps({
            'name': 'cyberchef', 'build': 'a' * 40,
            'archive_sha256': 'b' * 64}), encoding='utf-8')
        env = {'CYBERDECK_RUNTIME_MODE': 'headless',
               'CYBERDECK_HOSTNAME': 'family-library.local',
               'CYBERDECK_CYBERCHEF_PORT': '8445'}
        with patch.dict(webapp.os.environ, env), patch.object(webapp, 'CYBERCHEF_ROOT', root), \
                patch.object(webapp, 'cyberchef_service_active', return_value=True):
            page = self.client.get('/', base_url='https://family-library.local')
            self.assertIn(b'href="https://family-library.local:8445/"', page.data)
            self.assertNotIn(b'href="https://chef.family-library.local/"', page.data)
            self.assertNotIn(b'CyberChef fixture', page.data)

        with patch.dict(webapp.os.environ, {**env, 'CYBERDECK_RUNTIME_MODE': 'container'}), \
                patch.object(webapp, 'CYBERCHEF_ROOT', root):
            page = self.client.get('/', base_url='https://family-library.local')
            self.assertNotIn(b'href="https://family-library.local:8445/"', page.data)

    def test_cyberchef_admin_status_and_toggle_are_full_runtime_only(self):
        with patch.dict(webapp.os.environ, {'CYBERDECK_RUNTIME_MODE': 'headless'}), \
                patch.object(webapp, 'cyberchef_module', return_value={'hostname': 'localhost'}), \
                patch.object(webapp.subprocess, 'run', side_effect=[
                    webapp.subprocess.CompletedProcess([], 1),
                    webapp.subprocess.CompletedProcess([], 1),
                ]) as systemctl, \
                patch.object(webapp, 'helper', side_effect=[
                    {'installed': True, 'enabled': True, 'active': True},
                ]) as helper:
            status = self.client.get('/api/admin/cyberchef', base_url='https://localhost')
            self.assertEqual(status.status_code, 200)
            self.assertEqual(status.get_json()['installed'], True)
            enabled = self.client.post('/api/admin/cyberchef', json={'action': 'enable'},
                headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')
            self.assertEqual(enabled.status_code, 200)
            self.assertEqual(enabled.get_json()['active'], True)
            self.assertEqual(systemctl.call_count, 2)
            self.assertEqual(helper.call_args_list[0].args, ('cyberchef-enable',))
        with patch.dict(webapp.os.environ, {'CYBERDECK_RUNTIME_MODE': 'container'}):
            unavailable = self.client.get('/api/admin/cyberchef', base_url='https://localhost')
            self.assertEqual(unavailable.status_code, 404)

    def test_cyberchef_card_remains_hidden_without_verified_module_marker(self):
        root = Path(self.temp.name) / 'cyberchef'
        root.mkdir()
        (root / 'index.html').write_text('<title>Unverified</title>', encoding='utf-8')
        env = {'CYBERDECK_RUNTIME_MODE': 'headless',
               'CYBERDECK_HOSTNAME': 'family-library.local'}
        with patch.dict(webapp.os.environ, env), patch.object(webapp, 'CYBERCHEF_ROOT', root):
            home = self.client.get('/', base_url='https://family-library.local')
            self.assertNotIn(b'href="https://family-library.local:8445/"', home.data)

    def test_public_certificate_help_and_download_after_rename(self):
        # Synthetic certificate bytes exercise encoding and fingerprint identity;
        # this test neither generates keys nor changes device trust.
        der = b'public-certificate-test-bytes'
        pem = ssl.DER_cert_to_PEM_cert(der).encode('ascii')
        certificate = Path(self.temp.name) / 'ca.crt'
        certificate.write_bytes(pem)
        anonymous = webapp.app.test_client()
        with patch.dict(webapp.os.environ, {'CYBERDECK_CA_CERT_FILE': str(certificate),
                                           'CYBERDECK_HOSTNAME': 'family-library.local'}):
            page = anonymous.get('/help/certificate')
            self.assertEqual(page.status_code, 200)
            self.assertIn(b'https://family-library.local/', page.data)
            self.assertIn(b'/trust/ca.cer', page.data)
            fingerprint = ':'.join(f'{byte:02X}' for byte in hashlib.sha256(der).digest())
            self.assertIn(fingerprint.encode(), page.data)
            self.assertIn(b'Certificate Trust Settings', page.data)
            self.assertIn(b'/help/certificate', anonymous.get('/').data)
            for extension, expected in [('cer', der), ('crt', pem)]:
                response = anonymous.get('/trust/ca.' + extension)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data, expected)
                self.assertEqual(response.mimetype, 'application/x-x509-ca-cert')
                self.assertIn('cyberdeck-local-ca.' + extension, response.headers['Content-Disposition'])
                self.assertEqual(anonymous.head('/trust/ca.' + extension).data, b'')
            self.assertEqual(anonymous.get('/trust/ca.key').status_code, 404)

    def test_container_health_endpoint_and_kiwix_index_include_verified_zims_only(self):
        self.assertEqual(self.client.get('/healthz').status_code, 200)
        archive_dir = webapp.DATA_ROOT / 'zim'
        archive_dir.mkdir(parents=True)
        (archive_dir / 'ready.zim').write_bytes(b'verified fixture')
        (archive_dir / 'failed.zim').write_bytes(b'unverified fixture')
        with closing(webapp.connect_db()) as db:
            db.execute('INSERT INTO zim(id,title,subject,filename,source_url,status) '
                       'VALUES(?,?,?,?,?,?)',
                       ('ready-id', 'Ready', 'general-reference', 'ready.zim',
                        'https://download.kiwix.org/zim/ready.zim', 'ready'))
            db.execute('INSERT INTO zim(id,title,subject,filename,source_url,status) '
                       'VALUES(?,?,?,?,?,?)',
                       ('failed-id', 'Failed', 'general-reference', 'failed.zim',
                        'https://download.kiwix.org/zim/failed.zim', 'failed: validator'))
            db.commit()
        webapp.sync_kiwix_index()
        index = (webapp.DATA_ROOT / 'kiwix-index.txt').read_text(encoding='utf-8')
        self.assertEqual(index, 'ready.zim\n')
        with closing(webapp.connect_db()) as db:
            db.execute("UPDATE zim SET status='paused' WHERE id='ready-id'")
            db.commit()
        webapp.sync_kiwix_index()
        self.assertEqual((webapp.DATA_ROOT / 'kiwix-index.txt').read_text(encoding='utf-8'), '')
        with patch.dict(webapp.os.environ, {'CYBERDECK_RUNTIME_MODE': 'container'}), \
                patch.object(webapp.subprocess, 'run') as host_process:
            self.assertIsNone(webapp.restart_kiwix())
            host_process.assert_not_called()

    def test_certificate_help_handles_missing_or_invalid_certificate(self):
        certificate = Path(self.temp.name) / 'missing.crt'
        anonymous = webapp.app.test_client()
        with patch.dict(webapp.os.environ, {'CYBERDECK_CA_CERT_FILE': str(certificate)}):
            for content in (None, b'not a certificate', b'x' * 65537):
                if content is not None:
                    certificate.write_bytes(content)
                page = anonymous.get('/help/certificate')
                self.assertEqual(page.status_code, 200)
                self.assertIn(b'certificate is unavailable', page.data)
                self.assertNotIn(b'href="/trust/ca.cer"', page.data)
                self.assertEqual(anonymous.get('/trust/ca.cer').status_code, 404)

    def test_hostname_api_requires_admin_csrf_and_exact_confirmation(self):
        with patch.object(webapp, 'helper') as helper:
            anonymous = webapp.app.test_client()
            self.assertEqual(anonymous.get('/api/admin/hostname', base_url='https://localhost').status_code, 401)
            self.assertEqual(anonymous.post('/api/admin/hostname', json={}, base_url='https://localhost').status_code, 401)
            self.assertEqual(self.client.post('/api/admin/hostname', json={}, base_url='https://localhost').status_code, 400)
            for payload in ([], {'hostname': 'bad.name', 'confirm': 'bad.name'},
                            {'hostname': 'family-library', 'confirm': 'wrong'},
                            {'hostname': 'localhost', 'confirm': 'localhost'}):
                response = self.client.post('/api/admin/hostname', json=payload,
                    headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')
                self.assertEqual(response.status_code, 400)
            helper.assert_not_called()

    def test_hostname_api_status_and_schedule(self):
        with patch.object(webapp, 'helper', return_value={'hostname': 'old-name', 'change': {}}) as helper:
            response = self.client.get('/api/admin/hostname', base_url='https://localhost')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            helper.assert_called_once_with('hostname-status')
        with patch.object(webapp, 'helper', return_value={'scheduled': True}) as helper:
            response = self.client.post('/api/admin/hostname', json={'hostname': 'family-library', 'confirm': 'family-library'},
                headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')
            self.assertEqual(response.status_code, 202)
            helper.assert_called_once_with('hostname-configure', {'hostname': 'family-library', 'confirm': 'family-library'})

    def test_hostname_change_rejects_active_download_and_returns_helper_errors(self):
        with closing(webapp.connect_db()) as db, db:
            db.execute("INSERT INTO zim(id,title,subject,filename,source_url,status) VALUES('test','Test','regional-maps','test.zim','https://example.org/test.zim','pid:123')")
        with patch.object(webapp, 'helper') as helper:
            response = self.client.post('/api/admin/hostname', json={'hostname': 'family-library', 'confirm': 'family-library'},
                headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')
            self.assertEqual(response.status_code, 409)
            helper.assert_not_called()
        with closing(webapp.connect_db()) as db, db:
            db.execute("UPDATE zim SET status='paused'")
        with patch.object(webapp, 'helper', side_effect=RuntimeError('Name already in use')):
            response = self.client.post('/api/admin/hostname', json={'hostname': 'family-library', 'confirm': 'family-library'},
                headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.get_json()['error'], 'Name already in use')

    def test_running_release_is_visible_and_versions_browser_assets(self):
        self.assertRegex(webapp.APP_VERSION, r'^0\.\d+\.\d+(?:-(?:alpha|beta|rc)\.\d+)?$')
        # A release bump must update the GUI and cache keys from one value.
        with patch.object(webapp, 'APP_VERSION', '0.2.3'):
            anonymous = webapp.app.test_client()
            for client, path, script in (
                    (anonymous, '/', 'home.js'),
                    (anonymous, '/login', None),
                    (anonymous, '/subjects/first-aid', None),
                    (self.client, '/admin', 'admin.js')):
                with self.subTest(path=path):
                    response = client.get(path, base_url='https://localhost')
                    self.assertEqual(response.status_code, 200)
                    page = response.get_data(as_text=True)
                    self.assertIn('Cyberdeck Hub v0.2.3', page)
                    self.assertIn('cyberdeck.css?v=0.2.3', page)
                    self.assertIn('i18n.js?v=0.2.3', page)
                    if script:
                        self.assertIn(script + '?v=0.2.3', page)

    def test_language_picker_persists_per_visitor_and_defaults_to_english(self):
        page = self.client.get('/', base_url='https://localhost').get_data(as_text=True)
        self.assertIn('<html lang="en"', page)
        self.assertIn('Explore by subject', page)
        changed = self.client.post('/language', data={
            'language': 'da', 'next': '/', 'csrf_token': self.csrf},
            base_url='https://localhost')
        self.assertEqual(changed.status_code, 303)
        danish = self.client.get('/', base_url='https://localhost').get_data(as_text=True)
        self.assertIn('<html lang="da"', danish)
        self.assertIn('Udforsk efter emne', danish)
        self.assertIn('Gennemse ZIM-biblioteker', danish)
        for subject_id, title, description in webapp.DEFAULT_SUBJECTS:
            translated = webapp.DEFAULT_SUBJECT_TRANSLATIONS[subject_id]['da']
            self.assertIn(translated['title'], danish)
            self.assertIn(translated['description'], danish)
        certificate_help = self.client.get('/help/certificate', base_url='https://localhost')
        self.assertEqual(certificate_help.status_code, 200)
        self.assertIn('FORBIND DIN ENHED', certificate_help.get_data(as_text=True))
        self.assertIn('Hent certifikat (.cer)', certificate_help.get_data(as_text=True))
        admin = self.client.get('/admin', base_url='https://localhost')
        self.assertEqual(admin.status_code, 200)
        self.assertIn('data-translations=', admin.get_data(as_text=True))
        self.assertNotIn('onchange=', admin.get_data(as_text=True))
        self.assertIn("language-picker select')?.addEventListener('change'",
                      (Path(webapp.__file__).resolve().parent / 'static' / 'i18n.js').read_text(encoding='utf-8'))
        # Dynamic admin text is translated in the browser from this serialized
        # catalogue; the Flask test client does not execute admin.js.
        self.assertIn('Indl\\u00e6ser aktuelt indhold...', admin.get_data(as_text=True))
        self.assertIn('Biblioteksadministration', admin.get_data(as_text=True))
        admin_html = admin.get_data(as_text=True)
        self.assertIn('Eksport og import', admin_html)
        rendered_admin = re.sub(r" data-translations='[^']*'", '', admin_html)
        for source_text in ('PORTABLE COLLECTIONS', 'Export configuration',
                            'Export name', 'Include saved display preferences',
                            'Prepare downloads', 'Import configuration',
                            'Configuration and catalogue files', 'Preview import'):
            with self.subTest(source_text=source_text):
                translated = webapp.TRANSLATIONS['da'][webapp.DEFAULT_TEXT_IDS[source_text]]
                self.assertIn(translated, rendered_admin)
                self.assertNotIn(source_text, rendered_admin)
        unsafe_next = self.client.post('/language', data={
            'language': 'en', 'next': '//example.org/', 'csrf_token': self.csrf},
            base_url='https://localhost')
        self.assertEqual(unsafe_next.headers['Location'], '/')

    def test_translation_loader_discovers_new_catalogues_and_uses_english_fallback(self):
        locale_dir = Path(self.temp.name) / 'translations'
        locale_dir.mkdir()
        (locale_dir / 'languages.json').write_text(json.dumps({
            'en': 'English', 'da': 'Dansk', 'fr': 'Français'}), encoding='utf-8')
        (locale_dir / 'en.json').write_text(json.dumps({
            'ui.0001': {'default': 'Hello', 'context': 'Greeting shown on the home page.'},
            'ui.0002': {'default': 'Goodbye', 'context': 'Closing label.'}}), encoding='utf-8')
        (locale_dir / 'da.json').write_text(json.dumps({'ui.0001': 'Hej'}), encoding='utf-8')
        (locale_dir / 'fr.json').write_text(json.dumps({'ui.0001': 'Bonjour'}), encoding='utf-8')
        languages, catalogues, defaults = webapp.load_translation_catalogues(locale_dir)
        self.assertEqual(languages['fr'], 'Français')
        with patch.object(webapp, 'SUPPORTED_LANGUAGES', languages), \
                patch.object(webapp, 'TRANSLATIONS', catalogues), \
                patch.object(webapp, 'ENGLISH_DEFAULTS', defaults), \
                patch.object(webapp, 'DEFAULT_TEXT_IDS', {value: key for key, value in defaults.items()}), \
                webapp.app.test_request_context('/'):
            webapp.session['language'] = 'fr'
            self.assertEqual(webapp.translate('ui.0001'), 'Bonjour')
            self.assertEqual(webapp.translate('ui.0002'), 'Goodbye')
            self.assertEqual(webapp.translate('Hello'), 'Bonjour')

    def test_translations_cover_ui_source_keys_and_preserve_placeholders(self):
        app_root = Path(webapp.__file__).resolve().parent
        source_keys = set()
        call_pattern = re.compile(r"\b(?:t|cyberdeckTranslate)\(\s*(['\"])(.*?)\1", re.S)
        for source_root in (app_root / 'static', app_root / 'templates'):
            for source_path in source_root.rglob('*'):
                if source_path.suffix not in {'.js', '.html'}:
                    continue
                source = source_path.read_text(encoding='utf-8')
                source_keys.update(match.group(2) for match in call_pattern.finditer(source))
        literal_ui_patterns = (
            (re.compile(r"\.(?:textContent|placeholder|title)\s*=\s*(['\"])(.*?)\1"), 2),
            (re.compile(r"\.setAttribute\(\s*(['\"])(?:aria-label|placeholder|title)\1\s*,\s*(['\"])(.*?)\2"), 3),
            (re.compile(r"\b(?:alert|confirm|prompt)\(\s*(['\"])(.*?)\1"), 2),
        )
        # Include every literal branch in conditional assignments too. A plain
        # regex for `textContent = '...'` misses ternaries, even though each
        # branch is user-visible when that state is selected.
        ui_assignment_pattern = re.compile(
            r"\.(?:textContent|placeholder|title)\s*=\s*([^;\n]+)")
        ui_string_pattern = re.compile(r"(['\"])(.*?)\1")
        non_translatable_ui_literals = {
            # Values used to choose states or join translated pieces, rather
            # than words shown to the reader.
            'zim', 'online', 'scheduled', 'applying', 'enable', 'poweroff',
            'recovery-required', ' ', ', ', ' · ',
        }
        for source_path in (app_root / 'static').glob('*.js'):
            source = source_path.read_text(encoding='utf-8')
            for pattern, value_group in literal_ui_patterns:
                source_keys.update(match.group(value_group) for match in pattern.finditer(source))
            for assignment in ui_assignment_pattern.finditer(source):
                source_keys.update(match.group(2) for match in
                                   ui_string_pattern.finditer(assignment.group(1))
                                   if match.group(2) and
                                   match.group(2) not in non_translatable_ui_literals)
        api_source = (app_root / 'webapp.py').read_text(encoding='utf-8')
        api_error_pattern = re.compile(r"jsonify\(\s*error=(?:f)?(['\"])(.*?)\1", re.S)
        source_keys.update(match.group(2) for match in api_error_pattern.finditer(api_source))
        api_warning_pattern = re.compile(r"\bwarnings\s*=\s*\[\s*(['\"])(.*?)\1", re.S)
        source_keys.update(match.group(2) for match in api_warning_pattern.finditer(api_source))

        english = webapp.TRANSLATIONS['en']
        english_texts = set(english.values())
        self.assertTrue(set(webapp.LEGACY_CARD_TEXT_MIGRATIONS).isdisjoint(english))
        self.assertNotIn('ui.0717', english)
        self.assertNotIn('ui.0723', english)
        self.assertIn('CyberChef', english_texts)
        self.assertIn('Kiwix', english_texts)
        self.assertFalse(source_keys - (english.keys() | english_texts),
                         f'UI source contains untranslated IDs or defaults: {sorted(source_keys - (english.keys() | english_texts))}')

        # The mutation-aware browser localizer also handles literal template
        # text. Catch additions that bypass t() and cyberdeckTranslate().
        # Preserve the brand, certificate subject, and machine-readable examples.
        non_translatable_literals = {
            'CYBERDECK HUB', 'Cyberdeck Hub', 'Cyberdeck Local Library CA',
            'family-library', 'water-safety', 'knowledge-hub',
        }
        uncovered_template_text = []

        class TemplateTextCoverage(HTMLParser):
            ignored_tags = {'script', 'style', 'textarea', 'pre', 'code'}
            localizable_attributes = {'aria-label', 'placeholder', 'title'}

            def __init__(self, filename):
                super().__init__()
                self.filename = filename
                self.ignored = []

            def handle_starttag(self, tag, attrs):
                if tag in self.ignored_tags:
                    self.ignored.append(tag)
                for name, value in attrs:
                    if (name in self.localizable_attributes and value and
                            '{{' not in value and value not in english_texts and
                            value not in non_translatable_literals and
                            not value.startswith(('http://', 'https://'))):
                        uncovered_template_text.append(
                            f'{self.filename} {name}={value!r}')

            def handle_endtag(self, tag):
                if tag in self.ignored_tags and tag in self.ignored:
                    self.ignored.remove(tag)

            def handle_data(self, data):
                value = data.strip()
                if (self.ignored or not value or '{{' in value or
                        value in english_texts or value in non_translatable_literals or
                        re.fullmatch(r'[\W\d_]+', value)):
                    return
                uncovered_template_text.append(f'{self.filename} text={value!r}')

        for template_path in (app_root / 'templates').glob('*.html'):
            template = template_path.read_text(encoding='utf-8')
            template = re.sub(r'{%.*?%}|{#.*?#}', '', template, flags=re.S)
            parser = TemplateTextCoverage(template_path.name)
            parser.feed(template)
        self.assertFalse(uncovered_template_text,
                         f'Template text is missing from English catalogue: {uncovered_template_text}')

        self.assertEqual(set(webapp.DEFAULT_SUBJECT_TRANSLATIONS),
                         {subject_id for subject_id, _title, _description in webapp.DEFAULT_SUBJECTS})
        for translations in webapp.DEFAULT_SUBJECT_TRANSLATIONS.values():
            self.assertIn('da', translations)
            self.assertIn('title', translations['da'])
            self.assertIn('description', translations['da'])
        for language, catalogue in webapp.TRANSLATIONS.items():
            with self.subTest(language=language):
                self.assertEqual(catalogue.keys(), english.keys())
                for key, source_text in webapp.ENGLISH_DEFAULTS.items():
                    placeholders = set(re.findall(r'{([A-Za-z_][A-Za-z0-9_]*)}', source_text))
                    translated = set(re.findall(r'{([A-Za-z_][A-Za-z0-9_]*)}', catalogue[key]))
                    self.assertEqual(translated, placeholders, f'{language}: {key}')
                if language == 'da':
                    # These are Danish loan words/proper names or formatting
                    # strings whose visible words are supplied as translated
                    # placeholders. Review any new identical English values.
                    accepted_identical = {
                        'CyberChef', 'Kiwix', 'Hotspot', 'System', 'Windows', 'Start hotspot',
                        'Stop hotspot', 'Download', '{received} / {total} ({percent}%)',
                        '{status} · {progress}', ' · {filename} · {availability}',
                        'Variant: {value}', '{device} — {state} — {support}',
                        '{action} {filename} ({size})', 'LAN', 'Wi-Fi', '{mount}',
                        '{model} · {capacity}',
                    }
                    identical = {webapp.ENGLISH_DEFAULTS[key] for key, value in english.items()
                                 if catalogue[key] == value}
                    self.assertEqual(identical, accepted_identical,
                                     f'Review identical Danish translations: {sorted(identical ^ accepted_identical)}')
        with webapp.app.test_request_context('/'):
            webapp.session['language'] = 'da'
            self.assertEqual(webapp.translate('Import would overwrite existing files: {files}',
                                              files='public/guide.pdf'),
                             'Importen ville overskrive eksisterende filer: public/guide.pdf')

    def prepare_export(self, selected, **kwargs):
        return self.client.post('/api/admin/export', json={
            'name': 'My Offline Library', 'selected': selected, **kwargs},
            headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')

    def catalogue_download(self, token):
        return self.client.post('/api/admin/export/catalogue',
            data={'csrf_token': self.csrf, 'token': token}, base_url='https://localhost')

    def export_fixture(self):
        public = webapp.DATA_ROOT / 'public'
        public.mkdir()
        (public / 'card.html').write_text('<h1>Recovery</h1>', encoding='utf-8')
        records = {
            'public/guide.pdf': {'asset': {'path': 'public/guide.pdf', 'title': 'Original',
                'collection': 'first-aid', 'url': 'https://example.org/guide.pdf',
                'max_bytes': 1000, 'sha256': 'a' * 64, 'rights': 'Retain notices'}},
            'public/card.html': {'asset': {'path': 'public/card.html', 'title': 'Recovery',
                'source_file': 'assets/hub/library-startup.html', 'collection': 'general-reference',
                'max_bytes': 1000,
                'rights': 'Project authors'}}}
        (webapp.DATA_ROOT / 'acquired.json').write_text(json.dumps(records), encoding='utf-8')
        html = io.BytesIO()
        with zipfile.ZipFile(html, 'w') as archive:
            archive.writestr('index.html', '<h1>Offline manual</h1>')
            archive.writestr('images/test.txt', 'reference')
        html.seek(0)
        response = self.client.post('/api/admin/items',
            headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost',
            data={'title': 'Reference guides', 'description': 'Notes and manuals',
                  'subject': 'computing-docs',
                  'attachments': [(io.BytesIO(b'%PDF-1.4 test'), 'cheat.pdf'),
                                  (io.BytesIO(b'PK\x03\x04 test'), 'manual.docx'), (html, 'guide.zip')],
                  'cover': (io.BytesIO(b'\x89PNG\r\n\x1a\ntest'), 'cover.png')})
        self.assertEqual(response.status_code, 201, response.data)
        return response.get_json()['id']

    def test_export_sources_preserve_metadata_overrides_and_pending_zim(self):
        item_id = self.export_fixture()
        with closing(webapp.connect_db()) as db:
            db.execute('INSERT INTO archive_metadata VALUES(?,?,?)',
                       ('guide.pdf', 'Edited guide', 'computing-docs'))
            db.execute('INSERT INTO site_setting VALUES(?,?)', ('pdf_open_mode', 'new_tab'))
            db.execute('INSERT INTO site_setting VALUES(?,?)', ('not-exportable', 'secret'))
            db.execute('INSERT INTO zim(id,title,subject,filename,source_url,status) VALUES(?,?,?,?,?,?)',
                       ('queued-test', 'Science', 'general-reference', 'science.zim',
                        'https://download.kiwix.org/zim/science.zim', 'paused'))
            db.commit()
        requests = webapp.PRIVATE_ROOT / 'requests'
        requests.mkdir()
        (requests / 'queued-test.json').write_text(json.dumps({'assets': [{
            'path': 'zim/science.zim', 'title': 'Old title',
            'url': 'https://download.kiwix.org/zim/science.zim', 'max_bytes': 500,
            'expected_bytes': 500, 'sha256': 'b' * 64, 'checksum_url': 'https://example.org/hash'}]}), encoding='utf-8')
        with patch.object(webapp.urllib.request, 'urlopen') as network:
            options = self.client.get('/api/admin/export/options', base_url='https://localhost').get_json()
            response = self.prepare_export(['asset:public/guide.pdf', 'asset:zim/science.zim'])
        network.assert_not_called()
        self.assertEqual(response.status_code, 200, response.data)
        result = response.get_json()
        self.assertEqual(result['filename'], 'my_offline_library.json')
        config = result['config']
        self.assertEqual(config['site_settings'], {'pdf_open_mode': 'new_tab'})
        self.assertNotIn('secret', json.dumps(config))
        self.assertNotIn('owner', json.dumps(config))
        self.assertEqual(config['offline_catalogues'], [])
        self.assertEqual(config['assets'][0]['title'], 'Edited guide')
        self.assertEqual(config['assets'][0]['collection'], 'computing-docs')
        self.assertEqual(config['assets'][0]['rights'], 'Retain notices')
        self.assertEqual(config['assets'][1]['title'], 'Science')
        self.assertEqual(config['assets'][1]['expected_bytes'], 500)
        manifest = Path(self.temp.name) / 'custom.json'
        manifest.write_text(json.dumps(config), encoding='utf-8')
        self.assertEqual(len(webapp.library.load_manifest(manifest)[1]), 2)
        self.assertTrue(any(e['id'] == 'item:' + item_id and e['mode'] == 'offline' for e in options))
        self.assertNotIn('site_settings', self.prepare_export(
            ['asset:public/guide.pdf'], include_settings=False).get_json()['config'])

    def test_export_local_catalogues_round_trip_payloads_metadata_and_hashes(self):
        item_id = self.export_fixture()
        prepared = self.prepare_export(['item:' + item_id, 'asset:public/card.html'])
        self.assertEqual(prepared.status_code, 200, prepared.data)
        result = prepared.get_json()
        self.assertEqual(result['config']['assets'], [])
        self.assertEqual(len(result['catalogues']), 2)
        self.assertTrue(all(name.startswith('my_offline_library-') and name.endswith('.zip')
                            for name in (item['filename'] for item in result['catalogues'])))
        self.assertTrue(any('reference_guides' in item['filename'] for item in result['catalogues']))
        for index, download in enumerate(result['catalogues']):
            response = self.catalogue_download(download['token'])
            self.assertEqual(response.status_code, 200, response.data[:200])
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            self.assertIn(download['filename'], response.headers['Content-Disposition'])
            data = response.data
            response.close()
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                metadata = json.loads(archive.read('catalogue.json'))
                self.assertEqual(metadata['entry'], result['config']['offline_catalogues'][index]['entry'])
                self.assertEqual(set(archive.namelist()), {'catalogue.json'} | {f['path'] for f in metadata['files']})
                for file in metadata['files']:
                    payload = archive.read(file['path'])
                    self.assertEqual(len(payload), file['bytes'])
                    self.assertEqual(hashlib.sha256(payload).hexdigest(), file['sha256'])
                self.assertFalse(any('sqlite' in name or 'session' in name for name in archive.namelist()))
                if index == 0:
                    self.assertEqual(len(metadata['files']), 4)  # PDF, DOCX, original HTML ZIP, cover.
                    self.assertEqual(metadata['entry']['item']['description'], 'Notes and manuals')
                    self.assertEqual(metadata['subjects'][0]['id'], 'computing-docs')

    def test_combined_configuration_import_round_trip_on_empty_library(self):
        item_id = self.export_fixture()
        with closing(webapp.connect_db()) as db:
            db.execute('INSERT INTO site_setting VALUES(?,?)', ('accent_color', '#79ace6'))
            db.commit()
        selected = ['item:' + item_id, 'asset:public/card.html', 'asset:public/guide.pdf']
        bundle = self.client.post('/api/admin/export/bundle',
            data={'name': 'Field Reference', 'include_settings': 'true', 'selected': selected},
            headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')
        self.assertEqual(bundle.status_code, 200, bundle.data[:200])
        payload = bundle.get_data()
        bundle.close()
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = archive.namelist()
            self.assertEqual(len([name for name in names if name.endswith('.json')]), 1)
            self.assertTrue(any(name.startswith('catalogues/') for name in names))

        # Switch to a clean target root while retaining an authenticated client.
        target = Path(self.temp.name) / 'fresh-target'
        self.use_data_root(target)
        preview = self.client.post('/api/admin/import/preview',
            data={'files': (io.BytesIO(payload), 'field-reference-bundle.zip')},
            headers={'X-CSRF-Token': self.csrf}, content_type='multipart/form-data',
            base_url='https://localhost')
        self.assertEqual(preview.status_code, 200, preview.get_data(as_text=True))
        plan = preview.get_json()
        self.assertEqual(plan['online_sources'], 1)
        self.assertEqual(len(plan['catalogues']), 2)
        self.assertFalse(plan['path_conflicts'])
        mapping = {subject['id']: subject['id'] for subject in plan['subjects']}
        mapping['computing-docs'] = 'preparedness'
        applied = self.client.post('/api/admin/import/apply', json={
            'token': plan['token'], 'subject_mapping': mapping, 'apply_settings': True},
            headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')
        self.assertEqual(applied.status_code, 200, applied.get_data(as_text=True))
        saved_config = webapp.PRIVATE_ROOT / 'imported-configs' / applied.get_json()['saved_config']
        imported_config = json.loads(saved_config.read_text(encoding='utf-8'))
        self.assertEqual(imported_config['assets'][0]['collection'], 'first-aid')
        imported_subjects = {catalogue['entry'].get('item', {}).get(
            'subject', catalogue['entry'].get('asset', {}).get('collection'))
            for catalogue in imported_config['offline_catalogues']}
        self.assertEqual(imported_subjects, {'preparedness', 'general-reference'})
        self.assertEqual((webapp.DATA_ROOT / 'public' / 'card.html').read_text(encoding='utf-8'), '<h1>Recovery</h1>')
        with closing(webapp.connect_db()) as db:
            imported_item = db.execute('SELECT * FROM item').fetchone()
            attachments = db.execute('SELECT * FROM attachment WHERE item_id=?',
                                     (imported_item['id'],)).fetchall()
            self.assertEqual(imported_item['title'], 'Reference guides')
            self.assertEqual(imported_item['subject'], 'preparedness')
            self.assertEqual(len(attachments), 3)
            self.assertEqual(db.execute("SELECT value FROM site_setting WHERE key='accent_color'").fetchone()[0], '#79ace6')
        item_dir = webapp.PRIVATE_ROOT / 'files' / imported_item['id']
        self.assertTrue(all((item_dir / row['stored_path']).is_file() for row in attachments))
        self.assertTrue(any(item_dir.glob('*.html/index.html')))

        # A separate unauthenticated browser session must read imported content.
        reader = webapp.app.test_client()
        subject_page = reader.get('/subjects/preparedness', base_url='https://localhost')
        self.assertEqual(subject_page.status_code, 200)
        self.assertIn(b'Reference guides', subject_page.data)
        public_card = reader.get('/library/card.html', base_url='https://localhost')
        self.assertEqual(public_card.status_code, 200)
        self.assertEqual(public_card.data, b'<h1>Recovery</h1>')
        public_card.close()
        pdf_attachment = next(row for row in attachments if row['kind'] == 'pdf')
        public_pdf = reader.get(f"/documents/{imported_item['id']}/{pdf_attachment['id']}",
                                base_url='https://localhost')
        self.assertEqual(public_pdf.status_code, 200)
        self.assertTrue(public_pdf.data.startswith(b'%PDF-'))
        public_pdf.close()
        html_attachment = next(row for row in attachments if row['kind'] == 'html-zip')
        public_viewer = reader.get(
            f"/documents/{imported_item['id']}/{html_attachment['id']}/viewer",
            base_url='https://localhost')
        self.assertEqual(public_viewer.status_code, 200)
        public_viewer.close()
        public_html = reader.get(
            f"/documents/{imported_item['id']}/{html_attachment['id']}/html/index.html",
            base_url='https://localhost')
        self.assertEqual(public_html.status_code, 200)
        self.assertEqual(public_html.data, b'<h1>Offline manual</h1>')
        public_html.close()

    def test_combined_import_rejects_duplicate_outer_zip_member_paths(self):
        item_id = self.export_fixture()
        bundle = self.client.post('/api/admin/export/bundle',
            data={'name': 'Duplicate path case', 'selected': ['item:' + item_id]},
            headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')
        self.assertEqual(bundle.status_code, 200, bundle.data[:200])
        payload = bundle.get_data()
        bundle.close()
        with zipfile.ZipFile(io.BytesIO(payload)) as source:
            members = [(info.filename, source.read(info)) for info in source.infolist()]
        duplicate_bundle = io.BytesIO()
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(duplicate_bundle, 'w') as archive:
                for name, data in members:
                    archive.writestr(name, data)
                json_name, json_data = next((name, data) for name, data in members
                                            if name.endswith('.json'))
                archive.writestr(json_name, json_data)
        duplicate_bundle.seek(0)
        response = self.client.post('/api/admin/import/preview',
            data={'files': (duplicate_bundle, 'duplicate-paths.zip')},
            headers={'X-CSRF-Token': self.csrf}, content_type='multipart/form-data',
            base_url='https://localhost')
        self.assertEqual(response.status_code, 400)
        self.assertIn('duplicate archive paths', response.get_json()['error'])

    def test_separate_catalogue_upload_rejects_duplicate_sanitized_filenames(self):
        duplicate = io.BytesIO()
        with zipfile.ZipFile(duplicate, 'w') as archive:
            archive.writestr('not-inspected-yet', 'fixture')
        payload = duplicate.getvalue()
        response = self.client.post('/api/admin/import/preview',
            data={'files': [(io.BytesIO(payload), 'same?.zip'),
                            (io.BytesIO(payload), 'same*.zip')]},
            headers={'X-CSRF-Token': self.csrf}, content_type='multipart/form-data',
            base_url='https://localhost')
        self.assertEqual(response.status_code, 400)
        self.assertIn('Duplicate catalogue upload filename', response.get_json()['error'])

    def test_separate_configuration_and_catalogue_upload_import_round_trip(self):
        self.export_fixture()
        prepared = self.prepare_export(['asset:public/guide.pdf', 'asset:public/card.html'])
        self.assertEqual(prepared.status_code, 200, prepared.data)
        result = prepared.get_json()
        config_payload = json.dumps(result['config']).encode('utf-8')
        self.assertEqual(len(result['catalogues']), 1)
        catalogue_response = self.catalogue_download(result['catalogues'][0]['token'])
        self.assertEqual(catalogue_response.status_code, 200)
        catalogue_payload = catalogue_response.get_data()
        catalogue_response.close()

        target = Path(self.temp.name) / 'separate-files-target'
        self.use_data_root(target, include_computing_subject=True)

        preview = self.client.post('/api/admin/import/preview',
            data={'files': [(io.BytesIO(config_payload), 'field-reference.json'),
                            (io.BytesIO(catalogue_payload), result['catalogues'][0]['filename'])]},
            headers={'X-CSRF-Token': self.csrf}, content_type='multipart/form-data',
            base_url='https://localhost')
        self.assertEqual(preview.status_code, 200, preview.get_data(as_text=True))
        plan = preview.get_json()
        self.assertEqual(plan['online_sources'], 1)
        self.assertEqual(len(plan['catalogues']), 1)
        self.assertFalse(plan['path_conflicts'])
        mapping = {subject['id']: subject['id'] for subject in plan['subjects']}
        applied = self.client.post('/api/admin/import/apply', json={
            'token': plan['token'], 'subject_mapping': mapping},
            headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')
        self.assertEqual(applied.status_code, 200, applied.get_data(as_text=True))

        imported_card = webapp.DATA_ROOT / 'public' / 'card.html'
        self.assertFalse((webapp.DATA_ROOT / 'public' / 'guide.pdf').exists())
        self.assertEqual(imported_card.read_text(encoding='utf-8'), '<h1>Recovery</h1>')
        saved_config = webapp.PRIVATE_ROOT / 'imported-configs' / applied.get_json()['saved_config']
        saved = json.loads(saved_config.read_text(encoding='utf-8'))
        self.assertEqual(saved['assets'][0]['url'], 'https://example.org/guide.pdf')
        records = json.loads((webapp.DATA_ROOT / 'acquired.json').read_text(encoding='utf-8'))
        self.assertTrue(records['public/card.html']['asset']['local_payload'])

    def test_starter_acquisition_manifest_previews_and_saves_as_hub_configuration(self):
        profile_path = Path(__file__).resolve().parents[1] / 'config' / 'debian' / 'starter.json'
        profile = json.loads(profile_path.read_text(encoding='utf-8'))
        preview = self.client.post('/api/admin/import/preview',
            data={'files': (io.BytesIO(json.dumps(profile).encode('utf-8')), 'starter.json')},
            headers={'X-CSRF-Token': self.csrf}, content_type='multipart/form-data',
            base_url='https://localhost')
        self.assertEqual(preview.status_code, 200, preview.get_data(as_text=True))
        plan = preview.get_json()
        self.assertEqual(plan['name'], 'Cyberdeck Hub Starter')
        self.assertEqual(plan['online_sources'], sum('url' in asset for asset in profile['assets']))
        self.assertEqual(plan['local_sources'], sum('source_file' in asset for asset in profile['assets']))
        self.assertFalse(plan['catalogues'])
        self.assertTrue(all(subject['exists'] for subject in plan['subjects']))
        mapping = {subject['id']: subject['id'] for subject in plan['subjects']}
        applied = self.client.post('/api/admin/import/apply', json={
            'token': plan['token'], 'subject_mapping': mapping},
            headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')
        self.assertEqual(applied.status_code, 200, applied.get_data(as_text=True))
        self.assertEqual(applied.get_json()['imported_catalogues'], 0)
        self.assertEqual(applied.get_json()['pending_sources'],
                         sum('url' in asset or 'source_file' in asset for asset in profile['assets']))
        saved_path = webapp.PRIVATE_ROOT / 'imported-configs' / applied.get_json()['saved_config']
        saved = json.loads(saved_path.read_text(encoding='utf-8'))
        self.assertEqual((saved['format'], saved['version'], saved['name']),
                         ('cyberdeck-config', 1, 'Cyberdeck Hub Starter'))
        self.assertTrue(any('source_file' in asset for asset in saved['assets']))
        _, saved_assets = webapp.library.load_manifest(saved_path)
        self.assertEqual(len(saved_assets), len(profile['assets']))

    def test_acquisition_profile_rejects_duplicate_subject_definitions(self):
        profile = {
            'name': 'Ambiguous profile',
            'assets': [{'path': 'public/guide.pdf', 'url': 'https://example.org/guide.pdf',
                        'max_bytes': 1000, 'collection': 'preparedness'}],
            'subjects': [
                {'id': 'preparedness', 'title': 'Preparedness'},
                {'id': 'preparedness', 'title': 'Emergency planning'},
            ],
        }
        response = self.client.post('/api/admin/import/preview',
            data={'files': (io.BytesIO(json.dumps(profile).encode('utf-8')), 'ambiguous.json')},
            headers={'X-CSRF-Token': self.csrf}, content_type='multipart/form-data',
            base_url='https://localhost')
        self.assertEqual(response.status_code, 400)
        self.assertIn('duplicate subject definitions', response.get_json()['error'])

    def test_generic_debian_starter_profile_imports_and_fetches_local_source(self):
        repo_root = Path(__file__).resolve().parents[1]
        profile = json.loads((repo_root / 'config' / 'debian' / 'starter.json').read_text(encoding='utf-8'))
        # Exercise upgrade from the empty index written by the earlier importer.
        (webapp.DATA_ROOT / 'acquired.json').write_text('{}\n', encoding='utf-8')
        preview = self.client.post('/api/admin/import/preview',
            data={'files': (io.BytesIO(json.dumps(profile).encode('utf-8')), 'starter.json')},
            headers={'X-CSRF-Token': self.csrf}, content_type='multipart/form-data',
            base_url='https://localhost')
        self.assertEqual(preview.status_code, 200, preview.get_data(as_text=True))
        plan = preview.get_json()
        self.assertEqual(plan['name'], 'Cyberdeck Hub Starter')
        mapping = {subject['id']: subject['id'] for subject in plan['subjects']}
        applied = self.client.post('/api/admin/import/apply', json={
            'token': plan['token'], 'subject_mapping': mapping},
            headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')
        self.assertEqual(applied.status_code, 200, applied.get_data(as_text=True))
        result = applied.get_json()
        self.assertEqual(result['imported_catalogues'], 0)
        self.assertEqual(result['pending_sources'], 1)
        self.assertFalse((webapp.DATA_ROOT / 'public' / 'library-startup.html').exists())
        saved_path = webapp.PRIVATE_ROOT / 'imported-configs' / result['saved_config']
        saved = json.loads(saved_path.read_text(encoding='utf-8'))
        self.assertEqual(saved['assets'][0]['source_file'], 'assets/hub/library-startup.html')
        self.assertFalse((webapp.DATA_ROOT / 'acquired.json').exists())
        webapp.library.fetch(webapp.DATA_ROOT, saved_path)
        verified = webapp.library.verify_manifest(webapp.DATA_ROOT, saved_path)
        self.assertEqual(verified['public/library-startup.html']['asset'], saved['assets'][0])
        self.assertEqual(
            (webapp.DATA_ROOT / 'public' / 'library-startup.html').read_bytes(),
            (repo_root / 'assets' / 'hub' / 'library-startup.html').read_bytes())

    def test_installed_import_profiles_list_and_download_valid_profiles_only(self):
        root = Path(self.temp.name) / 'profiles'
        root.mkdir()
        profile = {'version': 1, 'name': 'Preparedness Starter', 'reserve_bytes': 1_000_000_000,
                   'assets': [{'path': 'public/guide.pdf', 'url': 'https://example.org/guide.pdf',
                               'max_bytes': 1000, 'collection': 'general-reference'}]}
        (root / 'starter.json').write_text(json.dumps(profile), encoding='utf-8')
        (root / 'invalid.json').write_text('{not json', encoding='utf-8')
        (root / 'bad name.json').write_text(json.dumps(profile), encoding='utf-8')
        outside = Path(self.temp.name) / 'outside.json'
        outside.write_text(json.dumps(profile), encoding='utf-8')
        linked = root / 'linked.json'
        try:
            linked.symlink_to(outside)
        except (OSError, NotImplementedError):
            linked = None

        with patch.object(webapp, 'CONFIG_PROFILES_ROOT', root):
            listing = self.client.get('/api/admin/import/profiles', base_url='https://localhost')
            self.assertEqual(listing.status_code, 200)
            self.assertEqual(listing.get_json()['profiles'], [
                {'filename': 'starter.json', 'name': 'Preparedness Starter'}])
            downloaded = self.client.get('/api/admin/import/profiles/starter.json',
                                         base_url='https://localhost')
            self.assertEqual(downloaded.status_code, 200)
            self.assertEqual(downloaded.get_json()['profile'], profile)
            self.assertEqual(downloaded.headers['Cache-Control'], 'no-store')
            self.assertEqual(self.client.get('/api/admin/import/profiles/../outside.json',
                                             base_url='https://localhost').status_code, 404)
            if linked is not None:
                self.assertEqual(self.client.get('/api/admin/import/profiles/linked.json',
                                                 base_url='https://localhost').status_code, 404)

    def test_import_config_version_requires_an_integer(self):
        config = {'format': 'cyberdeck-config', 'version': 1, 'name': 'Test',
                  'assets': [], 'offline_catalogues': [], 'subjects': []}
        self.assertIs(webapp._validate_import_config(config), config)
        for invalid_version in (True, 1.0, '1'):
            with self.subTest(version=invalid_version):
                invalid = {**config, 'version': invalid_version}
                with self.assertRaisesRegex(ValueError, 'Unsupported configuration format'):
                    webapp._validate_import_config(invalid)
        with self.assertRaisesRegex(ValueError, 'reserve must be at least 1 GB'):
            webapp._validate_import_config({**config, 'reserve_bytes': 999_999_999})

    def test_import_preview_rejects_duplicate_subject_definitions(self):
        config = {'format': 'cyberdeck-config', 'version': 1, 'name': 'Duplicate subjects',
                  'assets': [], 'offline_catalogues': [],
                  'subjects': [{'id': 'preparedness', 'title': 'First'},
                               {'id': 'preparedness', 'title': 'Second'}]}
        response = self.client.post('/api/admin/import/preview',
            data={'files': (io.BytesIO(json.dumps(config).encode('utf-8')), 'duplicate.json')},
            headers={'X-CSRF-Token': self.csrf}, content_type='multipart/form-data',
            base_url='https://localhost')
        self.assertEqual(response.status_code, 400)
        self.assertIn('duplicate subject definition', response.get_json()['error'])

    def test_settings_only_import_previews_and_remaps_before_removing_subjects(self):
        manifest = {'public/field-guide.html': {'asset': {
            'path': 'public/field-guide.html', 'title': 'Field guide',
            'collection': 'preparedness'}}}
        (webapp.DATA_ROOT / 'acquired.json').write_text(json.dumps(manifest), encoding='utf-8')
        config = {'format': 'cyberdeck-config', 'version': 1, 'name': 'Updated settings',
                  'assets': [{'path': 'public/ignored.html'}],
                  'offline_catalogues': [{'filename': 'ignored.zip'}],
                  'subjects': [
                      {'id': 'first-aid', 'title': 'Emergency care',
                       'description': 'Updated first-aid references', 'display_order': 0},
                      {'id': 'survival', 'title': 'Survival skills', 'display_order': 1}],
                  'site_settings': {'accent_color': '#79ace6'}}
        preview = self.client.post('/api/admin/import/preview',
            data={'mode': 'settings_only', 'remove_omitted_subjects': 'true',
                  'files': (io.BytesIO(json.dumps(config).encode('utf-8')), 'settings.json')},
            headers={'X-CSRF-Token': self.csrf}, content_type='multipart/form-data',
            base_url='https://localhost')
        self.assertEqual(preview.status_code, 200, preview.get_data(as_text=True))
        plan = preview.get_json()
        self.assertEqual(plan['mode'], 'settings_only')
        self.assertEqual(plan['ignored_content'], {'assets': 1, 'catalogues': 1})
        self.assertEqual([item['id'] for item in plan['additions']], ['survival'])
        self.assertEqual([item['id'] for item in plan['edits']], ['first-aid'])
        self.assertIn('preparedness', {item['id'] for item in plan['omitted']})
        self.assertEqual(next(item for item in plan['omitted'] if item['id'] == 'preparedness')['assigned_items'],
                         [{'kind': 'Library file', 'title': 'Field guide'}])
        applied = self.client.post('/api/admin/import/apply', json={
            'token': plan['token'], 'subject_mapping': {'preparedness': 'survival'},
            'apply_settings': True}, headers={'X-CSRF-Token': self.csrf},
            base_url='https://localhost')
        self.assertEqual(applied.status_code, 200, applied.get_data(as_text=True))
        self.assertEqual(applied.get_json()['subjects_added'], 1)
        self.assertEqual(applied.get_json()['subjects_updated'], 1)
        with closing(webapp.connect_db()) as db:
            self.assertIsNone(db.execute("SELECT id FROM library_subject WHERE id='preparedness'").fetchone())
        self.assertEqual(json.loads((webapp.DATA_ROOT / 'acquired.json').read_text())[
            'public/field-guide.html']['asset']['collection'], 'survival')
        with closing(webapp.connect_db()) as db:
            subjects = db.execute('SELECT id,title,display_order FROM library_subject ORDER BY display_order').fetchall()
            self.assertEqual([(row['id'], row['title'], row['display_order']) for row in subjects],
                             [('first-aid', 'Emergency care', 0), ('survival', 'Survival skills', 1)])
            self.assertEqual(db.execute("SELECT value FROM site_setting WHERE key='accent_color'").fetchone()[0], '#79ace6')

    def test_settings_only_import_requires_one_json_upload(self):
        response = self.client.post('/api/admin/import/preview',
            data={'mode': 'settings_only',
                  'files': (io.BytesIO(b'{}'), 'not-settings.zip')},
            headers={'X-CSRF-Token': self.csrf}, content_type='multipart/form-data',
            base_url='https://localhost')
        self.assertEqual(response.status_code, 400)
        self.assertIn('exactly one configuration JSON', response.get_json()['error'])

    def test_import_lists_and_starts_selected_internet_pdf(self):
        config = {
            'format': 'cyberdeck-config', 'version': 1, 'name': 'Online PDF import',
            'reserve_bytes': 1_000_000_000, 'offline_catalogues': [],
            'subjects': [{'id': 'preparedness', 'title': 'Preparedness'}],
            'assets': [{
                'path': 'public/field-guide.pdf', 'title': 'Field guide',
                'collection': 'preparedness', 'url': 'https://example.org/field-guide.pdf',
                'max_bytes': 1024, 'expected_bytes': 512, 'sha256': 'a' * 64,
            }],
        }
        preview = self.client.post('/api/admin/import/preview',
            data={'files': (io.BytesIO(json.dumps(config).encode('utf-8')), 'online-pdf.json')},
            headers={'X-CSRF-Token': self.csrf}, content_type='multipart/form-data',
            base_url='https://localhost')
        self.assertEqual(preview.status_code, 200, preview.get_data(as_text=True))
        plan = preview.get_json()
        self.assertEqual(plan['online_pdf_options'], [{
            'key': 'online-pdf:public/field-guide.pdf', 'title': 'Field guide',
            'path': 'public/field-guide.pdf', 'bytes': 512, 'conflict': False,
            'update': False, 'update_path': None, 'update_paths': [],
            'duplicate': False, 'reason': '',
        }])

        with patch.object(webapp.subprocess, 'Popen') as worker:
            worker.return_value.pid = 123
            applied = self.client.post('/api/admin/import/apply', json={
                'token': plan['token'], 'subject_mapping': {'preparedness': 'preparedness'},
                'selected_online_pdfs': ['online-pdf:public/field-guide.pdf'],
            }, headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')
        self.assertEqual(applied.status_code, 200, applied.get_data(as_text=True))
        self.assertEqual(applied.get_json()['pdf_downloads_started'], 1)
        self.assertEqual(applied.get_json()['pdf_download_errors'], [])
        worker.assert_called_once()
        request_id = applied.get_json()['pdf_import_id']
        self.assertRegex(request_id, r'^[a-f0-9]{32}$')
        manifest_path, status_path, _log_path = webapp.pdf_import_paths(request_id)
        self.assertEqual(worker.call_args.args[0][-2:], ['--request-id', request_id])
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        self.assertEqual(manifest['assets'][0]['path'], 'public/field-guide.pdf')
        self.assertEqual(manifest['assets'][0]['collection'], 'preparedness')
        status = json.loads(status_path.read_text(encoding='utf-8'))
        self.assertEqual(status['files'][0]['status'], 'queued')

    def test_catalogue_zip_only_import_creates_missing_subject(self):
        self.export_fixture()
        acquired_path = webapp.DATA_ROOT / 'acquired.json'
        acquired = json.loads(acquired_path.read_text(encoding='utf-8'))
        acquired['public/card.html']['asset']['collection'] = 'computing-docs'
        acquired_path.write_text(json.dumps(acquired), encoding='utf-8')
        prepared = self.prepare_export(['asset:public/card.html'])
        self.assertEqual(prepared.status_code, 200, prepared.data)
        download = self.catalogue_download(prepared.get_json()['catalogues'][0]['token'])
        self.assertEqual(download.status_code, 200)
        payload = download.get_data()
        download.close()

        target = Path(self.temp.name) / 'zip-only-target'
        self.use_data_root(target)
        with closing(webapp.connect_db()) as db:
            db.execute('DELETE FROM library_subject WHERE id=?', ('computing-docs',))
            db.commit()
        preview = self.client.post('/api/admin/import/preview',
            data={'files': (io.BytesIO(payload), 'human-readable-catalogue.zip')},
            headers={'X-CSRF-Token': self.csrf}, content_type='multipart/form-data',
            base_url='https://localhost')
        self.assertEqual(preview.status_code, 200, preview.get_data(as_text=True))
        plan = preview.get_json()
        self.assertEqual(plan['online_sources'], 0)
        mapping = {'computing-docs': '__create__'}
        applied = self.client.post('/api/admin/import/apply', json={
            'token': plan['token'], 'subject_mapping': mapping},
            headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')
        self.assertEqual(applied.status_code, 200, applied.get_data(as_text=True))
        with closing(webapp.connect_db()) as db:
            subject = db.execute('SELECT title FROM library_subject WHERE id=?',
                                 ('computing-docs',)).fetchone()
            self.assertEqual(subject['title'], 'Computing and recovery')
        self.assertTrue((webapp.DATA_ROOT / 'public' / 'card.html').is_file())

    def test_import_cannot_create_a_subject_id_that_already_exists(self):
        self.export_fixture()
        acquired_path = webapp.DATA_ROOT / 'acquired.json'
        acquired = json.loads(acquired_path.read_text(encoding='utf-8'))
        acquired['public/card.html']['asset']['collection'] = 'computing-docs'
        acquired_path.write_text(json.dumps(acquired), encoding='utf-8')
        prepared = self.prepare_export(['asset:public/card.html'])
        self.assertEqual(prepared.status_code, 200, prepared.data)
        catalogue = self.catalogue_download(prepared.get_json()['catalogues'][0]['token'])
        self.assertEqual(catalogue.status_code, 200)
        payload = catalogue.get_data()
        catalogue.close()

        target = Path(self.temp.name) / 'existing-subject-target'
        self.use_data_root(target, include_computing_subject=True)

        preview = self.client.post('/api/admin/import/preview',
            data={'files': (io.BytesIO(payload), 'computing-catalogue.zip')},
            headers={'X-CSRF-Token': self.csrf}, content_type='multipart/form-data',
            base_url='https://localhost')
        self.assertEqual(preview.status_code, 200, preview.get_data(as_text=True))
        plan = preview.get_json()
        self.assertTrue(next(subject for subject in plan['subjects']
                             if subject['id'] == 'computing-docs')['exists'])
        applied = self.client.post('/api/admin/import/apply', json={
            'token': plan['token'], 'subject_mapping': {'computing-docs': '__create__'}},
            headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')
        self.assertEqual(applied.status_code, 409)
        self.assertEqual(applied.get_json()['error'],
                         'Subject {subject} already exists; map it to an existing subject')
        self.assertEqual(applied.get_json()['error_params'], {'subject': 'computing-docs'})
        self.assertFalse((webapp.DATA_ROOT / 'public' / 'card.html').exists())

        unmapped = self.client.post('/api/admin/import/apply', json={
            'token': plan['token'], 'subject_mapping': {}},
            headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')
        self.assertEqual(unmapped.status_code, 409)
        self.assertEqual(unmapped.get_json()['error'],
                         'Map imported subject {title} to an existing subject or create it')
        self.assertEqual(unmapped.get_json()['error_params'],
                         {'title': 'Computing and recovery'})

    def test_import_conflict_is_reported_and_never_overwritten(self):
        self.export_fixture()
        prepared = self.prepare_export(['asset:public/card.html'])
        self.assertEqual(prepared.status_code, 200, prepared.data)
        exported = prepared.get_json()
        config = json.dumps(exported['config']).encode('utf-8')
        download = exported['catalogues'][0]
        catalogue = self.catalogue_download(download['token'])
        self.assertEqual(catalogue.status_code, 200)
        catalogue_payload = catalogue.get_data()
        catalogue.close()

        target = Path(self.temp.name) / 'conflict-target'
        self.use_data_root(target, include_computing_subject=True)
        existing = webapp.DATA_ROOT / 'public' / 'card.html'
        existing.parent.mkdir(parents=True)
        existing.write_text('<h1>Keep the current file</h1>', encoding='utf-8')
        preview = self.client.post('/api/admin/import/preview',
            data={'files': [(io.BytesIO(config), 'profile.json'),
                            (io.BytesIO(catalogue_payload), download['filename'])]},
            headers={'X-CSRF-Token': self.csrf}, content_type='multipart/form-data',
            base_url='https://localhost')
        self.assertEqual(preview.status_code, 200, preview.get_data(as_text=True))
        plan = preview.get_json()
        self.assertIn('public/card.html', plan['path_conflicts'])
        mapping = {subject['id']: subject['id'] for subject in plan['subjects']}
        applied = self.client.post('/api/admin/import/apply', json={
            'token': plan['token'], 'subject_mapping': mapping},
            headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')
        self.assertEqual(applied.status_code, 409)
        self.assertEqual(applied.get_json()['error'], 'Import would overwrite existing files: {files}')
        self.assertEqual(applied.get_json()['error_params'], {'files': 'public/card.html'})
        self.assertEqual(existing.read_text(encoding='utf-8'), '<h1>Keep the current file</h1>')

    def test_document_catalogue_can_be_imported_without_overwriting_its_source_item(self):
        source_id = self.export_fixture()
        with closing(webapp.connect_db()) as db:
            source_attachments = [dict(row) for row in db.execute(
                'SELECT stored_path,filename,kind FROM attachment WHERE item_id=?', (source_id,))]
        original_payloads = {
            row['stored_path']: (webapp.PRIVATE_ROOT / 'files' / source_id / row['stored_path']).read_bytes()
            for row in source_attachments
        }
        prepared = self.prepare_export(['item:' + source_id])
        self.assertEqual(prepared.status_code, 200, prepared.data)
        catalogue = self.catalogue_download(prepared.get_json()['catalogues'][0]['token'])
        self.assertEqual(catalogue.status_code, 200)
        payload = catalogue.get_data()
        catalogue.close()

        preview = self.client.post('/api/admin/import/preview',
            data={'files': (io.BytesIO(payload), 'documents.zip')},
            headers={'X-CSRF-Token': self.csrf}, content_type='multipart/form-data',
            base_url='https://localhost')
        self.assertEqual(preview.status_code, 200, preview.get_data(as_text=True))
        plan = preview.get_json()
        self.assertFalse(plan['path_conflicts'])
        mapping = {subject['id']: subject['id'] for subject in plan['subjects']}
        applied = self.client.post('/api/admin/import/apply', json={
            'token': plan['token'], 'subject_mapping': mapping,
            'selected_documents': [option['key'] for option in plan['document_options']]},
            headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')

        self.assertEqual(applied.status_code, 200, applied.get_data(as_text=True))
        with closing(webapp.connect_db()) as db:
            items = [dict(row) for row in db.execute('SELECT id,title FROM item ORDER BY id')]
            self.assertEqual(len(items), 2)
            imported_id = next(row['id'] for row in items if row['id'] != source_id)
            imported_attachments = [dict(row) for row in db.execute(
                'SELECT stored_path,filename,kind FROM attachment WHERE item_id=?', (imported_id,))]
        self.assertEqual(
            {row['filename']: (row['kind'], (webapp.PRIVATE_ROOT / 'files' / imported_id / row['stored_path']).read_bytes())
             for row in imported_attachments},
            {row['filename']: (row['kind'], original_payloads[row['stored_path']])
             for row in source_attachments})
        self.assertEqual(
            {row['stored_path']: (webapp.PRIVATE_ROOT / 'files' / source_id / row['stored_path']).read_bytes()
             for row in source_attachments}, original_payloads)

    def test_import_rechecks_storage_before_writing_any_files(self):
        self.export_fixture()
        prepared = self.prepare_export(['asset:public/card.html'])
        self.assertEqual(prepared.status_code, 200, prepared.data)
        catalogue = self.catalogue_download(prepared.get_json()['catalogues'][0]['token'])
        self.assertEqual(catalogue.status_code, 200)
        catalogue_payload = catalogue.get_data()
        catalogue.close()

        target = Path(self.temp.name) / 'low-storage-target'
        self.use_data_root(target, include_computing_subject=True)
        preview = self.client.post('/api/admin/import/preview',
            data={'files': (io.BytesIO(catalogue_payload), 'catalogue.zip')},
            headers={'X-CSRF-Token': self.csrf}, content_type='multipart/form-data',
            base_url='https://localhost')
        self.assertEqual(preview.status_code, 200, preview.get_data(as_text=True))
        plan = preview.get_json()
        mapping = {subject['id']: subject['id'] for subject in plan['subjects']}
        with patch.object(webapp.shutil, 'disk_usage', return_value=Mock(free=0)):
            applied = self.client.post('/api/admin/import/apply', json={
                'token': plan['token'], 'subject_mapping': mapping},
                headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')

        self.assertEqual(applied.status_code, 409, applied.get_data(as_text=True))
        self.assertIn('Insufficient free library storage', applied.get_json()['error'])
        self.assertFalse((webapp.DATA_ROOT / 'public' / 'card.html').exists())
        self.assertFalse((webapp.PRIVATE_ROOT / 'imported-configs').exists())
        with closing(webapp.connect_db()) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM item').fetchone()[0], 0)

    def test_import_storage_preview_and_apply_include_extracted_html(self):
        self.export_fixture()
        options = self.client.get('/api/admin/export/options', base_url='https://localhost').get_json()
        item_id = next(entry['id'] for entry in options if entry['id'].startswith('item:'))
        prepared = self.prepare_export([item_id])
        self.assertEqual(prepared.status_code, 200, prepared.data)
        catalogue = self.catalogue_download(prepared.get_json()['catalogues'][0]['token'])
        self.assertEqual(catalogue.status_code, 200)
        catalogue_payload = catalogue.get_data()
        catalogue.close()

        target = Path(self.temp.name) / 'html-storage-target'
        self.use_data_root(target, include_computing_subject=True)
        preview = self.client.post('/api/admin/import/preview',
            data={'files': (io.BytesIO(catalogue_payload), 'documents.zip')},
            headers={'X-CSRF-Token': self.csrf}, content_type='multipart/form-data',
            base_url='https://localhost')
        self.assertEqual(preview.status_code, 200, preview.get_data(as_text=True))
        plan = preview.get_json()
        catalogue_info = plan['catalogues'][0]
        self.assertEqual(catalogue_info['expanded_html_bytes'], len('<h1>Offline manual</h1>') + len('reference'))
        self.assertGreater(plan['required_bytes'], catalogue_info['expanded_html_bytes'])
        self.assertEqual(plan['required_data_bytes'], 0)
        mapping = {subject['id']: subject['id'] for subject in plan['subjects']}
        private_free = plan['required_bytes'] - 1

        def disk_usage(path):
            free = 10**12 if Path(path) == webapp.DATA_ROOT else private_free
            return Mock(free=free)

        with patch.object(webapp.shutil, 'disk_usage', side_effect=disk_usage):
            applied = self.client.post('/api/admin/import/apply', json={
                'token': plan['token'], 'subject_mapping': mapping},
                headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')

        self.assertEqual(applied.status_code, 409, applied.get_data(as_text=True))
        self.assertIn('Insufficient free library storage', applied.get_json()['error'])
        self.assertFalse((webapp.PRIVATE_ROOT / 'imported-configs').exists())
        self.assertFalse(list((webapp.PRIVATE_ROOT / 'files').glob('*')) if
                         (webapp.PRIVATE_ROOT / 'files').exists() else [])
        with closing(webapp.connect_db()) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM item').fetchone()[0], 0)

    def test_import_disk_full_during_payload_write_rolls_back_partial_state(self):
        self.export_fixture()
        prepared = self.prepare_export(['asset:public/card.html'])
        self.assertEqual(prepared.status_code, 200, prepared.data)
        catalogue = self.catalogue_download(prepared.get_json()['catalogues'][0]['token'])
        self.assertEqual(catalogue.status_code, 200)
        catalogue_payload = catalogue.get_data()
        catalogue.close()

        target = Path(self.temp.name) / 'disk-full-target'
        self.use_data_root(target, include_computing_subject=True)
        preview = self.client.post('/api/admin/import/preview',
            data={'files': (io.BytesIO(catalogue_payload), 'catalogue.zip')},
            headers={'X-CSRF-Token': self.csrf}, content_type='multipart/form-data',
            base_url='https://localhost')
        self.assertEqual(preview.status_code, 200, preview.get_data(as_text=True))
        plan = preview.get_json()
        mapping = {subject['id']: subject['id'] for subject in plan['subjects']}

        def fill_disk_during_copy(source, destination, length=0):
            destination.write(source.read(3))
            raise OSError(errno.ENOSPC, 'No space left on device')

        with patch.object(webapp.shutil, 'copyfileobj', side_effect=fill_disk_during_copy):
            applied = self.client.post('/api/admin/import/apply', json={
                'token': plan['token'], 'subject_mapping': mapping},
                headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')

        self.assertEqual(applied.status_code, 409, applied.get_data(as_text=True))
        self.assertIn('No space left on device', applied.get_json()['error'])
        public_root = webapp.DATA_ROOT / 'public'
        self.assertFalse(public_root.exists() and any(public_root.iterdir()))
        self.assertFalse((webapp.DATA_ROOT / 'acquired.json').exists())
        self.assertFalse((webapp.PRIVATE_ROOT / 'imported-configs').exists())
        with closing(webapp.connect_db()) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM archive_metadata').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM import_transaction').fetchone()[0], 0)

    def test_same_import_preview_cannot_be_applied_concurrently(self):
        self.export_fixture()
        prepared = self.prepare_export(['asset:public/card.html'])
        self.assertEqual(prepared.status_code, 200, prepared.data)
        catalogue = self.catalogue_download(prepared.get_json()['catalogues'][0]['token'])
        self.assertEqual(catalogue.status_code, 200)
        catalogue_payload = catalogue.get_data()
        catalogue.close()

        target = Path(self.temp.name) / 'concurrent-import-target'
        self.use_data_root(target, include_computing_subject=True)
        preview = self.client.post('/api/admin/import/preview',
            data={'files': (io.BytesIO(catalogue_payload), 'catalogue.zip')},
            headers={'X-CSRF-Token': self.csrf}, content_type='multipart/form-data',
            base_url='https://localhost')
        self.assertEqual(preview.status_code, 200, preview.get_data(as_text=True))
        plan = preview.get_json()
        mapping = {subject['id']: subject['id'] for subject in plan['subjects']}

        def logged_in_client():
            client = webapp.app.test_client()
            response = client.get('/login', base_url='https://localhost')
            self.assertEqual(response.status_code, 200)
            with client.session_transaction(base_url='https://localhost') as session:
                token = session['csrf']
            response = client.post('/login', data={
                'username': 'owner', 'password': 'correct horse battery staple',
                'csrf_token': token}, base_url='https://localhost')
            self.assertEqual(response.status_code, 302)
            with client.session_transaction(base_url='https://localhost') as session:
                token = session['csrf']
            return client, token

        first_client, first_csrf = logged_in_client()
        second_client, second_csrf = logged_in_client()
        entered_validation = threading.Event()
        continue_validation = threading.Event()
        original_validate = webapp._validate_import_config
        first_result = {}

        def pause_first_validation(config):
            entered_validation.set()
            if not continue_validation.wait(10):
                raise TimeoutError('Concurrent import test did not release validation')
            return original_validate(config)

        def apply_first():
            first_result['response'] = first_client.post('/api/admin/import/apply', json={
                'token': plan['token'], 'subject_mapping': mapping},
                headers={'X-CSRF-Token': first_csrf}, base_url='https://localhost')

        with patch.object(webapp, '_validate_import_config', side_effect=pause_first_validation):
            worker = threading.Thread(target=apply_first)
            worker.start()
            self.assertTrue(entered_validation.wait(10), 'First import did not reach validation')
            rejected = second_client.post('/api/admin/import/apply', json={
                'token': plan['token'], 'subject_mapping': mapping},
                headers={'X-CSRF-Token': second_csrf}, base_url='https://localhost')
            continue_validation.set()
            worker.join(10)

        self.assertFalse(worker.is_alive(), 'First import did not finish')
        self.assertIn('response', first_result)
        self.assertEqual(first_result['response'].status_code, 200,
                         first_result['response'].get_data(as_text=True))
        self.assertEqual(rejected.status_code, 409, rejected.get_data(as_text=True))
        self.assertEqual(rejected.get_json()['error'],
                         'This configuration import is already being applied; preview the files again')
        self.assertTrue((webapp.DATA_ROOT / 'public' / 'card.html').is_file())

    def test_import_apply_failure_removes_partial_document_files(self):
        item_id = self.export_fixture()
        prepared = self.prepare_export(['item:' + item_id])
        self.assertEqual(prepared.status_code, 200, prepared.data)
        catalogue = self.catalogue_download(prepared.get_json()['catalogues'][0]['token'])
        self.assertEqual(catalogue.status_code, 200)
        catalogue_payload = catalogue.get_data()
        catalogue.close()

        target = Path(self.temp.name) / 'rollback-target'
        self.use_data_root(target, include_computing_subject=True)
        preview = self.client.post('/api/admin/import/preview',
            data={'files': [(io.BytesIO(catalogue_payload), 'document-catalogue.zip')]},
            headers={'X-CSRF-Token': self.csrf}, content_type='multipart/form-data',
            base_url='https://localhost')
        self.assertEqual(preview.status_code, 200, preview.get_data(as_text=True))
        plan = preview.get_json()
        mapping = {subject['id']: subject['id'] for subject in plan['subjects']}

        def fail_after_creating_extraction_dir(_archive, output):
            output.mkdir(parents=True)
            raise OSError('simulated extraction failure')

        with patch.object(webapp, 'validate_and_extract_zip',
                          side_effect=fail_after_creating_extraction_dir):
            applied = self.client.post('/api/admin/import/apply', json={
                'token': plan['token'], 'subject_mapping': mapping},
                headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')
        self.assertEqual(applied.status_code, 409)
        with closing(webapp.connect_db()) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM item').fetchone()[0], 0)
        files_root = webapp.PRIVATE_ROOT / 'files'
        self.assertFalse(files_root.exists() and any(files_root.iterdir()))

    def test_interrupted_import_recovery_rolls_back_uncommitted_files(self):
        transaction_id = 'a' * 32
        stage = webapp.PRIVATE_ROOT / 'import-staging' / transaction_id
        (stage / 'rollback').mkdir(parents=True)
        (stage / 'rollback' / 'acquired.json').write_text('{"old": {}}', encoding='utf-8')
        data_file = webapp.DATA_ROOT / 'public' / 'interrupted.pdf'
        data_file.parent.mkdir(parents=True)
        data_file.write_bytes(b'partial import')
        item_dir = webapp.PRIVATE_ROOT / 'files' / ('b' * 32)
        item_dir.mkdir(parents=True)
        (item_dir / 'partial.pdf').write_bytes(b'partial document')
        acquired_path = webapp.DATA_ROOT / 'acquired.json'
        acquired_path.parent.mkdir(parents=True, exist_ok=True)
        acquired_path.write_text('{"partial": {}}', encoding='utf-8')
        (stage / 'apply-journal.json').write_text(json.dumps({
            'id': transaction_id,
            'targets': [
                {'root': 'data', 'path': 'public/interrupted.pdf', 'kind': 'file'},
                {'root': 'private', 'path': 'files/' + ('b' * 32), 'kind': 'directory'},
            ],
            'acquired': {'existed': True},
        }), encoding='utf-8')

        recovered = self.client.get('/', base_url='https://localhost')
        self.assertEqual(recovered.status_code, 200)

        self.assertFalse(data_file.exists())
        self.assertFalse(item_dir.exists())
        self.assertEqual(acquired_path.read_text(encoding='utf-8'), '{"old": {}}')
        self.assertFalse(stage.exists())

    def test_import_recovery_preserves_committed_files_and_clears_marker(self):
        transaction_id = 'c' * 32
        stage = webapp.PRIVATE_ROOT / 'import-staging' / transaction_id
        stage.mkdir(parents=True)
        data_file = webapp.DATA_ROOT / 'public' / 'committed.pdf'
        data_file.parent.mkdir(parents=True)
        data_file.write_bytes(b'committed import')
        (stage / 'apply-journal.json').write_text(json.dumps({
            'id': transaction_id,
            'targets': [{'root': 'data', 'path': 'public/committed.pdf', 'kind': 'file'}],
            'acquired': {'existed': False},
        }), encoding='utf-8')
        with closing(webapp.connect_db()) as db:
            db.execute('INSERT INTO import_transaction(id) VALUES(?)', (transaction_id,))
            db.commit()
        recovered = self.client.get('/', base_url='https://localhost')
        self.assertEqual(recovered.status_code, 200)
        with closing(webapp.connect_db()) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM import_transaction').fetchone()[0], 0)

        self.assertEqual(data_file.read_bytes(), b'committed import')
        self.assertFalse(stage.exists())

    def test_committed_import_cleanup_failure_keeps_marker_for_recovery(self):
        self.export_fixture()
        prepared = self.prepare_export(['asset:public/card.html'])
        self.assertEqual(prepared.status_code, 200, prepared.data)
        config = json.dumps(prepared.get_json()['config']).encode('utf-8')
        catalogue = prepared.get_json()['catalogues'][0]
        download = self.catalogue_download(catalogue['token'])
        self.assertEqual(download.status_code, 200)
        catalogue_payload = download.get_data()
        download.close()

        target = Path(self.temp.name) / 'cleanup-target'
        self.use_data_root(target, include_computing_subject=True)
        preview = self.client.post('/api/admin/import/preview',
            data={'files': [(io.BytesIO(config), 'configuration.json'),
                            (io.BytesIO(catalogue_payload), catalogue['filename'])]},
            headers={'X-CSRF-Token': self.csrf}, content_type='multipart/form-data',
            base_url='https://localhost')
        self.assertEqual(preview.status_code, 200, preview.get_data(as_text=True))
        plan = preview.get_json()
        transaction_id = webapp.import_serializer().loads(plan['token'])['id']
        stage = webapp.PRIVATE_ROOT / 'import-staging' / transaction_id
        mapping = {subject['id']: subject['id'] for subject in plan['subjects']}
        original_rmtree = webapp.shutil.rmtree

        def fail_stage_cleanup(path, *args, **kwargs):
            if Path(path) == stage:
                raise OSError(errno.EBUSY, 'Import staging directory is temporarily locked')
            return original_rmtree(path, *args, **kwargs)

        with patch.object(webapp.shutil, 'rmtree', side_effect=fail_stage_cleanup):
            applied = self.client.post('/api/admin/import/apply', json={
                'token': plan['token'], 'subject_mapping': mapping},
                headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')

        self.assertEqual(applied.status_code, 200, applied.get_data(as_text=True))
        imported_file = webapp.DATA_ROOT / 'public' / 'card.html'
        self.assertTrue(imported_file.is_file())
        self.assertTrue((stage / 'apply-journal.json').is_file())
        self.assertFalse((stage / 'apply.lock').exists())
        with closing(webapp.connect_db()) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM import_transaction WHERE id=?',
                                         (transaction_id,)).fetchone()[0], 1)

        recovered = self.client.get('/', base_url='https://localhost')
        self.assertEqual(recovered.status_code, 200)
        self.assertTrue(imported_file.is_file())
        self.assertFalse(stage.exists())
        with closing(webapp.connect_db()) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM import_transaction WHERE id=?',
                                         (transaction_id,)).fetchone()[0], 0)

    def test_import_recovery_restores_acquisition_index_without_extra_space(self):
        transaction_id = 'd' * 32
        stage = webapp.PRIVATE_ROOT / 'import-staging' / transaction_id
        backup = stage / 'rollback' / 'acquired.json'
        backup.parent.mkdir(parents=True)
        backup.write_text('{"before": {}}', encoding='utf-8')
        acquired_path = webapp.DATA_ROOT / 'acquired.json'
        acquired_path.parent.mkdir(parents=True, exist_ok=True)
        acquired_path.write_text('{"partial": {}}', encoding='utf-8')
        (stage / 'apply-journal.json').write_text(json.dumps({
            'id': transaction_id, 'targets': [], 'acquired': {'existed': True},
        }), encoding='utf-8')

        with patch.object(webapp.shutil, 'disk_usage', return_value=Mock(free=0)):
            recovered = self.client.get('/', base_url='https://localhost')

        self.assertEqual(recovered.status_code, 200)
        self.assertEqual(acquired_path.read_text(encoding='utf-8'), '{"before": {}}')
        self.assertFalse(stage.exists())

    def test_import_recovery_copies_acquisition_index_across_filesystems(self):
        transaction_id = 'e' * 32
        stage = webapp.PRIVATE_ROOT / 'import-staging' / transaction_id
        backup = stage / 'rollback' / 'acquired.json'
        backup.parent.mkdir(parents=True)
        backup.write_text('{"before": {}}', encoding='utf-8')
        acquired_path = webapp.DATA_ROOT / 'acquired.json'
        acquired_path.parent.mkdir(parents=True, exist_ok=True)
        acquired_path.write_text('{"partial": {}}', encoding='utf-8')
        (stage / 'apply-journal.json').write_text(json.dumps({
            'id': transaction_id, 'targets': [], 'acquired': {'existed': True},
        }), encoding='utf-8')
        real_replace = webapp.os.replace

        def replace_or_raise_exdev(source, destination):
            if Path(source) == backup and Path(destination) == acquired_path:
                raise OSError(errno.EXDEV, 'Cross-device link')
            return real_replace(source, destination)

        with patch.object(webapp.os, 'replace', side_effect=replace_or_raise_exdev):
            recovered = self.client.get('/', base_url='https://localhost')

        self.assertEqual(recovered.status_code, 200)
        self.assertEqual(acquired_path.read_text(encoding='utf-8'), '{"before": {}}')
        self.assertFalse(stage.exists())

    def test_export_requires_admin_csrf_and_valid_selection(self):
        anonymous = webapp.app.test_client()
        self.assertEqual(anonymous.get('/api/admin/export/options').status_code, 401)
        self.assertEqual(anonymous.post('/api/admin/export').status_code, 401)
        self.assertEqual(anonymous.post('/api/admin/export/catalogue').status_code, 401)
        for endpoint in ['/api/admin/export', '/api/admin/export/catalogue']:
            self.assertEqual(self.client.post(endpoint, base_url='https://localhost').status_code, 400)
        for selected in [[], {}, ['missing'], ['missing', 'missing'], [None]]:
            self.assertIn(self.prepare_export(selected).status_code, (400, 409))
        self.assertEqual(self.prepare_export(['missing'], name='x' * 81).status_code, 400)
        self.assertEqual(self.catalogue_download('forged').status_code, 400)
        self.export_fixture()
        token = self.prepare_export(['asset:public/card.html']).get_json()['catalogues'][0]['token']
        signer = webapp.URLSafeTimedSerializer(webapp.app.secret_key, salt='content-export-v1')
        ticket = signer.loads(token)
        with patch('itsdangerous.timed.TimestampSigner.get_timestamp',
                   return_value=int(webapp.time.time()) - 3601):
            expired_token = signer.dumps(ticket)
        self.assertEqual(self.catalogue_download(expired_token).status_code, 400)

    def test_export_rejects_changed_files_traversal_and_low_disk_space(self):
        item_id = self.export_fixture()
        response = self.prepare_export(['asset:public/card.html'])
        token = response.get_json()['catalogues'][0]['token']
        (webapp.DATA_ROOT / 'public/card.html').write_text('changed', encoding='utf-8')
        self.assertEqual(self.catalogue_download(token).status_code, 409)
        result = self.prepare_export(['item:' + item_id]).get_json()
        with patch.object(webapp.shutil, 'disk_usage', return_value=Mock(free=0)):
            self.assertEqual(self.catalogue_download(result['catalogues'][0]['token']).status_code, 409)
        with patch.object(webapp, 'MAX_EXPORT_BYTES', 1):
            self.assertEqual(self.prepare_export(['item:' + item_id]).status_code, 409)
        with closing(webapp.connect_db()) as db:
            db.execute('UPDATE attachment SET stored_path=? WHERE item_id=?', ('../../metadata.sqlite3', item_id))
            db.commit()
        self.assertEqual(self.prepare_export(['item:' + item_id]).status_code, 409)

    def test_export_rejects_symlinked_payload(self):
        self.export_fixture()
        path = (webapp.DATA_ROOT / 'public/card.html').resolve()
        original_is_symlink = Path.is_symlink
        # Mock only the symlink observation so Windows needs no symlink privilege.
        def is_symlink(candidate):
            return candidate == path or original_is_symlink(candidate)
        with patch.object(Path, 'is_symlink', is_symlink):
            self.assertEqual(self.prepare_export(['asset:public/card.html']).status_code, 409)

    def test_home_online_catalog_is_hidden_without_delaying_offline_page(self):
        with patch.object(webapp.urllib.request, 'urlopen') as network:
            response = webapp.app.test_client().get('/')
        network.assert_not_called()
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="online-kiwix-catalog"', response.data)
        self.assertIn(b'rel="noopener noreferrer" hidden', response.data)
        self.assertIn(b'https://browse.library.kiwix.org/', response.data)
        self.assertEqual(response.data.count(b'/static/home.js'), 1)
        link = response.data.split(b'id="online-kiwix-catalog"', 1)[1].split(b'>', 1)[0]
        self.assertNotIn(b'target="_blank"', link)
        with closing(webapp.connect_db()) as db:
            db.execute("INSERT INTO site_setting(key,value) VALUES('pdf_open_mode','new_tab')")
            db.commit()
        response = webapp.app.test_client().get('/')
        link = response.data.split(b'id="online-kiwix-catalog"', 1)[1].split(b'>', 1)[0]
        self.assertIn(b'target="_blank"', link)

    def test_legacy_online_crisis_route_redirects_to_configured_card(self):
        with patch.object(webapp.urllib.request, 'urlopen') as network:
            response = self.client.get('/online-crisis-links')
        network.assert_not_called()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers['Location'], '/online-sources/online-sources')

    def test_police_rss_api_rejects_unlisted_feed_without_network_access(self):
        with patch.object(webapp.urllib.request, 'build_opener') as build_opener:
            response = self.client.get('/api/online/police-rss?feed=https://example.org/feed')
        self.assertEqual(response.status_code, 400)
        build_opener.assert_not_called()

    def test_shared_card_api_edits_metadata_and_prevents_type_change_with_children(self):
        headers = {'X-CSRF-Token': self.csrf, 'Content-Type': 'application/json'}
        subject = {'id': 'water-safety', 'type': 'subject', 'title': 'Water safety',
                   'description': 'Water storage and treatment.',
                   'translations': {'da': {'title': 'Vandsikkerhed', 'description': 'Vand og rensning.'}},
                   'entries': []}
        created = self.client.post('/api/admin/cards', json=subject, headers=headers,
                                   base_url='https://localhost')
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.get_json()['card']['id'], 'water-safety')
        edit = self.client.put('/api/admin/cards/water-safety', json={**subject,
                              'title': 'Safe water'}, headers=headers,
                              base_url='https://localhost')
        self.assertEqual(edit.status_code, 200)
        self.assertEqual(edit.get_json()['card']['title'], 'Safe water')

        with closing(webapp.connect_db()) as db:
            db.execute('INSERT INTO item(id,title,description,subject) VALUES(?,?,?,?)',
                       ('water-item', 'Water guide', '', 'water-safety'))
            db.commit()
        changed_type = self.client.put('/api/admin/cards/water-safety', json={**subject,
                                    'type': 'rss'}, headers=headers,
                                    base_url='https://localhost')
        self.assertEqual(changed_type.status_code, 409)
        self.assertIn('child data', changed_type.get_json()['error'])

    def test_empty_card_can_change_type_and_disabled_rss_feed_cannot_be_fetched(self):
        headers = {'X-CSRF-Token': self.csrf, 'Content-Type': 'application/json'}
        card = {'id': 'quiet-updates', 'type': 'rss', 'title': 'Quiet updates',
                'description': '', 'entries': [{'id': 'daily', 'title': 'Daily',
                'url': 'https://feeds.example.org/daily.xml', 'enabled': False}]}
        created = self.client.post('/api/admin/cards', json=card, headers=headers,
                                   base_url='https://localhost')
        self.assertEqual(created.status_code, 201)
        with patch.object(webapp.urllib.request, 'build_opener') as build_opener:
            unavailable = self.client.get('/api/online/rss?card=quiet-updates&feed=daily',
                                          base_url='https://localhost')
        self.assertEqual(unavailable.status_code, 400)
        build_opener.assert_not_called()

        empty = self.client.post('/api/admin/cards', json={'id': 'empty-links', 'type': 'online',
                                   'title': 'Empty links', 'description': '', 'entries': []},
                                 headers=headers, base_url='https://localhost')
        self.assertEqual(empty.status_code, 201)
        changed = self.client.put('/api/admin/cards/empty-links', json={'type': 'subject',
                                  'title': 'Empty links', 'description': '', 'translations': {},
                                  'entries': []}, headers=headers, base_url='https://localhost')
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(changed.get_json()['card']['type'], 'subject')

    def test_card_entry_admin_api_adds_edits_toggles_and_removes_entries(self):
        headers = {'X-CSRF-Token': self.csrf, 'Content-Type': 'application/json'}
        created = self.client.post('/api/admin/cards', json={'id': 'police-update', 'type': 'rss',
            'title': 'Police Update', 'description': '', 'entries': []}, headers=headers,
            base_url='https://localhost')
        self.assertEqual(created.status_code, 201)
        added = self.client.post('/api/admin/cards/police-update/entries', json={
            'id': 'national-police', 'title': 'National Police',
            'url': 'https://feeds.example.org/police.xml'}, headers=headers,
            base_url='https://localhost')
        self.assertEqual(added.status_code, 201)
        self.assertTrue(added.get_json()['card']['entries'][0]['enabled'])
        edited_card = self.client.put('/api/admin/cards/police-update', json={
            'type': 'rss', 'title': 'Police updates', 'description': 'Current notices',
            'translations': {'da': {'title': 'Politimeddelelser', 'description': ''}},
            'offline_display': 'inactive'}, headers=headers, base_url='https://localhost')
        self.assertEqual(edited_card.status_code, 200)
        self.assertEqual(edited_card.get_json()['card']['title'], 'Police updates')
        self.assertEqual(edited_card.get_json()['card']['entries'][0]['id'], 'national-police')
        self.assertEqual(edited_card.get_json()['card']['translations']['da']['title'], 'Politimeddelelser')
        locked = self.client.put('/api/admin/cards/police-update', json={'type': 'online',
            'title': 'Police Update', 'description': '', 'translations': {},
            'offline_display': 'hide'}, headers=headers, base_url='https://localhost')
        self.assertEqual(locked.status_code, 409)
        disabled = self.client.put('/api/admin/cards/police-update/entries/national-police',
            json={'enabled': False}, headers=headers, base_url='https://localhost')
        self.assertEqual(disabled.status_code, 200)
        self.assertFalse(disabled.get_json()['card']['entries'][0]['enabled'])
        removed = self.client.delete('/api/admin/cards/police-update/entries/national-police',
            headers=headers, base_url='https://localhost')
        self.assertEqual(removed.status_code, 200)
        self.assertEqual(removed.get_json()['card']['entries'], [])

    def test_card_language_edits_save_only_the_active_locale(self):
        headers = {'X-CSRF-Token': self.csrf, 'Content-Type': 'application/json'}
        created = self.client.post('/api/admin/cards', json={
            'id': 'danish-notices', 'type': 'rss', 'title': 'Danske nyheder',
            'description': 'Dansk beskrivelse', 'language': 'da', 'entries': []},
            headers=headers, base_url='https://localhost')
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.get_json()['card']['source_language'], 'da')

        unchanged_fallback = self.client.put('/api/admin/cards/danish-notices', json={
            'type': 'rss', 'title': 'Danske nyheder', 'description': 'Dansk beskrivelse',
            'language': 'en', 'changed_fields': []}, headers=headers,
            base_url='https://localhost')
        self.assertEqual(unchanged_fallback.status_code, 200)
        self.assertEqual(unchanged_fallback.get_json()['card']['translations'], {})

        english_edit = self.client.put('/api/admin/cards/danish-notices', json={
            'type': 'rss', 'title': 'Danish notices', 'description': 'English description',
            'language': 'en', 'changed_fields': ['title', 'description']},
            headers=headers, base_url='https://localhost')
        self.assertEqual(english_edit.status_code, 200)
        saved = english_edit.get_json()['card']
        self.assertEqual(saved['title'], 'Danske nyheder')
        self.assertEqual(saved['source_language'], 'da')
        self.assertEqual(saved['translations']['en']['title'], 'Danish notices')
        self.assertEqual(saved['translations']['en']['description'], 'English description')

    def test_police_update_card_page_includes_feed_details(self):
        with closing(webapp.connect_db()) as db:
            db.execute('INSERT INTO site_setting(key,value) VALUES(?,?)',
                       ('rss_cards', json.dumps([{'id': 'danish-police',
                        'title': 'Danish Police Update RSS',
                        'description': 'Police updates', 'feeds': []}])))
            db.commit()
        response = self.client.get('/rss/danish-police', base_url='https://localhost')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'data-rss-feed', response.data)
        self.assertIn(b'value="national-police"', response.data)

    def test_hotspot_module_toggle_is_persisted_without_removing_hotspot_settings(self):
        headers = {'X-CSRF-Token': self.csrf, 'Content-Type': 'application/json'}
        with closing(webapp.connect_db()) as db:
            db.execute('INSERT INTO site_setting(key,value) VALUES(?,?)',
                       ('hotspot_profile_snapshot', '{"ssid":"Saved network"}'))
            db.commit()
        with patch.object(webapp, 'capability_available', return_value=True), \
                patch.object(webapp, 'helper', return_value={'enabled': False}) as helper:
            response = self.client.put('/api/admin/modules', json={'hotspot_enabled': False},
                                       headers=headers, base_url='https://localhost')
        self.assertEqual(response.status_code, 200)
        helper.assert_called_once_with('hotspot-module-disable')
        with closing(webapp.connect_db()) as db:
            settings = {row['key']: row['value'] for row in db.execute('SELECT key,value FROM site_setting')}
        self.assertEqual(settings['hotspot_module_enabled'], 'false')
        self.assertEqual(settings['hotspot_profile_snapshot'], '{"ssid":"Saved network"}')

    def test_card_configuration_import_defaults_and_preserves_translations_and_feed_state(self):
        config = {'format': 'cyberdeck-config', 'version': 1, 'name': 'Cards',
                  'assets': [], 'offline_catalogues': [], 'subjects': [],
                  'online_source_cards': [{'id': 'health-links', 'title': 'Health links',
                      'source_language': 'da',
                      'description': 'Trusted health sources.', 'translations': {
                          'da': {'title': 'Sundhedskilder', 'description': 'Pålidelige kilder.'}},
                      'links': [{'id': 'world', 'title': 'World Monitor',
                                'url': 'https://example.org', 'description': 'ui.0756'}]}],
                  'rss_cards': [{'id': 'health-rss', 'title': 'ui.0761', 'description': 'ui.0762',
                      'feeds': [{'id': 'alerts', 'title': 'Alerts',
                                 'url': 'https://feeds.example.org/alerts.xml', 'enabled': False}]}]}
        normalized = webapp._validate_import_config(config)
        source = normalized['online_source_cards'][0]
        feed = normalized['rss_cards'][0]
        self.assertEqual(source['offline_display'], 'hide')
        self.assertEqual(source['translations']['da']['title'], 'Sundhedskilder')
        self.assertEqual(source['source_language'], 'da')
        self.assertEqual(source['links'][0]['description'],
                         webapp.LEGACY_CARD_TEXT_MIGRATIONS['ui.0756']['en'])
        self.assertEqual(source['links'][0]['translations']['da']['description'],
                         webapp.LEGACY_CARD_TEXT_MIGRATIONS['ui.0756']['da'])
        self.assertFalse(feed['feeds'][0]['enabled'])
        self.assertEqual(feed['source_language'], 'en')
        self.assertEqual(feed['offline_display'], 'hide')
        self.assertEqual(feed['title'], 'Danish Police Update RSS')
        self.assertEqual(feed['translations']['da']['title'], 'Politi Update RSS')

    def test_builtin_source_card_defaults_are_card_text_not_locale_ids(self):
        for card, children_key in ((webapp.DEFAULT_ONLINE_SOURCE_CARDS[0], 'links'),
                                   (webapp.DEFAULT_RSS_CARDS[0], 'feeds')):
            for field in ('title', 'description'):
                self.assertFalse(str(card[field]).startswith('ui.'), (card['id'], field))
            self.assertEqual(card['source_language'], 'en')
            self.assertIn('da', card['translations'])
            for child in card[children_key]:
                for field in ('title', 'description'):
                    self.assertFalse(str(child.get(field, '')).startswith('ui.'),
                                     (card['id'], child['id'], field))

    def test_legacy_card_translation_migration_preserves_custom_values_and_is_idempotent(self):
        with closing(webapp.connect_db()) as db:
            db.execute("DELETE FROM site_setting WHERE key='card_locale_migration_v1'")
            db.execute('UPDATE library_subject SET title=?,description=?,translations=?,source_language=? WHERE id=?',
                       ('ui.0477', 'ui.0478', json.dumps({'da': {'title': 'My edited title'}}),
                        'en', 'first-aid'))
            db.execute('INSERT INTO site_setting(key,value) VALUES(?,?)',
                       ('online_source_cards', json.dumps([{
                           'id': 'health-links', 'title': 'Health links', 'description': '',
                           'links': [{'id': 'world', 'title': 'World Monitor',
                                      'url': 'https://example.org', 'description': 'ui.0756'}]}])))
            db.execute('INSERT INTO site_setting(key,value) VALUES(?,?)',
                       ('rss_cards', json.dumps([{
                           'id': 'police', 'title': 'ui.0761', 'description': 'ui.0762',
                           'feeds': [{'id': 'all', 'title': 'All police updates',
                                      'url': 'https://example.org/feed.xml'}]}])))
            webapp._migrate_stored_card_locales(db)
            db.commit()
            subject = db.execute('SELECT id,title,description,translations FROM library_subject WHERE id=?',
                                 ('first-aid',)).fetchone()
            self.assertEqual(subject['id'], 'first-aid')
            self.assertEqual(subject['title'], 'Medical and first aid')
            subject_translations = json.loads(subject['translations'])
            self.assertEqual(subject_translations['da']['title'], 'My edited title')
            self.assertEqual(subject_translations['da']['description'], 'Førstehjælp, sundhedsoplysninger og akut behandling.')
            online = json.loads(db.execute("SELECT value FROM site_setting WHERE key='online_source_cards'").fetchone()[0])
            self.assertEqual(online[0]['links'][0]['translations']['da']['description'],
                             webapp.LEGACY_CARD_TEXT_MIGRATIONS['ui.0756']['da'])
            rss = json.loads(db.execute("SELECT value FROM site_setting WHERE key='rss_cards'").fetchone()[0])
            self.assertEqual(rss[0]['title'], 'Danish Police Update RSS')
            self.assertEqual(rss[0]['translations']['da']['title'], 'Politi Update RSS')
            before = json.dumps(rss, sort_keys=True)
            webapp._migrate_stored_card_locales(db)
            after = db.execute("SELECT value FROM site_setting WHERE key='rss_cards'").fetchone()[0]
            self.assertEqual(json.dumps(json.loads(after), sort_keys=True), before)

    def test_legacy_card_translation_migration_rolls_back_without_marker_on_failure(self):
        with closing(webapp.connect_db()) as db:
            db.execute("DELETE FROM site_setting WHERE key='card_locale_migration_v1'")
            db.execute('UPDATE library_subject SET title=? WHERE id=?', ('ui.0477', 'first-aid'))
            with patch.object(webapp, '_migrate_legacy_card_text', side_effect=RuntimeError('conversion failed')):
                with self.assertRaises(RuntimeError):
                    webapp._migrate_stored_card_locales(db)
            db.rollback()
            self.assertIsNone(db.execute("SELECT 1 FROM site_setting WHERE key='card_locale_migration_v1'").fetchone())
            self.assertEqual(db.execute('SELECT title FROM library_subject WHERE id=?',
                                        ('first-aid',)).fetchone()['title'], 'ui.0477')

    def test_police_rss_reader_sanitizes_feed_links_and_caches_results(self):
        feed = b'''<?xml version="1.0" encoding="utf-8"?>
        <rss version="2.0"><channel>
          <item><title>Service alert &amp; update</title>
            <link>https://politi.dk/notice/one</link>
            <description><![CDATA[<p>Road closed near <strong>town</strong>.</p>]]></description>
            <pubDate>Sun, 25 Oct 2026 08:00:00 GMT</pubDate>
          </item>
          <item><title>External destination</title>
            <link>https://outside.example/notice</link>
            <description>Check the official channel.</description>
          </item>
        </channel></rss>'''
        response_body = MagicMock()
        response_body.geturl.return_value = webapp.POLICE_RSS_BASE
        response_body.read.return_value = feed
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value = response_body
        with patch.object(webapp, '_police_rss_cache', {}), \
                patch.object(webapp, '_police_rss_locks', {}), \
                patch.object(webapp.urllib.request, 'build_opener', return_value=opener):
            first = self.client.get('/api/online/police-rss?feed=all')
            second = self.client.get('/api/online/police-rss?feed=all')
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.headers['Cache-Control'], 'no-store')
        result = first.get_json()
        self.assertEqual(result['items'][0]['title'], 'Service alert & update')
        self.assertEqual(result['items'][0]['summary'], 'Road closed near town.')
        self.assertEqual(result['items'][0]['link'], 'https://politi.dk/notice/one')
        self.assertEqual(result['items'][1]['link'], '')
        self.assertNotIn('<strong>', result['items'][0]['summary'])
        self.assertEqual(second.get_json(), result)
        opener.open.assert_called_once()
        self.assertEqual(opener.open.call_args.args[0].full_url, webapp.POLICE_RSS_BASE)

    def test_catalog_connectivity_cache_and_recovery(self):
        client = webapp.app.test_client()
        with patch.dict(webapp._catalog_connectivity, available=False, expires=0), \
                patch.object(webapp.time, 'monotonic', return_value=100) as clock, \
                patch.object(webapp.urllib.request, 'urlopen') as network:
            network.return_value.__enter__.return_value.status = 200
            self.assertTrue(client.get('/api/connectivity/kiwix').get_json()['available'])
            self.assertTrue(client.get('/api/connectivity/kiwix').get_json()['available'])
            network.assert_called_once()
            probe = network.call_args.args[0]
            self.assertEqual((probe.full_url, probe.method), (webapp.KIWIX_ONLINE_CATALOG, 'HEAD'))
            self.assertEqual(network.call_args.kwargs['timeout'], 3)
            clock.return_value = 161
            network.side_effect = OSError('offline')
            response = client.get('/api/connectivity/kiwix')
            self.assertFalse(response.get_json()['available'])
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            clock.return_value = 222
            network.side_effect = None
            self.assertTrue(client.get('/api/connectivity/kiwix').get_json()['available'])

    def test_catalog_connectivity_handles_errors_and_parallel_requests(self):
        client = webapp.app.test_client()
        for error, expected in [(TimeoutError(), False),
                (webapp.urllib.error.URLError('TLS validation failed'), False),
                (webapp.urllib.error.HTTPError(webapp.KIWIX_ONLINE_CATALOG, 403, 'challenge', {}, None), True),
                (webapp.urllib.error.HTTPError(webapp.KIWIX_ONLINE_CATALOG, 503, 'unavailable', {}, None), False)]:
            with self.subTest(error=error), \
                    patch.dict(webapp._catalog_connectivity, available=False, expires=0), \
                    patch.object(webapp.urllib.request, 'urlopen', side_effect=error):
                self.assertEqual(client.get('/api/connectivity/kiwix').get_json()['available'], expected)
        with webapp._catalog_connectivity_lock, \
                patch.dict(webapp._catalog_connectivity, available=False, expires=0), \
                patch.object(webapp.urllib.request, 'urlopen') as network:
            self.assertFalse(client.get('/api/connectivity/kiwix').get_json()['available'])
            network.assert_not_called()

    def worker_fixture(self):
        import library
        zid = '5d2b3f3e-9aa5-498c-ad9a-6769f7718659'
        archive = webapp.DATA_ROOT / 'zim' / 'sample.zim'
        archive.parent.mkdir()
        archive.write_bytes(b'ZIM\x04' + b'x' * 100)
        asset = {'path': 'zim/sample.zim', 'title': 'Sample', 'collection': 'general-reference',
                 'url': 'https://download.kiwix.org/zim/sample.zim',
                 'expected_bytes': 104, 'max_bytes': 104, 'sha256': library.sha256(archive)}
        manifest = webapp.PRIVATE_ROOT / 'requests' / (zid + '.json')
        manifest.parent.mkdir()
        manifest.write_text(json.dumps({'assets': [asset]}), encoding='utf-8')
        lock = webapp.DATA_ROOT / 'acquired.json'
        lock.write_text(json.dumps({'zim/sample.zim': library.acquisition_record(asset, archive, asset['sha256'])}), encoding='utf-8')
        with closing(webapp.connect_db()) as db:
            db.execute('INSERT INTO zim(id,title,subject,filename,source_url,status) VALUES(?,?,?,?,?,?)',
                       (zid, 'Sample', 'general-reference', archive.name, asset['url'], 'downloading'))
            db.commit()
        return zid, archive, manifest, lock

    def test_zim_worker_checks_only_its_requested_archive(self):
        zid, archive, manifest, lock = self.worker_fixture()
        version = webapp.subprocess.CompletedProcess([], 0, 'zim-tools 3.8.0\nlibzim 9.8.2\n', '')
        success = webapp.subprocess.CompletedProcess([], 0)
        with patch.object(webapp.subprocess, 'run', side_effect=[version, success]) as run, \
                patch.object(webapp, 'run_zim_step', side_effect=[success, success]) as step, \
                patch.object(webapp.shutil, 'which', return_value='/usr/bin/zimcheck'):
            webapp.fetch_zim_worker(zid)
        fetch_command = step.call_args_list[0].args[0]
        self.assertEqual(fetch_command[1:2], [str(webapp.APP_DIR / 'library.py')])
        self.assertIn('--missing-only', fetch_command)
        self.assertEqual(step.call_args_list[1].args[0],
                         ['/usr/bin/zimcheck', '--checksum', '--integrity', '--main',
                          '--redirect_loop', str(archive)])
        log = (webapp.PRIVATE_ROOT / 'logs' / (zid + '.log')).read_text()
        self.assertIn('Publisher content-quality checks are not run.', log)
        with closing(webapp.connect_db()) as db:
            self.assertEqual(db.execute('SELECT status FROM zim WHERE id=?', (zid,)).fetchone()[0], 'ready')

    def test_zim_worker_blocks_old_validator_before_downloading(self):
        zid, archive, manifest, lock = self.worker_fixture()
        for output in ('zim-tools 3.5.0\nlibzim 9.2.3\n', 'unrecognized version'):
            with self.subTest(output=output), \
                    patch.object(webapp.shutil, 'which', return_value='/usr/bin/zimcheck'), \
                    patch.object(webapp.subprocess, 'run', return_value=webapp.subprocess.CompletedProcess([], 0, output, '')) as run:
                with self.assertRaises(ValueError):
                    webapp.fetch_zim_worker(zid)
                run.assert_called_once()  # Version probe only; no transfer or service operation.
        with closing(webapp.connect_db()) as db:
            self.assertEqual(db.execute('SELECT status FROM zim WHERE id=?', (zid,)).fetchone()[0], 'failed: validator unavailable')
        log = (webapp.PRIVATE_ROOT / 'logs' / (zid + '.log')).read_text()
        self.assertEqual(log.count('=== ZIM attempt'), 2)
        self.assertIn('9.2.3', log)
        self.assertTrue(archive.is_file())

    def test_zim_worker_retains_failed_download_and_retries_without_network(self):
        import library
        zid, archive, manifest, lock = self.worker_fixture()
        payload, original_lock = archive.read_bytes(), lock.read_bytes()
        version = webapp.subprocess.CompletedProcess([], 0, 'zim-tools 3.8.0\nlibzim 9.8.2\n', '')
        success = webapp.subprocess.CompletedProcess([], 0)
        failure = webapp.subprocess.CompletedProcess([], 1)
        with patch.object(webapp.shutil, 'which', return_value='/usr/bin/zimcheck'), \
                patch.object(webapp.subprocess, 'run', return_value=version) as run, \
                patch.object(webapp, 'run_zim_step', side_effect=[success, failure]):
            with self.assertRaisesRegex(ValueError, 'full download retained'):
                webapp.fetch_zim_worker(zid)
        self.assertEqual(run.call_count, 1)  # Version probe only; a rejection never activates Kiwix.
        partial = archive.with_name(archive.name + '.part')
        self.assertEqual(partial.read_bytes(), payload)
        self.assertFalse(archive.exists())
        self.assertEqual(lock.read_bytes(), original_lock)
        with closing(webapp.connect_db()) as db:
            self.assertIn('download retained', db.execute('SELECT status FROM zim WHERE id=?', (zid,)).fetchone()[0])
        def retry_run(command, *args, **kwargs):
            if command[-1] == '--version':
                return version
            if 'fetch' in command:
                library.fetch(webapp.DATA_ROOT, manifest, missing_only=True)
            return success
        with patch.object(webapp.shutil, 'which', return_value='/usr/bin/zimcheck'), \
                patch.object(webapp.subprocess, 'run', side_effect=retry_run), \
                patch.object(webapp, 'run_zim_step', side_effect=retry_run), \
                patch.object(library.urllib.request, 'urlopen') as network:
            webapp.fetch_zim_worker(zid)
            network.assert_not_called()
        self.assertEqual(archive.read_bytes(), payload)
        self.assertFalse(partial.exists())
        with closing(webapp.connect_db()) as db:
            self.assertEqual(db.execute('SELECT status FROM zim WHERE id=?', (zid,)).fetchone()[0], 'ready')
        log = (webapp.PRIVATE_ROOT / 'logs' / (zid + '.log')).read_text()
        self.assertEqual(log.count('=== ZIM attempt'), 2)
        self.assertIn('validation failed', log)

    def test_retained_zim_checksum_still_checked(self):
        import library
        zid, archive, manifest, lock = self.worker_fixture()
        webapp.retain_zim_for_retry(archive, manifest)
        partial = archive.with_name(archive.name + '.part')
        partial.write_bytes(b'ZIM\x04' + b'y' * 100)
        with patch.object(library.urllib.request, 'urlopen') as network:
            with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
                library.fetch(webapp.DATA_ROOT, manifest, missing_only=True)
            network.assert_not_called()
        self.assertTrue(partial.is_file())
        self.assertFalse(archive.exists())

    def test_zim_pause_api_requires_admin_csrf_and_running_job(self):
        zid, archive, manifest, lock = self.worker_fixture()
        url = f'/api/admin/zims/{zid}/pause'
        self.assertEqual(webapp.app.test_client().post(url).status_code, 401)
        self.assertEqual(self.client.post(url, base_url='https://localhost').status_code, 400)
        headers = {'X-CSRF-Token': self.csrf}
        self.assertEqual(self.client.post(url, headers=headers, base_url='https://localhost').status_code, 409)
        with closing(webapp.connect_db()) as db:
            db.execute('UPDATE zim SET status=? WHERE id=?', ('pid:1234', zid)); db.commit()
        with patch.object(webapp, 'zim_worker_alive', return_value=True), \
                patch.object(webapp.subprocess, 'Popen') as launch:
            response = self.client.post(url, headers=headers, base_url='https://localhost')
            self.assertEqual(response.status_code, 202)
            self.assertTrue(webapp.zim_pause_path(zid).exists())
            listed = self.client.get('/api/admin/zims', base_url='https://localhost').get_json()[0]
            self.assertTrue(listed['pause_requested'])
            self.assertEqual(listed['status'], 'pid:1234')
            self.assertEqual(self.client.post(f'/api/admin/zims/{zid}/retry', headers=headers,
                             base_url='https://localhost').status_code, 409)
            self.assertTrue(webapp.zim_pause_path(zid).exists())
            launch.assert_not_called()
        with patch.object(webapp, 'zim_worker_alive', return_value=False):
            self.assertEqual(self.client.post(url, headers=headers, base_url='https://localhost').status_code, 409)

    def test_pause_reaps_only_owned_child_before_reporting_paused(self):
        marker = webapp.PRIVATE_ROOT / 'stop.pause'
        child = Mock()
        def waiting(timeout=None):
            if timeout == 0.5:
                marker.touch()
                raise webapp.subprocess.TimeoutExpired('fetch', timeout)
            return -15
        child.wait.side_effect = waiting
        child.poll.return_value = None
        with patch.object(webapp.subprocess, 'Popen', return_value=child):
            with self.assertRaises(webapp.ZimPaused):
                webapp.run_zim_step(['mock-download'], io.StringIO(), marker)
        child.terminate.assert_called_once()
        child.wait.assert_any_call(timeout=10)
        child.kill.assert_not_called()
        child.reset_mock()
        with patch.object(webapp.subprocess, 'Popen') as launch:
            with self.assertRaises(webapp.ZimPaused):
                webapp.run_zim_step(['mock-download'], io.StringIO(), marker)
            launch.assert_not_called()  # Already paused before a subprocess starts.

    def test_pause_escalates_only_if_owned_child_ignores_termination(self):
        marker = webapp.PRIVATE_ROOT / 'stop.pause'
        child = Mock()
        def waiting(timeout=None):
            if timeout == 0.5:
                marker.touch()
            if timeout is not None:
                raise webapp.subprocess.TimeoutExpired('fetch', timeout)
            return -9
        child.wait.side_effect = waiting
        child.poll.return_value = None
        with patch.object(webapp.subprocess, 'Popen', return_value=child):
            with self.assertRaises(webapp.ZimPaused):
                webapp.run_zim_step(['mock-download'], io.StringIO(), marker)
        child.terminate.assert_called_once()
        child.kill.assert_called_once()
        self.assertEqual(child.wait.call_args_list[-1].kwargs, {})  # Reaped after kill.

    def test_pause_preserves_partial_and_poll_does_not_overwrite_paused(self):
        zid, archive, manifest, lock = self.worker_fixture()
        partial = archive.with_name(archive.name + '.part')
        archive.rename(partial)
        partial.write_bytes(b'ZIM\x04' + b'x' * 36)
        webapp.zim_pause_path(zid).touch()
        with patch.object(webapp, 'zim_validator', return_value='/mock/zimcheck'), \
                patch.object(webapp.subprocess, 'run') as run:
            webapp.fetch_zim_worker(zid)
            run.assert_not_called()
        self.assertEqual(partial.stat().st_size, 40)
        with closing(webapp.connect_db()) as db:
            db.execute('UPDATE zim SET status=? WHERE id=?', ('pid:1234', zid)); db.commit()
        def worker_finished(*args):
            webapp.g.db.execute('UPDATE zim SET status=? WHERE id=?', ('paused', zid))
            return False
        with patch.object(webapp, 'zim_worker_alive', side_effect=worker_finished):
            item = self.client.get('/api/admin/zims', base_url='https://localhost').get_json()[0]
        self.assertEqual(item['status'], 'paused')
        self.assertEqual(item['received_bytes'], 40)
        self.assertFalse(item['pause_requested'])

    def test_pause_worker_retains_complete_file_and_resume_clears_request(self):
        zid, archive, manifest, lock = self.worker_fixture()
        payload = archive.read_bytes()
        webapp.zim_pause_path(zid).touch()
        with patch.object(webapp, 'zim_validator', return_value='/mock/zimcheck'), \
                patch.object(webapp.subprocess, 'run') as run, \
                patch.object(webapp.subprocess, 'Popen') as launch:
            webapp.fetch_zim_worker(zid)
            run.assert_not_called(); launch.assert_not_called()
        self.assertFalse(archive.exists())
        self.assertEqual(archive.with_name(archive.name + '.part').read_bytes(), payload)
        with closing(webapp.connect_db()) as db:
            self.assertEqual(db.execute('SELECT status FROM zim WHERE id=?', (zid,)).fetchone()[0], 'paused')
        with patch.object(webapp.subprocess, 'Popen', return_value=Mock(pid=4321)) as launch:
            response = self.client.post(f'/api/admin/zims/{zid}/retry',
                headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')
        self.assertEqual(response.status_code, 202)
        self.assertFalse(webapp.zim_pause_path(zid).exists())
        self.assertEqual(launch.call_args.args[0][-2:], ['fetch-zim', zid])
        with closing(webapp.connect_db()) as db:
            self.assertEqual(db.execute('SELECT status FROM zim WHERE id=?', (zid,)).fetchone()[0], 'pid:4321')

    def test_zim_transfer_state_reports_partial_and_verification(self):
        zim_id = '5d2b3f3e-9aa5-498c-ad9a-6769f7718659'
        filename = 'sample.zim'
        request_dir = webapp.PRIVATE_ROOT / 'requests'
        request_dir.mkdir(parents=True)
        (request_dir / f'{zim_id}.json').write_text(json.dumps({
            'assets': [{'path': f'zim/{filename}', 'expected_bytes': 100}],
        }), encoding='utf-8')
        archive_dir = webapp.DATA_ROOT / 'zim'
        archive_dir.mkdir(parents=True)
        partial = archive_dir / f'{filename}.part'
        partial.write_bytes(b'x' * 40)
        state = webapp.zim_transfer_state(zim_id, filename, 'pid:1234')
        self.assertEqual((state['received_bytes'], state['expected_bytes'], state['phase']),
                         (40, 100, 'downloading'))
        partial.write_bytes(b'x' * 100)
        state = webapp.zim_transfer_state(zim_id, filename, 'pid:1234')
        self.assertEqual(state['phase'], 'verifying')
        partial.write_bytes(b'x' * 40)
        with patch.object(webapp.time, 'time', return_value=partial.stat().st_mtime + 180):
            state = webapp.zim_transfer_state(zim_id, filename, 'pid:1234')
        self.assertEqual(state['phase'], 'stalled')
        failed = webapp.zim_transfer_state(zim_id, filename, 'failed: zimcheck')
        self.assertEqual(failed, {})

    def test_public_subject_pages_and_private_api_boundary(self):
        anon = webapp.app.test_client()
        self.assertEqual(anon.get('/api/subjects').status_code, 200)
        self.assertEqual(anon.get('/subjects/first-aid').status_code, 200)
        self.assertEqual(anon.get('/api/admin/items').status_code, 401)
        self.assertEqual(anon.post('/api/admin/items').status_code, 401)
        self.assertEqual(anon.get('/api/admin/subjects').status_code, 401)
        self.assertEqual(anon.get('/api/admin/system').status_code, 401)
        self.assertEqual(anon.get('/private/unknown/file').status_code, 302)

    def test_catalog_search_returns_only_zim_download_entries(self):
        atom = b'''<?xml version="1.0"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry><title>First aid</title>
            <link rel="http://opds-spec.org/acquisition/open-access" type="application/x-zim" href="https://download.kiwix.org/zim/other/first-aid.zim"/>
          </entry>
          <entry><title>Web page</title>
            <link rel="alternate" type="text/html" href="https://library.kiwix.org/viewer#web-page"/>
          </entry>
        </feed>'''

        class Response:
            status = 200

            def __init__(self, body):
                self.body = body
                self.headers = {'Content-Length': str(len(body))}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit):
                return self.body

        with patch.object(webapp.urllib.request, 'urlopen', return_value=Response(atom)) as open_url:
            response = self.client.get('/api/admin/catalog?q=first+aid', base_url='https://localhost')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['items'], [{
            'title': 'First aid',
            'url': 'https://download.kiwix.org/zim/other/first-aid.zim',
            'filename': 'first-aid.zim', 'description': '', 'language': '',
            'edition': '', 'flavour': '', 'bytes': None,
        }])
        self.assertIn('first+aid', open_url.call_args.args[0].full_url)

        with patch.object(webapp.urllib.request, 'urlopen', return_value=Response(atom)) as open_url:
            response = self.client.get('/api/admin/catalog?q=Danish', base_url='https://localhost')
        self.assertEqual(response.status_code, 200)
        catalog_query = webapp.urllib.parse.parse_qs(webapp.urllib.parse.urlsplit(
            open_url.call_args.args[0].full_url).query)
        self.assertEqual(catalog_query.get('q'), ['Danish'])
        self.assertNotIn('lang', catalog_query)

    def test_catalog_search_reads_kiwix_metalinks(self):
        # Acquisition links observed in Kiwix's q=denmark feed on 2026-10-18.
        atom = b'''<feed xmlns="http://www.w3.org/2005/Atom">
          <entry><title>Denmark</title><summary>Full map, including roads and landmarks</summary><language>eng</language><updated>2026-06-01T00:00:00Z</updated>
            <link rel="http://opds-spec.org/acquisition" href="https://download.kiwix.org/unrelated.pdf"/>
            <link type="text/html" href="https://browse.library.kiwix.org/content/maps_en_denmark_2026-06"/>
            <link rel="http://opds-spec.org/acquisition/open-access" type="application/x-zim" href="https://lb.download.kiwix.org/zim/maps/maps_en_denmark_2026-06.zim.meta4" length="622355456"/>
          </entry>
          <entry><title>Nordics</title><summary>Regional map for Finland, Sweden, Norway, Denmark, Faroe and Iceland.</summary>
            <link rel="http://opds-spec.org/acquisition/open-access" type="application/x-zim" href="https://lb.download.kiwix.org/zim/maps/maps_en_nordics_2026-08a.zim.meta4" length="5668622336"/>
          </entry>
          <entry><title>Unapproved host</title>
            <link type="application/x-zim" href="https://download.kiwix.org.attacker.example/evil.zim.meta4"/>
          </entry>
          <entry><title>Not HTTPS</title>
            <link type="application/x-zim" href="http://download.kiwix.org/evil.zim.meta4"/>
          </entry>
        </feed>'''
        upstream = io.BytesIO(atom)
        upstream.status = 200
        upstream.headers = {'Content-Length': str(len(atom))}
        with patch.object(webapp.urllib.request, 'urlopen', return_value=upstream) as open_url:
            response = self.client.get('/api/admin/catalog?q=Denmark', base_url='https://localhost')
        self.assertEqual(response.status_code, 200, response.get_json())
        items = response.get_json()['items']
        self.assertEqual([{key: item[key] for key in ('title', 'url')} for item in items], [
            {'title': 'Denmark', 'url': 'https://lb.download.kiwix.org/zim/maps/maps_en_denmark_2026-06.zim'},
            {'title': 'Nordics', 'url': 'https://lb.download.kiwix.org/zim/maps/maps_en_nordics_2026-08a.zim'},
        ])
        self.assertEqual(items[0]['description'], 'Full map, including roads and landmarks')
        self.assertEqual(items[0]['language'], 'eng')
        self.assertEqual(items[0]['edition'], '2026-06-01')
        self.assertEqual(items[0]['bytes'], 622355456)
        self.assertEqual(items[0]['filename'], 'maps_en_denmark_2026-06.zim')
        open_url.assert_called_once()  # Search must not fetch archives or mirrors.

    def test_catalog_does_not_report_unusable_responses_as_no_matches(self):
        cases = [
            (b'<feed xmlns="http://www.w3.org/2005/Atom"/>', 200),
            (b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Changed feed</title>'
             b'<link type="application/x-zim" href="https://unapproved.example/book.zim.meta4"/>'
             b'</entry></feed>', 502),
            (b'<html><body>Catalog has moved</body></html>', 502),
        ]
        for xml, expected_status in cases:
            with self.subTest(xml=xml):
                upstream = io.BytesIO(xml)
                upstream.status = 200
                upstream.headers = {}
                with patch.object(webapp.urllib.request, 'urlopen', return_value=upstream):
                    response = self.client.get('/api/admin/catalog?q=maps', base_url='https://localhost')
                self.assertEqual(response.status_code, expected_status)
                if expected_status == 200:
                    self.assertEqual(response.get_json(), {'items': []})
                else:
                    self.assertIn('error', response.get_json())

    def test_catalog_search_requires_admin_and_minimum_query(self):
        anonymous = webapp.app.test_client()
        self.assertEqual(anonymous.get('/api/admin/catalog?q=wiki').status_code, 401)
        with patch.object(webapp.urllib.request, 'urlopen') as open_url:
            response = self.client.get('/api/admin/catalog?q=x', base_url='https://localhost')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {'items': []})
        open_url.assert_not_called()

    def edit_zim(self, zid, body):
        return self.client.put('/api/admin/zims/' + zid, json=body,
                               headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')

    def seed_zim_record(self, filename='sample.zim'):
        archive = webapp.DATA_ROOT / 'zim' / filename
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_bytes(b'fake archive; no external validator runs in metadata tests')
        lock = webapp.DATA_ROOT / 'acquired.json'
        lock.write_text(json.dumps({'zim/' + filename: {
            'asset': {'title': 'Original title', 'collection': 'general-reference',
                      'url': 'https://download.kiwix.org/zim/' + filename},
            'bytes': archive.stat().st_size, 'sha256': 'a' * 64,
        }}), encoding='utf-8')
        return archive, lock

    def test_zim_edit_requires_admin_csrf_and_valid_metadata(self):
        body = {'title': 'New title', 'subject': 'first-aid'}
        anonymous = webapp.app.test_client()
        self.assertEqual(anonymous.put('/api/admin/zims/unknown', json=body).status_code, 401)
        response = self.client.put('/api/admin/zims/unknown', json=body, base_url='https://localhost')
        self.assertEqual(response.status_code, 400)
        for invalid in ({}, [], {'title': ' ', 'subject': 'first-aid'},
                        {'title': 'x' * 201, 'subject': 'first-aid'},
                        {'title': 'Title', 'subject': 'missing'},
                        {'title': 'Title', 'subject': []}):
            with self.subTest(body=invalid):
                self.assertEqual(self.edit_zim('unknown', invalid).status_code, 400)
        self.assertEqual(self.edit_zim('unknown', body).status_code, 404)
        self.assertEqual(self.edit_zim('file-invalid.txt', body).status_code, 404)

    def test_zim_edit_adopts_starter_metadata_without_changing_acquisition(self):
        archive, lock = self.seed_zim_record()
        before = (archive.read_bytes(), lock.read_bytes())
        with patch.object(webapp.subprocess, 'run') as run, \
                patch.object(webapp.subprocess, 'Popen') as launch, \
                patch.object(webapp, 'inspect_kiwix_asset') as inspect:
            response = self.edit_zim('file-sample.zim', {'title': '  First aid library  ', 'subject': 'first-aid'})
            self.assertEqual(response.status_code, 200, response.get_json())
            zid = response.get_json()['id']
            # An old open tab still using the file-ID must update, not duplicate.
            response = self.edit_zim('file-sample.zim', {'title': 'Updated library', 'subject': 'first-aid'})
            self.assertEqual(response.get_json()['id'], zid)
            run.assert_not_called(); launch.assert_not_called(); inspect.assert_not_called()
        self.assertEqual((archive.read_bytes(), lock.read_bytes()), before)
        with webapp.app.test_request_context():
            webapp.load_request_state()
            self.assertEqual(webapp.public_items('general-reference'), [])
            items = webapp.public_items('first-aid')
            self.assertEqual([(item['title'], item['filename']) for item in items], [('Updated library', 'sample.zim')])
            self.assertEqual(webapp.subject_assigned_count('general-reference'), 0)
            self.assertEqual(webapp.subject_assigned_count('first-aid'), 1)
        listed = self.client.get('/api/admin/zims', base_url='https://localhost').get_json()
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]['status'], 'ready')
        self.assertEqual(listed[0]['sha256'], 'a' * 64)

    def test_zim_edit_stale_file_id_removal_does_not_leave_a_public_entry(self):
        archive, lock = self.seed_zim_record()
        self.assertEqual(self.edit_zim('file-sample.zim', {'title': 'Edited', 'subject': 'first-aid'}).status_code, 200)
        with patch.object(webapp.subprocess, 'run'):
            response = self.client.delete('/api/admin/zims/file-sample.zim',
                json={'confirm': 'sample.zim'}, headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')
        self.assertEqual(response.status_code, 204)
        self.assertFalse(archive.exists())
        self.assertEqual(self.client.get('/api/admin/zims', base_url='https://localhost').get_json(), [])

    def test_zim_edit_preserves_active_download_and_same_title_archives(self):
        archive, lock = self.seed_zim_record()
        request_dir = webapp.PRIVATE_ROOT / 'requests'
        request_dir.mkdir()
        request_file = request_dir / 'active.json'
        request_file.write_text('{"original": "resume identity"}', encoding='utf-8')
        before = (lock.read_bytes(), request_file.read_bytes())
        db = webapp.connect_db()
        try:
            for zid, filename, status in [('active', 'sample.zim', 'pid:1234'),
                                          ('one', 'one.zim', 'ready'), ('two', 'two.zim', 'ready')]:
                db.execute('INSERT INTO zim(id,title,subject,filename,source_url,bytes,sha256,status) '
                           'VALUES(?,?,?,?,?,?,?,?)',
                           (zid, 'Shared title', 'general-reference', filename,
                            'https://download.kiwix.org/zim/' + filename, 123, 'a' * 64, status))
            db.commit()
            response = self.edit_zim('active', {'title': 'In progress', 'subject': 'first-aid'})
            self.assertEqual(response.status_code, 200)
            record = db.execute('SELECT * FROM zim WHERE id=?', ('active',)).fetchone()
            self.assertEqual((record['status'], record['bytes'], record['sha256']), ('pid:1234', 123, 'a' * 64))
        finally:
            db.close()
        self.assertEqual((lock.read_bytes(), request_file.read_bytes()), before)
        with webapp.app.test_request_context():
            webapp.load_request_state()
            self.assertEqual(webapp.public_items('first-aid'), [])  # Still unverified.
            self.assertEqual({item['filename'] for item in webapp.public_items('general-reference')}, {'one.zim', 'two.zim'})
            self.assertEqual(webapp.subject_assigned_count('general-reference'), 2)
            self.assertEqual(webapp.subject_assigned_count('first-aid'), 1)

    def test_admin_system_overview_includes_multiple_filesystems(self):
        filesystems = [
            {'mount': '/', 'device': '/dev/sda2', 'filesystem': 'ext4',
             'total_bytes': 1000, 'used_bytes': 600, 'free_bytes': 400, 'used_percent': 60.0},
            {'mount': '/srv/cyberdeck', 'device': '/dev/sdb1', 'filesystem': 'ext4',
             'total_bytes': 2000, 'used_bytes': 500, 'free_bytes': 1500, 'used_percent': 25.0},
        ]
        with patch.object(webapp, '_system_mount_usage', return_value=filesystems), \
                patch.object(webapp, '_system_network', return_value={'available': False, 'interfaces': []}):
            response = self.client.get('/api/admin/system', base_url='https://localhost')
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row['mount'] for row in response.get_json()['filesystems']],
                         ['/', '/srv/cyberdeck'])
        self.assertFalse(response.get_json()['network']['available'])

    def test_first_admin_setup_gates_library_until_account_is_created(self):
        with closing(webapp.connect_db()) as db, db:
            db.execute('DELETE FROM admin')

        self.client = webapp.app.test_client()
        response = self.client.get('/', base_url='https://localhost')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers['Location'], '/setup')

        setup = self.client.get('/setup', base_url='https://localhost')
        self.assertEqual(setup.status_code, 200)
        self.assertIn(b'Create the first administrator', setup.data)
        with self.client.session_transaction(base_url='https://localhost') as saved:
            csrf = saved['csrf']
        created = self.client.post('/setup', data={
            'csrf_token': csrf,
            'username': 'owner',
            'password': 'a sufficiently long setup password',
            'password_confirmation': 'a sufficiently long setup password',
        }, base_url='https://localhost')
        self.assertEqual(created.status_code, 302)
        self.assertEqual(created.headers['Location'], '/admin')
        self.assertEqual(self.client.get('/admin', base_url='https://localhost').status_code, 200)

        another_client = webapp.app.test_client()
        locked_setup = another_client.get('/setup', base_url='https://localhost')
        self.assertEqual(locked_setup.status_code, 302)
        self.assertEqual(locked_setup.headers['Location'], '/login')

    def test_home_shows_non_clickable_kiwix_card_for_queued_downloads(self):
        with closing(webapp.connect_db()) as db, db:
            db.execute('INSERT INTO zim(id,title,subject,filename,source_url,status) '
                       'VALUES(?,?,?,?,?,?)',
                       ('pending-zim', 'Pending library', 'preparedness', 'pending.zim',
                        'https://download.kiwix.org/zim/pending.zim', 'queued'))

        response = self.client.get('/', base_url='https://localhost')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'class="card service-card kiwix-public-item service-card-kiwix service-card-pending"',
                      response.data)
        self.assertIn(b'Preparing offline libraries.', response.data)
        self.assertIn(b'1 downloads in progress', response.data)
        self.assertNotIn(b'href="/kiwix/"', response.data)

    def test_system_network_lists_active_interfaces_first_and_preserves_connection_names(self):
        output = ('wlan1:wifi:disconnected:--\n'
                  'wlan0:wifi:connected:Field: library\\Wi-Fi\n'
                  'lo:loopback:connected (externally):lo\n'
                  'enp1s0:ethernet:connected (externally):Wired connection\n'
                  'eth2:ethernet:connecting (getting IP configuration):Wired backup\n')
        with patch.object(webapp.subprocess, 'run', return_value=Mock(stdout=output)) as run:
            network = webapp._system_network()
        self.assertTrue(network['available'])
        rows = network['interfaces']
        self.assertEqual([row['device'] for row in rows], ['enp1s0', 'wlan0', 'eth2', 'wlan1'])
        self.assertEqual([row['active'] for row in rows], [True, True, False, False])
        self.assertEqual(rows[1]['connection'], 'Field: library\\Wi-Fi')
        self.assertIsNone(rows[3]['connection'])
        self.assertEqual(run.call_args.kwargs['env']['LC_ALL'], 'C')
        self.assertEqual(run.call_args.kwargs['timeout'], 5)

    def test_system_network_errors_are_unavailable_not_disconnected(self):
        failures = [OSError('missing nmcli'), webapp.subprocess.TimeoutExpired('nmcli', 5),
                    webapp.subprocess.CalledProcessError(1, 'nmcli')]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__), \
                    patch.object(webapp.subprocess, 'run', side_effect=failure):
                self.assertEqual(webapp._system_network(), {'available': False, 'interfaces': []})
        with patch.object(webapp.subprocess, 'run', return_value=Mock(stdout='invalid\n')):
            self.assertFalse(webapp._system_network()['available'])

    def test_admin_can_manage_subjects_but_cannot_delete_assigned_subjects(self):
        headers = {'X-CSRF-Token': self.csrf}
        invalid = self.client.post('/api/admin/subjects', headers=headers,
            json={'id': 'Not Valid', 'title': 'Bad', 'description': 'Invalid ID'},
            base_url='https://localhost')
        self.assertEqual(invalid.status_code, 400)

        def add_subject(slug):
            response = self.client.post('/api/admin/subjects', headers=headers,
                json={'id': slug, 'title': slug.replace('-', ' ').title(),
                      'description': f'Material about {slug}.'}, base_url='https://localhost')
            self.assertEqual(response.status_code, 201, response.get_data(as_text=True))

        add_subject('temporary-topic')
        selected = self.client.put('/api/admin/settings', headers=headers,
            json={'always_show_subjects': ['temporary-topic']}, base_url='https://localhost')
        self.assertEqual(selected.status_code, 200)
        removed = self.client.delete('/api/admin/subjects/temporary-topic', headers=headers,
                                     base_url='https://localhost')
        self.assertEqual(removed.status_code, 204)
        with closing(webapp.connect_db()) as db:
            saved_subjects = db.execute("SELECT value FROM site_setting "
                                        "WHERE key='always_show_subjects'").fetchone()[0]
        self.assertNotIn('temporary-topic', json.loads(saved_subjects))

        add_subject('reference-files')
        webapp.DATA_ROOT.mkdir(parents=True, exist_ok=True)
        (webapp.DATA_ROOT / 'acquired.json').write_text(json.dumps({
            'public/topic.pdf': {'asset': {'title': 'Topic file', 'collection': 'reference-files'}}
        }), encoding='utf-8')
        blocked = self.client.delete('/api/admin/subjects/reference-files', headers=headers,
                                     base_url='https://localhost')
        self.assertEqual(blocked.status_code, 409)

        add_subject('zim-library')
        with closing(webapp.connect_db()) as db:
            db.execute('INSERT INTO zim(id,title,subject,filename,source_url,status) '
                       'VALUES(?,?,?,?,?,?)',
                       ('assigned-zim', 'Assigned archive', 'zim-library', 'assigned.zim',
                        'https://download.kiwix.org/zim/assigned.zim', 'queued'))
            db.commit()
        blocked = self.client.delete('/api/admin/subjects/zim-library', headers=headers,
                                     base_url='https://localhost')
        self.assertEqual(blocked.status_code, 409)

        add_subject('uploaded-documents')
        with closing(webapp.connect_db()) as db:
            db.execute('INSERT INTO item(id,title,description,subject) VALUES(?,?,?,?)',
                       ('assigned-item', 'Assigned upload', '', 'uploaded-documents'))
            db.commit()
        blocked = self.client.delete('/api/admin/subjects/uploaded-documents', headers=headers,
                                     base_url='https://localhost')
        self.assertEqual(blocked.status_code, 409)

    def test_home_category_counts_and_hide_empty_preference(self):
        home = self.client.get('/', base_url='https://localhost')
        self.assertIn(b'class="card-count">0 items</span>', home.data)
        self.assertIn(b'href="/subjects/preparedness"', home.data)

        webapp.DATA_ROOT.mkdir(parents=True, exist_ok=True)
        (webapp.DATA_ROOT / 'acquired.json').write_text(json.dumps({
            'public/first-aid.pdf': {'asset': {'title': 'First aid', 'collection': 'first-aid'},
                                     'bytes': 1}
        }), encoding='utf-8')
        response = self.client.put('/api/admin/settings',
            headers={'X-CSRF-Token': self.csrf},
            json={'hide_empty_subjects': True, 'always_show_subjects': ['preparedness']},
            base_url='https://localhost')
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))

        home = self.client.get('/', base_url='https://localhost')
        self.assertIn(b'href="/subjects/first-aid"', home.data)
        self.assertIn(b'class="card-count">1 item</span>', home.data)
        self.assertIn(b'href="/subjects/preparedness"', home.data)
        self.assertNotIn(b'href="/subjects/general-reference"', home.data)

    def test_subject_kiwix_entries_link_to_their_viewer_ids(self):
        webapp.DATA_ROOT.mkdir(parents=True, exist_ok=True)
        (webapp.DATA_ROOT / 'acquired.json').write_text(json.dumps({
            'zim/wikipedia_da_all_maxi_2026-09.zim': {
                'asset': {'title': 'Danish Wikipedia', 'collection': 'general-reference'},
                'bytes': 123, 'sha256': 'a' * 64,
            }
        }), encoding='utf-8')
        with closing(webapp.connect_db()) as db, db:
            db.execute('INSERT INTO zim(id,title,subject,filename,source_url,status) '
                       'VALUES(?,?,?,?,?,?)',
                       ('manual-zim', 'Handbook ZIM', 'general-reference',
                        'handbook_2026-01.zim', 'https://download.kiwix.org/zim/handbook_2026-01.zim',
                        'ready'))

        response = self.client.get('/subjects/general-reference', base_url='https://localhost')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'href="https://cyberdeck.local/kiwix/viewer#wikipedia_da_all_maxi_2026-09"',
                      response.data)
        self.assertIn(b'href="https://cyberdeck.local/kiwix/viewer#handbook_2026-01"',
                      response.data)
        self.assertIn(b'class="public-item kiwix-public-item"', response.data)
        self.assertIn(b'Open in Kiwix', response.data)

        saved = self.client.put('/api/admin/settings',
            headers={'X-CSRF-Token': self.csrf}, json={'pdf_open_mode': 'new_tab'},
            base_url='https://localhost')
        self.assertEqual(saved.status_code, 200)
        new_tab = self.client.get('/subjects/general-reference', base_url='https://localhost')
        self.assertIn(b'target="_blank" rel="noopener"><span><b>Danish Wikipedia', new_tab.data)
        self.assertIn(b'target="_blank" rel="noopener">Open full Kiwix library', new_tab.data)

    def test_kiwix_links_use_the_renamed_https_host(self):
        with patch.dict(webapp.os.environ, {'CYBERDECK_HOSTNAME': 'family-library.local'}):
            for path in ('/', '/login', '/admin', '/subjects/general-reference'):
                response = self.client.get(path, base_url='https://localhost')
                self.assertEqual(response.status_code, 200)
                self.assertNotIn(b':8080/', response.data)
            response = self.client.get('/api/subjects/general-reference', base_url='https://localhost')
            self.assertEqual(response.get_json()['kiwix'], 'https://localhost/kiwix/')
            self.assertEqual(webapp.kiwix_viewer_url('regional map.zim'),
                             'https://family-library.local/kiwix/viewer#regional%20map')

    def assert_inline_pdf_responses(self, client, endpoint, expected):
        for method, headers, status, body in (
                ('GET', {}, 200, expected),
                ('HEAD', {}, 200, b''),
                ('GET', {'Range': 'bytes=0-4'}, 206, expected[:5])):
            with self.subTest(method=method, headers=headers, endpoint=endpoint):
                response = client.open(endpoint, method=method, headers=headers,
                                       base_url='https://localhost')
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.mimetype, 'application/pdf')
                self.assertTrue(response.headers['Content-Disposition'].startswith('inline;'))
                self.assertEqual(response.headers['Content-Security-Policy'], "frame-ancestors 'none'")
                self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
                self.assertEqual(response.headers['X-Frame-Options'], 'DENY')
                self.assertEqual(response.data, body)
                if status == 206:
                    self.assertEqual(response.headers['Content-Range'], f'bytes 0-4/{len(expected)}')
                response.close()

    def test_library_pdf_headers_and_range_requests(self):
        path, _ = self.archive_fixture()
        anon = webapp.app.test_client()
        self.assert_inline_pdf_responses(anon, '/library/field-guide.pdf', path.read_bytes())
        for endpoint in ('/', '/library/missing.pdf'):
            response = anon.get(endpoint, base_url='https://localhost')
            self.assertEqual(response.mimetype, 'text/html')
            self.assertIn("object-src 'none'", response.headers['Content-Security-Policy'])
            self.assertIn("script-src 'self'", response.headers['Content-Security-Policy'])
        self.assertEqual(anon.get('/library/missing.pdf').status_code, 404)
        html_path = path.with_name('card.html')
        html_path.write_text('<h1>Reference card</h1>', encoding='utf-8')
        (webapp.DATA_ROOT / 'acquired.json').write_text(
            json.dumps({'public/card.html': {}}), encoding='utf-8')
        with anon.get('/library/card.html', base_url='https://localhost') as response:
            self.assertEqual(response.status_code, 200)
            self.assertIn('sandbox;', response.headers['Content-Security-Policy'])
            self.assertIn("object-src 'none'", response.headers['Content-Security-Policy'])

    def test_upload_edit_download_and_delete_pdf(self):
        response = self.client.post('/api/admin/items', headers={'X-CSRF-Token': self.csrf},
            data={'title': 'Field guide', 'description': 'Reference', 'subject': 'preparedness',
                  'attachments': (io.BytesIO(b'%PDF-1.7 test fixture'), 'guide.pdf')},
            content_type='multipart/form-data', base_url='https://localhost')
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        item_id = response.get_json()['id']
        item = self.client.get('/api/admin/items', base_url='https://localhost').get_json()[0]
        attachment_id = item['attachments'][0]['id']
        self.assertEqual(item['attachments'][0]['source'], 'upload')
        with self.client.get(f'/private/{item_id}/{attachment_id}',
                             base_url='https://localhost') as private_download:
            self.assertEqual(private_download.status_code, 200)
            self.assertTrue(private_download.headers['Content-Disposition'].startswith('attachment;'))
        anon = webapp.app.test_client()
        subject = anon.get('/subjects/preparedness', base_url='https://localhost')
        self.assertEqual(subject.status_code, 200)
        self.assertIn(b'AVAILABLE HERE', subject.data)
        self.assertIn(b'Field guide', subject.data)
        listing = anon.get('/api/subjects/preparedness', base_url='https://localhost').get_json()
        self.assertTrue(any(entry['title'] == 'Field guide' and entry['url'].startswith('/documents/')
                            for entry in listing['items']))
        document = anon.get(f'/documents/{item_id}/{attachment_id}', base_url='https://localhost')
        self.assertEqual(document.status_code, 200)
        self.assertNotIn('attachment;', document.headers.get('Content-Disposition', ''))
        document.close()
        self.assert_inline_pdf_responses(anon, f'/documents/{item_id}/{attachment_id}',
                                         b'%PDF-1.7 test fixture')
        self.assertEqual(anon.get('/api/admin/items', base_url='https://localhost').status_code, 401)
        self.assertEqual(self.client.put(f'/api/admin/items/{item_id}',
            headers={'X-CSRF-Token': self.csrf, 'Content-Type': 'application/json'},
            json={'title': 'Updated field guide', 'description': 'Updated', 'subject': 'first-aid'},
            base_url='https://localhost').status_code, 204)
        self.assertEqual(self.client.delete(f'/api/admin/items/{item_id}',
            headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost').status_code, 204)

    def test_admin_can_add_document_from_a_public_url(self):
        def fake_download(url, destination):
            self.assertEqual(url, 'https://example.org/guide.pdf')
            destination.write_bytes(b'%PDF-1.7 downloaded fixture')
            return 'downloaded-guide.pdf'

        with patch.object(webapp, 'download_public_attachment', side_effect=fake_download) as downloader:
            response = self.client.post('/api/admin/items', headers={'X-CSRF-Token': self.csrf},
                data={'title': 'Remote field guide', 'description': 'Reference',
                      'subject': 'preparedness',
                      'cover': (io.BytesIO(b'\x89PNG\r\n\x1a\ntest'), 'cover.png'),
                      'attachment_url': 'https://example.org/guide.pdf'},
                content_type='multipart/form-data', base_url='https://localhost')
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        downloader.assert_called_once()
        item = self.client.get('/api/admin/items', base_url='https://localhost').get_json()[0]
        self.assertEqual(item['attachments'][0]['filename'], 'downloaded-guide.pdf')
        self.assertEqual(item['attachments'][0]['source'], 'url')
        options = self.client.get('/api/admin/export/options', base_url='https://localhost').get_json()
        self.assertEqual([(entry['id'], entry['mode']) for entry in options],
                         [('source:' + item['attachments'][0]['id'], 'online')])
        result = self.prepare_export([entry['id'] for entry in options]).get_json()
        self.assertEqual(result['catalogues'], [])
        exported = result['config']
        self.assertEqual(exported['offline_catalogues'], [])
        self.assertEqual(self.prepare_export(['item:' + item['id']]).status_code, 400)
        asset = exported['assets'][0]
        self.assertEqual(asset['url'], 'https://example.org/guide.pdf')
        self.assertEqual(asset['sha256'], hashlib.sha256(b'%PDF-1.7 downloaded fixture').hexdigest())
        self.assertEqual(asset['expected_bytes'], len(b'%PDF-1.7 downloaded fixture'))
        webapp.library.validate_asset(asset)
        with self.client.get(
                f"/private/{item['id']}/{item['attachments'][0]['id']}", base_url='https://localhost') as document:
            self.assertEqual(document.data, b'%PDF-1.7 downloaded fixture')

    def test_document_sources_preserve_mixed_attachments_after_edit(self):
        def fake_download(url, destination):
            destination.write_bytes(b'%PDF-1.7 imported fixture')
            return 'imported.pdf'

        with patch.object(webapp, 'download_public_attachment', side_effect=fake_download):
            response = self.client.post('/api/admin/items', headers={'X-CSRF-Token': self.csrf},
                data={'title': 'Mixed sources', 'description': 'Reference',
                      'subject': 'preparedness', 'attachment_url': 'https://example.org/guide.pdf',
                      'cover': (io.BytesIO(b'\x89PNG\r\n\x1a\ntest'), 'cover.png'),
                      'attachments': (io.BytesIO(b'%PDF-1.7 uploaded fixture'), 'uploaded.pdf')},
                content_type='multipart/form-data', base_url='https://localhost')
        self.assertEqual(response.status_code, 201, response.data)
        item_id = response.get_json()['id']
        response = self.client.put(f'/api/admin/items/{item_id}',
            headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost',
            json={'title': 'Edited sources', 'description': 'New description', 'subject': 'first-aid'})
        self.assertEqual(response.status_code, 204)
        item = self.client.get('/api/admin/items', base_url='https://localhost').get_json()[0]
        self.assertEqual((item['title'], item['description'], item['subject']),
                         ('Edited sources', 'New description', 'first-aid'))
        self.assertEqual({a['filename']: a['source'] for a in item['attachments']},
                         {'uploaded.pdf': 'upload', 'imported.pdf': 'url'})
        options = self.client.get('/api/admin/export/options', base_url='https://localhost').get_json()
        self.assertEqual(sorted(entry['mode'] for entry in options), ['offline', 'online'])
        with patch.object(webapp.urllib.request, 'urlopen') as network:
            result = self.prepare_export([entry['id'] for entry in options]).get_json()
            self.assertEqual(len(result['config']['assets']), 1)
            self.assertEqual(result['config']['assets'][0]['url'], 'https://example.org/guide.pdf')
            self.assertEqual(result['config']['assets'][0]['collection'], 'first-aid')
            self.assertEqual(len(result['catalogues']), 1)
            with self.catalogue_download(result['catalogues'][0]['token']) as response:
                self.assertEqual(response.status_code, 200)
                with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
                    catalogue = json.loads(archive.read('catalogue.json'))
                    self.assertEqual([a['filename'] for a in catalogue['entry']['item']['attachments']],
                                     ['uploaded.pdf'])
                    self.assertEqual(len(catalogue['files']), 2)  # Upload and cover only.
                    payloads = [archive.read(f['path']) for f in catalogue['files']]
                    self.assertIn(b'%PDF-1.7 uploaded fixture', payloads)
                    self.assertNotIn(b'%PDF-1.7 imported fixture', payloads)
        network.assert_not_called()

    def test_export_rejects_stale_zip_ticket_after_source_url_restored(self):
        item_id = self.export_fixture()
        result = self.prepare_export(['item:' + item_id]).get_json()
        with closing(webapp.connect_db()) as db:
            attachment = db.execute('SELECT * FROM attachment WHERE item_id=? LIMIT 1',
                                    (item_id,)).fetchone()
            source = {'path': 'public/' + attachment['stored_path'],
                      'url': 'https://example.org/restored.pdf', 'max_bytes': 1000,
                      'sha256': 'a' * 64}
            db.execute('INSERT INTO attachment_source VALUES(?,?)',
                       (attachment['id'], json.dumps(source)))
            db.commit()
        self.assertEqual(self.catalogue_download(result['catalogues'][0]['token']).status_code, 409)

    def test_remote_document_urls_must_be_public_https(self):
        with self.assertRaisesRegex(ValueError, 'public HTTPS'):
            webapp.validate_public_attachment_url('http://example.org/guide.pdf')
        with patch.object(webapp.socket, 'getaddrinfo', return_value=[
                (webapp.socket.AF_INET, webapp.socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))]):
            with self.assertRaisesRegex(ValueError, 'public IP'):
                webapp.validate_public_attachment_url('https://example.org/guide.pdf')

    def archive_fixture(self, filename='field-guide.pdf'):
        public = webapp.DATA_ROOT / 'public'
        public.mkdir(parents=True, exist_ok=True)
        path = public / filename
        path.write_bytes(b'%PDF-test-content')
        record = {'asset': {'title': 'Field guide', 'collection': 'general-reference',
                            'path': 'public/' + filename}, 'bytes': path.stat().st_size,
                  'sha256': 'a' * 64}
        lock = webapp.DATA_ROOT / 'acquired.json'
        lock.write_text(json.dumps({'public/' + filename: record}), encoding='utf-8')
        return path, lock

    def test_archive_edit_requires_admin_csrf_and_valid_metadata(self):
        self.archive_fixture()
        endpoint = '/api/admin/archive/field-guide.pdf'
        valid = {'title': 'Updated guide', 'subject': 'first-aid'}
        self.assertEqual(webapp.app.test_client().put(endpoint, json=valid).status_code, 401)
        self.assertEqual(self.client.put(endpoint, json=valid, base_url='https://localhost').status_code, 400)
        for body in [[], {}, {**valid, 'title': ' '}, {**valid, 'title': 'x' * 201},
                     {**valid, 'title': 12}, {**valid, 'subject': 'unknown'},
                     {**valid, 'subject': []}]:
            self.assertEqual(self.client.put(endpoint, json=body,
                headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost').status_code, 400)
        self.assertEqual(self.client.put('/api/admin/archive/missing.pdf', json=valid,
            headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost').status_code, 404)

    def test_archive_edit_persists_without_changing_download_identity(self):
        path, lock = self.archive_fixture()
        original = (path.read_bytes(), lock.read_bytes())
        webapp.STARTER_MANIFEST.write_text(json.dumps({'assets': [{'path': 'public/' + path.name}]}))
        response = self.client.put('/api/admin/archive/' + path.name,
            json={'title': '  Outdoor first aid  ', 'subject': 'first-aid'},
            headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')
        self.assertEqual(response.status_code, 200)
        self.assertEqual((path.read_bytes(), lock.read_bytes()), original)
        # A later starter metadata refresh must not undo the local display edit.
        records = json.loads(lock.read_text())
        records['public/' + path.name]['asset']['title'] = 'New publisher title'
        lock.write_text(json.dumps(records))
        listed = self.client.get('/api/admin/archive', base_url='https://localhost').get_json()[0]
        self.assertEqual((listed['title'], listed['subject'], listed['managed']),
                         ('Outdoor first aid', 'first-aid', True))
        public = webapp.app.test_client()
        self.assertEqual(public.get('/api/subjects/general-reference').get_json()['items'], [])
        entries = public.get('/api/subjects/first-aid').get_json()['items']
        self.assertEqual([(row['title'], row['filename']) for row in entries],
                         [('Outdoor first aid', path.name)])
        with webapp.app.test_request_context():
            webapp.g.db = webapp.connect_db()
            self.assertEqual(webapp.subject_assigned_count('general-reference'), 0)
            self.assertEqual(webapp.subject_assigned_count('first-aid'), 1)
        with public.get('/library/' + path.name) as response:
            self.assertEqual(response.status_code, 200)
        removed = self.client.delete('/api/admin/archive/' + path.name,
            json={'confirm': path.name}, headers={'X-CSRF-Token': self.csrf},
            base_url='https://localhost')
        self.assertEqual(removed.status_code, 204)
        with closing(webapp.connect_db()) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM archive_metadata').fetchone()[0], 0)

    def test_archive_html_edit_and_stale_override_subject_cleanup(self):
        path, lock = self.archive_fixture('startup-card.html')
        self.assertEqual(self.client.put('/api/admin/archive/' + path.name,
            json={'title': 'Recovery card', 'subject': 'computing-docs'},
            headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost').status_code, 200)
        # CLI/reset can retire the acquisition without going through the web UI.
        lock.write_text('{}')
        self.assertEqual(self.client.delete('/api/admin/subjects/computing-docs',
            headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost').status_code, 204)
        with closing(webapp.connect_db()) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM archive_metadata').fetchone()[0], 0)

    def test_personal_archive_removes_retired_and_starter_assets(self):
        public = webapp.DATA_ROOT / 'public'
        public.mkdir(parents=True)
        old_name = 'public/retired-guide.pdf'
        active_name = 'public/current-guide.pdf'
        active_non_pdf = 'public/startup-card.html'
        (public / 'retired-guide.pdf').write_bytes(b'%PDF-old')
        (public / 'current-guide.pdf').write_bytes(b'%PDF-current')
        (public / 'startup-card.html').write_text('<p>Start</p>', encoding='utf-8')
        records = {
            old_name: {'asset': {'title': 'Retired guide'}, 'bytes': 8},
            active_name: {'asset': {'title': 'Current guide'}, 'bytes': 12},
            active_non_pdf: {'asset': {'title': 'Startup card'}, 'bytes': 12},
        }
        (webapp.DATA_ROOT / 'acquired.json').write_text(json.dumps(records), encoding='utf-8')
        webapp.STARTER_MANIFEST.write_text(json.dumps({'assets': [
            {'path': active_name}, {'path': active_non_pdf}]}),
                                           encoding='utf-8')

        anonymous = webapp.app.test_client()
        self.assertEqual(anonymous.get('/api/admin/archive', base_url='https://localhost').status_code, 401)
        listed = self.client.get('/api/admin/archive', base_url='https://localhost')
        self.assertEqual(listed.status_code, 200)
        self.assertEqual({item['filename']: item['managed'] for item in listed.get_json()},
                         {'retired-guide.pdf': False, 'current-guide.pdf': True,
                          'startup-card.html': True})

        endpoint = '/api/admin/archive/retired-guide.pdf'
        missing_confirmation = self.client.delete(endpoint,
            headers={'X-CSRF-Token': self.csrf, 'Content-Type': 'application/json'}, json={},
            base_url='https://localhost')
        self.assertEqual(missing_confirmation.status_code, 400)
        removed = self.client.delete(endpoint,
            headers={'X-CSRF-Token': self.csrf}, json={'confirm': 'retired-guide.pdf'},
            base_url='https://localhost')
        self.assertEqual(removed.status_code, 204)
        self.assertFalse((public / 'retired-guide.pdf').exists())
        remaining = json.loads((webapp.DATA_ROOT / 'acquired.json').read_text())
        self.assertNotIn(old_name, remaining)

        managed_pdf = self.client.delete('/api/admin/archive/current-guide.pdf',
            headers={'X-CSRF-Token': self.csrf}, json={'confirm': 'current-guide.pdf'},
            base_url='https://localhost')
        self.assertEqual(managed_pdf.status_code, 204)
        self.assertFalse((public / 'current-guide.pdf').exists())

        managed_html = self.client.delete('/api/admin/archive/startup-card.html',
            headers={'X-CSRF-Token': self.csrf}, json={'confirm': 'startup-card.html'},
            base_url='https://localhost')
        self.assertEqual(managed_html.status_code, 204)
        self.assertFalse((public / 'startup-card.html').exists())
        self.assertNotIn(active_non_pdf, json.loads((webapp.DATA_ROOT / 'acquired.json').read_text()))

    def test_admin_preferences_set_pdf_tab_behavior_and_library_subtitle(self):
        with patch.dict(webapp.os.environ, {'CYBERDECK_HOSTNAME': 'cyberdeck-test.lan'}):
            home = self.client.get('/', base_url='https://localhost')
        self.assertIn('OFFLINE LIBRARY · CYBERDECK-TEST'.encode(), home.data)
        self.assertIn(b'class="cards columns-3"', home.data)

        public = webapp.DATA_ROOT / 'public'
        public.mkdir(parents=True)
        (public / 'guide.pdf').write_bytes(b'%PDF-preference-test')
        (webapp.DATA_ROOT / 'acquired.json').write_text(json.dumps({
            'public/guide.pdf': {'asset': {'title': 'Guide', 'collection': 'preparedness'},
                                 'bytes': 20}
        }), encoding='utf-8')
        same_tab = self.client.get('/subjects/preparedness', base_url='https://localhost')
        self.assertNotIn(b'target="_blank"', same_tab.data)

        response = self.client.put('/api/admin/settings',
            headers={'X-CSRF-Token': self.csrf},
            json={'pdf_open_mode': 'new_tab', 'subtitle': 'FIELD LIBRARY · HOUSEHOLD',
                  'home_columns': '4', 'accent_color': '#336699'},
            base_url='https://localhost')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['settings']['subtitle'], 'FIELD LIBRARY · HOUSEHOLD')
        self.assertEqual(response.get_json()['settings']['home_columns'], 4)
        self.assertEqual(response.get_json()['settings']['pdf_open_mode'], 'new_tab')
        self.assertEqual(response.get_json()['settings']['accent_color'], '#336699')
        new_tab = self.client.get('/subjects/preparedness', base_url='https://localhost')
        self.assertIn(b'target="_blank" rel="noopener"', new_tab.data)
        self.assertIn(('FIELD LIBRARY \u00b7 HOUSEHOLD').encode(), new_tab.data)
        home = self.client.get('/', base_url='https://localhost')
        self.assertIn(b'class="cards columns-4"', home.data)
        self.assertIn(b'<main class="home-main-columns-4">', home.data)
        self.assertIn(b'id="site-accent-theme" href="/accent.css"', home.data)
        accent = self.client.get('/accent.css', base_url='https://localhost')
        self.assertEqual(accent.data, b':root{--accent:#336699;}')
        self.assertIn(b'<meta name="theme-color" content="#336699">', home.data)
        self.assertIn(b'href="https://browse.library.kiwix.org/" rel="noopener noreferrer" hidden target="_blank"',
                      home.data)
        self.assertIn(b'Link opening', self.client.get('/admin', base_url='https://localhost').data)

        invalid = self.client.put('/api/admin/settings',
            headers={'X-CSRF-Token': self.csrf},
            json={'pdf_open_mode': [], 'subtitle': 'Bad'}, base_url='https://localhost')
        self.assertEqual(invalid.status_code, 400)

        invalid_columns = self.client.put('/api/admin/settings',
            headers={'X-CSRF-Token': self.csrf},
            json={'home_columns': 6}, base_url='https://localhost')
        self.assertEqual(invalid_columns.status_code, 400)
        invalid_color = self.client.put('/api/admin/settings',
            headers={'X-CSRF-Token': self.csrf}, json={'accent_color': 'url(javascript:alert(1))'},
            base_url='https://localhost')
        self.assertEqual(invalid_color.status_code, 400)

    def test_default_accent_is_green_and_applied_to_all_public_views(self):
        for path in ('/', '/subjects/first-aid'):
            with self.subTest(path=path):
                response = self.client.get(path, base_url='https://localhost')
                self.assertEqual(response.status_code, 200)
                self.assertIn(b'id="site-accent-theme" href="/accent.css"', response.data)
                accent = self.client.get('/accent.css', base_url='https://localhost')
                self.assertEqual(accent.data, b':root{--accent:#c4f36b;}')

    def test_favicon_preview_is_public_validated_and_preserves_artwork(self):
        client = webapp.app.test_client()
        original = (webapp.APP_DIR / 'static' / 'favicon.svg').read_text(encoding='utf-8')
        default = client.get('/favicon.svg', base_url='https://localhost')
        self.assertEqual(default.status_code, 200)
        self.assertEqual(default.get_data(as_text=True), original)
        preview = client.get('/favicon.svg', query_string={'color': '#79ACE6'},
                             base_url='https://localhost')
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.mimetype, 'image/svg+xml')
        self.assertEqual(preview.get_data(as_text=True), original.replace('#c4f36b', '#79ace6'))
        self.assertEqual(client.get('/favicon.svg', base_url='https://localhost').data, default.data)
        saved = self.client.put('/api/admin/settings/accent',
            headers={'X-CSRF-Token': self.csrf}, json={'accent_color': '#336699'},
            base_url='https://localhost')
        self.assertEqual(saved.status_code, 200)
        home = client.get('/', base_url='https://localhost')
        self.assertIn(b'href="/favicon.svg?color=%23336699"', home.data)
        favicon = client.get('/favicon.svg', base_url='https://localhost')
        self.assertEqual(favicon.get_data(as_text=True), original.replace('#c4f36b', '#336699'))
        for color in ('red', '#123', '<script>alert(1)</script>'):
            with self.subTest(color=color):
                invalid = client.get('/favicon.svg', query_string={'color': color},
                                     base_url='https://localhost')
                self.assertEqual(invalid.status_code, 400)
        with closing(webapp.connect_db()) as db, db:
            db.execute('DELETE FROM admin')
        self.assertEqual(client.get('/favicon.svg', base_url='https://localhost').status_code, 200)

    def test_document_inventory_combines_profile_and_live_added_content(self):
        item_id = self.export_fixture()
        response = self.client.get('/api/admin/documents', base_url='https://localhost')
        self.assertEqual(response.status_code, 200)
        entries = response.get_json()
        self.assertTrue(any(row['record_type'] == 'managed' and row['origin'] == 'acquired'
                            for row in entries))
        self.assertTrue(any(row['record_type'] == 'uploaded' and row['id'] == item_id
                            and row['origin'] == 'live-added' for row in entries))

    def test_headless_modes_expose_hotspot_while_container_hides_host_controls(self):
        for mode in ('container', 'debian', 'headless'):
            with self.subTest(mode=mode), patch.dict(webapp.os.environ,
                                                      {'CYBERDECK_RUNTIME_MODE': mode}), \
                    patch('webapp.helper', return_value={'active': False, 'configured': False}):
                page = self.client.get('/admin', base_url='https://localhost')
                self.assertEqual(page.status_code, 200)
                self.assertNotIn(b'id="system"', page.data)
                if mode == 'container':
                    self.assertNotIn(b'id="hotspot"', page.data)
                else:
                    self.assertIn(b'id="hotspot"', page.data)
                if mode == 'container':
                    self.assertNotIn(b'id="overview"', page.data)
                    unavailable_endpoints = ('/api/admin/system', '/api/admin/hotspot',
                                             '/api/admin/hotspot/password',
                                             '/api/admin/hostname')
                    power_unavailable = self.client.post('/api/admin/power',
                        json={'action': 'poweroff', 'confirm': 'POWEROFF'},
                        headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')
                    self.assertEqual(power_unavailable.status_code, 404)
                else:
                    self.assertIn(b'id="overview"', page.data)
                    self.assertEqual(self.client.get('/api/admin/system',
                                     base_url='https://localhost').status_code, 200)
                    for endpoint in ('/api/admin/hotspot', '/api/admin/hotspot/password'):
                        self.assertEqual(self.client.get(endpoint,
                            base_url='https://localhost').status_code, 200)
                    self.assertIn(b'id="hostname-form"', page.data)
                    self.assertEqual(self.client.get('/api/admin/hostname',
                                     base_url='https://localhost').status_code, 200)
                    unavailable_endpoints = ()
                for endpoint in unavailable_endpoints:
                    self.assertEqual(self.client.get(endpoint, base_url='https://localhost').status_code, 404)
                if mode != 'container':
                    self.assertEqual(self.client.post('/api/admin/hotspot', json={'action': 'start'},
                        headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost').status_code, 200)

    def test_zip_path_traversal_is_rejected(self):
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, 'w') as archive:
            archive.writestr('../outside/index.html', '<script>bad()</script>')
        output = webapp.PRIVATE_ROOT / 'escape-test'
        with self.assertRaisesRegex(ValueError, 'unsafe paths'):
            webapp.validate_and_extract_zip(io.BytesIO(payload.getvalue()), output)
        self.assertFalse((webapp.PRIVATE_ROOT / 'outside').exists())

    def test_html_preview_uses_an_isolated_sandbox(self):
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, 'w') as archive:
            archive.writestr('index.html', '<h1>Offline reader</h1>')
        response = self.client.post('/api/admin/items', headers={'X-CSRF-Token': self.csrf},
            data={'title': 'Book', 'description': '', 'subject': 'general-reference',
                  'attachments': (io.BytesIO(payload.getvalue()), 'book.zip')},
            content_type='multipart/form-data', base_url='https://localhost')
        self.assertEqual(response.status_code, 201)
        item_id = response.get_json()['id']
        attachment = self.client.get('/api/admin/items', base_url='https://localhost').get_json()[0]['attachments'][0]
        self.client.post('/language', data={'language': 'da', 'next': '/', 'csrf_token': self.csrf},
                         base_url='https://localhost')
        viewer = self.client.get(f"/private/{item_id}/{attachment['id']}/viewer", base_url='https://localhost')
        self.assertEqual(viewer.status_code, 200)
        self.assertIn(b'<html lang="da">', viewer.data)
        self.assertIn('<title>Dokumentlæser</title>'.encode(), viewer.data)
        self.assertIn(b'sandbox="allow-scripts"', viewer.data)
        self.assertIn(b'name="language"', viewer.data)
        self.assertIn('Skift sprog'.encode(), viewer.data)
        self.assertIn(f'viewer.css?v={webapp.APP_VERSION}'.encode(), viewer.data)
        viewer_css = (Path(webapp.__file__).resolve().parent / 'static' / 'viewer.css').read_text(encoding='utf-8')
        self.assertIn('iframe{display:block;margin:0;width:100%;height:100%;border:0;background:#fff;color-scheme:light}',
                      viewer_css)
        self.assertIn("script-src 'none'", viewer.headers['Content-Security-Policy'])
        self.assertIn("frame-src 'self'", viewer.headers['Content-Security-Policy'])
        self.assertIn("form-action 'self'", viewer.headers['Content-Security-Policy'])
        changed_language = self.client.post('/language', data={
            'language': 'en', 'next': f'/private/{item_id}/{attachment["id"]}/viewer',
            'csrf_token': self.csrf}, base_url='https://localhost')
        self.assertEqual(changed_language.status_code, 303)
        english_viewer = self.client.get(
            f"/private/{item_id}/{attachment['id']}/viewer", base_url='https://localhost')
        self.assertIn('<title>Document reader</title>'.encode(), english_viewer.data)
        public_viewer = webapp.app.test_client().get(
            f"/documents/{item_id}/{attachment['id']}/viewer", base_url='https://localhost')
        self.assertEqual(public_viewer.status_code, 200)
        self.assertIn(b'sandbox="allow-scripts"', public_viewer.data)
        self.assertIn(b'name="language"', public_viewer.data)

    def test_power_actions_need_typed_confirmation_and_are_mocked(self):
        with patch.object(webapp.subprocess, 'run', return_value=Mock(returncode=0, stderr='')) as run:
            payload = {'action': 'poweroff', 'confirm': 'NO'}
            response = self.client.post('/api/admin/power', headers={'X-CSRF-Token': self.csrf},
                                        json=payload, base_url='https://localhost')
            self.assertEqual(response.status_code, 400)
            run.assert_not_called()
            payload['confirm'] = 'POWEROFF'
            response = self.client.post('/api/admin/power', headers={'X-CSRF-Token': self.csrf},
                                        json=payload, base_url='https://localhost')
            self.assertEqual(response.status_code, 200)
            run.assert_called_once_with(['sudo', '-n', '/usr/bin/systemctl', 'poweroff'],
                                        capture_output=True, text=True, timeout=30, check=False)

    def test_hotspot_password_reveal_is_admin_only_and_not_cacheable(self):
        anonymous = webapp.app.test_client()
        denied = anonymous.get('/api/admin/hotspot/password', base_url='https://localhost')
        self.assertEqual(denied.status_code, 401)
        with patch.object(webapp, 'helper', return_value={'password': 'secret-pass-8'}) as helper:
            response = self.client.get('/api/admin/hotspot/password', base_url='https://localhost')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {'password': 'secret-pass-8'})
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        helper.assert_called_once_with('hotspot-password')

    def test_download_source_is_https_and_kiwix_only(self):
        self.assertEqual(webapp.safe_public_https_url('https://download.kiwix.org/zim/a.zim'),
                         'https://download.kiwix.org/zim/a.zim')
        load_balancer = 'https://lb.download.kiwix.org/zim/maps/maps_en_nordics_2026-08a.zim'
        self.assertEqual(webapp.safe_public_https_url(load_balancer), load_balancer)
        self.assertEqual(
            webapp.canonical_kiwix_download_url(load_balancer),
            'https://mirror.download.kiwix.org/zim/maps/maps_en_nordics_2026-08a.zim')
        self.assertEqual(
            webapp.canonical_kiwix_download_url('https://mirror.download.kiwix.org/zim/a.zim'),
            'https://mirror.download.kiwix.org/zim/a.zim')
        with self.assertRaises(ValueError):
            webapp.safe_public_https_url('http://download.kiwix.org/zim/a.zim')
        with self.assertRaises(ValueError):
            webapp.safe_public_https_url('https://127.0.0.1/private.zim')
        with self.assertRaises(ValueError):
            webapp.safe_public_https_url('https://download.kiwix.org.attacker.example/zim/a.zim')

    def test_document_url_save_and_refresh_preserve_identity_and_failed_copy(self):
        old_payload = b'%PDF-1.7 old copy'
        def download(url, destination):
            destination.write_bytes(old_payload)
            return 'guide.pdf'
        with patch.object(webapp, 'download_public_attachment', side_effect=download):
            created = self.client.post('/api/admin/items', headers={'X-CSRF-Token': self.csrf},
                data={'title': 'Guide', 'subject': 'first-aid', 'description': 'Keep description',
                      'origin_source': 'https://example.org/publisher',
                      'attachment_url': 'https://example.org/old.pdf',
                      'attachments': (io.BytesIO(b'%PDF-local'), 'local.pdf')},
                base_url='https://localhost')
        self.assertEqual(created.status_code, 201, created.data)
        item_id = created.get_json()['id']
        item = self.client.get('/api/admin/items', base_url='https://localhost').get_json()[0]
        remote = next(a for a in item['attachments'] if a['source'] == 'url')
        local = next(a for a in item['attachments'] if a['source'] == 'upload')
        endpoint = f"/api/admin/items/{item_id}/attachments/{remote['id']}/refresh"
        public_url = f"/documents/{item_id}/{remote['id']}"
        body = {'title': 'Edited guide', 'description': 'Keep description', 'subject': 'first-aid',
                'attachment_urls': {remote['id']: 'https://example.org/new.pdf'}}
        with patch.object(webapp, 'validate_public_attachment_url', side_effect=lambda url: url), \
                patch.object(webapp, 'download_public_attachment') as network:
            response = self.client.put(f'/api/admin/items/{item_id}', json=body,
                headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')
            self.assertEqual(response.status_code, 204, response.data)
            network.assert_not_called()
        item = self.client.get('/api/admin/items', base_url='https://localhost').get_json()[0]
        self.assertEqual(item['origin_source'], 'https://example.org/publisher')
        self.assertEqual(next(a for a in item['attachments'] if a['id'] == remote['id'])['download_url'],
                         'https://example.org/new.pdf')
        with webapp.app.test_request_context('/'):
            webapp.g.db = webapp.connect_db()
            exported = next(e['asset'] for e in webapp.export_inventory() if e['id'] == 'source:' + remote['id'])
            self.assertEqual(exported['url'], 'https://example.org/new.pdf')
            self.assertNotIn('sha256', exported)
            self.assertNotIn('expected_bytes', exported)
        with self.client.get(public_url, base_url='https://localhost') as response:
            self.assertEqual(response.data, old_payload)
        self.assertEqual(webapp.app.test_client().post(endpoint, base_url='https://localhost').status_code, 401)
        self.assertEqual(self.client.post(endpoint, base_url='https://localhost').status_code, 400)
        bad = {**body, 'title': 'Must not save', 'attachment_urls': {local['id']: 'https://example.org/no.pdf'}}
        response = self.client.put(f'/api/admin/items/{item_id}', json=bad,
            headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get('/api/admin/items', base_url='https://localhost').get_json()[0]['title'], 'Edited guide')
        with patch.object(webapp.socket, 'getaddrinfo', return_value=[
                (webapp.socket.AF_INET, webapp.socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))]):
            unsafe = {**body, 'attachment_urls': {remote['id']: 'https://localhost/internal.pdf'}}
            response = self.client.put(f'/api/admin/items/{item_id}', json=unsafe,
                headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')
        self.assertEqual(response.status_code, 400)
        for failure in ('invalid', 'interrupted'):
            def fail(url, destination):
                destination.write_bytes(b'<html>not a PDF</html>')
                if failure == 'interrupted':
                    raise OSError('connection interrupted')
                return 'guide.pdf'
            with patch.object(webapp, 'download_public_attachment', side_effect=fail):
                response = self.client.post(endpoint, headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')
            self.assertEqual(response.status_code, 409, response.data)
            with self.client.get(public_url, base_url='https://localhost') as response:
                self.assertEqual(response.data, old_payload)
        def replacement(url, destination):
            self.assertEqual(url, 'https://example.org/new.pdf')
            destination.write_bytes(b'%PDF-1.7 replacement')
            return 'renamed.pdf'
        with patch.object(webapp, 'download_public_attachment', side_effect=replacement):
            response = self.client.post(endpoint, headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')
        self.assertEqual(response.status_code, 204, response.data)
        with self.client.get(public_url, base_url='https://localhost') as response:
            self.assertEqual(response.data, b'%PDF-1.7 replacement')
        current = self.client.get('/api/admin/items', base_url='https://localhost').get_json()[0]
        self.assertEqual(current['id'], item_id)
        self.assertEqual(current['description'], 'Keep description')
        self.assertEqual({a['id'] for a in current['attachments']}, {remote['id'], local['id']})
        self.assertEqual(next(a for a in current['attachments'] if a['id'] == remote['id'])['filename'], 'guide.pdf')

    def test_html_attachment_refresh_validates_before_switching_viewer(self):
        def html_zip(text, path='index.html'):
            payload = io.BytesIO()
            with zipfile.ZipFile(payload, 'w') as archive:
                archive.writestr(path, text)
            return payload.getvalue()
        def download(url, destination):
            destination.write_bytes(html_zip('old page'))
            return 'site.zip'
        with patch.object(webapp, 'download_public_attachment', side_effect=download):
            response = self.client.post('/api/admin/items', headers={'X-CSRF-Token': self.csrf},
                data={'title': 'Site', 'subject': 'first-aid', 'attachment_url': 'https://example.org/site.zip'},
                base_url='https://localhost')
        self.assertEqual(response.status_code, 201, response.data)
        item = self.client.get('/api/admin/items', base_url='https://localhost').get_json()[0]
        attachment = item['attachments'][0]
        endpoint = f"/api/admin/items/{item['id']}/attachments/{attachment['id']}/refresh"
        public_url = f"/documents/{item['id']}/{attachment['id']}/html/index.html"
        for archive_path, expected_status, content in [('../index.html', 409, b'old page'), ('index.html', 204, b'new page')]:
            def replace(url, destination):
                destination.write_bytes(html_zip('new page', archive_path))
                return 'site.zip'
            with patch.object(webapp, 'download_public_attachment', side_effect=replace):
                response = self.client.post(endpoint, headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')
            self.assertEqual(response.status_code, expected_status, response.data)
            with self.client.get(public_url, base_url='https://localhost') as response:
                self.assertEqual(response.data, content)

    def test_imported_document_source_edit_and_refresh_keep_metadata(self):
        path, lock = self.archive_fixture()
        record = json.loads(lock.read_text())['public/field-guide.pdf']
        record['sha256'] = webapp.library.sha256(path)
        record['asset'].update(url='https://example.org/old.pdf', max_bytes=1024,
                               document_id='stable-guide', origin_source='https://example.org/publisher')
        lock.write_text(json.dumps({'public/field-guide.pdf': record}))
        item = self.client.get('/api/admin/archive', base_url='https://localhost').get_json()[0]
        self.assertEqual(item['origin_source'], 'https://example.org/publisher')
        original = path.read_bytes()
        body = {'title': 'My guide', 'subject': 'first-aid', 'search_terms': 'medical',
                'download_url': 'https://example.org/new.pdf'}
        with patch.object(webapp, 'validate_public_attachment_url', side_effect=lambda url: url):
            response = self.client.put('/api/admin/archive/field-guide.pdf', json=body,
                headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(json.loads(lock.read_text())['public/field-guide.pdf'], record)
        endpoint = '/api/admin/archive/field-guide.pdf/refresh'
        with patch.object(webapp, 'download_public_attachment', side_effect=OSError('failed')):
            response = self.client.post(endpoint, headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(path.read_bytes(), original)
        def download(url, destination):
            self.assertEqual(url, 'https://example.org/new.pdf')
            destination.write_bytes(b'%PDF-1.7 new edition')
            return 'new.pdf'
        write_json = webapp.library.write_json
        def fail_index_commit(destination, data):
            if destination == lock and data['public/field-guide.pdf']['sha256'] != record['sha256']:
                raise OSError('Cannot commit acquisition index')
            return write_json(destination, data)
        with patch.object(webapp, 'download_public_attachment', side_effect=download), \
                patch.object(webapp.library, 'write_json', side_effect=fail_index_commit):
            response = self.client.post(endpoint, headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(json.loads(lock.read_text())['public/field-guide.pdf'], record)
        with patch.object(webapp, 'download_public_attachment', side_effect=download):
            response = self.client.post(endpoint, headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')
        self.assertEqual(response.status_code, 204, response.data)
        self.assertEqual(path.read_bytes(), b'%PDF-1.7 new edition')
        current = json.loads(lock.read_text())
        self.assertEqual(list(current), ['public/field-guide.pdf'])
        self.assertEqual(current['public/field-guide.pdf']['asset']['document_id'], 'stable-guide')
        item = self.client.get('/api/admin/archive', base_url='https://localhost').get_json()[0]
        self.assertEqual((item['title'], item['subject'], item['search_terms'], item['origin_source']),
                         ('My guide', 'first-aid', 'medical', 'https://example.org/publisher'))
        self.assertEqual(item['sha256'], webapp.library.sha256(path))
        self.assertFalse(list((webapp.PRIVATE_ROOT / 'document-update-staging').iterdir()))

    def test_document_refresh_preserves_pinned_publisher_url_resolution(self):
        path, lock = self.archive_fixture()
        digest = webapp.library.sha256(path)
        record = {'asset': {'path': 'public/field-guide.pdf', 'title': 'Guide',
                           'collection': 'first-aid', 'max_bytes': 1024, 'sha256': digest,
                           'url': 'https://www.mediafire.com/file/abc123/guide.pdf/file',
                           'url_resolver': 'mediafire'}, 'sha256': digest, 'bytes': path.stat().st_size}
        lock.write_text(json.dumps({'public/field-guide.pdf': record}))
        def resolve(asset):
            webapp.library.validate_asset(asset)
            self.assertEqual(asset['sha256'], digest)
            return 'https://download1.mediafire.com/abc123/guide.pdf'
        def download(url, destination):
            self.assertEqual(url, 'https://download1.mediafire.com/abc123/guide.pdf')
            destination.write_bytes(b'%PDF-new-publisher-edition')
            return 'guide.pdf'
        with patch.object(webapp.library, 'download_url', side_effect=resolve), \
                patch.object(webapp, 'download_public_attachment', side_effect=download):
            response = self.client.post('/api/admin/archive/field-guide.pdf/refresh',
                headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')
        self.assertEqual(response.status_code, 204, response.data)
        saved = json.loads(lock.read_text())['public/field-guide.pdf']
        self.assertEqual(saved['asset']['url'], record['asset']['url'])
        self.assertEqual(saved['asset']['sha256'], webapp.library.sha256(path))

    def test_imported_zim_origin_is_loaded_and_saved_on_first_edit(self):
        filename = 'test.zim'
        path = webapp.DATA_ROOT / 'zim' / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'ZIM\x04test')
        (webapp.DATA_ROOT / 'acquired.json').write_text(json.dumps({'zim/test.zim': {
            'asset': {'path': 'zim/test.zim', 'title': 'Test', 'collection': 'first-aid',
                      'url': 'https://download.kiwix.org/zim/test.zim',
                      'origin_source': 'https://example.org/original'},
            'bytes': 8, 'sha256': 'a' * 64}}))
        item = self.client.get('/api/admin/zims', base_url='https://localhost').get_json()[0]
        self.assertEqual(item['origin_source'], 'https://example.org/original')
        response = self.client.put('/api/admin/zims/file-test.zim', json={
            'title': 'Edited', 'subject': 'first-aid', 'origin_source': 'https://example.org/updated'},
            headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')
        self.assertEqual(response.status_code, 200, response.data)
        item = self.client.get('/api/admin/zims', base_url='https://localhost').get_json()[0]
        self.assertEqual(item['origin_source'], 'https://example.org/updated')

    def test_manual_zim_checksum_is_pinned_in_the_download_manifest(self):
        url = 'https://download.kiwix.org/zim/test.zim'
        with patch.object(webapp, 'inspect_kiwix_asset', return_value=(url, 123, 'b' * 64, None)) as inspect, \
                patch.object(webapp, 'ensure_zim_capacity'):
            response = self.client.post('/api/admin/zims', json={
                'title': 'Test', 'subject': 'first-aid', 'url': url, 'expected_sha256': 'B' * 64,
                'origin_source': 'https://example.org/publisher'},
                headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')
        self.assertEqual(response.status_code, 202, response.data)
        inspect.assert_called_once_with(url, 'B' * 64)
        manifest = webapp.PRIVATE_ROOT / 'requests' / (response.get_json()['id'] + '.json')
        asset = json.loads(manifest.read_text())['assets'][0]
        self.assertEqual(asset['sha256'], 'b' * 64)
        self.assertEqual(asset['expected_bytes'], 123)
        self.assertEqual(asset['origin_source'], 'https://example.org/publisher')
        self.assertIn('administrator', asset['hash_provenance'])
        webapp.library.validate_asset(asset)

    def test_manual_zim_checksum_fallback_conflict_and_validation(self):
        url = 'https://download.kiwix.org/zim/test.zim'
        def response(body=b'', headers=None):
            result = MagicMock()
            result.__enter__.return_value = result
            result.geturl.return_value = url
            result.headers = headers or {}
            result.read.return_value = body
            return result
        def head():
            return response(headers={'Content-Length': '123'})
        # Sidecar responses must retain their requested path.
        sidecar = response(b'a' * 64)
        sidecar.geturl.return_value = url + '.sha256'
        with patch.object(webapp.urllib.request, 'urlopen', side_effect=[head(), sidecar]):
            with self.assertRaisesRegex(ValueError, 'conflicts'):
                webapp.inspect_kiwix_asset(url, 'b' * 64)
        with patch.object(webapp.urllib.request, 'urlopen', side_effect=[head(), sidecar]):
            self.assertEqual(webapp.inspect_kiwix_asset(url, 'A' * 64)[2], 'a' * 64)
        with patch.object(webapp.urllib.request, 'urlopen', side_effect=[head(), OSError(), OSError()]):
            result = webapp.inspect_kiwix_asset(url, 'B' * 64)
            self.assertEqual(result[2:], ('b' * 64, None))
        with patch.object(webapp.urllib.request, 'urlopen', side_effect=[head(), OSError(), OSError()]):
            with self.assertRaisesRegex(ValueError, 'pinned checksum'):
                webapp.inspect_kiwix_asset(url)
        for value in ('invalid', 'g' * 64, 'a' * 63, 123, None):
            with patch.object(webapp.urllib.request, 'urlopen') as network:
                response = self.client.post('/api/admin/zims', json={
                    'title': 'Test', 'subject': 'first-aid', 'url': url, 'expected_sha256': value},
                    headers={'X-CSRF-Token': self.csrf}, base_url='https://localhost')
                self.assertEqual(response.status_code, 400, response.data)
                network.assert_not_called()

    def test_inspect_kiwix_asset_reads_checksum_from_canonical_download_host(self):
        digest = 'a' * 64

        class Response:
            def __init__(self, url, headers=None, body=b''):
                self.url = url
                self.headers = headers or {}
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def geturl(self):
                return self.url

            def read(self, limit=-1):
                return self.body[:limit]

        responses = [
            Response('https://mirror.download.kiwix.org/zim/maps/maps_en_nordics_2026-08a.zim',
                     {'Content-Length': '5300000000'}),
            Response('https://download.kiwix.org/zim/maps/maps_en_nordics_2026-08a.zim.sha256',
                     body=f'{digest}  maps_en_nordics_2026-08a.zim\n'.encode('ascii')),
        ]
        source = 'https://lb.download.kiwix.org/zim/maps/maps_en_nordics_2026-08a.zim'
        with patch.object(webapp.urllib.request, 'urlopen', side_effect=responses) as open_url:
            result = webapp.inspect_kiwix_asset(source)

        self.assertEqual(result, (
            'https://mirror.download.kiwix.org/zim/maps/maps_en_nordics_2026-08a.zim',
            5_300_000_000,
            digest,
            'https://download.kiwix.org/zim/maps/maps_en_nordics_2026-08a.zim.sha256',
        ))
        checksum_request = open_url.call_args_list[1].args[0]
        self.assertEqual(checksum_request.full_url,
                         'https://download.kiwix.org/zim/maps/maps_en_nordics_2026-08a.zim.sha256')


if __name__ == '__main__':
    unittest.main()
