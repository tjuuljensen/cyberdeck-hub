#!/usr/bin/env python3
"""Cyberdeck public library and authenticated content administration."""
from __future__ import annotations

import argparse
from contextlib import closing
import errno
import functools
import hashlib
import hmac
import html
import http.client
import ipaddress
import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import os
from pathlib import Path, PurePosixPath
import platform
import re
import secrets
import shutil
import socket
import ssl
import stat
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import xml.etree.ElementTree as ET
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones
from html.parser import HTMLParser

import library
from itsdangerous import URLSafeTimedSerializer, BadSignature

from flask import (Flask, abort, g, jsonify, make_response, redirect, render_template,
                   request, send_file, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.exceptions import NotFound
from werkzeug.utils import secure_filename

# Release identity shipped with the app; bump for each deployed app release.
APP_VERSION = '0.2.0-beta.12'
DEFAULT_ACCENT_COLOR = '#c4f36b'
APP_DIR = Path(__file__).resolve().parent
TRANSLATIONS_DIR = APP_DIR / 'translations'
DATA_ROOT = Path(os.environ.get('CYBERDECK_ROOT', '/srv/cyberdeck'))
PRIVATE_ROOT = Path(os.environ.get('CYBERDECK_PRIVATE', DATA_ROOT / 'private'))
DB_PATH = PRIVATE_ROOT / 'metadata.sqlite3'
STARTER_MANIFEST = Path(os.environ.get('CYBERDECK_STARTER_MANIFEST',
                                      '/usr/local/lib/cyberdeck/starter.json'))
CONFIG_PROFILES_ROOT = Path(os.environ.get(
    'CYBERDECK_CONFIG_PROFILES', '/usr/local/lib/cyberdeck/profiles'))
CYBERCHEF_ROOT = Path(os.environ.get('CYBERDECK_CYBERCHEF_DIR',
                                    '/opt/cyberdeck/modules/cyberchef'))
MAX_UPLOAD = 8 * 1024**3
MAX_ITEM_UPLOAD = 2 * 1024**3
MAX_ZIP_EXPANDED = 512 * 1024**2
MAX_ZIP_FILES = 2500
ZIM_DOWNLOAD_RESERVE_BYTES = 1_000_000_000
DEFAULT_SUBJECTS = [
    ('preparedness', 'Preparedness', 'Practical guidance for outages, weather, and emergencies.'),
    ('first-aid', 'Health and first aid', 'First aid, health references, and emergency care.'),
    ('equipment-manuals', 'Equipment and repair', 'Device manuals, repair guides, and workshop references.'),
    ('regional-maps', 'Maps and navigation', 'Regional maps and navigation resources.'),
    ('general-reference', 'General reference', 'Wikipedia and broad reference collections.'),
]
ONLINE_CRISIS_LINKS = [
    {'id': 'world-monitor', 'title': 'World Monitor', 'url': 'https://www.worldmonitor.app/',
     'description': 'ui.0756'},
    {'id': 'dr-nyheder', 'title': 'DR Nyheder', 'url': 'https://www.dr.dk/nyheder',
     'description': 'ui.0757'},
    {'id': 'dr-lyd-and-p4', 'title': 'DR Lyd and P4', 'url': 'https://www.dr.dk/lyd',
     'description': 'ui.0758'},
    {'id': 'tv-2-nyheder', 'title': 'TV 2 Nyheder', 'url': 'https://nyheder.tv2.dk/',
     'description': 'ui.0759'},
    {'id': 'politi-update-rss-directory', 'title': 'Politi Update RSS directory', 'url': 'https://politi.dk/faa-politi-update-som-mobilapp-og-rss-feed',
     'description': 'ui.0772'},
]
POLICE_RSS_BASE = 'https://via.ritzau.dk/rss/short-messages/latest'
POLICE_RSS_FEEDS = {
    'all': ('All police updates', ''),
    'bornholm': ('Bornholms Politi', '90799'),
    'funen': ('Fyns Politi', '90797'),
    'greenland': ('Grønlands Politi', '13562883'),
    'copenhagen': ('Københavns Politi', '90685'),
    'western-copenhagen': ('Københavns Vestegns Politi', '90718'),
    'central-west-jutland': ('Midt- og Vestjyllands Politi', '90687'),
    'central-west-zealand': ('Midt- og Vestsjællands Politi', '13562881'),
    'special-crime': ('National enhed for Særlig Kriminalitet', '13562884'),
    'north-jutland': ('Nordjyllands Politi', '13562880'),
    'north-zealand': ('Nordsjællands Politi', '90719'),
    'south-jutland': ('Syd- og Sønderjyllands Politi', '90686'),
    'south-east-jutland': ('Sydøstjyllands Politi', '90720'),
    'south-zealand': ('Sydsjællands og Lolland-Falsters Politi', '90594'),
    'east-jutland': ('Østjyllands Politi', '90721'),
    'national-police': ('Rigspolitiet', '90752'),
}
POLICE_RSS_MAX_BYTES = 1024 * 1024
POLICE_RSS_MAX_ITEMS = 30
POLICE_RSS_CACHE_SECONDS = 120
_police_rss_cache = {}
_police_rss_locks = {}
_police_rss_state_lock = threading.Lock()
DEFAULT_ONLINE_SOURCE_CARDS = [{
    'id': 'online-sources', 'title': 'Internet-required sources',
    'description': 'ui.0752', 'links': ONLINE_CRISIS_LINKS,
}]
DEFAULT_RSS_CARDS = [{
    'id': 'danish-police', 'title': 'Danish Police Update RSS',
    'description': 'ui.0762',
    'feeds': [{'id': feed_id, 'title': label,
               'url': POLICE_RSS_BASE + (('?' + urllib.parse.urlencode({'publisherId': publisher_id}))
                                         if publisher_id else '')}
              for feed_id, (label, publisher_id) in POLICE_RSS_FEEDS.items()],
}]
ALLOWED_EXTENSIONS = {'.pdf', '.docx', '.zip'}
IMAGE_MIMES = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp'}
KIWIX_DOWNLOAD_HOSTS = {'download.kiwix.org', 'lb.download.kiwix.org'}
KIWIX_FIRST_PARTY_MIRROR = 'mirror.download.kiwix.org'
KIWIX_ONLINE_CATALOG = 'https://browse.library.kiwix.org/'
_catalog_connectivity = {'available': False, 'expires': 0.0}
_catalog_connectivity_lock = threading.Lock()


class _PlainFeedText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        if data.strip():
            self.parts.append(data.strip())


def validate_rss_url(value, expected_host=None):
    """Accept public HTTPS feed URLs only; disallow credentials and private hosts."""
    if not isinstance(value, str) or len(value) > 2048 or any(ord(char) < 32 for char in value):
        raise ValueError('RSS feed URL must be a valid HTTPS URL')
    parsed = urllib.parse.urlsplit(value)
    host = (parsed.hostname or '').lower().rstrip('.')
    if (parsed.scheme != 'https' or not host or parsed.port not in (None, 443) or
            parsed.username or parsed.password or parsed.fragment or
            (expected_host and host != expected_host)):
        raise ValueError('RSS feed URLs and redirects must use the same public HTTPS host')
    try:
        address = ipaddress.ip_address(host)
        addresses = [address]
    except ValueError:
        try:
            addresses = [ipaddress.ip_address(row[4][0])
                         for row in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)]
        except (OSError, ValueError) as error:
            raise ValueError('RSS feed host could not be resolved') from error
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError('RSS feed URL must resolve only to public IP addresses')
    return parsed, host


class _SameHostRssRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, hostname):
        super().__init__()
        self.hostname = hostname

    def redirect_request(self, request, fp, code, message, headers, new_url):
        try:
            validate_rss_url(new_url, self.hostname)
        except ValueError:
            return None
        return super().redirect_request(request, fp, code, message, headers, new_url)


def _feed_text(element, limit):
    if element is None:
        return ''
    raw = ''.join(element.itertext())[:8192]
    parser = _PlainFeedText()
    try:
        parser.feed(html.unescape(raw))
        parser.close()
    except (ValueError, TypeError):
        return ''
    plain_text = re.sub(r'\s+([,.;:!?])', r'\1', ' '.join(parser.parts))
    return plain_text[:limit]


def _published_utc(value):
    """Normalize common RSS and Atom date forms to UTC ISO-8601."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    published = None
    try:
        published = parsedate_to_datetime(raw)
    except (TypeError, ValueError, OverflowError):
        pass
    if published is None:
        try:
            iso_value = raw[:-1] + '+00:00' if raw[-1:].lower() == 'z' else raw
            published = datetime.fromisoformat(iso_value)
        except (TypeError, ValueError, OverflowError):
            pass
    if published is None and re.fullmatch(r'\d{9,13}(?:\.\d+)?', raw):
        try:
            timestamp = float(raw)
            if len(raw.split('.', 1)[0]) >= 13:
                timestamp /= 1000
            published = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            pass
    if published is None:
        return None
    # Some feeds omit an offset even though RFC 3339/RSS producers should include one.
    # Assume UTC so the same entry has a stable instant on every Cyberdeck client.
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    return published.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def _published_field_utc(fields):
    """Try common RSS, RDF/RSS 1.0, and Atom item date fields in priority order."""
    for name in ('pubdate', 'published', 'updated', 'issued', 'created', 'date', 'modified'):
        element = fields.get(name)
        if element is None:
            continue
        published = _published_utc(_feed_text(element, 128))
        if published:
            return published
    return None


def valid_timezone_name(value):
    if not isinstance(value, str) or len(value) > 64:
        return False
    try:
        ZoneInfo(value)
        return True
    except (ValueError, ZoneInfoNotFoundError):
        return False


def host_timezone_name():
    """Read the Debian host's configured IANA timezone, falling back to UTC."""
    candidates = [os.environ.get('TZ')]
    try:
        candidates.append(Path('/etc/timezone').read_text(encoding='utf-8').strip())
    except OSError:
        pass
    try:
        localtime = Path('/etc/localtime').resolve(strict=True).as_posix()
        marker = '/zoneinfo/'
        if marker in localtime:
            candidates.append(localtime.split(marker, 1)[1])
    except OSError:
        pass
    for candidate in candidates:
        if candidate and valid_timezone_name(candidate):
            return candidate
    return 'UTC'


def timezone_choices():
    return sorted(name for name in available_timezones()
                  if name == 'UTC' or not name.startswith(('posix/', 'right/')))


def _valid_card_url(value, label):
    if not isinstance(value, str) or len(value) > 2048 or any(ord(char) < 32 for char in value):
        raise ValueError(f'{label} must be a valid HTTPS URL')
    parsed = urllib.parse.urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.port not in (None, 443) or
            parsed.username or parsed.password):
        raise ValueError(f'{label} must use HTTPS and cannot include credentials')
    return value


def _validate_card_list(cards, kind):
    max_cards = 10 if kind == 'RSS' else 50
    if not isinstance(cards, list) or len(cards) > max_cards:
        raise ValueError(f'Invalid {kind} card list')
    seen_cards = set()
    result = []
    total_entries = 0
    for card in cards:
        if not isinstance(card, dict):
            raise ValueError(f'Invalid {kind} card')
        card_id = card.get('id')
        title = card.get('title')
        description = card.get('description', '')
        if (not isinstance(card_id, str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', card_id) or
                card_id in seen_cards or not isinstance(title, str) or not 1 <= len(title.strip()) <= 100 or
                not isinstance(description, str) or len(description) > 500 or
                any(ord(char) < 32 and char not in '\n\t' for char in title + description)):
            raise ValueError(f'Invalid or duplicate {kind} card definition')
        seen_cards.add(card_id)
        normalized = {'id': card_id, 'title': title.strip(), 'description': description.strip()}
        source_language = card.get('source_language', 'en')
        if not isinstance(source_language, str) or source_language not in SUPPORTED_LANGUAGES:
            raise ValueError('Card source language must be supported')
        normalized['source_language'] = source_language
        field = 'links' if kind == 'online source' else 'feeds'
        entries = card.get(field)
        if not isinstance(entries, list) or len(entries) > 100:
            raise ValueError(f'{kind.title()} cards must contain at most 100 entries')
        total_entries += len(entries)
        if total_entries > 500:
            raise ValueError(f'Too many {kind} card entries')
        seen_entries = set()
        normalized_entries = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError(f'Invalid {kind} card entry')
            entry_id = entry.get('id')
            entry_title = entry.get('title')
            if (not isinstance(entry_id, str) or
                    not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', entry_id) or
                    entry_id in seen_entries or not isinstance(entry_title, str) or
                    not 1 <= len(entry_title.strip()) <= 120):
                raise ValueError(f'Invalid or duplicate {kind} entry')
            seen_entries.add(entry_id)
            if kind == 'online source':
                entry_description = entry.get('description', '')
                if not isinstance(entry_description, str) or len(entry_description) > 300:
                    raise ValueError('Online source descriptions must be at most 300 characters')
                normalized_entries.append({'id': entry_id, 'title': entry_title.strip(),
                                           'url': _valid_card_url(entry.get('url'), 'Online source URL'),
                                           'description': entry_description.strip()})
            else:
                enabled = entry.get('enabled', True)
                if type(enabled) is not bool:
                    raise ValueError('RSS feed enabled must be true or false')
                normalized_entries.append({'id': entry_id, 'title': entry_title.strip(),
                                           'url': _valid_card_url(entry.get('url'), 'RSS feed URL'),
                                           'enabled': enabled})
        normalized[field] = normalized_entries
        translations = card.get('translations', {})
        if not isinstance(translations, dict) or any(code not in SUPPORTED_LANGUAGES for code in translations):
            raise ValueError('Card translations must use supported languages')
        normalized_translations = {}
        for code, value in translations.items():
            if (not isinstance(value, dict) or
                    not isinstance(value.get('title', ''), str) or len(value.get('title', '')) > 100 or
                    not isinstance(value.get('description', ''), str) or len(value.get('description', '')) > 500):
                raise ValueError('Card translations contain invalid titles or descriptions')
            normalized_translations[code] = {
                'title': value.get('title', '').strip(),
                'description': value.get('description', '').strip()}
        normalized['translations'] = normalized_translations
        offline_display = card.get('offline_display', 'hide')
        if not isinstance(offline_display, str) or offline_display not in {'hide', 'inactive'}:
            raise ValueError('Offline display must be hide or inactive')
        normalized['offline_display'] = offline_display
        result.append(normalized)
    return result


def _configured_card_list(key, defaults, kind):
    row = g.db.execute('SELECT value FROM site_setting WHERE key=?', (key,)).fetchone()
    if row is None:
        return json.loads(json.dumps(defaults))
    try:
        return _validate_card_list(json.loads(row['value']), kind)
    except (TypeError, ValueError, json.JSONDecodeError):
        app.logger.error('Ignoring invalid stored %s card configuration', kind)
        return json.loads(json.dumps(defaults))


def configured_online_source_cards():
    return _configured_card_list('online_source_cards', DEFAULT_ONLINE_SOURCE_CARDS, 'online source')


def configured_rss_cards():
    return _configured_card_list('rss_cards', DEFAULT_RSS_CARDS, 'RSS')


def restore_empty_default_police_feeds(cards):
    """Repair the original built-in Police card once if a prior edit erased its feeds."""
    was_in_transaction = getattr(g.db, 'in_transaction', False)
    marker = g.db.execute("SELECT value FROM site_setting WHERE key='police_rss_feeds_restored'").fetchone()
    if marker:
        return cards
    default = next((card for card in DEFAULT_RSS_CARDS if card['id'] == 'danish-police'), None)
    existing = next((card for card in cards if card['id'] == 'danish-police'), None)
    if existing and not existing['feeds'] and default:
        existing['feeds'] = json.loads(json.dumps(default['feeds']))
        cards = _validate_card_list(cards, 'RSS')
        g.db.execute('INSERT INTO site_setting(key,value) VALUES(?,?) '
                     'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                     ('rss_cards', json.dumps(cards, ensure_ascii=False)))
    g.db.execute('INSERT INTO site_setting(key,value) VALUES(?,?) '
                 'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                 ('police_rss_feeds_restored', '1'))
    if not was_in_transaction:
        g.db.commit()
    return cards


def _localized_text(title, description, translations=None):
    localized = (translations or {}).get(current_language(), {})
    return {'display_title': localized.get('title') or translate(title),
            'display_description': localized.get('description') or translate(description)}


def _localized_card(card):
    return {**card, **_localized_text(card.get('title', ''), card.get('description', ''),
                                      card.get('translations'))}


def _rss_entry(card_id, feed_id):
    cards = configured_rss_cards()
    card = next((item for item in cards if item['id'] == card_id), None)
    feed = next((item for item in card['feeds'] if item['id'] == feed_id), None) if card else None
    if not card or not feed or not feed.get('enabled', True):
        raise ValueError('Choose a configured RSS feed')
    feed_url_digest = hashlib.sha256(feed['url'].encode('utf-8')).hexdigest()[:16]
    cache_key = f'{card_id}:{feed_id}:{feed_url_digest}'
    now = time.monotonic()
    with _police_rss_state_lock:
        cached = _police_rss_cache.get(cache_key)
        if cached and now < cached['expires']:
            return {key: value for key, value in cached.items() if key != 'expires'}
        fetch_lock = _police_rss_locks.setdefault(cache_key, threading.Lock())
    if not fetch_lock.acquire(blocking=False):
        if cached:
            return {**{key: value for key, value in cached.items() if key != 'expires'}, 'stale': True}
        raise RuntimeError('The selected feed is already being retrieved; try again shortly')
    try:
        with _police_rss_state_lock:
            cached = _police_rss_cache.get(cache_key)
            if cached and time.monotonic() < cached['expires']:
                return {key: value for key, value in cached.items() if key != 'expires'}
        url = feed['url']
        _parsed, hostname = validate_rss_url(url)
        request = urllib.request.Request(url, headers={'User-Agent': 'Cyberdeck-Hub-RSS/1',
                                                       'Accept': 'application/rss+xml, application/xml, text/xml'})
        opener = urllib.request.build_opener(_SameHostRssRedirect(hostname))
        with opener.open(request, timeout=5) as response:
            validate_rss_url(response.geturl(), hostname)
            raw = response.read(POLICE_RSS_MAX_BYTES + 1)
        if len(raw) > POLICE_RSS_MAX_BYTES:
            raise ValueError('RSS response exceeds the size limit')
        lowered = raw.lower()
        if b'<!doctype' in lowered or b'<!entity' in lowered:
            raise ValueError('RSS response contains unsupported XML declarations')
        root = ET.fromstring(raw)
        root_name = root.tag.rsplit('}', 1)[-1].lower()
        if root_name == 'rss':
            container = next((child for child in root if child.tag.rsplit('}', 1)[-1].lower() == 'channel'), None)
            item_name = 'item'
        elif root_name == 'feed':
            container = root
            item_name = 'entry'
        else:
            raise ValueError('The selected source did not return RSS or Atom')
        if container is None:
            raise ValueError('RSS channel is missing')
        entries = []
        for item in container:
            if item.tag.rsplit('}', 1)[-1].lower() != item_name:
                continue
            fields = {child.tag.rsplit('}', 1)[-1].lower(): child for child in item}
            title = _feed_text(fields.get('title'), 240)
            if not title:
                continue
            link_element = fields.get('link')
            link = (link_element.attrib.get('href', '') if link_element is not None and
                    link_element.attrib.get('href') else _feed_text(link_element, 2048))
            try:
                parsed_link = urllib.parse.urlsplit(link)
                if (parsed_link.scheme != 'https' or not parsed_link.hostname or
                        parsed_link.port not in (None, 443) or parsed_link.username or parsed_link.password):
                    link = ''
            except ValueError:
                link = ''
            summary = fields.get('description') or fields.get('summary') or fields.get('content')
            entries.append({'title': title, 'link': link,
                            'summary': _feed_text(summary, 700),
                            'published': _published_field_utc(fields)})
            if len(entries) >= POLICE_RSS_MAX_ITEMS:
                break
        result = {'feed': feed_id, 'label': feed['title'], 'items': entries,
                  'fetched_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                  'stale': False}
        with _police_rss_state_lock:
            _police_rss_cache[cache_key] = {**result, 'expires': time.monotonic() + POLICE_RSS_CACHE_SECONDS}
        return result
    except (OSError, ValueError, ET.ParseError, urllib.error.URLError, TimeoutError,
            http.client.HTTPException) as error:
        if cached:
            return {**{key: value for key, value in cached.items() if key != 'expires'}, 'stale': True}
        raise RuntimeError('The selected RSS feed is temporarily unavailable') from error
    finally:
        fetch_lock.release()

app = Flask(__name__, template_folder='templates', static_folder='static')
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SECURE=True,
                  SESSION_COOKIE_SAMESITE='Strict', MAX_CONTENT_LENGTH=MAX_UPLOAD,
                  PERMANENT_SESSION_LIFETIME=3600)
secret = os.environ.get('CYBERDECK_SESSION_KEY_FILE')
if secret and Path(secret).is_file():
    app.secret_key = Path(secret).read_bytes()
else:
    app.secret_key = os.environ.get('CYBERDECK_SESSION_KEY')

def load_translation_catalogues(directory=TRANSLATIONS_DIR):
    """Load stable message IDs, English defaults with context, and locale strings."""
    directory = Path(directory)
    languages = json.loads((directory / 'languages.json').read_text(encoding='utf-8'))
    if (not isinstance(languages, dict) or 'en' not in languages or
            any(not re.fullmatch(r'[a-z]{2,3}(?:-[A-Z]{2})?', str(code)) or
                not isinstance(label, str) or not label.strip()
                for code, label in languages.items())):
        raise ValueError('Translation language metadata is invalid or has no English default')
    english = json.loads((directory / 'en.json').read_text(encoding='utf-8'))
    if (not isinstance(english, dict) or
            any(not re.fullmatch(r'ui\.[0-9]{4}', str(key)) or
                not isinstance(value, dict) or
                not isinstance(value.get('default'), str) or
                not value['default'] or
                not isinstance(value.get('context'), str) or
                not value['context'].strip()
                for key, value in english.items())):
        raise ValueError('English catalogue must pair stable message IDs with defaults and context')
    defaults = {key: value['default'] for key, value in english.items()}
    catalogues = {'en': dict(defaults)}
    for code in languages:
        if code == 'en':
            continue
        catalogue = json.loads((directory / f'{code}.json').read_text(encoding='utf-8'))
        if (not isinstance(catalogue, dict) or
                any(not isinstance(key, str) or key not in defaults or
                    not isinstance(value, str) for key, value in catalogue.items())):
            raise ValueError(f'Translation catalogue {code} must map known message IDs to strings')
        catalogues[code] = {key: catalogue.get(key, value)
                            for key, value in defaults.items()}
    return languages, catalogues, defaults


SUPPORTED_LANGUAGES, TRANSLATIONS, ENGLISH_DEFAULTS = load_translation_catalogues()
DEFAULT_TEXT_IDS = {message: message_id for message_id, message in ENGLISH_DEFAULTS.items()}
RUNTIME_CAPABILITIES = {
    'debian': frozenset({'system', 'hotspot', 'power', 'hostname', 'storage', 'cyberchef'}),
    'headless': frozenset({'system', 'hotspot', 'power', 'hostname', 'storage', 'cyberchef'}),
    'container': frozenset(),
}


def current_language():
    selected = session.get('language', 'en')
    return selected if selected in SUPPORTED_LANGUAGES else 'en'


def translate(message, **values):
    message_id = message if message in ENGLISH_DEFAULTS else DEFAULT_TEXT_IDS.get(message)
    default = ENGLISH_DEFAULTS.get(message_id, message)
    translated = TRANSLATIONS[current_language()].get(message_id, default)
    for name, value in values.items():
        translated = translated.replace('{' + name + '}', str(value))
    return translated


app.jinja_env.globals['t'] = translate


@app.post('/language')
def language_select():
    token = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token')
    if not token or not hmac.compare_digest(token, session.get('csrf', '')):
        abort(400, 'CSRF validation failed')
    selected = request.form.get('language', '')
    if selected not in SUPPORTED_LANGUAGES:
        return jsonify(error='Choose a supported interface language'), 400
    session['language'] = selected
    destination = request.form.get('next', '/')
    parsed = urllib.parse.urlsplit(destination)
    if parsed.scheme or parsed.netloc or not destination.startswith('/') or destination.startswith('//'):
        destination = '/'
    return redirect(destination, code=303)

# Kiwix remains on its loopback HTTP backend but shares the Hub's HTTPS origin.
from kiwix_https import proxy as kiwix_proxy
app.add_url_rule('/kiwix/', endpoint='kiwix_root', view_func=kiwix_proxy,
                 defaults={'path': ''}, methods=['GET', 'HEAD'])
app.add_url_rule('/kiwix/<path:path>', endpoint='kiwix_path', view_func=kiwix_proxy,
                 methods=['GET', 'HEAD'])

# Preserve existing Kiwix bookmarks created before the single-origin migration.
@app.get('/content/kiwix/', defaults={'path': ''})
@app.get('/content/kiwix/<path:path>')
def legacy_kiwix_path(path):
    target = url_for('kiwix_root') if not path else url_for('kiwix_path', path=path)
    if request.query_string:
        target += '?' + request.query_string.decode('latin1')
    return redirect(target, code=308)

@app.context_processor
def template_settings():
    capabilities = runtime_capabilities()
    return {'app_version': APP_VERSION,
            'default_accent_color': DEFAULT_ACCENT_COLOR,
            'language': current_language(), 'languages': SUPPORTED_LANGUAGES,
            'locale_catalog': {
                **TRANSLATIONS[current_language()],
                **{default: TRANSLATIONS[current_language()][message_id]
                   for message_id, default in ENGLISH_DEFAULTS.items()},
            },
            'cyberdeck_host': os.environ.get('CYBERDECK_HOSTNAME', 'cyberdeck.local'),
            'capabilities': capabilities,
            'admin_configured': admin_account_exists(),
            'site_preferences': site_preferences()}


def runtime_capabilities():
    """Return the host actions supported by the selected deployment adapter."""
    mode = os.environ.get('CYBERDECK_RUNTIME_MODE', 'debian').lower()
    supported = RUNTIME_CAPABILITIES.get(mode, frozenset())
    return {name: name in supported for name in
            ('system', 'hotspot', 'power', 'hostname', 'storage', 'cyberchef')}


def cyberchef_request_host():
    """Return the Hub hostname for an installed full-Debian CyberChef module."""
    if os.environ.get('CYBERDECK_RUNTIME_MODE', 'debian').lower() not in {'debian', 'headless'}:
        return None
    hostname = os.environ.get('CYBERDECK_HOSTNAME', '').strip().lower().rstrip('.')
    if not hostname or len(hostname) > 253 or not all(
            re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label)
            for label in hostname.split('.')):
        return None
    return hostname


def cyberchef_module():
    """Return module metadata only when an installed static build is safe to serve."""
    host = cyberchef_request_host()
    if not host or CYBERCHEF_ROOT.is_symlink():
        return None
    root = CYBERCHEF_ROOT.resolve()
    index = root / 'index.html'
    marker = root / 'cyberdeck-module.json'
    if (not index.is_file() or index.is_symlink() or not marker.is_file() or
            marker.is_symlink()):
        return None
    try:
        metadata = json.loads(marker.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if (not isinstance(metadata, dict) or metadata.get('name') != 'cyberchef' or
            not re.fullmatch(r'[a-f0-9]{40}', str(metadata.get('build', ''))) or
            not re.fullmatch(r'[a-f0-9]{64}', str(metadata.get('archive_sha256', '')))):
        return None
    try:
        port = int(os.environ.get('CYBERDECK_CYBERCHEF_PORT', '8445'))
    except ValueError:
        return None
    if not 1024 <= port <= 65535:
        return None
    return {'hostname': host, 'port': port, 'root': root, 'build': metadata['build']}


def capability_available(name):
    return runtime_capabilities().get(name, False)


def cyberchef_service_active():
    if not cyberchef_request_host():
        return False
    try:
        result = subprocess.run(['systemctl', 'is-active', '--quiet',
                                 'cyberdeck-cyberchef.service'],
                                check=False, capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def site_preferences():
    settings = {row['key']: row['value'] for row in g.db.execute(
        'SELECT key,value FROM site_setting').fetchall()}
    configured_mode = settings.get('pdf_open_mode', 'same_tab')
    if configured_mode not in {'same_tab', 'new_tab'}:
        configured_mode = 'same_tab'
    configured_columns = settings.get('home_columns', '3')
    if configured_columns not in {'3', '4', '5'}:
        configured_columns = '3'
    accent_color = settings.get('accent_color', DEFAULT_ACCENT_COLOR).lower()
    if not re.fullmatch(r'#[0-9a-f]{6}', accent_color):
        accent_color = '#c4f36b'
    try:
        always_show = json.loads(settings.get('always_show_subjects', '[]'))
    except (TypeError, json.JSONDecodeError):
        always_show = []
    valid_subjects = {row[0] for row in get_subjects()}
    if not isinstance(always_show, list):
        always_show = []
    always_show = [subject for subject in always_show
                   if isinstance(subject, str) and subject in valid_subjects]
    hostname = (os.environ.get('CYBERDECK_HOSTNAME') or socket.gethostname()).split('.', 1)[0].upper()
    display_timezone = settings.get('display_timezone', host_timezone_name())
    if not valid_timezone_name(display_timezone):
        display_timezone = host_timezone_name()
    return {'pdf_open_mode': configured_mode,
            'subtitle': settings.get('subtitle') or f'OFFLINE LIBRARY · {hostname}',
            'accent_color': accent_color,
            'home_columns': int(configured_columns),
            'display_timezone': display_timezone,
            'hide_empty_subjects': settings.get('hide_empty_subjects') == 'true',
            'always_show_subjects': always_show}


def hotspot_module_enabled():
    if not capability_available('hotspot'):
        return False
    row = g.db.execute("SELECT value FROM site_setting WHERE key='hotspot_module_enabled'").fetchone()
    return row is None or row['value'] == 'true'


def connect_db():
    PRIVATE_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    if DB_PATH.is_symlink():
        raise RuntimeError('Refusing a symlink at the private metadata database')
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('''CREATE TABLE IF NOT EXISTS admin (
        username TEXT PRIMARY KEY, password_hash TEXT NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS item (
        id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL,
        search_terms TEXT NOT NULL DEFAULT '',
        subject TEXT NOT NULL, cover TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
    db.execute('''CREATE TABLE IF NOT EXISTS attachment (
        id TEXT PRIMARY KEY, item_id TEXT NOT NULL REFERENCES item(id) ON DELETE CASCADE,
        filename TEXT NOT NULL, stored_path TEXT NOT NULL, kind TEXT NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS attachment_source (
        attachment_id TEXT PRIMARY KEY REFERENCES attachment(id) ON DELETE CASCADE,
        asset TEXT NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS zim (
        id TEXT PRIMARY KEY, title TEXT NOT NULL, subject TEXT NOT NULL,
        filename TEXT NOT NULL UNIQUE, source_url TEXT NOT NULL,
        bytes INTEGER, sha256 TEXT, status TEXT NOT NULL DEFAULT 'queued')''')
    db.execute('''CREATE TABLE IF NOT EXISTS site_setting (
        key TEXT PRIMARY KEY, value TEXT NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS import_transaction (
        id TEXT PRIMARY KEY, committed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
    subject_table_exists = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='library_subject'").fetchone()
    db.execute('''CREATE TABLE IF NOT EXISTS library_subject (
        id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL,
        display_order INTEGER NOT NULL, translations TEXT NOT NULL DEFAULT '{}',
        source_language TEXT NOT NULL DEFAULT 'en')''')
    if not subject_table_exists:
        db.executemany('INSERT INTO library_subject(id,title,description,display_order) VALUES(?,?,?,?)',
                       [(slug, title, description, order)
                        for order, (slug, title, description) in enumerate(DEFAULT_SUBJECTS)])
    subject_columns = {row['name'] for row in db.execute('PRAGMA table_info(library_subject)')}
    if 'translations' not in subject_columns:
        db.execute("ALTER TABLE library_subject ADD COLUMN translations TEXT NOT NULL DEFAULT '{}'")
    if 'source_language' not in subject_columns:
        db.execute("ALTER TABLE library_subject ADD COLUMN source_language TEXT NOT NULL DEFAULT 'en'")
    db.execute('''CREATE TABLE IF NOT EXISTS archive_metadata (
        filename TEXT PRIMARY KEY, title TEXT NOT NULL, search_terms TEXT NOT NULL DEFAULT '',
        subject TEXT NOT NULL REFERENCES library_subject(id) ON DELETE CASCADE)''')
    item_columns = {row['name'] for row in db.execute('PRAGMA table_info(item)')}
    if 'search_terms' not in item_columns:
        db.execute("ALTER TABLE item ADD COLUMN search_terms TEXT NOT NULL DEFAULT ''")
    archive_columns = {row['name'] for row in db.execute('PRAGMA table_info(archive_metadata)')}
    if 'search_terms' not in archive_columns:
        db.execute("ALTER TABLE archive_metadata ADD COLUMN search_terms TEXT NOT NULL DEFAULT ''")
    db.executescript('''
        CREATE TRIGGER IF NOT EXISTS item_subject_insert
        BEFORE INSERT ON item
        WHEN NOT EXISTS (SELECT 1 FROM library_subject WHERE id=NEW.subject)
        BEGIN SELECT RAISE(ABORT, 'unknown subject'); END;
        CREATE TRIGGER IF NOT EXISTS item_subject_update
        BEFORE UPDATE OF subject ON item
        WHEN NOT EXISTS (SELECT 1 FROM library_subject WHERE id=NEW.subject)
        BEGIN SELECT RAISE(ABORT, 'unknown subject'); END;
        CREATE TRIGGER IF NOT EXISTS zim_subject_insert
        BEFORE INSERT ON zim
        WHEN NOT EXISTS (SELECT 1 FROM library_subject WHERE id=NEW.subject)
        BEGIN SELECT RAISE(ABORT, 'unknown subject'); END;
        CREATE TRIGGER IF NOT EXISTS zim_subject_update
        BEFORE UPDATE OF subject ON zim
        WHEN NOT EXISTS (SELECT 1 FROM library_subject WHERE id=NEW.subject)
        BEGIN SELECT RAISE(ABORT, 'unknown subject'); END;
    ''')
    db.commit()
    return db


def admin_account_exists():
    """Return whether the private database has an administrator account."""
    return g.db.execute('SELECT 1 FROM admin LIMIT 1').fetchone() is not None


def write_import_journal(stage_root, journal):
    """Persist the rollback plan before an import changes shared files."""
    path = stage_root / 'apply-journal.json'
    temporary = stage_root / '.apply-journal.tmp'
    with temporary.open('x', encoding='utf-8') as handle:
        json.dump(journal, handle, ensure_ascii=False)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    directory_flag = getattr(os, 'O_DIRECTORY', None)
    if directory_flag is not None:
        descriptor = os.open(stage_root, os.O_RDONLY | directory_flag)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def rollback_import_files(stage_root, journal):
    """Undo only destinations reserved by an uncommitted import journal."""
    roots = {'data': DATA_ROOT, 'private': PRIVATE_ROOT}
    for target in reversed(journal.get('targets', [])):
        if (not isinstance(target, dict) or target.get('root') not in roots or
                target.get('kind') not in {'file', 'directory'} or
                not isinstance(target.get('path'), str)):
            raise ValueError('Import recovery journal contains an unsafe destination')
        destination = library.safe_path(roots[target['root']], target['path'])
        if destination.is_symlink():
            raise ValueError('Import recovery refused a symlinked destination')
        if target['kind'] == 'directory':
            if destination.is_dir():
                shutil.rmtree(destination)
        elif destination.is_file():
            expected_hash = target.get('sha256')
            if expected_hash is None or library.sha256(destination) == expected_hash:
                destination.unlink()
    acquired = journal.get('acquired')
    if acquired is not None:
        if not isinstance(acquired, dict) or type(acquired.get('existed')) is not bool:
            raise ValueError('Import recovery journal has invalid acquisition state')
        destination = library.safe_path(DATA_ROOT, 'acquired.json')
        if destination.is_symlink():
            raise ValueError('Import recovery refused a symlinked acquisition index')
        if acquired['existed']:
            backup = library.safe_path(stage_root, 'rollback/acquired.json')
            if backup.is_file() and not backup.is_symlink():
                try:
                    # Reuse the already allocated backup blocks during a full-disk
                    # rollback when both roots share a filesystem.
                    os.replace(backup, destination)
                except OSError as error:
                    if error.errno != errno.EXDEV:
                        raise
                    # Cross-filesystem fallback keeps the backup intact so a
                    # later recovery can retry if this copy is interrupted.
                    with backup.open('rb') as source, destination.open('wb') as handle:
                        shutil.copyfileobj(source, handle, 1024 * 1024)
                        handle.flush()
                        os.fsync(handle.fileno())
        else:
            destination.unlink(missing_ok=True)


def recover_import_transactions(db):
    """Recover filesystem changes left by an interrupted configuration import."""
    staging = PRIVATE_ROOT / 'import-staging'
    if staging.is_symlink():
        raise RuntimeError('Refusing a symlink at the import staging directory')
    stages = [path for path in staging.iterdir() if path.is_dir() and not path.is_symlink()] \
        if staging.is_dir() else []
    journal_stages = {path.name: path for path in stages if (path / 'apply-journal.json').is_file()}
    committed = {row['id'] for row in db.execute('SELECT id FROM import_transaction').fetchall()}
    if not journal_stages and not committed:
        return
    db.execute('BEGIN IMMEDIATE')
    try:
        stages = [path for path in staging.iterdir() if path.is_dir() and not path.is_symlink()] \
            if staging.is_dir() else []
        journal_stages = {path.name: path for path in stages if (path / 'apply-journal.json').is_file()}
        committed = {row['id'] for row in db.execute('SELECT id FROM import_transaction').fetchall()}
        for transaction_id, stage_root in journal_stages.items():
            if not re.fullmatch(r'[0-9a-f]{32}', transaction_id):
                raise RuntimeError('Refusing an import journal with an invalid transaction ID')
            journal_path = stage_root / 'apply-journal.json'
            if journal_path.is_symlink():
                raise RuntimeError('Refusing a symlinked import recovery journal')
            journal = json.loads(journal_path.read_text(encoding='utf-8'))
            if not isinstance(journal, dict) or journal.get('id') != transaction_id:
                raise RuntimeError('Import recovery journal does not match its staging directory')
            if transaction_id not in committed:
                rollback_import_files(stage_root, journal)
            shutil.rmtree(stage_root)
            db.execute('DELETE FROM import_transaction WHERE id=?', (transaction_id,))
        for transaction_id in committed - journal_stages.keys():
            db.execute('DELETE FROM import_transaction WHERE id=?', (transaction_id,))
        db.commit()
    except Exception:
        db.rollback()
        raise


def get_subjects():
    return [tuple(row) for row in g.db.execute(
        'SELECT id,title,description FROM library_subject ORDER BY display_order,id').fetchall()]


def subject_assigned_count(subject):
    """Count manifest, ZIM, and uploaded records assigned to a subject.

    Return None when the acquisition manifest cannot be trusted, so removal
    fails closed rather than orphaning an uninspectable content assignment.
    """
    acquired_path = DATA_ROOT / 'acquired.json'
    records = {}
    try:
        if acquired_path.is_file():
            records = json.loads(acquired_path.read_text(encoding='utf-8'))
            if not isinstance(records, dict):
                return None
    except (OSError, json.JSONDecodeError):
        return None
    database_zims = {row['filename']: row['subject'] for row in
                     g.db.execute('SELECT filename,subject FROM zim')}
    archive_subjects = {row['filename']: row['subject'] for row in
                        g.db.execute('SELECT filename,subject FROM archive_metadata')}
    manifest_paths = {
        path for path, record in records.items()
        if isinstance(record, dict) and isinstance(record.get('asset'), dict)
        and (archive_subjects.get(path.removeprefix('public/'), record['asset'].get('collection'))
             if path.startswith('public/') else record['asset'].get('collection')) == subject
        and not (path.startswith('zim/') and Path(path).name in database_zims)
    }
    pending_zim_names = {name for name, assigned in database_zims.items() if assigned == subject}
    upload_count = g.db.execute('SELECT COUNT(*) FROM item WHERE subject=?', (subject,)).fetchone()[0]
    return len(manifest_paths) + len(pending_zim_names) + upload_count


def _subject_assigned_items(subject, limit=30):
    """List safe display labels for the records counted by subject_assigned_count."""
    items = [{'kind': 'ZIM', 'title': row['title'] or row['filename']}
             for row in g.db.execute('SELECT title,filename FROM zim WHERE subject=? ORDER BY title,filename',
                                     (subject,))]
    items.extend({'kind': 'Document', 'title': row['title']}
                 for row in g.db.execute('SELECT title FROM item WHERE subject=? ORDER BY title',
                                         (subject,)))
    acquired_path = DATA_ROOT / 'acquired.json'
    if acquired_path.is_symlink():
        raise ValueError('Refusing a symlink at the acquisition index')
    records = {}
    if acquired_path.is_file():
        records = json.loads(acquired_path.read_text(encoding='utf-8'))
        if not isinstance(records, dict):
            raise ValueError('Current acquisition index is not a JSON object')
    zims = {row['filename'] for row in g.db.execute('SELECT filename FROM zim')}
    archive_subjects = {row['filename']: row['subject'] for row in
                        g.db.execute('SELECT filename,subject FROM archive_metadata')}
    for path, record in records.items():
        if not isinstance(record, dict) or not isinstance(record.get('asset'), dict):
            continue
        asset = record['asset']
        filename = path.removeprefix('public/') if isinstance(path, str) else ''
        assigned = (archive_subjects.get(filename, asset.get('collection'))
                    if isinstance(path, str) and path.startswith('public/')
                    else asset.get('collection'))
        if assigned != subject or (isinstance(path, str) and path.startswith('zim/') and
                                   Path(path).name in zims):
            continue
        label = (asset.get('title') or Path(path).name
                 if isinstance(path, str) else 'Library item')
        kind = 'ZIM' if isinstance(path, str) and path.startswith('zim/') else 'Library file'
        items.append({'kind': kind, 'title': str(label)[:200]})
    return items[:limit]


def _settings_only_plan(config, remove_omitted, include_labels=True):
    """Compare imported settings with current subjects without touching content."""
    current_rows = [dict(row) for row in g.db.execute(
        'SELECT id,title,description,display_order FROM library_subject ORDER BY display_order,id')]
    current = {row['id']: row for row in current_rows}
    indexed = list(enumerate(config.get('subjects', [])))
    indexed.sort(key=lambda pair: (pair[1].get('display_order', pair[0]), pair[0]))
    incoming = []
    for order, (_source_order, subject) in enumerate(indexed):
        incoming.append({'id': subject['id'], 'title': subject['title'],
                         'description': subject.get('description', ''),
                         'translations': subject.get('translations', {}),
                         'display_order': order})
    incoming_ids = {row['id'] for row in incoming}
    additions, edits, unchanged = [], [], []
    for subject in incoming:
        old = current.get(subject['id'])
        if old is None:
            additions.append(subject)
            continue
        changes = {key: {'from': old[key], 'to': subject[key]}
                   for key in ('title', 'description', 'display_order', 'translations')
                   if (json.loads(old.get('translations') or '{}') if key == 'translations' else old[key]) != subject[key]}
        if changes:
            edits.append({'id': subject['id'], 'title': subject['title'], 'changes': changes})
        else:
            unchanged.append(subject['id'])
    omitted = []
    state_rows = []
    for row in current_rows:
        assigned_count = subject_assigned_count(row['id'])
        state_rows.append({'id': row['id'], 'title': row['title'],
                           'description': row['description'],
                           'display_order': row['display_order'],
                           'assigned_count': assigned_count})
        if row['id'] in incoming_ids:
            continue
        item = {'id': row['id'], 'title': row['title'],
                'display_order': row['display_order'],
                'assigned_count': assigned_count,
                'action': ('remove' if remove_omitted else 'keep')}
        if include_labels and assigned_count is not None:
            item['assigned_items'] = _subject_assigned_items(row['id'])
        omitted.append(item)
    state_hash = hashlib.sha256(json.dumps(state_rows, sort_keys=True,
                                           separators=(',', ':')).encode()).hexdigest()
    return {'current': current_rows, 'incoming': incoming,
            'additions': additions, 'edits': edits, 'unchanged': unchanged,
            'omitted': omitted, 'state_hash': state_hash}


@app.before_request
def reject_unavailable_runtime_routes():
    route_capabilities = {
        '/api/admin/system': 'system',
        '/api/admin/storage': 'storage',
        '/api/admin/hotspot': 'hotspot',
        '/api/admin/hotspot/password': 'hotspot',
        '/api/admin/hostname': 'hostname',
        '/api/admin/power': 'power',
        '/api/admin/cyberchef': 'cyberchef',
    }
    capability = route_capabilities.get(request.path)
    if capability and not capability_available(capability):
        abort(404)


@app.before_request
def pause_writes_during_storage_health_check():
    if request.method not in {'POST', 'PUT', 'PATCH', 'DELETE'}:
        return None
    status_path = Path('/run/cyberdeck-storage/storage-migration-status.json')
    try:
        status = json.loads(status_path.read_text(encoding='utf-8')).get('status')
    except (OSError, UnicodeError, json.JSONDecodeError, AttributeError):
        return None
    if status in {'switching', 'pending-health'}:
        return jsonify(error='Storage migration health checks are running; try again shortly'), 503
    return None


@app.before_request
def load_request_state():
    if not app.secret_key:
        abort(503, 'Session key is not configured. Run setup.sh to initialize the service.')
    g.db = connect_db()
    recover_import_transactions(g.db)
    g.csrf = session.setdefault('csrf', secrets.token_urlsafe(32))
    if not admin_account_exists():
        allowed_endpoints = {'first_admin_setup', 'static', 'trust_ca',
                             'certificate_help', 'language_select'}
        if request.endpoint not in allowed_endpoints:
            if request.path.startswith('/api/'):
                return jsonify(error='Create the first administrator to finish setup'), 503
            return redirect(url_for('first_admin_setup'))


@app.teardown_request
def close_db(_error=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def admin_required(fn):
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get('admin'):
            if request.path.startswith('/api/'):
                return jsonify(error='authentication required'), 401
            return redirect(url_for('login', next=request.path))
        return fn(*args, **kwargs)
    return wrapped


def csrf_required(fn):
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        token = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token')
        if not token or not hmac.compare_digest(token, session.get('csrf', '')):
            abort(400, 'CSRF validation failed')
        return fn(*args, **kwargs)
    return wrapped


@app.after_request
def security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    if request.path.startswith('/kiwix/'):
        response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    else:
        response.headers.setdefault('X-Frame-Options', 'DENY')
    # Native PDF readers create their own viewer document. Do not apply our
    # HTML resource restrictions to it; retain the restriction on embedding.
    if response.mimetype == 'application/pdf':
        response.headers.setdefault('Content-Security-Policy', "frame-ancestors 'none'")
    elif not request.path.startswith('/kiwix/'):
        response.headers.setdefault('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; frame-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'")
    response.headers['Cache-Control'] = 'no-store' if request.path.startswith(('/admin', '/api/admin', '/api/connectivity', '/api/online', '/private')) else 'no-cache'
    response.headers.setdefault('Strict-Transport-Security', 'max-age=31536000')
    return response


@app.get('/')
def home():
    preferences = site_preferences()
    subjects = []
    installed_zim_count = 0
    for slug, title, description in get_subjects():
        items = public_items(slug)
        count = len(items)
        installed_zim_count += sum(item['kind'] == 'zim' for item in items)
        if (preferences['hide_empty_subjects'] and count == 0 and
                slug not in preferences['always_show_subjects']):
            continue
        translations_row = g.db.execute('SELECT translations FROM library_subject WHERE id=?', (slug,)).fetchone()
        display = _localized_text(title, description,
                                  json.loads(translations_row['translations'] or '{}') if translations_row else {})
        subjects.append({'id': slug, 'title': title, 'description': description, **display,
                         'count': count, 'index': len(subjects) + 1})
    services = []
    active_zim_downloads = g.db.execute(
        "SELECT COUNT(*) FROM zim WHERE status IN ('queued','downloading') "
        "OR status LIKE 'pid:%'").fetchone()[0]
    if installed_zim_count or active_zim_downloads:
        services.append({'id': 'kiwix', 'title': 'Kiwix',
                         'description': ('Browse your offline ZIM libraries.'
                                         if installed_zim_count else
                                         'Preparing offline libraries.'),
                         'count': installed_zim_count,
                         'download_count': active_zim_downloads,
                         'ready': bool(installed_zim_count), 'url': '/kiwix/',
                         'new_tab': preferences['pdf_open_mode'] == 'new_tab'})
    module = cyberchef_module()
    if module and cyberchef_service_active():
        services.append({'id': 'cyberchef', 'title': 'CyberChef',
                         'description': 'Analyze and transform data in your browser.',
                         'url': f"https://{module['hostname']}:{module['port']}/",
                         'new_tab': True})
    return render_template('index.html', subjects=subjects,
                           services=services,
                           online_source_cards=[_localized_card(card) for card in configured_online_source_cards()],
                           rss_cards=[_localized_card(card) for card in configured_rss_cards()],
                           home_columns=preferences['home_columns'])


@app.get('/search')
def local_search():
    query = request.args.get('q', '').strip()
    if len(query) > 120:
        abort(400)
    results = search_local_library(query) if len(query) >= 2 else []
    return render_template('search.html', query=query, results=results,
                           needs_query=len(query) < 2)


@app.get('/online-crisis-links')
def online_crisis_links():
    cards = configured_online_source_cards()
    return redirect(f"/online-sources/{cards[0]['id']}" if cards else '/', code=302)


@app.get('/online-sources/<card_id>')
def online_source_page(card_id):
    cards = configured_online_source_cards()
    card = next((item for item in cards if item['id'] == card_id), None)
    if not card:
        abort(404)
    return render_template('resource-card.html', card=_localized_card(card),
                           card_index=cards.index(card) + 1, resource_kind='online')


@app.get('/rss/<card_id>')
def rss_card_page(card_id):
    cards = restore_empty_default_police_feeds(configured_rss_cards())
    card = next((item for item in cards if item['id'] == card_id), None)
    if not card:
        abort(404)
    return render_template('resource-card.html', card=_localized_card(card),
                           card_index=cards.index(card) + 1, resource_kind='rss')


@app.get('/api/online/rss')
def online_rss():
    card_id = request.args.get('card', '')
    feed_id = request.args.get('feed', 'all')
    try:
        result = _rss_entry(card_id, feed_id)
    except ValueError as error:
        return jsonify(error=str(error)), 400
    except RuntimeError as error:
        return jsonify(error=str(error)), 503
    response = jsonify(result)
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/api/online/police-rss')
def online_police_rss_compat():
    """Keep old RSS clients working while the reader moves into home cards."""
    try:
        result = _rss_entry('danish-police', request.args.get('feed', 'all'))
    except ValueError as error:
        return jsonify(error=str(error)), 400
    except RuntimeError as error:
        return jsonify(error=str(error)), 503
    response = jsonify(result)
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/accent.css')
def accent_stylesheet():
    color = request.args.get('color')
    if color is None:
        color = site_preferences()['accent_color']
    elif not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
        abort(400)
    response = make_response(f':root{{--accent:{color.lower()};}}')
    response.headers['Content-Type'] = 'text/css; charset=utf-8'
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/api/connectivity/kiwix')
def catalog_connectivity():
    # Called after the home page renders, so offline reading never waits for WAN.
    # Cache per worker and suppress overlapping probes from multiple LAN clients.
    if time.monotonic() >= _catalog_connectivity['expires'] and _catalog_connectivity_lock.acquire(blocking=False):
        try:
            available = False
            probe = urllib.request.Request(KIWIX_ONLINE_CATALOG, method='HEAD')
            try:
                with urllib.request.urlopen(probe, timeout=3) as response:
                    available = 200 <= response.status < 400
            except urllib.error.HTTPError as error:
                # The public browser can complete a crawler/access challenge or
                # wait out rate limiting. A verified HTTPS reply proves reachability.
                available = error.code in {403, 429}
                error.close()
            except (OSError, ValueError):
                pass
            _catalog_connectivity.update(available=available, expires=time.monotonic() + 60)
        finally:
            _catalog_connectivity_lock.release()
    response = jsonify(available=_catalog_connectivity['available'])
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/subjects/<slug>')
def subject_page(slug):
    subject = next((row for row in get_subjects() if row[0] == slug), None)
    if not subject:
        abort(404)
    translations_row = g.db.execute('SELECT translations FROM library_subject WHERE id=?', (slug,)).fetchone()
    subject_display = _localized_text(subject[1], subject[2],
                                     json.loads(translations_row['translations'] or '{}') if translations_row else {})
    items = public_items(slug)
    return render_template('subject.html', subject=subject, subject_display=subject_display, items=items,
                           kiwix_items=[item for item in items if item['kind'] == 'zim'],
                           local_items=[item for item in items if item['kind'] != 'zim'])


@app.get('/api/subjects')
def subject_index():
    return jsonify([{'id': i, 'title': t, 'description': d} for i, t, d in get_subjects()])


@app.get('/api/subjects/<slug>')
def subject_items(slug):
    if slug not in {row[0] for row in get_subjects()}:
        abort(404)
    return jsonify({'subject': slug, 'kiwix': request.host_url.rstrip('/') + '/kiwix/',
                    'items': public_items(slug)})


def kiwix_viewer_url(filename):
    zim_id = Path(filename).stem
    host = os.environ.get('CYBERDECK_HOSTNAME', 'cyberdeck.local')
    return f"https://{host}/kiwix/viewer#{urllib.parse.quote(zim_id, safe='')}"


def public_items(subject):
    acquired = DATA_ROOT / 'acquired.json'
    records = {}
    try:
        if acquired.is_file():
            records = json.loads(acquired.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        records = {}
    database_zims = {row['filename']: dict(row) for row in g.db.execute(
        'SELECT title,filename,subject,status FROM zim ORDER BY title')}
    result = []
    overrides = archive_metadata()
    for path, record in records.items():
        if path.startswith('zim/') and Path(path).name in database_zims:
            continue  # Local display metadata and readiness take precedence.
        asset = record.get('asset', {})
        if path.startswith('public/') and path.removeprefix('public/') in overrides:
            local = overrides[path.removeprefix('public/')]
            asset = {**asset, 'title': local['title'], 'collection': local['subject']}
        if asset.get('collection') != subject:
            continue
        filename = Path(path).name
        if path.startswith('public/'):
            result.append({'title': asset.get('title', filename), 'kind': 'document',
                           'filename': filename, 'description': asset.get('description', ''),
                           'search_terms': overrides.get(filename, {}).get(
                               'search_terms', asset.get('search_terms', '')),
                           'url': '/library/' + urllib.parse.quote(filename)})
        elif path.startswith('zim/'):
            result.append({'title': asset.get('title', filename), 'kind': 'zim',
                           'filename': filename, 'description': asset.get('description', ''),
                           'search_terms': asset.get('search_terms', ''),
                           'url': kiwix_viewer_url(filename)})
    for zim in database_zims.values():
        if zim['subject'] == subject and zim['status'] == 'ready':
            result.append({'title': zim['title'], 'kind': 'zim', 'filename': zim['filename'],
                           'url': kiwix_viewer_url(zim['filename'])})
    # Personal documents are public reference material once uploaded, but their
    # metadata and files can only be created or changed through admin routes.
    for item in g.db.execute('SELECT id,title,description,search_terms,cover FROM item WHERE subject=? ORDER BY created_at DESC',
                             (subject,)).fetchall():
        for attachment in g.db.execute(
                'SELECT id,filename,kind FROM attachment WHERE item_id=? ORDER BY filename',
                (item['id'],)).fetchall():
            is_html = attachment['kind'] == 'html-zip'
            result.append({'id': item['id'], 'title': item['title'],
                           'description': item['description'], 'search_terms': item['search_terms'],
                           'kind': 'document',
                           'attachment_kind': attachment['kind'],
                           'url': (f"/documents/{item['id']}/{attachment['id']}/viewer" if is_html
                                   else f"/documents/{item['id']}/{attachment['id']}"),
                           'filename': attachment['filename'],
                           'cover_url': f"/documents/{item['id']}/cover" if item['cover'] else None})
    return result


def _search_tokens(value):
    normalized = unicodedata.normalize('NFKC', str(value)).casefold()
    return re.findall(r'[^\W_]+', normalized, flags=re.UNICODE)


def _catalogue_match_score(query_terms, fields):
    """Require every query word and score matches by the field users value most."""
    weights = {'title': 100, 'search_terms': 80, 'subject': 50,
               'description': 30, 'filename': 20}
    token_fields = {name: _search_tokens(value) for name, value in fields.items()}
    score = 0
    for term in query_terms:
        best = 0
        for name, tokens in token_fields.items():
            weight = weights[name]
            if any(token == term for token in tokens):
                best = max(best, weight)
            elif len(term) >= 3 and any(token.startswith(term) for token in tokens):
                best = max(best, weight - 10)
        if not best:
            return 0
        if term in token_fields['title']:
            best += 20
        score += best
    query_text = ' '.join(query_terms)
    title_text = ' '.join(token_fields['title'])
    if title_text == query_text:
        score += 100
    elif title_text.startswith(query_text):
        score += 40
    return score


def search_local_library(query, limit=50):
    """Search indexed catalogue metadata without reading document payloads."""
    query_terms = _search_tokens(query)
    if not query_terms:
        return []
    results = []
    seen = set()
    for slug, title, description in get_subjects():
        row = g.db.execute('SELECT translations FROM library_subject WHERE id=?', (slug,)).fetchone()
        display = _localized_text(title, description,
                                  json.loads(row['translations'] or '{}') if row else {})
        title_text = display['display_title']
        description_text = display['display_description']
        subject_fields = {'title': title_text, 'search_terms': '',
                          'subject': slug + ' ' + title_text,
                          'description': description_text, 'filename': ''}
        subject_score = _catalogue_match_score(query_terms, subject_fields)
        if subject_score:
            results.append((subject_score, {'kind': 'subject', 'title': title_text,
                            'description': description_text, 'subject': slug,
                            'subject_title': title_text, 'url': '/subjects/' + slug}))
        for item in public_items(slug):
            key = (item.get('kind'), item.get('url'))
            if key in seen:
                continue
            subject_text = title_text
            fields = {'title': item.get('title', ''),
                      'search_terms': item.get('search_terms', ''),
                      'subject': slug + ' ' + subject_text,
                      'description': str(item.get('description', '')) + ' ' + description_text,
                      'filename': item.get('filename', '')}
            score = _catalogue_match_score(query_terms, fields)
            if not score:
                continue
            results.append((score, {'kind': item.get('kind', 'document'),
                            'title': item.get('title', ''),
                            'description': item.get('description', ''),
                            'filename': item.get('filename', ''),
                            'subject': slug, 'subject_title': subject_text,
                            'url': item.get('url', '/subjects/' + slug)}))
            seen.add(key)
    results.sort(key=lambda row: row[0], reverse=True)
    return [entry for _score, entry in results[:limit]]


@app.get('/library/<path:name>')
def public_file(name):
    if '/' in name or '\\' in name or name in {'.', '..'}:
        abort(404)
    lock = DATA_ROOT / 'acquired.json'
    if not lock.is_file():
        abort(404)
    records = json.loads(lock.read_text(encoding='utf-8'))
    if 'public/' + name not in records:
        abort(404)
    path = DATA_ROOT / 'public' / name
    if path.is_symlink() or not path.is_file():
        abort(404)
    response = make_response(send_file(path, conditional=True,
                                      mimetype='application/pdf' if path.suffix.lower() == '.pdf' else None,
                                      as_attachment=path.suffix.lower() not in {'.pdf'}))
    if path.suffix.lower() == '.html':
        response.headers['Content-Security-Policy'] = "sandbox; default-src 'self'; connect-src 'none'; form-action 'none'; object-src 'none'"
    return response


def acquired_records():
    lock = DATA_ROOT / 'acquired.json'
    if lock.is_symlink():
        raise ValueError('Refusing a symlink at the acquisition index')
    if not lock.is_file():
        return {}
    data = json.loads(lock.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError('Acquisition index must be a JSON object')
    return data


def active_starter_paths():
    if STARTER_MANIFEST.is_symlink() or not STARTER_MANIFEST.is_file():
        raise ValueError('Current starter manifest is missing or unsafe')
    manifest = json.loads(STARTER_MANIFEST.read_text(encoding='utf-8'))
    assets = manifest.get('assets') if isinstance(manifest, dict) else None
    if not isinstance(assets, list):
        raise ValueError('Current starter manifest has no asset list')
    return {asset.get('path') for asset in assets if isinstance(asset, dict)}


def archive_metadata():
    return {row['filename']: dict(row) for row in
            g.db.execute('SELECT filename,title,subject,search_terms FROM archive_metadata')}


def export_inventory():
    """Combine current content records without exporting operational state."""
    entries = {}
    overrides = archive_metadata()
    for path, record in acquired_records().items():
        if not isinstance(record, dict) or not isinstance(record.get('asset'), dict):
            raise ValueError('Invalid acquired content metadata')
        asset = dict(record['asset'])
        if asset.get('path') != path:
            raise ValueError('Acquired content path does not match its metadata')
        library.validate_asset(asset)
        local = overrides.get(path.removeprefix('public/'), {}) if path.startswith('public/') else {}
        asset.update({key: local[value] for key, value in
                      [('title', 'title'), ('collection', 'subject'),
                       ('search_terms', 'search_terms')] if value in local})
        entries[path] = asset
    for row in g.db.execute('SELECT * FROM zim ORDER BY filename'):
        path = 'zim/' + row['filename']
        asset = entries.get(path)
        if asset is None:
            manifest = library.safe_path(PRIVATE_ROOT, 'requests/' + row['id'] + '.json')
            if manifest.is_file():
                _, assets = library.load_manifest(manifest)
                asset = next((dict(a) for a in assets if a['path'] == path), None)
            if asset is None:
                if not row['bytes'] or not row['sha256']:
                    raise ValueError('ZIM source metadata is incomplete; retry or remove the affected download')
                asset = {'path': path, 'url': row['source_url'], 'max_bytes': row['bytes'],
                         'expected_bytes': row['bytes'], 'sha256': row['sha256']}
        asset.update(title=row['title'], collection=row['subject'])
        library.validate_asset(asset)
        entries[path] = asset
    result = []
    for path, asset in sorted(entries.items()):
        result.append({'id': 'asset:' + path, 'title': asset.get('title', path),
                       'subject': asset.get('collection', ''),
                       'mode': 'online' if 'url' in asset else 'offline', 'asset': asset})
    for row in g.db.execute('SELECT * FROM item ORDER BY title,id'):
        item = dict(row)
        item['attachments'] = [dict(a) for a in g.db.execute(
            'SELECT id,filename,stored_path,kind FROM attachment WHERE item_id=? ORDER BY id', (row['id'],))]
        local_attachments = []
        for attachment in item['attachments']:
            source = g.db.execute('SELECT asset FROM attachment_source WHERE attachment_id=?',
                                  (attachment['id'],)).fetchone()
            if source:
                asset = json.loads(source['asset'])
                asset.update(title=row['title'] + ' - ' + attachment['filename'],
                             collection=row['subject'], description=row['description'],
                             search_terms=row['search_terms'])
                library.validate_asset(asset)
                result.append({'id': 'source:' + attachment['id'], 'title': asset['title'],
                               'subject': row['subject'], 'mode': 'online', 'asset': asset})
            else:
                local_attachments.append(attachment)
        if local_attachments:
            item['attachments'] = local_attachments
            result.append({'id': 'item:' + row['id'], 'title': row['title'],
                           'subject': row['subject'], 'mode': 'offline', 'item': item})
    return result


MAX_EXPORT_BYTES = 8 * 1024**3
_export_lock = threading.Lock()


def catalogue_files(entry):
    """Explicit payload allowlist: never recursively copy the private directory."""
    if 'asset' in entry:
        asset = entry['asset']
        files = [(library.safe_path(DATA_ROOT, asset['path']), asset['path'])]
    else:
        item = entry['item']
        files = []
        for attachment in item['attachments']:
            stored = attachment['stored_path']
            if Path(stored).name != stored:
                raise ValueError('Invalid attachment filename')
            files.append((library.safe_path(PRIVATE_ROOT, f"files/{item['id']}/{stored}"),
                          f"files/{item['id']}/{stored}"))
        if item['cover']:
            files.append((library.safe_path(PRIVATE_ROOT, f"files/{item['id']}/{item['cover']}"),
                          f"files/{item['id']}/{item['cover']}"))
    if not files or len(files) > MAX_ZIP_FILES:
        raise ValueError('Catalogue has no files or too many files')
    total = 0
    for source, _ in files:
        if not source.is_file():
            raise ValueError('A selected local file is missing; refresh the selection')
        total += source.stat().st_size
    if total > MAX_EXPORT_BYTES:
        raise ValueError('One catalogue exceeds the 8 GiB export limit; select a smaller document group')
    return files, total


def export_version(entry, files):
    state = {'entry': entry, 'files': [(name, path.stat().st_size, path.stat().st_mtime_ns)
                                     for path, name in files]}
    return hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()


def catalogue_name(slug, entry):
    subject = secure_filename(entry.get('subject') or 'unassigned').lower().strip('._-') or 'unassigned'
    title = secure_filename(entry.get('title') or 'content').lower().strip('._-') or 'content'
    return f'{slug[:32]}-{subject[:32]}-{title[:64]}.zip'


def build_export_config(name, selected, include_settings):
    """Build the versioned configuration and resolve every selected local payload."""
    if (not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or
            any(ord(c) < 32 for c in name) or not isinstance(selected, list) or
            not 1 <= len(selected) <= 5000 or any(not isinstance(key, str) for key in selected) or
            len(set(selected)) != len(selected) or type(include_settings) is not bool):
        raise ValueError('Choose a name and at least one distinct content entry')
    name = name.strip()
    slug = secure_filename(name).lower().strip('._-')[:80] or 'custom-config'
    inventory = {entry['id']: entry for entry in export_inventory()}
    if any(key not in inventory for key in selected):
        raise ValueError('Content selection changed; reload the export list')
    config = {'format': 'cyberdeck-config', 'version': 1, 'name': name,
              'exported_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'reserve_bytes': 1_000_000_000, 'assets': [], 'offline_catalogues': []}
    config['online_source_cards'] = configured_online_source_cards()
    config['rss_cards'] = configured_rss_cards()
    signer = URLSafeTimedSerializer(app.secret_key, salt='content-export-v1')
    downloads = []
    local_catalogues = []
    used_catalogue_names = set()
    for key in selected:
        entry = inventory[key]
        if entry['mode'] == 'online':
            config['assets'].append(entry['asset'])
            continue
        files, size = catalogue_files(entry)
        filename = catalogue_name(slug, entry)
        stem = filename[:-4]
        suffix = 2
        while filename.casefold() in used_catalogue_names:
            filename = f'{stem[:120]}-{suffix}.zip'
            suffix += 1
        used_catalogue_names.add(filename.casefold())
        config['offline_catalogues'].append({'filename': filename, 'entry': entry})
        token = signer.dumps({'id': key, 'name': name, 'slug': slug,
                              'version': export_version(entry, files)})
        downloads.append({'filename': filename, 'title': entry['title'],
                          'bytes': size, 'token': token})
        local_catalogues.append((entry, filename, files, size, export_version(entry, files)))
    if len({asset['path'] for asset in config['assets']}) != len(config['assets']):
        raise ValueError('Two selected sources use the same destination filename; select only one.')
    config['subjects'] = []
    for row in g.db.execute(
            'SELECT id,title,description,display_order,translations,source_language FROM library_subject ORDER BY display_order,id'):
        subject = dict(row)
        subject['translations'] = json.loads(subject.pop('translations') or '{}')
        config['subjects'].append(subject)
    if include_settings:
        # Export only stored display preferences, never the hostname-derived default.
        allowed = {'pdf_open_mode', 'subtitle', 'accent_color', 'home_columns', 'display_timezone',
                   'hide_empty_subjects', 'always_show_subjects'}
        config['site_settings'] = {row['key']: row['value'] for row in g.db.execute(
            'SELECT key,value FROM site_setting') if row['key'] in allowed}
    return name, slug, config, downloads, local_catalogues


def write_catalogue_archive(output, entry, files, total, expected_version=None, export_name=None):
    """Write one checksum-verified offline catalogue to a seekable file object."""
    metadata = {'format': 'cyberdeck-offline-catalogue', 'version': 1,
                'name': export_name or entry.get('title', 'Offline catalogue'), 'entry': entry,
                'files': [], 'subjects': [dict(row) for row in g.db.execute(
                    'SELECT id,title,description,display_order FROM library_subject WHERE id=?',
                    (entry.get('subject'),))]}
    written = 0
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        for source, archive_path in files:
            digest = hashlib.sha256()
            count = 0
            with source.open('rb') as incoming, archive.open(archive_path, 'w', force_zip64=True) as outgoing:
                while chunk := incoming.read(1024 * 1024):
                    written += len(chunk)
                    count += len(chunk)
                    if written > total:
                        raise ValueError('Selected files changed during export')
                    digest.update(chunk)
                    outgoing.write(chunk)
            metadata['files'].append({'path': archive_path, 'bytes': count,
                                      'sha256': digest.hexdigest()})
        if (written != total or
                (expected_version is not None and export_version(entry, files) != expected_version)):
            raise ValueError('Selected files changed during export')
        archive.writestr('catalogue.json', json.dumps(metadata, ensure_ascii=False, indent=2) + '\n')


@app.get('/api/admin/export/options')
@admin_required
def export_options():
    try:
        return jsonify([{key: entry[key] for key in ('id', 'title', 'subject', 'mode')}
                        for entry in export_inventory()])
    except (OSError, ValueError, KeyError, TypeError):
        return jsonify(error='Cannot read content metadata for export; inspect acquisition records.'), 409


@app.post('/api/admin/export')
@admin_required
@csrf_required
def export_prepare():
    if request.content_length is None or request.content_length > 1024 * 1024:
        return jsonify(error='Export selection is too large'), 400
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error='Expected an export selection'), 400
    try:
        name, slug, config, downloads, local_catalogues = build_export_config(
            body.get('name'), body.get('selected'), body.get('include_settings', True))
        return jsonify(filename=slug + '.json', config=config, catalogues=downloads)
    except (OSError, ValueError, KeyError, TypeError) as error:
        if isinstance(error, ValueError) and str(error).startswith(('Choose a name', 'Content selection changed')):
            return jsonify(error=str(error)), 400
        return jsonify(error='Selected metadata or local files are missing, unsafe, or exceed export limits. Refresh the list and review the selection.'), 409


@app.post('/api/admin/export/bundle')
@admin_required
@csrf_required
def export_bundle():
    if request.content_length is None or request.content_length > 1024 * 1024:
        return jsonify(error='Export selection is too large'), 400
    try:
        selected = request.form.getlist('selected')
        include_settings = request.form.get('include_settings') == 'true'
        name, slug, config, _downloads, local_catalogues = build_export_config(
            request.form.get('name'), selected, include_settings)
        payload_bytes = sum(item[3] for item in local_catalogues)
        if payload_bytes + 128 * 1024**2 > MAX_UPLOAD:
            raise ValueError('Combined bundle would exceed the 8 GiB import limit; use separate downloads instead')
        # The nested catalogues and outer bundle both occupy temporary storage.
        needed = payload_bytes * 2 + 128 * 1024**2
        if shutil.disk_usage(PRIVATE_ROOT).free < needed:
            raise ValueError('Insufficient temporary space for a combined bundle; use the separate downloads instead')
    except (OSError, ValueError, KeyError, TypeError) as error:
        return jsonify(error=str(error) or 'The selection is no longer available; refresh and prepare it again.'), 409
    if not _export_lock.acquire(blocking=False):
        return jsonify(error='Another catalogue is being prepared; retry after it finishes'), 409
    temporary_root = None
    try:
        temporary_root = Path(tempfile.mkdtemp(prefix='cyberdeck-export-', dir=PRIVATE_ROOT))
        catalogue_dir = temporary_root / 'catalogues'
        catalogue_dir.mkdir()
        outer_path = temporary_root / (slug + '.zip')
        for entry, filename, files, total, expected_version in local_catalogues:
            catalogue_path = catalogue_dir / filename
            with catalogue_path.open('xb') as output:
                write_catalogue_archive(output, entry, files, total, expected_version, name)
        with zipfile.ZipFile(outer_path, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
            archive.writestr(slug + '.json', json.dumps(config, ensure_ascii=False, indent=2) + '\n')
            for entry, filename, _files, _total, _version in local_catalogues:
                archive.write(catalogue_dir / filename, 'catalogues/' + filename)
        response = send_file(outer_path, mimetype='application/zip', as_attachment=True,
                             download_name=slug + '-bundle.zip', conditional=False)
        response.content_length = outer_path.stat().st_size
        response.call_on_close(lambda: shutil.rmtree(temporary_root, ignore_errors=True))
        return response
    except (OSError, ValueError, KeyError, TypeError):
        if temporary_root is not None:
            shutil.rmtree(temporary_root, ignore_errors=True)
        return jsonify(error='Cannot build combined bundle: content changed, files are unsafe/missing, or temporary space is insufficient.'), 409
    finally:
        _export_lock.release()


@app.post('/api/admin/export/catalogue')
@admin_required
@csrf_required
def export_catalogue():
    if request.content_length is None or request.content_length > 16384:
        return jsonify(error='Invalid catalogue request'), 400
    try:
        ticket = URLSafeTimedSerializer(app.secret_key, salt='content-export-v1').loads(
            request.form.get('token', ''), max_age=3600)
    except BadSignature:
        return jsonify(error='Download selection expired or is invalid; prepare the export again'), 400
    if not _export_lock.acquire(blocking=False):
        return jsonify(error='Another catalogue is being prepared; retry after it finishes'), 409
    output = None
    try:
        entry = next((e for e in export_inventory() if e['id'] == ticket['id']), None)
        if entry is None or entry['mode'] != 'offline':
            raise ValueError('Selected local entry no longer exists')
        files, total = catalogue_files(entry)
        if export_version(entry, files) != ticket['version']:
            raise ValueError('Selected content changed; prepare the export again')
        if shutil.disk_usage(PRIVATE_ROOT).free < total + 64 * 1024**2:
            raise ValueError('Insufficient temporary disk space for this catalogue')
        # Disk-backed and deleted when the response closes, including interrupted downloads.
        output = tempfile.TemporaryFile(dir=PRIVATE_ROOT)
        metadata = {'format': 'cyberdeck-offline-catalogue', 'version': 1,
                    'name': ticket['name'], 'entry': entry, 'files': [],
                    'subjects': [dict(row) for row in g.db.execute(
                        'SELECT id,title,description,display_order FROM library_subject WHERE id=?',
                        (entry['subject'],))]}
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
            written = 0
            for source, archive_path in files:
                digest = hashlib.sha256()
                count = 0
                with source.open('rb') as incoming, archive.open(archive_path, 'w', force_zip64=True) as outgoing:
                    while chunk := incoming.read(1024 * 1024):
                        written += len(chunk)
                        count += len(chunk)
                        if written > total:
                            raise ValueError('Selected files changed during export')
                        digest.update(chunk)
                        outgoing.write(chunk)
                metadata['files'].append({'path': archive_path, 'bytes': count, 'sha256': digest.hexdigest()})
            if written != total or export_version(entry, files) != ticket['version']:
                raise ValueError('Selected files changed during export')
            archive.writestr('catalogue.json', json.dumps(metadata, ensure_ascii=False, indent=2) + '\n')
        size = output.tell()
        output.seek(0)
        response = send_file(output, mimetype='application/zip', as_attachment=True,
                             download_name=catalogue_name(ticket['slug'], entry), conditional=False)
        response.content_length = size
        # Flask's file wrapper owns the temporary file until the download ends.
        return response
    except (OSError, ValueError, KeyError, TypeError):
        if output is not None:
            output.close()
        return jsonify(error='Cannot build catalogue: content changed, files are unsafe/missing, or temporary space is insufficient. Prepare the export again.'), 409
    finally:
        _export_lock.release()


IMPORT_MAX_BYTES = MAX_UPLOAD


def import_serializer():
    return URLSafeTimedSerializer(app.secret_key, salt='configuration-import-v1')


def _safe_zip_name(name):
    if (not isinstance(name, str) or not name or '\\' in name or name.startswith('/') or
            any(part in {'', '.', '..'} for part in name.split('/')) or
            re.match(r'^[A-Za-z]:', name)):
        raise ValueError('Archive contains an unsafe path')
    return name


def _read_json_member(archive, name, limit=1024 * 1024):
    info = archive.getinfo(name)
    _safe_zip_name(info.filename)
    if info.file_size > limit or info.is_dir() or info.flag_bits & 1:
        raise ValueError('Configuration metadata is too large or unsupported')
    return json.loads(archive.read(info))


def _normalise_import_profile(profile, filename):
    """Convert a reviewed acquisition manifest into the Hub import format."""
    if not isinstance(profile, dict) or 'format' in profile:
        return _validate_import_config(profile)
    assets = profile.get('assets')
    if not isinstance(assets, list):
        return _validate_import_config(profile)
    name = profile.get('name')
    if not isinstance(name, str) or not name.strip():
        name = Path(filename or 'library profile').stem.replace('_', ' ').replace('-', ' ')
        name = name[:1].upper() + name[1:]
    supplied_subjects = profile.get('subjects', [])
    if not isinstance(supplied_subjects, list):
        raise ValueError('Profile subjects must be a list')
    subjects_by_id = {}
    for subject in supplied_subjects:
        if (not isinstance(subject, dict) or
                not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', str(subject.get('id', ''))) or
                not isinstance(subject.get('title'), str) or
                not 1 <= len(subject['title']) <= 80 or
                not isinstance(subject.get('description', ''), str) or
                len(subject.get('description', '')) > 300):
            raise ValueError('Profile contains an invalid subject definition')
        if subject['id'] in subjects_by_id:
            raise ValueError('Profile contains duplicate subject definitions')
        subjects_by_id[subject['id']] = subject
    known_subjects = {slug: (title, description) for slug, title, description in DEFAULT_SUBJECTS}
    normalized_assets = []
    required_subjects = set()
    for source in assets:
        if not isinstance(source, dict):
            raise ValueError('Profile assets must be objects')
        asset = dict(source)
        subject_id = asset.get('collection') or 'general-reference'
        if not isinstance(subject_id, str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', subject_id):
            raise ValueError('Profile asset has an invalid subject ID')
        asset['collection'] = subject_id
        normalized_assets.append(asset)
        required_subjects.add(subject_id)
    subjects = []
    for subject_id in sorted(required_subjects):
        definition = subjects_by_id.get(subject_id)
        if definition:
            title = definition.get('title')
            description = definition.get('description', '')
        elif subject_id in known_subjects:
            title, description = known_subjects[subject_id]
        else:
            title, description = subject_id.replace('-', ' ').capitalize(), ''
        subjects.append({'id': subject_id, 'title': title, 'description': description})
    normalized = {
        'format': 'cyberdeck-config', 'version': 1, 'name': name,
        'reserve_bytes': profile.get('reserve_bytes', 1_000_000_000),
        'assets': normalized_assets, 'subjects': subjects, 'offline_catalogues': [],
    }
    return _validate_import_config(normalized)


def _validate_import_config(config):
    if (not isinstance(config, dict) or config.get('format') != 'cyberdeck-config' or
            type(config.get('version')) is not int or config['version'] != 1 or
            not isinstance(config.get('name'), str) or
            not 1 <= len(config['name'].strip()) <= 80 or
            not isinstance(config.get('assets', []), list) or
            not isinstance(config.get('offline_catalogues', []), list)):
        raise ValueError('Unsupported configuration format or version')
    if (type(config.get('reserve_bytes', 1_000_000_000)) is not int or
            config.get('reserve_bytes', 1_000_000_000) < 1_000_000_000):
        raise ValueError('Storage reserve must be at least 1 GB')
    if len(config.get('assets', [])) > 5000 or len(config.get('offline_catalogues', [])) > 5000:
        raise ValueError('Configuration contains too many entries')
    if 'online_source_cards' in config:
        config['online_source_cards'] = _validate_card_list(
            config['online_source_cards'], 'online source')
    if 'rss_cards' in config:
        config['rss_cards'] = _validate_card_list(config['rss_cards'], 'RSS')
    paths = set()
    for asset in config.get('assets', []):
        library.validate_asset(asset)
        if asset['path'] in paths:
            raise ValueError('Configuration has duplicate destination paths')
        paths.add(asset['path'])
    subjects = config.get('subjects', [])
    if not isinstance(subjects, list) or len(subjects) > 500:
        raise ValueError('Invalid subject list')
    subject_ids = set()
    for subject in subjects:
        translations = subject.get('translations', {}) if isinstance(subject, dict) else {}
        if (not isinstance(subject, dict) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', str(subject.get('id', ''))) or
                not isinstance(subject.get('title'), str) or not 1 <= len(subject['title']) <= 80 or
                not isinstance(subject.get('description', ''), str) or len(subject.get('description', '')) > 300 or
                not isinstance(subject.get('source_language', 'en'), str) or
                subject.get('source_language', 'en') not in SUPPORTED_LANGUAGES or
                not isinstance(translations, dict) or any(code not in SUPPORTED_LANGUAGES for code in translations) or
                any(not isinstance(value, dict) or not isinstance(value.get('title', ''), str) or
                    len(value.get('title', '')) > 80 or not isinstance(value.get('description', ''), str) or
                    len(value.get('description', '')) > 300 for value in translations.values()) or
                ('display_order' in subject and
                 (type(subject['display_order']) is not int or
                  not 0 <= subject['display_order'] <= 5000)) or
                subject['id'] in subject_ids):
            raise ValueError('Invalid or duplicate subject definition')
        subject_ids.add(subject['id'])
    for asset in config.get('assets', []):
        if asset.get('collection') not in subject_ids:
            source = asset.get('path', 'unknown path')
            subject = asset.get('collection') or 'no subject assigned'
            raise ValueError(
                f'Online source {source} refers to {subject}, which is missing from the configuration. '
                'Assign an existing subject or remove the source from the JSON.'
            )
    catalogs = config.get('offline_catalogues', [])
    names = set()
    subjects_by_id = {subject['id'] for subject in subjects}
    for catalog in catalogs:
        if (not isinstance(catalog, dict) or not isinstance(catalog.get('filename'), str) or
                Path(catalog['filename']).name != catalog['filename'] or '/' in catalog['filename'] or '\\' in catalog['filename'] or
                not catalog['filename'].lower().endswith('.zip') or catalog['filename'] in names or
                not isinstance(catalog.get('entry'), dict)):
            raise ValueError('Invalid offline catalogue reference')
        names.add(catalog['filename'])
        entry = catalog['entry']
        if (('asset' in entry and (not isinstance(entry['asset'], dict) or
                                   entry['asset'].get('collection') not in subjects_by_id)) or
                ('item' in entry and (not isinstance(entry['item'], dict) or
                                      entry['item'].get('subject') not in subjects_by_id)) or
                ('asset' in entry) == ('item' in entry)):
            raise ValueError('Offline catalogue refers to an invalid subject or entry type')
        if 'asset' in entry:
            library.validate_asset(entry['asset'])
            if entry['asset']['path'] in paths:
                raise ValueError('Configuration has duplicate content paths')
            paths.add(entry['asset']['path'])
        else:
            item = entry['item']
            item_search_terms = item.get('search_terms', '')
            if (not isinstance(item.get('attachments'), list) or not item['attachments'] or
                    not isinstance(item.get('title'), str) or len(item['title']) > 200 or
                    not isinstance(item.get('id'), str) or not re.fullmatch(r'[0-9a-fA-F-]{36}', item['id']) or
                    not isinstance(item_search_terms, str) or len(item_search_terms) > 1000 or
                    any(ord(char) < 32 and char not in '\t\r\n' for char in item_search_terms)):
                raise ValueError('Invalid local document metadata')
    allowed_settings = {'pdf_open_mode', 'subtitle', 'accent_color', 'home_columns', 'display_timezone',
                        'hide_empty_subjects', 'always_show_subjects'}
    settings = config.get('site_settings', {})
    if not isinstance(settings, dict) or set(settings) - allowed_settings:
        raise ValueError('Configuration contains unsupported site preferences')
    if ('accent_color' in settings and not re.fullmatch(r'#[0-9a-fA-F]{6}', str(settings['accent_color'])) or
            'pdf_open_mode' in settings and settings['pdf_open_mode'] not in {'same_tab', 'new_tab'} or
            'subtitle' in settings and (not isinstance(settings['subtitle'], str) or not settings['subtitle'].strip() or len(settings['subtitle']) > 80) or
            'home_columns' in settings and str(settings['home_columns']) not in {'3', '4', '5'} or
            'display_timezone' in settings and not valid_timezone_name(settings['display_timezone']) or
            'hide_empty_subjects' in settings and settings['hide_empty_subjects'] not in {'true', 'false', True, False}):
        raise ValueError('Configuration contains invalid site preferences')
    if 'always_show_subjects' in settings:
        try:
            always_show = json.loads(settings['always_show_subjects'])
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError('Configuration contains invalid subject display preferences') from error
        if not isinstance(always_show, list) or any(not isinstance(value, str) for value in always_show):
            raise ValueError('Configuration contains invalid subject display preferences')
    return config


def _inspect_catalogue(stream, expected_entry=None):
    stream.seek(0)
    with zipfile.ZipFile(stream) as archive:
        infos = archive.infolist()
        if len(infos) > MAX_ZIP_FILES + 1:
            raise ValueError('Offline catalogue has too many files')
        seen = set()
        total = 0
        for info in infos:
            name = _safe_zip_name(info.filename)
            mode = (info.external_attr >> 16) & 0o170000
            if (name in seen or info.is_dir() or info.flag_bits & 1 or mode == 0o120000 or
                    info.file_size > MAX_EXPORT_BYTES):
                raise ValueError('Offline catalogue contains duplicate, encrypted, or oversized files')
            seen.add(name)
            total += info.file_size
            if total > MAX_EXPORT_BYTES:
                raise ValueError('Offline catalogue exceeds the 8 GiB limit')
        metadata = _read_json_member(archive, 'catalogue.json')
        if (not isinstance(metadata, dict) or metadata.get('format') != 'cyberdeck-offline-catalogue' or
                metadata.get('version') != 1 or not isinstance(metadata.get('entry'), dict) or
                (expected_entry is not None and metadata.get('entry') != expected_entry) or
                not isinstance(metadata.get('files'), list)):
            raise ValueError('Offline catalogue does not match its configuration entry')
        expected_files = {item.get('path'): item for item in metadata['files'] if isinstance(item, dict)}
        if len(expected_files) != len(metadata['files']) or set(expected_files) != seen - {'catalogue.json'}:
            raise ValueError('Offline catalogue file list does not match its ZIP members')
        entry = metadata['entry']
        if 'asset' in entry:
            library.validate_asset(entry['asset'])
            semantic_paths = {entry['asset']['path']}
        elif 'item' in entry:
            item = entry['item']
            if (not isinstance(item.get('attachments'), list) or not item['attachments'] or
                    not isinstance(item.get('id'), str) or not re.fullmatch(r'[0-9a-fA-F-]{36}', item['id'])):
                raise ValueError('Offline catalogue document metadata is invalid')
            semantic_paths = {f"files/{item['id']}/{a.get('stored_path', '')}" for a in item['attachments']
                              if isinstance(a, dict)}
            if len(semantic_paths) != len(item['attachments']):
                raise ValueError('Offline catalogue has duplicate or invalid attachment metadata')
            if item.get('cover'):
                semantic_paths.add(f"files/{item['id']}/{item['cover']}")
        else:
            raise ValueError('Offline catalogue has an unknown entry type')
        if semantic_paths != set(expected_files):
            raise ValueError('Offline catalogue metadata paths do not match its entry')
        for name, item in expected_files.items():
            if (type(item.get('bytes')) is not int or item['bytes'] != archive.getinfo(name).file_size or
                    not re.fullmatch(r'[0-9a-f]{64}', str(item.get('sha256', '')))):
                raise ValueError('Offline catalogue has invalid file size or checksum metadata')
            digest = hashlib.sha256()
            with archive.open(name) as member:
                while chunk := member.read(1024 * 1024):
                    digest.update(chunk)
            if digest.hexdigest() != item['sha256']:
                raise ValueError('Offline catalogue checksum verification failed')
        expanded_html_bytes = 0
        if 'item' in entry:
            for attachment in entry['item']['attachments']:
                if attachment.get('kind') != 'html-zip':
                    continue
                stored_path = f"files/{entry['item']['id']}/{attachment['stored_path']}"
                with archive.open(stored_path) as nested_archive:
                    expanded_html_bytes += inspect_html_archive(nested_archive)[0]
    stream.seek(0)
    return metadata, total, expanded_html_bytes


def _duplicate_import_warnings(db, catalogues):
    """Warn about duplicate non-PDF payloads handled outside the PDF selector."""
    incoming = {}
    duplicate_warnings = []
    incoming_sizes = set()
    selected_pdf_paths = set()
    selected_zim_paths = set()
    for _filename, metadata in catalogues:
        entry = metadata.get('entry', {})
        if 'item' in entry:
            item = entry['item']
            selected_pdf_paths.update(
                f"files/{item['id']}/{attachment.get('stored_path', '')}"
                for attachment in item.get('attachments', []) if attachment.get('kind') == 'pdf')
        elif 'asset' in entry and entry['asset'].get('path', '').startswith('zim/'):
            selected_zim_paths.add(entry['asset']['path'])
    for filename, metadata in catalogues:
        for item in metadata.get('files', []):
            if item.get('path') in selected_pdf_paths | selected_zim_paths:
                continue
            digest = str(item.get('sha256', '')).lower()
            size = item.get('bytes')
            label = f"{filename}: {item.get('path', 'unknown path')}"
            if not re.fullmatch(r'[0-9a-f]{64}', digest) or type(size) is not int:
                continue
            incoming_sizes.add(size)
            previous = incoming.get(digest)
            if previous:
                duplicate_warnings.append(
                    f'Duplicate file content: {label} matches {previous} in this import.'
                )
            else:
                incoming[digest] = label

    if not incoming:
        return duplicate_warnings

    existing = {}
    for record in acquired_records().values():
        if not isinstance(record, dict):
            continue
        digest = str(record.get('sha256', '')).lower()
        asset = record.get('asset')
        path = asset.get('path') if isinstance(asset, dict) else 'managed library content'
        if re.fullmatch(r'[0-9a-f]{64}', digest):
            existing.setdefault(digest, path)
    for row in db.execute('SELECT filename,sha256 FROM zim WHERE sha256 IS NOT NULL'):
        digest = str(row['sha256']).lower()
        if re.fullmatch(r'[0-9a-f]{64}', digest):
            existing.setdefault(digest, f"ZIM {row['filename']}")

    # Uploaded documents do not have a persisted checksum column. Hash only
    # existing attachments whose size can match an incoming payload.
    rows = db.execute(
        'SELECT item.id AS item_id, item.title AS title, attachment.filename AS filename, '
        'attachment.stored_path AS stored_path FROM attachment '
        'JOIN item ON item.id=attachment.item_id'
    ).fetchall()
    for row in rows:
        try:
            path = library.safe_path(
                PRIVATE_ROOT, f"files/{row['item_id']}/{row['stored_path']}"
            )
            if path.is_symlink() or not path.is_file() or path.stat().st_size not in incoming_sizes:
                continue
            digest = library.sha256(path).lower()
        except (OSError, ValueError, KeyError):
            continue
        existing.setdefault(digest, f"{row['title']} ({row['filename']})")

    for digest, label in incoming.items():
        previous = existing.get(digest)
        if previous:
            duplicate_warnings.append(
                f'Duplicate file content: {label} matches existing {previous}.'
            )
    return duplicate_warnings


def _document_import_options(db, catalogues):
    """Describe PDF attachments and mark matching existing or incoming content."""
    candidates = []
    sizes = set()
    for filename, metadata in sorted(catalogues, key=lambda entry: entry[0].casefold()):
        entry = metadata.get('entry', {})
        if 'item' not in entry:
            continue
        item = entry['item']
        file_map = {file.get('path'): file for file in metadata.get('files', [])
                    if isinstance(file, dict)}
        for attachment in item.get('attachments', []):
            if attachment.get('kind') != 'pdf':
                continue
            stored_path = attachment.get('stored_path', '')
            payload_path = f"files/{item['id']}/{stored_path}"
            payload = file_map.get(payload_path, {})
            digest = str(payload.get('sha256', '')).lower()
            size = payload.get('bytes', 0)
            if not re.fullmatch(r'[0-9a-f]{64}', digest) or type(size) is not int:
                continue
            sizes.add(size)
            candidates.append({'key': f'document:{filename}:{stored_path}',
                               'catalogue': filename, 'stored_path': stored_path,
                               'title': attachment.get('filename') or item.get('title') or filename,
                               'bytes': size, 'sha256': digest})

    existing = {}
    for row in db.execute(
            'SELECT item.title AS title, attachment.filename AS filename, '
            'attachment.stored_path AS stored_path, item.id AS item_id FROM attachment '
            'JOIN item ON item.id=attachment.item_id WHERE attachment.kind=\'pdf\''):
        try:
            path = library.safe_path(PRIVATE_ROOT, f"files/{row['item_id']}/{row['stored_path']}")
            if path.is_symlink() or not path.is_file() or path.stat().st_size not in sizes:
                continue
            existing.setdefault(library.sha256(path).lower(),
                                f"{row['title']} ({row['filename']})")
        except (OSError, ValueError, KeyError):
            continue

    seen = set()
    for option in candidates:
        prior = existing.get(option['sha256'])
        if prior:
            option['duplicate'] = True
            option['reason'] = f"Matches an existing PDF: {prior}"
        elif option['sha256'] in seen:
            option['duplicate'] = True
            option['reason'] = 'Matches another PDF in this import'
        else:
            option['duplicate'] = False
            option['reason'] = ''
            seen.add(option['sha256'])
        option.pop('sha256')
    return candidates


def _online_pdf_import_options(assets, catalogues=()):
    """Describe internet PDF acquisitions and mark matching content or paths."""
    options = []
    existing = {}
    existing_paths = set(acquired_records())
    for path, record in acquired_records().items():
        if not isinstance(record, dict):
            continue
        asset = record.get('asset')
        asset_path = asset.get('path') if isinstance(asset, dict) else path
        digest = str(record.get('sha256', '')).lower()
        if (isinstance(asset_path, str) and asset_path.startswith('public/') and
                asset_path.lower().endswith('.pdf') and
                re.fullmatch(r'[0-9a-f]{64}', digest)):
            existing.setdefault(digest, asset_path)

    incoming = set()
    for _filename, metadata in catalogues:
        entry = metadata.get('entry', {})
        if 'item' not in entry:
            continue
        file_map = {file.get('path'): file for file in metadata.get('files', [])
                    if isinstance(file, dict)}
        for attachment in entry['item'].get('attachments', []):
            if attachment.get('kind') != 'pdf':
                continue
            payload = file_map.get(f"files/{entry['item']['id']}/{attachment.get('stored_path', '')}", {})
            digest = str(payload.get('sha256', '')).lower()
            if re.fullmatch(r'[0-9a-f]{64}', digest):
                incoming.add(digest)

    seen = set(incoming)
    for asset in assets:
        path = asset['path']
        target = library.safe_path(DATA_ROOT, path)
        digest = str(asset.get('sha256', '')).lower()
        reason = ''
        if path in existing_paths or target.exists():
            reason = f'{path} is already installed or registered'
        elif re.fullmatch(r'[0-9a-f]{64}', digest) and digest in existing:
            reason = f'matches installed {existing[digest]}'
        elif re.fullmatch(r'[0-9a-f]{64}', digest) and digest in seen:
            reason = 'matches another PDF in this import'
        if re.fullmatch(r'[0-9a-f]{64}', digest):
            seen.add(digest)
        options.append({'key': 'online-pdf:' + path,
                        'title': str(asset.get('title') or Path(path).name),
                        'path': path,
                        'bytes': asset.get('expected_bytes', asset.get('max_bytes', 0)),
                        'conflict': path in existing_paths or target.exists(),
                        'duplicate': bool(reason), 'reason': reason})
    return options


def _zim_import_duplicates(db, catalogues, online_zims):
    """Mark bundled or online ZIMs that match installed or incoming archives."""
    existing_hashes = {}
    existing_names = {}
    for record in acquired_records().values():
        if not isinstance(record, dict):
            continue
        asset = record.get('asset')
        digest = str(record.get('sha256', '')).lower()
        path = asset.get('path') if isinstance(asset, dict) else ''
        if path.startswith('zim/') and re.fullmatch(r'[0-9a-f]{64}', digest):
            existing_hashes.setdefault(digest, path)
            existing_names[Path(path).name] = path
    for row in db.execute('SELECT filename,sha256 FROM zim'):
        path = f"zim/{row['filename']}"
        existing_names[row['filename']] = path
        digest = str(row['sha256'] or '').lower()
        if re.fullmatch(r'[0-9a-f]{64}', digest):
            existing_hashes.setdefault(digest, path)

    incoming_hashes = {}
    incoming_paths = {}
    options = {}
    for filename, metadata in sorted(catalogues, key=lambda entry: entry[0].casefold()):
        entry = metadata.get('entry', {})
        asset = entry.get('asset')
        if not isinstance(asset, dict) or not asset.get('path', '').startswith('zim/'):
            continue
        path = asset['path']
        key = 'catalog:' + filename
        payload = next((file for file in metadata.get('files', [])
                        if file.get('path') == path), {})
        options[key] = (path, str(payload.get('sha256', '')).lower(),
                        library.safe_path(DATA_ROOT, path).exists())
        digest = str(payload.get('sha256', '')).lower()
        if re.fullmatch(r'[0-9a-f]{64}', digest):
            incoming_paths.setdefault(digest, []).append(path)
    for asset in online_zims:
        path = asset['path']
        options['online:' + path] = (
            path, str(asset.get('sha256', '')).lower(),
            library.safe_path(DATA_ROOT, path).exists() or Path(path).name in existing_names)
        digest = str(asset.get('sha256', '')).lower()
        if re.fullmatch(r'[0-9a-f]{64}', digest):
            incoming_paths.setdefault(digest, []).append(path)

    for key, (path, digest, exists) in options.items():
        prior = existing_names.get(Path(path).name)
        if exists or prior:
            reason = f"{path} is already installed or registered"
        elif re.fullmatch(r'[0-9a-f]{64}', digest) and digest in existing_hashes:
            reason = f"matches installed {existing_hashes[digest]}"
        elif re.fullmatch(r'[0-9a-f]{64}', digest) and digest in incoming_hashes:
            reason = f"matches another ZIM in this import ({incoming_hashes[digest]})"
        elif re.fullmatch(r'[0-9a-f]{64}', digest) and len(incoming_paths.get(digest, [])) > 1:
            other = next(candidate for candidate in incoming_paths[digest] if candidate != path)
            reason = f"matches another ZIM in this import ({other})"
        else:
            reason = ''
        if reason:
            options[key] = {'duplicate': True, 'reason': reason}
        else:
            options[key] = {'duplicate': False, 'reason': ''}
        if re.fullmatch(r'[0-9a-f]{64}', digest):
            incoming_hashes.setdefault(digest, path)
    return options


def _available_import_profiles():
    try:
        if CONFIG_PROFILES_ROOT.is_symlink() or not CONFIG_PROFILES_ROOT.is_dir():
            return []
        candidates = sorted(CONFIG_PROFILES_ROOT.glob('*.json'))
    except OSError:
        return []
    profiles = []
    for path in candidates:
        if (not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}\.json', path.name) or
                path.is_symlink() or not path.is_file()):
            continue
        try:
            with path.open('rb') as handle:
                raw = handle.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                continue
            profile = json.loads(raw.decode('utf-8'))
            normalized = _normalise_import_profile(profile, path.name)
        except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
            continue
        profiles.append({'filename': path.name, 'name': normalized['name']})
    return profiles


@app.get('/api/admin/import/profiles')
@admin_required
def import_profiles():
    return jsonify(profiles=_available_import_profiles())


@app.get('/api/admin/import/profiles/<filename>')
@admin_required
def import_profile_download(filename):
    if (not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}\.json', filename) or
            CONFIG_PROFILES_ROOT.is_symlink() or not CONFIG_PROFILES_ROOT.is_dir()):
        return jsonify(error='Configuration profile is unavailable'), 404
    path = CONFIG_PROFILES_ROOT / filename
    if path.is_symlink() or not path.is_file():
        return jsonify(error='Configuration profile is unavailable'), 404
    try:
        with path.open('rb') as handle:
            raw = handle.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            return jsonify(error='Configuration profile is unavailable'), 404
        profile = json.loads(raw.decode('utf-8'))
        _normalise_import_profile(profile, path.name)
    except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
        return jsonify(error='Configuration profile is unavailable'), 404
    response = jsonify(filename=path.name, profile=profile)
    response.headers['Cache-Control'] = 'no-store'
    return response


def _apply_settings_only_import(stage_root, ticket, body):
    """Apply subject metadata/order and optional site preferences without importing payloads."""
    config_path = stage_root / 'config.json'
    if config_path.is_symlink() or not config_path.is_file():
        raise ValueError('Settings-only preview data is missing or unsafe')
    config = _validate_import_config(json.loads(config_path.read_text(encoding='utf-8')))
    if config.get('assets') or config.get('offline_catalogues'):
        raise ValueError('Settings-only preview contains content references')
    remove_omitted = ticket.get('remove_omitted')
    if type(remove_omitted) is not bool:
        raise ValueError('Settings-only preview has an invalid removal choice')
    if type(body.get('apply_settings', False)) is not bool:
        raise ValueError('Choose whether to apply saved site preferences')
    mapping = body.get('subject_mapping', {})
    if not isinstance(mapping, dict) or any(not isinstance(key, str) or not isinstance(value, str)
                                            for key, value in mapping.items()):
        raise ValueError('Choose a destination for each subject with assigned content')

    acquired_path = DATA_ROOT / 'acquired.json'
    if acquired_path.is_symlink():
        raise ValueError('Refusing a symlink at the acquisition index')
    journal = None
    journal_written = False
    temporary_index = None
    try:
        g.db.execute('BEGIN IMMEDIATE')
        old_acquired = acquired_path.read_bytes() if acquired_path.is_file() else None
        acquired = json.loads(old_acquired) if old_acquired is not None else {}
        if not isinstance(acquired, dict):
            raise ValueError('Current acquisition index is not a JSON object')
        plan = _settings_only_plan(config, remove_omitted, include_labels=False)
        if plan['state_hash'] != ticket.get('state_hash'):
            raise ValueError('Subjects or their content assignments changed; preview the settings again')
        incoming = plan['incoming']
        incoming_ids = {row['id'] for row in incoming}
        removals = plan['omitted'] if remove_omitted else []
        required_mappings = {row['id'] for row in removals
                             if isinstance(row['assigned_count'], int) and row['assigned_count'] > 0}
        if remove_omitted and any(row['assigned_count'] is None for row in removals):
            raise ValueError('Cannot verify content assignments; omitted subjects cannot be removed safely')
        if set(mapping) != required_mappings or any(target not in incoming_ids for target in mapping.values()):
            raise ValueError('Map every removed subject with content to a subject in the imported settings')
        remap = dict(mapping)
        removed_ids = {row['id'] for row in removals}
        final_ids = incoming_ids | ({row['id'] for row in plan['omitted']} - removed_ids)

        archive_subjects = {row['filename']: row['subject'] for row in
                            g.db.execute('SELECT filename,subject FROM archive_metadata')}
        acquired_changed = False
        if remap:
            for path, record in acquired.items():
                if not isinstance(record, dict) or not isinstance(record.get('asset'), dict):
                    continue
                asset = record['asset']
                filename = path.removeprefix('public/') if isinstance(path, str) else ''
                assigned = (archive_subjects.get(filename, asset.get('collection'))
                            if isinstance(path, str) and path.startswith('public/')
                            else asset.get('collection'))
                target = remap.get(assigned)
                if target and asset.get('collection') != target:
                    asset['collection'] = target
                    acquired_changed = True

        journal = {'id': ticket['id'], 'targets': [],
                   'acquired': {'existed': old_acquired is not None} if acquired_changed else None}
        if acquired_changed and old_acquired is not None:
            backup_path = stage_root / 'rollback' / 'acquired.json'
            backup_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with backup_path.open('xb') as backup:
                backup.write(old_acquired)
                backup.flush()
                os.fsync(backup.fileno())
        write_import_journal(stage_root, journal)
        journal_written = True
        g.db.execute('INSERT INTO import_transaction(id) VALUES(?)', (ticket['id'],))

        for order, subject in enumerate(incoming):
            g.db.execute('INSERT INTO library_subject(id,title,description,display_order,translations,source_language) VALUES(?,?,?,?,?,?) '
                         'ON CONFLICT(id) DO UPDATE SET title=excluded.title, '
                         'description=excluded.description,display_order=excluded.display_order,translations=excluded.translations,source_language=excluded.source_language',
                         (subject['id'], subject['title'], subject['description'], order,
                          json.dumps(subject.get('translations', {}), ensure_ascii=False),
                          subject.get('source_language', 'en')))
        if not remove_omitted:
            for offset, subject in enumerate(plan['omitted'], start=len(incoming)):
                g.db.execute('UPDATE library_subject SET display_order=? WHERE id=?',
                             (offset, subject['id']))
        for old_id, target_id in remap.items():
            g.db.execute('UPDATE item SET subject=? WHERE subject=?', (target_id, old_id))
            g.db.execute('UPDATE zim SET subject=? WHERE subject=?', (target_id, old_id))
            g.db.execute('UPDATE archive_metadata SET subject=? WHERE subject=?', (target_id, old_id))
        for old_id in removed_ids:
            g.db.execute('DELETE FROM library_subject WHERE id=?', (old_id,))

        preferences = site_preferences()
        current_always = preferences['always_show_subjects']
        imported_settings = config.get('site_settings', {}) if body.get('apply_settings') is True else {}
        if 'always_show_subjects' in imported_settings:
            try:
                incoming_always = json.loads(imported_settings['always_show_subjects'])
            except (TypeError, json.JSONDecodeError):
                incoming_always = []
            always_show = [remap.get(subject, subject) for subject in incoming_always
                           if remap.get(subject, subject) in final_ids]
        else:
            always_show = [remap.get(subject, subject) for subject in current_always
                           if remap.get(subject, subject) in final_ids]
        settings_to_save = dict(imported_settings)
        if body.get('apply_settings') is True:
            if 'online_source_cards' in config:
                settings_to_save['online_source_cards'] = config['online_source_cards']
            if 'rss_cards' in config:
                settings_to_save['rss_cards'] = config['rss_cards']
        if 'always_show_subjects' in imported_settings or removed_ids:
            settings_to_save['always_show_subjects'] = always_show
        if settings_to_save:
            g.db.executemany(
                'INSERT INTO site_setting(key,value) VALUES(?,?) '
                'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                [(key, json.dumps(value) if isinstance(value, (dict, list)) else str(value))
                 for key, value in settings_to_save.items()])

        if acquired_changed:
            temporary_index = DATA_ROOT / ('.acquired-' + uuid.uuid4().hex + '.tmp')
            with temporary_index.open('x', encoding='utf-8') as handle:
                json.dump(acquired, handle, ensure_ascii=False, indent=2)
                handle.write('\n')
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_index, acquired_path)
        g.db.commit()
        if 'rss_cards' in settings_to_save:
            with _police_rss_state_lock:
                _police_rss_cache.clear()
    except Exception:
        g.db.rollback()
        if temporary_index is not None:
            temporary_index.unlink(missing_ok=True)
        if journal_written:
            rollback_import_files(stage_root, journal)
        raise

    result = {'subjects_added': len(plan['additions']),
              'subjects_updated': len(plan['edits']),
              'subjects_removed': len(removed_ids),
              'content_records_remapped': sum(row['assigned_count'] for row in removals
                                              if row['id'] in remap),
              'site_settings_applied': bool(imported_settings or
                                            'online_source_cards' in settings_to_save or
                                            'rss_cards' in settings_to_save)}
    try:
        shutil.rmtree(stage_root)
    except OSError as error:
        app.logger.warning('Committed settings-only import cleanup deferred (%s)',
                           type(error).__name__)
        return jsonify(result), 200
    try:
        g.db.execute('BEGIN IMMEDIATE')
        g.db.execute('DELETE FROM import_transaction WHERE id=?', (ticket['id'],))
        g.db.commit()
    except sqlite3.Error:
        g.db.rollback()
        app.logger.warning('Could not clear completed settings-only import recovery marker')
    return jsonify(result), 200


@app.post('/api/admin/import/preview')
@admin_required
@csrf_required
def import_preview():
    if request.content_length is None or request.content_length > IMPORT_MAX_BYTES:
        return jsonify(error='Import upload exceeds the 8 GiB request limit'), 413
    mode = request.form.get('mode', 'full')
    if mode not in {'full', 'settings_only'}:
        return jsonify(error='Choose a supported import mode'), 400
    remove_omitted_value = request.form.get('remove_omitted_subjects', 'false').lower()
    if remove_omitted_value not in {'true', 'false', '1', '0', 'on', 'off'}:
        return jsonify(error='Choose whether omitted subjects should be removed'), 400
    remove_omitted = remove_omitted_value in {'true', '1', 'on'}
    uploads = [f for f in request.files.getlist('files') if f and f.filename]
    if not uploads:
        return jsonify(error='Select a configuration JSON, catalogue ZIPs, or combined bundle'), 400
    if mode == 'settings_only' and (len(uploads) != 1 or
                                    not uploads[0].filename.lower().endswith('.json')):
        return jsonify(error='Settings-only import requires exactly one configuration JSON file'), 400
    staging = PRIVATE_ROOT / 'import-staging'
    staging.mkdir(mode=0o700, exist_ok=True)
    if staging.is_symlink():
        return jsonify(error='Import staging path is unsafe'), 400
    stage = Path(tempfile.mkdtemp(prefix='preview-', dir=staging))
    try:
        config = None
        config_name = None
        catalogue_streams = {}
        total_in = 0
        for upload in uploads:
            name = secure_filename(upload.filename)
            if not name:
                raise ValueError('An uploaded filename is invalid')
            target = stage / (str(len(catalogue_streams)) + '-' + name)
            size = 0
            with target.open('xb') as output:
                while chunk := upload.stream.read(1024 * 1024):
                    size += len(chunk); total_in += len(chunk)
                    if total_in > IMPORT_MAX_BYTES:
                        raise ValueError('Import upload exceeds the 8 GiB limit')
                    output.write(chunk)
            if name.lower().endswith('.json'):
                if config is not None or size > 1024 * 1024:
                    raise ValueError('Provide exactly one configuration JSON no larger than 1 MiB')
                config = json.loads(target.read_text(encoding='utf-8'))
                config_name = Path(name).stem
            elif name.lower().endswith('.zip'):
                with zipfile.ZipFile(target) as outer:
                    members = outer.infolist()
                    if len(members) > MAX_ZIP_FILES + 2:
                        raise ValueError('Combined bundle has too many archive members')
                    member_names = set()
                    for info in members:
                        member_name = _safe_zip_name(info.filename)
                        if member_name in member_names:
                            raise ValueError('Combined bundle contains duplicate archive paths')
                        member_names.add(member_name)
                    names = {info.filename for info in members}
                    json_names = [n for n in names if n.lower().endswith('.json')]
                    bundled_configs = [n for n in json_names if n.count('/') == 0]
                    if config is None and len(bundled_configs) == 1 and any(n.startswith('catalogues/') for n in names):
                        config = _read_json_member(outer, bundled_configs[0])
                        config_name = Path(bundled_configs[0]).stem
                        for member in members:
                            if member.filename.startswith('catalogues/') and member.filename.lower().endswith('.zip'):
                                member_name = _safe_zip_name(member.filename)
                                leaf = Path(member_name).name
                                if leaf in catalogue_streams or member.file_size > IMPORT_MAX_BYTES - total_in:
                                    raise ValueError('Bundle has duplicate or oversized catalogues')
                                nested_path = stage / ('nested-' + hashlib.sha256(leaf.encode()).hexdigest() + '.zip')
                                with outer.open(member) as source, nested_path.open('xb') as destination:
                                    shutil.copyfileobj(source, destination, 1024 * 1024)
                                total_in += member.file_size
                                catalogue_streams[leaf] = nested_path
                    else:
                        if name in catalogue_streams:
                            raise ValueError('Duplicate catalogue upload filename')
                        catalogue_streams[name] = target
            else:
                raise ValueError('Import files must be JSON or ZIP')
        if mode == 'settings_only':
            if (not isinstance(config, dict) or config.get('format') != 'cyberdeck-config' or
                    not isinstance(config.get('subjects'), list) or not config.get('subjects')):
                raise ValueError('Settings-only import requires a versioned Cyberdeck configuration with subjects')
            ignored_assets = len(config.get('assets', [])) if isinstance(config.get('assets', []), list) else 0
            ignored_catalogues = (len(config.get('offline_catalogues', []))
                                  if isinstance(config.get('offline_catalogues', []), list) else 0)
            settings_config = dict(config)
            settings_config['assets'] = []
            settings_config['offline_catalogues'] = []
            config = _validate_import_config(settings_config)
            plan = _settings_only_plan(config, remove_omitted)
            (stage / 'config.json').write_text(json.dumps(config, ensure_ascii=False), encoding='utf-8')
            (stage / 'catalogue-map.json').write_text('[]', encoding='utf-8')
            token_id = uuid.uuid4().hex
            for stale in staging.iterdir():
                if (stale != stage and not stale.is_symlink() and stale.is_dir() and
                        time.time() - stale.stat().st_mtime > 24 * 60 * 60):
                    shutil.rmtree(stale, ignore_errors=True)
            final_stage = staging / token_id
            stage.rename(final_stage)
            stage = final_stage
            token = import_serializer().dumps({
                'id': token_id, 'mode': 'settings_only',
                'remove_omitted': remove_omitted, 'state_hash': plan['state_hash']})
            return jsonify(mode='settings_only', token=token, name=config['name'],
                           additions=plan['additions'], edits=plan['edits'],
                           unchanged=plan['unchanged'], incoming_subjects=plan['incoming'],
                           omitted=plan['omitted'],
                           remove_omitted=remove_omitted,
                           ignored_content={'assets': ignored_assets,
                                            'catalogues': ignored_catalogues},
                           site_settings_available=bool(config.get('site_settings') or
                                                       config.get('online_source_cards') is not None or
                                                       config.get('rss_cards') is not None),
                           online_source_cards=config.get('online_source_cards'),
                           rss_cards=config.get('rss_cards'),
                           can_remove=not any(item['assigned_count'] is None
                                              for item in plan['omitted']) if remove_omitted else True)
        refs = ({item['filename']: item['entry'] for item in config.get('offline_catalogues', [])}
                if config is not None else {})
        if config is not None and set(catalogue_streams) != set(refs):
            raise ValueError('Uploaded catalogue ZIPs do not match the configuration references')
        catalogs = []
        catalogue_metadata = []
        discovered_subjects = {}
        discovered_refs = []
        path_conflicts = []
        for filename, catalogue_path in catalogue_streams.items():
            with catalogue_path.open('rb') as stream:
                metadata, size, expanded_html_bytes = _inspect_catalogue(stream, refs.get(filename))
            catalogue_metadata.append((filename, metadata))
            discovered_refs.append({'filename': filename, 'entry': metadata['entry']})
            for subject in metadata.get('subjects', []):
                if isinstance(subject, dict) and isinstance(subject.get('id'), str):
                    discovered_subjects.setdefault(subject['id'], subject)
            entry = metadata['entry']
            asset_path = entry.get('asset', {}).get('path')
            if 'asset' in entry:
                target_path = library.safe_path(DATA_ROOT, asset_path)
                registered_zim = (asset_path.startswith('zim/') and g.db.execute(
                    'SELECT 1 FROM zim WHERE filename=?', (Path(asset_path).name,)).fetchone())
                if target_path.exists() or registered_zim: path_conflicts.append(asset_path)
            catalogs.append({'filename': filename, 'name': metadata.get('name', filename), 'bytes': size,
                             'expanded_html_bytes': expanded_html_bytes,
                             'asset_path': asset_path,
                             'entry_type': 'zim' if 'asset' in metadata.get('entry', {}) else 'document'})
        if config is None:
            if not discovered_refs:
                raise ValueError('Select a configuration JSON or at least one offline catalogue ZIP')
            config = {'format': 'cyberdeck-config', 'version': 1,
                      'name': catalogs[0]['name'] or 'Offline catalogue import',
                      'reserve_bytes': 1_000_000_000, 'assets': [],
                      'offline_catalogues': discovered_refs,
                      'subjects': list(discovered_subjects.values())}
        config = _normalise_import_profile(config, config_name)
        online_zims = [asset for asset in config.get('assets', [])
                       if asset.get('path', '').startswith('zim/') and 'url' in asset]
        online_pdfs = [asset for asset in config.get('assets', [])
                       if asset.get('path', '').startswith('public/') and
                       asset['path'].lower().endswith('.pdf') and 'url' in asset]
        existing_rows = [dict(r) for r in g.db.execute('SELECT id,title FROM library_subject')]
        existing = {r['id'] for r in existing_rows}
        subjects = [{'id': subject['id'], 'title': subject['title'],
                     'exists': subject['id'] in existing} for subject in config.get('subjects', [])]
        token_id = uuid.uuid4().hex
        (stage / 'config.json').write_text(json.dumps(config, ensure_ascii=False), encoding='utf-8')
        (stage / 'catalogue-map.json').write_text(json.dumps(sorted(catalogue_streams)), encoding='utf-8')
        for filename, catalogue_path in catalogue_streams.items():
            destination = stage / ('catalogue-' + hashlib.sha256(filename.encode()).hexdigest() + '.zip')
            if catalogue_path != destination:
                os.replace(catalogue_path, destination)
        for stale in staging.iterdir():
            if (stale != stage and not stale.is_symlink() and stale.is_dir() and
                    time.time() - stale.stat().st_mtime > 24 * 60 * 60):
                shutil.rmtree(stale, ignore_errors=True)
        final_stage = staging / token_id
        stage.rename(final_stage)
        stage = final_stage
        token = import_serializer().dumps({'id': token_id})
        zim_bytes = sum(item['bytes'] for item in catalogs if item['entry_type'] == 'zim')
        online_zim_bytes = sum(asset.get('expected_bytes', 0) for asset in online_zims)
        online_pdf_options = _online_pdf_import_options(online_pdfs, catalogue_metadata)
        zim_options = []
        for item in catalogs:
            if item['entry_type'] != 'zim':
                continue
            zim_options.append({'key': 'catalog:' + item['filename'], 'title': item['name'],
                                'bytes': item['bytes'], 'path': item['asset_path'],
                                'conflict': item['asset_path'] in path_conflicts,
                                'kind': 'catalogue'})
        for asset in online_zims:
            zim_options.append({'key': 'online:' + asset['path'],
                                'title': str(asset.get('title') or Path(asset['path']).name),
                                'bytes': asset.get('expected_bytes', 0), 'path': asset['path'],
                                'conflict': asset['path'] in path_conflicts,
                                'kind': 'download'})
        for asset in online_zims:
            filename = Path(asset['path']).name
            target_path = library.safe_path(DATA_ROOT, asset['path'])
            if (target_path.exists() or
                    g.db.execute('SELECT 1 FROM zim WHERE filename=?', (filename,)).fetchone()):
                path_conflicts.append(asset['path'])
        for option in zim_options:
            option['conflict'] = option['path'] in path_conflicts
        zim_duplicate_details = _zim_import_duplicates(g.db, catalogue_metadata, online_zims)
        for option in zim_options:
            option.update(zim_duplicate_details.get(option['key'],
                                                    {'duplicate': False, 'reason': ''}))
        document_options = _document_import_options(g.db, catalogue_metadata)
        document_bytes = sum(file['bytes'] for filename, metadata in catalogue_metadata
                             if 'item' in metadata['entry']
                             for file in metadata.get('files', []))
        expanded_html_bytes = sum(item['expanded_html_bytes'] for item in catalogs)
        reserve_bytes = config.get('reserve_bytes', 0)
        disk_free = shutil.disk_usage(PRIVATE_ROOT).free
        reserved_zim_bytes = active_zim_reservations(g.db)
        current_ids = {row['id'] for row in g.db.execute('SELECT id FROM library_subject')}
        candidates = [{'id': subject['id'], 'title': subject['title']} for subject in config.get('subjects', [])]
        return jsonify(token=token, name=config['name'],
                       online_sources=sum('url' in asset for asset in config.get('assets', [])),
                       online_source_cards=config.get('online_source_cards'),
                       rss_cards=config.get('rss_cards'),
                       local_sources=sum('source_file' in asset or asset.get('local_payload') is True
                                         for asset in config.get('assets', [])),
                       catalogues=catalogs, subjects=subjects, subject_candidates=candidates,
                       existing_subjects=existing_rows,
                       zim_options=zim_options,
                       document_options=document_options,
                       online_pdf_options=online_pdf_options,
                       required_bytes=document_bytes + expanded_html_bytes,
                       expanded_html_bytes=expanded_html_bytes,
                       required_data_bytes=zim_bytes + online_zim_bytes,
                       reserve_bytes=reserve_bytes,
                       available_bytes=disk_free,
                       available_data_bytes=max(0, shutil.disk_usage(DATA_ROOT).free - reserved_zim_bytes),
                       reserved_data_bytes=reserved_zim_bytes,
                       path_conflicts=path_conflicts,
                       warnings=['ZIM and internet PDF downloads start after you apply the import. Other online sources are saved for later acquisition.'] +
                       (['One or more online ZIM sources have no expected size; free-space preview may be low.']
                        if any('expected_bytes' not in asset for asset in online_zims) else []) +
                       _duplicate_import_warnings(g.db, catalogue_metadata))
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, json.JSONDecodeError) as error:
        shutil.rmtree(stage, ignore_errors=True)
        return jsonify(error=str(error) or 'Import package could not be read safely'), 400


@app.post('/api/admin/import/apply')
@admin_required
@csrf_required
def import_apply():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error='Expected an import preview token and subject mapping'), 400
    try:
        ticket = import_serializer().loads(body.get('token', ''), max_age=3600)
    except BadSignature:
        return jsonify(error='Import preview expired; upload and preview the files again'), 400
    stage_root = PRIVATE_ROOT / 'import-staging' / ticket.get('id', '')
    if (not re.fullmatch(r'[0-9a-f]{32}', ticket.get('id', '')) or
            stage_root.is_symlink() or not stage_root.is_dir()):
        return jsonify(error='Import preview is no longer available'), 400
    apply_claim = stage_root / 'apply.lock'
    try:
        with apply_claim.open('x', encoding='ascii') as handle:
            handle.write(str(os.getpid()))
            handle.write('\n')
    except FileExistsError:
        return jsonify(error='This configuration import is already being applied; preview the files again'), 409
    try:
        if ticket.get('mode') == 'settings_only':
            return _apply_settings_only_import(stage_root, ticket, body)
        if ticket.get('mode') not in (None, 'full'):
            raise ValueError('Import preview has an unsupported mode')
        config = _validate_import_config(json.loads((stage_root / 'config.json').read_text(encoding='utf-8')))
        selected_zims = body.get('selected_zims')
        catalogue_names = json.loads((stage_root / 'catalogue-map.json').read_text(encoding='utf-8'))
        online_zim_paths = [asset['path'] for asset in config.get('assets', [])
                            if asset.get('path', '').startswith('zim/') and 'url' in asset]
        all_zim_keys = ({'catalog:' + name for name in catalogue_names
                         if name.lower().endswith('.zip')} |
                        {'online:' + path for path in online_zim_paths})
        if selected_zims is None:
            selected_zims = sorted(all_zim_keys)
        if (not isinstance(selected_zims, list) or
                any(not isinstance(key, str) for key in selected_zims) or
                len(selected_zims) != len(set(selected_zims)) or
                not set(selected_zims).issubset(all_zim_keys)):
            return jsonify(error='The selected ZIM list does not match the import preview'), 400
        selected_zim_keys = set(selected_zims)
        all_online_pdf_assets = [asset for asset in config.get('assets', [])
                                 if asset.get('path', '').startswith('public/') and
                                 asset['path'].lower().endswith('.pdf') and 'url' in asset]
        mapping = body.get('subject_mapping')
        if not isinstance(mapping, dict):
            raise ValueError('Choose how every imported subject should be handled')
        current = {row['id']: dict(row) for row in g.db.execute('SELECT * FROM library_subject')}
        source_subjects = {row['id']: row for row in config.get('subjects', [])}
        resolved = {}
        for source_id, subject in source_subjects.items():
            target_id = mapping.get(source_id)
            if target_id == '__create__':
                if source_id in current:
                    return jsonify(error='Subject {subject} already exists; map it to an existing subject',
                                   error_params={'subject': source_id}), 409
                resolved[source_id] = source_id
            elif isinstance(target_id, str) and target_id in current:
                resolved[source_id] = target_id
            else:
                return jsonify(error='Map imported subject {title} to an existing subject or create it',
                               error_params={'title': subject['title']}), 409
        if set(mapping) != set(source_subjects):
            raise ValueError('Subject mapping does not match the preview')
        refs = {item['filename']: item['entry'] for item in config.get('offline_catalogues', [])}
        catalog_map = catalogue_names
        catalogue_plans = []
        for filename in catalog_map:
            expected = refs[filename]
            path = stage_root / ('catalogue-' + hashlib.sha256(filename.encode()).hexdigest() + '.zip')
            stream = path.open('rb')
            metadata, size, expanded_html_bytes = _inspect_catalogue(stream, expected)
            metadata['_catalogue_filename'] = filename
            catalogue_plans.append((path, metadata, size, expanded_html_bytes))
            stream.close()
        online_pdf_catalogues = [(metadata['_catalogue_filename'], metadata)
                                 for _path, metadata, _size, _html in catalogue_plans]
        online_pdf_options = _online_pdf_import_options(all_online_pdf_assets, online_pdf_catalogues)
        all_online_pdf_keys = {option['key'] for option in online_pdf_options}
        selected_online_pdfs = body.get('selected_online_pdfs')
        if selected_online_pdfs is None:
            selected_online_pdfs = [option['key'] for option in online_pdf_options
                                    if not option['duplicate']]
        if (not isinstance(selected_online_pdfs, list) or
                any(not isinstance(key, str) for key in selected_online_pdfs) or
                len(selected_online_pdfs) != len(set(selected_online_pdfs)) or
                not set(selected_online_pdfs).issubset(all_online_pdf_keys)):
            return jsonify(error='The selected internet PDF list does not match the import preview'), 400
        selected_online_pdf_keys = set(selected_online_pdfs)
        selected_pdf_conflicts = [option['path'] for option in online_pdf_options
                                  if option['key'] in selected_online_pdf_keys and option['conflict']]
        if selected_pdf_conflicts:
            return jsonify(error='Import would overwrite existing files: {files}',
                           error_params={'files': ', '.join(selected_pdf_conflicts[:8])}), 409
        document_options = _document_import_options(
            g.db, [(metadata['_catalogue_filename'], metadata)
                   for _path, metadata, _size, _html in catalogue_plans])
        all_document_keys = {option['key'] for option in document_options}
        selected_documents = body.get('selected_documents')
        if selected_documents is None:
            selected_documents = [option['key'] for option in document_options
                                  if not option['duplicate']]
        if (not isinstance(selected_documents, list) or
                any(not isinstance(key, str) for key in selected_documents) or
                len(selected_documents) != len(set(selected_documents)) or
                not set(selected_documents).issubset(all_document_keys)):
            return jsonify(error='The selected document list does not match the import preview'), 400
        selected_document_keys = set(selected_documents)
        omitted_document_catalogues = set()
        omitted_pdf_count = 0
        for _path, metadata, _size, _html in catalogue_plans:
            entry = metadata['entry']
            if 'item' not in entry:
                continue
            filename = metadata['_catalogue_filename']
            options = [option for option in document_options
                       if option['catalogue'] == filename]
            omitted_paths = {option['stored_path'] for option in options
                             if option['key'] not in selected_document_keys}
            if not omitted_paths:
                continue
            omitted_pdf_count += len(omitted_paths)
            item = entry['item']
            item['attachments'] = [attachment for attachment in item.get('attachments', [])
                                   if attachment.get('stored_path') not in omitted_paths]
            retained_paths = {f"files/{item['id']}/{attachment['stored_path']}"
                              for attachment in item['attachments']}
            if item.get('cover'):
                retained_paths.add(f"files/{item['id']}/{item['cover']}")
            metadata['files'] = [file for file in metadata['files']
                                 if file['path'] in retained_paths]
            omitted_document_catalogues.add(filename)
        empty_document_catalogues = {
            metadata['_catalogue_filename'] for _path, metadata, _size, _html in catalogue_plans
            if 'item' in metadata['entry'] and not metadata['entry']['item']['attachments']}
        if omitted_document_catalogues:
            # The original ZIP is no longer a faithful catalogue after selecting
            # individual attachments, and uploaded ZIPs are temporary. Do not
            # leave stale bundle references in the saved configuration.
            config['offline_catalogues'] = [
                item for item in config.get('offline_catalogues', [])
                if item.get('filename') not in omitted_document_catalogues]
        catalogue_plans = [plan for plan in catalogue_plans
                           if plan[1]['_catalogue_filename'] not in empty_document_catalogues]
        deferred_catalogue_zims = sum(
            1 for _path, metadata, _size, _html in catalogue_plans
            if 'asset' in metadata['entry'] and
            metadata['entry']['asset'].get('path', '').startswith('zim/') and
            'catalog:' + metadata['_catalogue_filename'] not in selected_zim_keys)
        deferred_catalogue_names = {
            metadata['_catalogue_filename'] for _path, metadata, _size, _html in catalogue_plans
            if 'asset' in metadata['entry'] and
            metadata['entry']['asset'].get('path', '').startswith('zim/') and
            'catalog:' + metadata['_catalogue_filename'] not in selected_zim_keys}
        if deferred_catalogue_names:
            config['offline_catalogues'] = [
                item for item in config.get('offline_catalogues', [])
                if item.get('filename') not in deferred_catalogue_names]
            deferred_paths = {
                metadata['entry']['asset']['path']
                for _path, metadata, _size, _html in catalogue_plans
                if metadata.get('_catalogue_filename') in deferred_catalogue_names and
                'asset' in metadata['entry']}
            config['assets'] = [
                asset for asset in config.get('assets', [])
                if not (asset.get('path') in deferred_paths and
                        'url' not in asset)]
        catalogue_plans = [plan for plan in catalogue_plans
                           if ('asset' not in plan[1]['entry'] or
                               not plan[1]['entry']['asset'].get('path', '').startswith('zim/') or
                               'catalog:' + plan[1]['_catalogue_filename'] in selected_zim_keys)]
        conflicts = []
        online_pdf_assets = [asset for asset in all_online_pdf_assets
                             if 'online-pdf:' + asset['path'] in selected_online_pdf_keys]
        for _path, metadata, _size, _html_bytes in catalogue_plans:
            entry = metadata['entry']
            if 'asset' in entry:
                dest = library.safe_path(DATA_ROOT, entry['asset']['path'])
                registered_zim = (entry['asset']['path'].startswith('zim/') and g.db.execute(
                    'SELECT 1 FROM zim WHERE filename=?', (Path(entry['asset']['path']).name,)).fetchone())
                if dest.exists() or registered_zim: conflicts.append(entry['asset']['path'])
        if conflicts:
            return jsonify(error='Import would overwrite existing files: {files}',
                           error_params={'files': ', '.join(conflicts[:8])}), 409
        zim_bytes = sum(size for _path, metadata, size, _html_bytes in catalogue_plans
                        if 'asset' in metadata['entry'])
        document_bytes = sum(file['bytes'] for _path, metadata, _size, _html_bytes in catalogue_plans
                             if 'item' in metadata['entry']
                             for file in metadata.get('files', []))
        expanded_html_bytes = sum(html_bytes for _path, _metadata, _size, html_bytes in catalogue_plans)
        online_zim_bytes = sum(asset.get('expected_bytes', 0) for asset in config.get('assets', [])
                               if asset.get('path', '').startswith('zim/') and 'url' in asset and
                               'online:' + asset['path'] in selected_zim_keys)
        online_pdf_bytes = sum(asset.get('expected_bytes', asset['max_bytes'])
                               for asset in online_pdf_assets)
        required_data_bytes = (zim_bytes + online_zim_bytes + online_pdf_bytes +
                               config.get('reserve_bytes', 0))
        reserved_zim_bytes = active_zim_reservations(g.db)
        if (shutil.disk_usage(DATA_ROOT).free < required_data_bytes + reserved_zim_bytes or
                shutil.disk_usage(PRIVATE_ROOT).free < document_bytes + expanded_html_bytes):
            return jsonify(error='Insufficient free library storage for this import'), 409
        acquired_path = DATA_ROOT / 'acquired.json'
        if acquired_path.is_symlink():
            raise ValueError('Refusing a symlink at the acquisition index')
        old_acquired = acquired_path.read_bytes() if acquired_path.is_file() else None
        acquired = json.loads(old_acquired) if old_acquired else {}
        if not isinstance(acquired, dict):
            raise ValueError('Current acquisition index is not a JSON object')
        planned_item_ids = {}
        planned_asset_temps = {}
        targets = []
        for path, metadata, _size, _html_bytes in catalogue_plans:
            entry = metadata['entry']
            if 'asset' in entry:
                source_path = entry['asset']['path']
                info = next(item for item in metadata['files'] if item['path'] == source_path)
                targets.append({'root': 'data', 'path': source_path, 'kind': 'file',
                                'sha256': info['sha256']})
                source_leaf = Path(source_path).name
                temporary_path = str(PurePosixPath(source_path).parent /
                                      ('.' + source_leaf + '.' + uuid.uuid4().hex + '.import'))
                planned_asset_temps[path] = temporary_path
                targets.append({'root': 'data', 'path': temporary_path, 'kind': 'file'})
            else:
                item_id = str(uuid.uuid4())
                planned_item_ids[path] = item_id
                targets.append({'root': 'private', 'path': f'files/{item_id}', 'kind': 'directory'})
        config_dir = PRIVATE_ROOT / 'imported-configs'
        if config_dir.is_symlink():
            raise ValueError('Refusing an unsafe imported-configuration directory')
        saved_config = config_dir / (uuid.uuid4().hex + '.json')
        targets.append({'root': 'private', 'path': f'imported-configs/{saved_config.name}', 'kind': 'file'})
        journal = {'id': ticket['id'], 'targets': targets,
                   'acquired': {'existed': old_acquired is not None}}
        journal_written = False
        g.db.execute('BEGIN IMMEDIATE')
        try:
            reserved_zim_bytes = active_zim_reservations(g.db)
            if shutil.disk_usage(DATA_ROOT).free < required_data_bytes + reserved_zim_bytes:
                raise ValueError('Available library storage changed; retry the import after active downloads finish')
            if old_acquired is not None:
                backup_path = stage_root / 'rollback' / 'acquired.json'
                backup_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                with backup_path.open('xb') as backup:
                    backup.write(old_acquired)
                    backup.flush()
                    os.fsync(backup.fileno())
            write_import_journal(stage_root, journal)
            journal_written = True
            g.db.execute('INSERT INTO import_transaction(id) VALUES(?)', (ticket['id'],))
            temporary_root = stage_root / 'apply-temp'
            temporary_root.mkdir(mode=0o700)
            for source_id, source in source_subjects.items():
                target_id = resolved[source_id]
                if mapping[source_id] == '__create__':
                    order = g.db.execute('SELECT COALESCE(MAX(display_order),-1)+1 FROM library_subject').fetchone()[0]
                    g.db.execute('INSERT INTO library_subject(id,title,description,display_order,translations,source_language) VALUES(?,?,?,?,?,?)',
                                 (target_id, source['title'], source.get('description', ''), order,
                                  json.dumps(source.get('translations', {}), ensure_ascii=False),
                                  source.get('source_language', 'en')))
                    current[target_id] = source
            for path, metadata, _size, _html_bytes in catalogue_plans:
                entry = metadata['entry']
                with zipfile.ZipFile(path) as archive:
                    if 'asset' in entry:
                        asset = dict(entry['asset'])
                        source_path = asset['path']
                        destination = library.safe_path(DATA_ROOT, source_path)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        info = next(item for item in metadata['files'] if item['path'] == source_path)
                        temp = library.safe_path(DATA_ROOT, planned_asset_temps[path])
                        temp.parent.mkdir(parents=True, exist_ok=True)
                        with archive.open(source_path) as src, temp.open('xb') as dst:
                            shutil.copyfileobj(src, dst, 1024 * 1024)
                        library.validate_payload(asset, temp)
                        digest = library.sha256(temp)
                        if digest != info['sha256']:
                            raise ValueError('Imported file changed after preview')
                        if destination.exists():
                            raise ValueError('Import destination appeared after preview')
                        os.replace(temp, destination)
                        asset['collection'] = resolved.get(asset.get('collection'), asset.get('collection'))
                        asset.pop('source_file', None)
                        if 'url' not in asset:
                            asset['local_payload'] = True
                        acquired[source_path] = {'asset': asset, 'bytes': info['bytes'], 'sha256': info['sha256']}
                        if source_path.startswith('zim/'):
                            filename = Path(source_path).name
                            title = asset.get('title', filename)
                            g.db.execute('INSERT INTO zim(id,title,subject,filename,source_url,bytes,sha256,status) VALUES(?,?,?,?,?,?,?,?)',
                                         (str(uuid.uuid4()), title, asset.get('collection', 'general-reference'), filename,
                                          asset.get('url', ''), info['bytes'], info['sha256'], 'ready'))
                        else:
                            g.db.execute('INSERT INTO archive_metadata(filename,title,subject,search_terms) VALUES(?,?,?,?)',
                                         (Path(source_path).name, asset.get('title', Path(source_path).name),
                                          asset.get('collection', 'general-reference'),
                                          asset.get('search_terms', '')))
                    else:
                        old_item = entry['item']
                        item_id = planned_item_ids[path]
                        files = {item['path']: item for item in metadata['files']}
                        g.db.execute('INSERT INTO item(id,title,description,subject,cover,search_terms) VALUES(?,?,?,?,NULL,?)',
                                     (item_id, old_item['title'], old_item.get('description', ''),
                                      resolved.get(old_item.get('subject'), old_item.get('subject', 'general-reference')),
                                      old_item.get('search_terms', '')))
                        cover = None
                        old_cover_path = f"files/{old_item['id']}/{old_item['cover']}" if old_item.get('cover') else None
                        item_dir = PRIVATE_ROOT / 'files' / item_id
                        item_dir.mkdir(parents=True, mode=0o700)
                        for old_attachment in old_item.get('attachments', []):
                            stored_name = old_attachment.get('stored_path', '')
                            if (not isinstance(stored_name, str) or Path(stored_name).name != stored_name or
                                    '/' in stored_name or '\\' in stored_name or
                                    old_attachment.get('kind') not in {'pdf', 'docx', 'html-zip'} or
                                    not isinstance(old_attachment.get('filename'), str) or
                                    len(old_attachment['filename']) > 255):
                                raise ValueError('Document attachment metadata is invalid')
                            old_path = f"files/{old_item['id']}/{stored_name}"
                            if old_path not in files:
                                raise ValueError('Document metadata refers to a missing payload')
                            stored = str(uuid.uuid4()) + Path(old_attachment['stored_path']).suffix.lower()
                            temp = temporary_root / (uuid.uuid4().hex + '.import')
                            with archive.open(old_path) as src, temp.open('xb') as dst:
                                shutil.copyfileobj(src, dst, 1024 * 1024)
                            if library.sha256(temp) != files[old_path]['sha256']:
                                raise ValueError('Imported document changed after preview')
                            if old_attachment['kind'] == 'html-zip':
                                validate_and_extract_zip(temp, item_dir / (stored + '.html'))
                            os.replace(temp, item_dir / stored)
                            attachment_id = str(uuid.uuid4())
                            g.db.execute('INSERT INTO attachment(id,item_id,filename,stored_path,kind) VALUES(?,?,?,?,?)',
                                         (attachment_id, item_id, old_attachment['filename'], stored, old_attachment['kind']))
                        if old_cover_path and old_cover_path in files:
                            old_ext = Path(old_item['cover']).suffix.lower()
                            if old_ext not in IMAGE_MIMES:
                                raise ValueError('Document cover filename is invalid')
                            cover = str(uuid.uuid4()) + old_ext
                            temp = temporary_root / (uuid.uuid4().hex + '.import')
                            with archive.open(old_cover_path) as src, temp.open('xb') as dst:
                                shutil.copyfileobj(src, dst, 1024 * 1024)
                            if library.sha256(temp) != files[old_cover_path]['sha256']:
                                raise ValueError('Imported cover changed after preview')
                            os.replace(temp, item_dir / cover)
                        g.db.execute('UPDATE item SET cover=? WHERE id=?', (cover, item_id))
            settings = config.get('site_settings', {}) if body.get('apply_settings') is True else {}
            import_settings = dict(settings)
            if 'online_source_cards' in config:
                import_settings['online_source_cards'] = config['online_source_cards']
            if 'rss_cards' in config:
                import_settings['rss_cards'] = config['rss_cards']
            if import_settings:
                if 'always_show_subjects' in import_settings:
                    try: incoming_always = json.loads(import_settings['always_show_subjects'])
                    except (TypeError, json.JSONDecodeError): incoming_always = []
                    import_settings['always_show_subjects'] = json.dumps([resolved.get(i, i) for i in incoming_always
                                                                          if resolved.get(i, i) in current or resolved.get(i, i) in source_subjects])
                if 'accent_color' in import_settings and not re.fullmatch(r'#[0-9a-fA-F]{6}', str(import_settings['accent_color'])):
                    raise ValueError('Imported accent color is invalid')
                if 'pdf_open_mode' in import_settings and import_settings['pdf_open_mode'] not in {'same_tab', 'new_tab'}:
                    raise ValueError('Imported PDF link preference is invalid')
                g.db.executemany('INSERT INTO site_setting(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                                 [(key, json.dumps(value) if isinstance(value, (dict, list)) else str(value))
                                  for key, value in import_settings.items()])
                if 'rss_cards' in import_settings:
                    with _police_rss_state_lock:
                        _police_rss_cache.clear()
            saved_document = json.loads(json.dumps(config))
            for asset in saved_document.get('assets', []):
                asset['collection'] = resolved.get(asset.get('collection'), asset.get('collection'))
            for catalogue in saved_document.get('offline_catalogues', []):
                entry = catalogue['entry']
                if 'asset' in entry:
                    entry['asset']['collection'] = resolved.get(
                        entry['asset'].get('collection'), entry['asset'].get('collection'))
                elif 'item' in entry:
                    entry['item']['subject'] = resolved.get(
                        entry['item'].get('subject'), entry['item'].get('subject'))
            mapped_subjects = {}
            for target_id in resolved.values():
                target = current[target_id]
                mapped_subjects[target_id] = {'id': target_id, 'title': target['title'],
                                              'description': target['description'],
                                              'display_order': target.get('display_order', 0)}
            saved_document['subjects'] = list(mapped_subjects.values())
            if 'site_settings' in saved_document and 'always_show_subjects' in saved_document['site_settings']:
                try:
                    saved_always = json.loads(saved_document['site_settings']['always_show_subjects'])
                except (TypeError, json.JSONDecodeError):
                    saved_always = []
                saved_document['site_settings']['always_show_subjects'] = json.dumps(
                    [resolved.get(subject, subject) for subject in saved_always])
            config_dir.mkdir(mode=0o700, exist_ok=True)
            if config_dir.is_symlink():
                raise ValueError('Refusing an unsafe imported-configuration directory')
            saved_config_text = json.dumps(saved_document, ensure_ascii=False, indent=2) + '\n'
            config_target = next(target for target in journal['targets']
                                 if target['path'] == f'imported-configs/{saved_config.name}')
            config_target['sha256'] = hashlib.sha256(saved_config_text.encode('utf-8')).hexdigest()
            write_import_journal(stage_root, journal)
            temporary_config = temporary_root / 'saved-config.tmp'
            temporary_config.write_text(saved_config_text, encoding='utf-8')
            if saved_config.exists():
                raise ValueError('Imported configuration destination already exists')
            os.replace(temporary_config, saved_config)
            if acquired:
                temporary_index = temporary_root / 'acquired.json'
                temporary_index.write_text(json.dumps(acquired, ensure_ascii=False, indent=2) + '\n',
                                           encoding='utf-8')
                os.replace(temporary_index, acquired_path)
            else:
                # An empty lock is rejected by the library verifier. Keep the
                # fresh-install state as an absent index until the first asset
                # is acquired; a previous empty index is covered by the journal
                # and restored if this import rolls back.
                acquired_path.unlink(missing_ok=True)
            g.db.commit()
        except Exception:
            g.db.rollback()
            if journal_written:
                rollback_import_files(stage_root, journal)
            shutil.rmtree(stage_root, ignore_errors=True)
            raise
        result = {'imported_catalogues': len(catalogue_plans),
                  'skipped_pdf_attachments': omitted_pdf_count,
                  'imported_zims': sum(1 for _path, metadata, _size, _html in catalogue_plans
                                       if 'asset' in metadata['entry'] and
                                       metadata['entry']['asset'].get('path', '').startswith('zim/')),
                  'online_sources': sum('url' in asset for asset in config.get('assets', [])),
                  'online_source_cards_imported': len(config.get('online_source_cards', [])),
                  'rss_cards_imported': len(config.get('rss_cards', [])),
                  'pending_sources': sum(('url' in asset or 'source_file' in asset) and
                                         not (asset.get('path', '').startswith('zim/') and 'url' in asset) and
                                         not (asset.get('path', '').startswith('public/') and
                                              asset['path'].lower().endswith('.pdf') and 'url' in asset)
                                         for asset in config.get('assets', [])),
                  'zim_downloads_started': 0, 'zim_download_errors': [],
                  'pdf_downloads_started': 0, 'pdf_download_errors': [],
                  'zims_deferred': deferred_catalogue_zims + len(online_zim_paths) - sum(
                      1 for path in online_zim_paths if 'online:' + path in selected_zim_keys),
                  'saved_config': saved_config.name}
        # The import transaction is durable before network acquisition begins.
        # ZIMs use the ordinary flow, which checks the Kiwix size and checksum
        # sidecar before starting a resumable transfer and validator worker.
        for asset in config.get('assets', []):
            if not asset.get('path', '').startswith('zim/') or 'url' not in asset:
                continue
            if 'online:' + asset['path'] not in selected_zim_keys:
                continue
            title = str(asset.get('title') or Path(asset['path']).name)
            try:
                target = library.safe_path(DATA_ROOT, asset['path'])
                filename = Path(asset['path']).name
                if (target.exists() or
                        g.db.execute('SELECT 1 FROM zim WHERE filename=?', (filename,)).fetchone()):
                    raise ValueError(f'{asset["path"]} already exists or is already registered')
                acquire_zim(title, resolved[asset['collection']], asset['url'])
                result['zim_downloads_started'] += 1
            except (OSError, ValueError, sqlite3.Error, subprocess.SubprocessError) as error:
                result['zim_download_errors'].append(f'{title}: {str(error)[:300]}')
        # Exported internet PDFs remain source references in the JSON. Reacquire
        # them through the verified library fetcher after the import is durable.
        # A single worker downloads this import's PDFs in order and waits for
        # active ZIM workers before updating the shared acquisition index.
        pdf_assets = []
        for asset in online_pdf_assets:
            if asset['path'] in acquired or library.safe_path(DATA_ROOT, asset['path']).exists():
                result['pdf_download_errors'].append(
                    f"{asset.get('title') or asset['path']}: destination already exists")
                continue
            pdf_asset = dict(asset)
            pdf_asset['collection'] = resolved.get(asset.get('collection'), asset.get('collection'))
            pdf_assets.append(pdf_asset)
        if pdf_assets:
            request_id = uuid.uuid4().hex
            manifest_path = None
            status_path = None
            log_path = None
            try:
                manifest_path = library.safe_path(
                    PRIVATE_ROOT, f'requests/import-pdfs-{request_id}.json')
                status_path = library.safe_path(
                    PRIVATE_ROOT, f'requests/import-pdfs-{request_id}.status.json')
                log_path = library.safe_path(PRIVATE_ROOT, f'logs/import-pdfs-{request_id}.log')
                manifest_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                log_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                with manifest_path.open('x', encoding='utf-8') as manifest_file:
                    json.dump({'reserve_bytes': 1_000_000_000, 'assets': pdf_assets},
                              manifest_file, ensure_ascii=False, indent=2)
                    manifest_file.write('\n')
                library.write_json(status_path, {
                    'id': request_id, 'created_at': time.time(), 'updated_at': time.time(),
                    'files': [{'path': asset['path'],
                               'title': str(asset.get('title') or Path(asset['path']).name),
                               'subject': str(asset.get('collection') or ''),
                               'expected_bytes': asset.get('expected_bytes'),
                               'status': 'queued', 'error': ''} for asset in pdf_assets]})
                start_pdf_import_worker(request_id)
                result['pdf_downloads_started'] = len(pdf_assets)
                result['pdf_import_id'] = request_id
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                if manifest_path is not None:
                    manifest_path.unlink(missing_ok=True)
                if status_path is not None:
                    status_path.unlink(missing_ok=True)
                if log_path is not None:
                    log_path.unlink(missing_ok=True)
                result['pdf_download_errors'].append(
                    f'Could not start PDF acquisition: {str(error)[:300]}')
        try:
            shutil.rmtree(stage_root)
        except OSError as error:
            # The database commit is durable. Keep the recovery marker until
            # the committed journal can be removed so a later request preserves
            # the imported files instead of treating this as a rollback.
            app.logger.warning('Committed configuration import cleanup deferred (%s)',
                               type(error).__name__)
            return jsonify(result), 200
        try:
            g.db.execute('BEGIN IMMEDIATE')
            g.db.execute('DELETE FROM import_transaction WHERE id=?', (ticket['id'],))
            g.db.commit()
        except sqlite3.Error:
            g.db.rollback()
            app.logger.warning('Could not clear completed import recovery marker')
        return jsonify(result), 200
    except (OSError, ValueError, KeyError, TypeError, sqlite3.IntegrityError, zipfile.BadZipFile) as error:
        app.logger.warning('Configuration import apply failed (%s)', type(error).__name__)
        return jsonify(error=str(error) or 'Import could not be applied safely; existing content was preserved'), 409
    finally:
        apply_claim.unlink(missing_ok=True)


def on_disk_file_size(root, relative_path):
    """Return bytes for a regular file beneath a data root, refusing links."""
    try:
        path = library.safe_path(root, relative_path)
        if not path.is_file():
            return None
        return path.stat().st_size
    except (OSError, ValueError):
        return None


@app.get('/api/admin/archive')
@admin_required
def archive_list():
    try:
        records = acquired_records()
        managed = active_starter_paths()
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return jsonify(error=str(error)), 503
    result = []
    overrides = archive_metadata()
    for name, record in records.items():
        if not isinstance(name, str) or not name.startswith('public/'):
            continue
        filename = name.removeprefix('public/')
        if not filename or '/' in filename or '\\' in filename or filename in {'.', '..'}:
            continue
        asset = record.get('asset', {}) if isinstance(record, dict) else {}
        if not isinstance(asset, dict):
            asset = {}
        local = overrides.get(filename, {})
        file_size = on_disk_file_size(DATA_ROOT, 'public/' + filename)
        result.append({'filename': filename,
                       'title': local.get('title', asset.get('title', filename)),
                       'subject': local.get('subject', asset.get('collection', '')),
                       'search_terms': local.get('search_terms', asset.get('search_terms', '')),
                       'bytes': file_size if file_size is not None else record.get('bytes'),
                       'available': file_size is not None,
                       'managed': name in managed})
    return jsonify(result)


@app.get('/api/admin/documents')
@admin_required
def documents_list():
    """Return one reader-facing document inventory with provenance as metadata."""
    managed_response = archive_list()
    if not hasattr(managed_response, 'get_json'):
        return managed_response
    uploaded_response = item_list()
    if not hasattr(uploaded_response, 'get_json'):
        return uploaded_response
    entries = [{'record_type': 'managed', **item,
                'origin': 'profile' if item['managed'] else 'acquired'}
               for item in managed_response.get_json()]
    entries.extend({'record_type': 'uploaded', **item, 'origin': 'live-added'}
                   for item in uploaded_response.get_json())
    return jsonify(entries)


@app.put('/api/admin/archive/<filename>')
@admin_required
@csrf_required
def archive_edit(filename):
    if not filename or '/' in filename or '\\' in filename or filename in {'.', '..'}:
        abort(404)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error='Expected a display title and subject'), 400
    title, subject = body.get('title'), body.get('subject')
    search_terms = body.get('search_terms', '')
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 200:
        return jsonify(error='Display title must contain 1 to 200 characters'), 400
    if not isinstance(subject, str) or subject not in {row[0] for row in get_subjects()}:
        return jsonify(error='Choose an existing subject'), 400
    if (not isinstance(search_terms, str) or len(search_terms) > 1000 or
            any(ord(char) < 32 and char not in '\t\r\n' for char in search_terms)):
        return jsonify(error='Search terms must be at most 1000 characters of text'), 400
    try:
        records = acquired_records()
    except (OSError, ValueError) as error:
        return jsonify(error=str(error)), 503
    if 'public/' + filename not in records:
        abort(404)
    # Display overrides never rewrite acquisition identity or downloaded bytes.
    g.db.execute('''INSERT INTO archive_metadata(filename,title,subject,search_terms) VALUES(?,?,?,?)
        ON CONFLICT(filename) DO UPDATE SET title=excluded.title,subject=excluded.subject,
        search_terms=excluded.search_terms''',
                 (filename, title.strip(), subject, search_terms.strip()))
    g.db.commit()
    return jsonify(filename=filename, title=title.strip(), subject=subject,
                   search_terms=search_terms.strip())


@app.delete('/api/admin/archive/<filename>')
@admin_required
@csrf_required
def archive_remove(filename):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', filename):
        abort(404)
    name = 'public/' + filename
    body = request.get_json(silent=True) or {}
    if body.get('confirm') != filename:
        return jsonify(error='Confirm removal by sending the exact filename'), 400
    try:
        records = acquired_records()
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return jsonify(error=str(error)), 503
    if name not in records:
        abort(404)
    public_root = DATA_ROOT / 'public'
    path = public_root / filename
    lock = DATA_ROOT / 'acquired.json'
    if public_root.is_symlink() or lock.is_symlink() or path.is_symlink():
        return jsonify(error='Refusing to remove a file through a symlink'), 409
    if not path.is_file():
        return jsonify(error='The indexed archive file is missing; inspect the acquisition record first.'), 409

    updated = dict(records)
    del updated[name]
    temporary = lock.with_name(f'.{lock.name}.{uuid.uuid4().hex}.tmp')
    pending = path.with_name(f'.{filename}.{uuid.uuid4().hex}.remove')
    try:
        temporary.write_text(json.dumps(updated, indent=2) + '\n', encoding='utf-8')
        temporary.chmod(lock.stat().st_mode & 0o777)
        os.replace(path, pending)
        try:
            os.replace(temporary, lock)
        except OSError:
            os.replace(pending, path)
            raise
        try:
            pending.unlink()
        except FileNotFoundError:
            pass
    except OSError as error:
        return jsonify(error='Archive removal failed: {error}',
                       error_params={'error': str(error)}), 500
    finally:
        temporary.unlink(missing_ok=True)
    g.db.execute('DELETE FROM archive_metadata WHERE filename=?', (filename,))
    g.db.commit()
    return '', 204


def public_ca():
    certificate = Path(os.environ.get('CYBERDECK_CA_CERT_FILE', '/etc/cyberdeck/tls/ca.crt'))
    try:
        with certificate.open('rb') as source:
            pem = source.read(65537)
        if len(pem) > 65536:
            raise ValueError('Certificate too large')
        der = ssl.PEM_cert_to_DER_cert(pem.decode('ascii'))
    except (OSError, ValueError, UnicodeError):
        abort(404)
    return pem, der


@app.get('/help/certificate')
def certificate_help():
    try:
        _, der = public_ca()
        fingerprint = ':'.join(f'{byte:02X}' for byte in hashlib.sha256(der).digest())
    except NotFound:
        fingerprint = None
    return render_template('certificate-help.html', fingerprint=fingerprint,
                           hub_addresses=_certificate_help_addresses())


@app.get('/trust/ca.crt')
@app.get('/trust/ca.cer')
def trust_ca():
    pem, der = public_ca()
    extension = 'cer' if request.path.endswith('.cer') else 'crt'
    response = make_response(der if extension == 'cer' else pem)
    response.headers['Content-Type'] = 'application/x-x509-ca-cert'
    response.headers['Content-Disposition'] = f'attachment; filename="cyberdeck-local-ca.{extension}"'
    return response


@app.get('/login')
def login():
    return render_template('login.html', error=None)


@app.post('/login')
def login_post():
    if not session.get('csrf') or not hmac.compare_digest(request.form.get('csrf_token', ''), session['csrf']):
        abort(400, 'CSRF validation failed')
    username = request.form.get('username', '')[:128]
    password = request.form.get('password', '')
    row = g.db.execute('SELECT password_hash FROM admin WHERE username=?', (username,)).fetchone()
    if not row or not check_password_hash(row['password_hash'], password):
        return render_template('login.html', error='Login failed.'), 401
    session.clear()
    session['admin'] = username
    session['csrf'] = secrets.token_urlsafe(32)
    session.permanent = True
    next_path = request.args.get('next', '')
    if not next_path.startswith('/') or next_path.startswith('//') or '\\' in next_path:
        next_path = '/admin'
    return redirect(next_path)


@app.route('/setup', methods=['GET', 'POST'])
def first_admin_setup():
    if admin_account_exists():
        if session.get('admin'):
            return redirect(url_for('admin_page'))
        return redirect(url_for('login'))
    error = None
    if request.method == 'POST':
        if not session.get('csrf') or not hmac.compare_digest(
                request.form.get('csrf_token', ''), session['csrf']):
            abort(400, 'CSRF validation failed')
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirmation = request.form.get('password_confirmation', '')
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', username):
            error = 'Use a username of 1 to 64 letters, numbers, dots, hyphens, or underscores.'
        elif len(password) < 14:
            error = 'Choose a password with at least 14 characters.'
        elif password != confirmation:
            error = 'The passwords do not match.'
        else:
            try:
                g.db.execute('BEGIN IMMEDIATE')
                if admin_account_exists():
                    g.db.rollback()
                    error = 'An administrator has already been created. Sign in instead.'
                else:
                    g.db.execute('INSERT INTO admin(username,password_hash) VALUES(?,?)',
                                 (username, generate_password_hash(password)))
                    g.db.commit()
                    session.clear()
                    session['admin'] = username
                    session['csrf'] = secrets.token_urlsafe(32)
                    session.permanent = True
                    return redirect(url_for('admin_page'))
            except sqlite3.IntegrityError:
                g.db.rollback()
                error = 'An administrator has already been created. Sign in instead.'
    return render_template('first_admin_setup.html', error=error)


@app.post('/logout')
@admin_required
@csrf_required
def logout():
    session.clear()
    return redirect(url_for('home'))


@app.get('/admin')
@admin_required
def admin_page():
    return render_template('admin.html', csrf=session['csrf'], username=session['admin'],
                           config_subjects=get_subjects(), preferences=site_preferences(),
                           time_zones=timezone_choices(), card_languages=SUPPORTED_LANGUAGES,
                           hotspot_module_enabled=hotspot_module_enabled())


def _system_mount_usage():
    ignored_filesystems = {
        'autofs', 'binfmt_misc', 'bpf', 'cgroup', 'cgroup2', 'configfs', 'debugfs', 'devpts',
        'ceph', 'cifs', 'davfs', 'devtmpfs', 'fuse.glusterfs', 'fuse.rclone',
        'fuse.sshfs', 'fusectl', 'glusterfs', 'hugetlbfs', 'mqueue', 'nfs', 'nfs4', 'nsfs',
        'overlay', 'proc', 'pstore', 'ramfs', 'securityfs', 'smb3', 'sshfs',
        'sysfs', 'tmpfs', 'tracefs', '9p',
    }
    mountinfo_file = Path('/proc/self/mountinfo')
    candidates = []

    def is_usb_block_source(source):
        """Identify mounted block devices whose sysfs ancestry is USB."""
        try:
            device_stat = os.stat(source)
            if not stat.S_ISBLK(device_stat.st_mode):
                return False
            sysfs_device = Path('/sys/dev/block') / (
                f'{os.major(device_stat.st_rdev)}:{os.minor(device_stat.st_rdev)}')
            resolved = sysfs_device.resolve(strict=True)
        except (OSError, RuntimeError):
            return False
        return any(part == 'usb' or re.fullmatch(r'usb[0-9]+', part)
                   for part in resolved.parts)

    def decode_mount_field(value):
        return re.sub(r'\\([0-7]{3})', lambda match: chr(int(match.group(1), 8)), value)

    # Mountinfo identifies the device and filesystem-root path for each mount.
    # Skip stale entries hidden by a later mount at the same target by checking
    # the visible target's st_dev against mountinfo's major:minor device number.
    if mountinfo_file.is_file():
        try:
            for line in mountinfo_file.read_text(encoding='utf-8', errors='replace').splitlines():
                before_separator, separator, mount_data = line.partition(' - ')
                fields = before_separator.split()
                after = mount_data.split() if separator else []
                if len(fields) < 5 or len(after) < 2:
                    continue
                major_minor = fields[2].split(':', 1)
                if len(major_minor) != 2:
                    continue
                try:
                    device_id = os.makedev(int(major_minor[0]), int(major_minor[1]))
                except (ValueError, OverflowError):
                    continue
                filesystem_root = decode_mount_field(fields[3])
                mountpoint = decode_mount_field(fields[4])
                filesystem = after[0]
                if filesystem in ignored_filesystems or not os.path.isdir(mountpoint):
                    continue
                try:
                    if os.stat(mountpoint).st_dev != device_id:
                        continue
                    usage = shutil.disk_usage(mountpoint)
                except OSError:
                    continue
                candidates.append((device_id, sum(bool(part) for part in filesystem_root.split('/')), {
                    'mount': mountpoint, 'device': decode_mount_field(after[1]),
                    'filesystem': filesystem, 'usb_storage': is_usb_block_source(decode_mount_field(after[1])),
                    'total_bytes': usage.total, 'used_bytes': usage.used,
                    'free_bytes': usage.free,
                    'used_percent': round(usage.used * 100 / usage.total, 1) if usage.total else 0,
                }))
        except OSError:
            candidates = []

    # Systemd's filesystem sandbox can expose the same filesystem through bind
    # mounts. Prefer the mount with the shallowest filesystem-root path, then the
    # shallowest mountpoint as a fallback. This reports /home or an adopted disk's
    # mount instead of its /srv/cyberdeck bind alias.
    by_device = {}
    by_device_rank = {}
    for device_id, root_depth, row in candidates:
        rank = (root_depth if root_depth is not None else 1_000_000,
                row['mount'].count(os.sep))
        current = by_device.get(device_id)
        if current is None or rank < by_device_rank[device_id]:
            by_device[device_id] = row
            by_device_rank[device_id] = rank
    configured_home_mount = os.environ.get('CYBERDECK_HOME_MOUNT', '')
    home_probe = Path('/home/.cyberdeck-storage-probe')
    home_probe_device = None
    if re.fullmatch(r'/home(?:/[^/]+)*', configured_home_mount):
        try:
            home_probe_device = os.stat(home_probe).st_dev
            home_row = by_device.get(home_probe_device)
            if home_row is not None:
                # ProtectHome hides the host's /home mount. The installer binds
                # only this empty probe directory so its filesystem can be
                # identified without exposing user home contents to the Hub.
                home_row['mount'] = configured_home_mount
        except OSError:
            home_probe_device = None
    if not by_device:
        try:
            usage = shutil.disk_usage(DATA_ROOT)
            by_device[os.stat(DATA_ROOT).st_dev] = {
                'mount': str(DATA_ROOT), 'device': 'unknown', 'filesystem': 'unknown',
                'total_bytes': usage.total, 'used_bytes': usage.used,
                'free_bytes': usage.free,
                'used_percent': round(usage.used * 100 / usage.total, 1) if usage.total else 0,
            }
        except OSError:
            pass
    try:
        root_device = os.stat('/').st_dev
        visible_devices = {root_device}
        data_device = os.stat(DATA_ROOT).st_dev
        if data_device != root_device:
            visible_devices.add(data_device)
        try:
            home_device = home_probe_device if home_probe_device is not None else os.stat('/home').st_dev
            if home_device != root_device:
                visible_devices.add(home_device)
        except OSError:
            pass
        visible_devices.update(device_id for device_id, row in by_device.items()
                               if row.get('usb_storage'))
    except OSError:
        visible_devices = set(by_device)
    return sorted((row for device_id, row in by_device.items()
                   if device_id in visible_devices), key=lambda row: row['mount'])


def _system_memory():
    values = {}
    try:
        for line in Path('/proc/meminfo').read_text(encoding='ascii').splitlines():
            key, raw = line.split(':', 1)
            if key in {'MemTotal', 'MemAvailable'}:
                values[key] = int(raw.split()[0]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return {'total_bytes': values.get('MemTotal'), 'available_bytes': values.get('MemAvailable')}


def _system_network():
    """Read NetworkManager device state without privileges or a Wi-Fi scan."""
    try:
        result = subprocess.run(
            ['nmcli', '--terse', '--escape', 'no', '--fields',
             'DEVICE,TYPE,STATE,CONNECTION', 'device', 'status'],
            text=True, capture_output=True, timeout=5, check=True,
            env={**os.environ, 'LC_ALL': 'C'},
        )
    except (OSError, subprocess.SubprocessError):
        return _system_network_sysfs()
    interfaces = []
    for line in result.stdout.splitlines():
        fields = line.split(':', 3)
        if len(fields) != 4:
            return _system_network_sysfs()
        device, kind, state, connection = fields
        if device == 'lo' or kind == 'loopback':
            continue
        interfaces.append({'device': device, 'type': kind, 'state': state,
                           'active': state in {'connected', 'connected (externally)'},
                           'connection': connection if connection not in {'', '--'} else None})
    return {'available': True, 'interfaces': sorted(
        interfaces, key=lambda item: (not item['active'], item['device']))}


def _system_network_sysfs():
    """Report kernel-visible interfaces when NetworkManager/nmcli is absent."""
    root = Path('/sys/class/net')
    try:
        entries = sorted(root.iterdir(), key=lambda path: path.name)
    except OSError:
        return {'available': False, 'interfaces': []}
    interfaces = []
    for entry in entries:
        if entry.name == 'lo':
            continue
        try:
            state = (entry / 'operstate').read_text(encoding='ascii').strip() or 'unknown'
        except OSError:
            state = 'unknown'
        try:
            carrier = (entry / 'carrier').read_text(encoding='ascii').strip() == '1'
        except OSError:
            carrier = False
        active = state == 'up' or carrier
        interface_type = 'wireless' if (entry / 'wireless').exists() else 'other'
        try:
            if interface_type == 'other' and (entry / 'type').read_text(encoding='ascii').strip() == '1':
                interface_type = 'ethernet'
        except OSError:
            pass
        interfaces.append({'device': entry.name, 'type': interface_type,
                           'state': 'connected' if active else state,
                           'active': active, 'connection': None})
    return {'available': True, 'interfaces': interfaces}


def _certificate_help_addresses():
    """List assigned IPv4 addresses on wired and Wi-Fi host interfaces, wired first."""
    network = _system_network()
    kinds = {}
    for interface in network.get('interfaces', []):
        kind = interface.get('type')
        if kind == 'ethernet':
            kinds[interface['device']] = 'lan'
        elif kind in {'wifi', 'wireless'}:
            kinds[interface['device']] = 'wifi'
    if not kinds:
        return []
    try:
        result = subprocess.run(['ip', '-j', '-4', 'address', 'show', 'up'],
                                text=True, capture_output=True, timeout=3, check=True)
        devices = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return []
    addresses = []
    for device in devices:
        name = device.get('ifname')
        kind = kinds.get(name)
        if not kind:
            continue
        for record in device.get('addr_info', []):
            if record.get('family') != 'inet' or record.get('scope') != 'global':
                continue
            try:
                address = ipaddress.ip_address(record['local'])
            except (KeyError, ValueError, TypeError):
                continue
            if address.is_loopback or address.is_link_local or address.is_multicast or address.is_unspecified:
                continue
            addresses.append({'kind': kind, 'device': name, 'address': str(address)})
    return sorted(addresses, key=lambda item: (item['kind'] != 'lan', item['device'],
                                                int(ipaddress.ip_address(item['address']))))


def _filesystem_mount_for(path, filesystems):
    """Return the reported filesystem mount backing a path, including bind mounts."""
    resolved = os.path.realpath(path)
    matches = []
    try:
        path_device = os.stat(path).st_dev
    except OSError:
        path_device = None
    for filesystem in filesystems:
        mount = os.path.realpath(filesystem['mount'])
        try:
            if path_device is not None and os.stat(mount).st_dev == path_device:
                matches.append((len(mount), filesystem['mount']))
                continue
            if os.path.commonpath((resolved, mount)) == mount:
                matches.append((len(mount), filesystem['mount']))
        except (OSError, ValueError):
            continue
    return max(matches)[1] if matches else None


@app.get('/api/admin/cyberchef')
@admin_required
def admin_cyberchef_status():
    if not capability_available('cyberchef'):
        abort(404)
    try:
        return jsonify(helper('cyberchef-status'))
    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
        return jsonify(error=str(error)), 503


@app.post('/api/admin/cyberchef')
@admin_required
@csrf_required
def admin_cyberchef_control():
    if not capability_available('cyberchef'):
        abort(404)
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or body.get('action') not in {'enable', 'disable'}:
        return jsonify(error='Choose whether to enable or disable CyberChef'), 400
    try:
        return jsonify(helper('cyberchef-' + body['action']))
    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
        return jsonify(error=str(error)), 503


@app.get('/api/admin/system')
@admin_required
def admin_system_overview():
    if not capability_available('system'):
        abort(404)
    uptime_seconds = None
    try:
        uptime_seconds = int(float(Path('/proc/uptime').read_text(encoding='ascii').split()[0]))
    except (OSError, ValueError, IndexError):
        pass
    try:
        operating_system = platform.freedesktop_os_release().get('PRETTY_NAME')
    except (AttributeError, OSError):
        operating_system = None
    filesystems = _system_mount_usage()
    return jsonify({
        'hostname': socket.gethostname(),
        'operating_system': operating_system or platform.system(),
        'kernel': platform.release(),
        'architecture': platform.machine() or 'Unknown',
        'cpu_threads': os.cpu_count(),
        'memory': _system_memory(),
        'uptime_seconds': uptime_seconds,
        'filesystems': filesystems,
        'data_root': str(DATA_ROOT),
        'data_filesystem_mount': _filesystem_mount_for(DATA_ROOT, filesystems),
        'network': _system_network(),
    })


def storage_helper(action, payload=None):
    result = subprocess.run(
        ['sudo', '-n', '/usr/local/lib/cyberdeck/storage-helper.py', action],
        input=json.dumps(payload or {}), text=True, capture_output=True, timeout=30)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or 'Storage operation failed')
    return json.loads(result.stdout or '{}')


@app.get('/api/admin/storage')
@admin_required
def admin_storage_status():
    if not capability_available('storage'):
        abort(404)
    try:
        response = jsonify(storage_helper('list'))
        response.headers['Cache-Control'] = 'no-store'
        return response
    except (RuntimeError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        return jsonify(error=str(error)), 503


@app.post('/api/admin/storage')
@admin_required
@csrf_required
def admin_storage_action():
    if not capability_available('storage'):
        abort(404)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error='Expected a storage action'), 400
    action = body.get('action')
    stable_id = body.get('stable_id')
    if action in {'adopt', 'initialize', 'use-existing'} and (
            not isinstance(stable_id, str) or len(stable_id) > 180):
        return jsonify(error='Select a disk with a stable identity'), 400
    try:
        if action == 'adopt':
            result = storage_helper('adopt', {'stable_id': stable_id})
        elif action == 'initialize':
            result = storage_helper('initialize', {
                'stable_id': stable_id, 'confirm': body.get('confirm')})
        elif action == 'use-existing':
            result = storage_helper('use-existing', {'stable_id': stable_id})
        elif action == 'migration-preview':
            target_mount = body.get('target_mount')
            if not isinstance(target_mount, str) or len(target_mount) > 512:
                return jsonify(error='Select an approved storage folder'), 400
            result = storage_helper('migration-preview', {'target_mount': target_mount})
        elif action == 'move-library':
            if g.db.execute("SELECT 1 FROM zim WHERE status LIKE 'pid:%' OR status='downloading' LIMIT 1").fetchone():
                return jsonify(error='Pause active downloads before moving library storage'), 409
            target_mount = body.get('target_mount')
            target_id = body.get('target_id')
            if (not isinstance(target_mount, str) or len(target_mount) > 512 or
                    not isinstance(target_id, str) or not re.fullmatch(r'[a-f0-9]{64}', target_id)):
                return jsonify(error='Review a valid storage destination before confirming'), 400
            result = storage_helper('migrate', {
                'target_mount': target_mount, 'target_id': target_id,
                'confirm': body.get('confirm')})
        else:
            return jsonify(error='Unknown storage action'), 400
        response = jsonify(result)
        response.headers['Cache-Control'] = 'no-store'
        return response
    except (RuntimeError, OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError) as error:
        return jsonify(error=str(error)), 503


def _admin_card_records():
    cards = []
    for row in g.db.execute('SELECT id,title,description,translations,source_language FROM library_subject ORDER BY display_order,id'):
        count = subject_assigned_count(row['id'])
        cards.append({'id': row['id'], 'type': 'subject', 'title': row['title'],
                      'description': row['description'],
                      'translations': json.loads(row['translations'] or '{}'),
                      'source_language': row['source_language'],
                      'entries': [], 'child_count': count if count is not None else 1,
                      'offline_display': 'hide',
                      **_localized_text(row['title'], row['description'],
                                        json.loads(row['translations'] or '{}'))})
    for kind, collection in (('online', configured_online_source_cards()),
                             ('rss', configured_rss_cards())):
        field = 'links' if kind == 'online' else 'feeds'
        for card in collection:
            cards.append({**_localized_card(card), 'type': kind, 'entries': card[field],
                          'child_count': len(card[field])})
    return cards


def _validate_card_metadata(card):
    card_id, kind = card.get('id'), card.get('type')
    title, description = card.get('title'), card.get('description', '')
    source_language = card.get('source_language', current_language())
    max_title, max_description = (80, 300) if kind == 'subject' else (100, 500)
    translations = card.get('translations', {})
    if (not isinstance(card_id, str) or len(card_id) > 64 or
            not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', card_id) or
            not isinstance(kind, str) or kind not in {'subject', 'online', 'rss'} or not isinstance(title, str) or
            not 1 <= len(title.strip()) <= max_title or not isinstance(description, str) or
            len(description) > max_description or any(ord(char) < 32 and char not in '\n\t' for char in title + description) or
            not isinstance(source_language, str) or source_language not in SUPPORTED_LANGUAGES or
            not isinstance(translations, dict) or
            any(code not in SUPPORTED_LANGUAGES for code in translations)):
        raise ValueError('Card details are invalid')
    normalized_translations = {}
    for code, value in translations.items():
        if (not isinstance(value, dict) or not isinstance(value.get('title', ''), str) or
                len(value.get('title', '')) > max_title or
                not isinstance(value.get('description', ''), str) or
                len(value.get('description', '')) > max_description or
                any(ord(char) < 32 and char not in '\n\t'
                    for char in value.get('title', '') + value.get('description', ''))):
            raise ValueError('Card translations are invalid')
        normalized_translations[code] = {'title': value.get('title', '').strip(),
                                         'description': value.get('description', '').strip()}
    return {'id': card_id, 'type': kind, 'title': title.strip(),
            'description': description.strip(), 'source_language': source_language,
            'translations': normalized_translations}


def _merge_card_locale_edit(body, previous=None):
    """Apply edits to the active locale while preserving every other locale."""
    language = body.get('language', previous.get('source_language', 'en') if previous else current_language())
    if not isinstance(language, str) or language not in SUPPORTED_LANGUAGES:
        raise ValueError('Choose a supported card language')
    if previous is None:
        result = dict(body)
        result['source_language'] = language
        translations = dict(result.get('translations') or {})
    else:
        result = {**previous, **body}
        result['title'] = previous['title']
        result['description'] = previous.get('description', '')
        result['source_language'] = previous.get('source_language', 'en')
        translations = dict(previous.get('translations') or {})
        if 'translations' in body:
            if not isinstance(body['translations'], dict):
                raise ValueError('Card translations are invalid')
            translations = dict(body['translations'])
        changed = body.get('changed_fields', ['title', 'description'])
        if not isinstance(changed, list) or any(field not in {'title', 'description'} for field in changed):
            raise ValueError('Card language changes are invalid')
        if language == result['source_language']:
            for field in changed:
                result[field] = body.get(field, result[field])
        elif changed:
            locale = dict(translations.get(language) or {})
            for field in changed:
                value = body.get(field, '')
                if value:
                    locale[field] = value
                else:
                    locale.pop(field, None)
            if locale:
                translations[language] = locale
            else:
                translations.pop(language, None)
    target_language = body.get('translation_language')
    if target_language:
        if not isinstance(target_language, str) or target_language not in SUPPORTED_LANGUAGES or target_language == language:
            raise ValueError('Choose another supported language for the translation')
        value = body.get('translation')
        if not isinstance(value, dict):
            raise ValueError('Translation details are invalid')
        locale = dict(translations.get(target_language) or {})
        for field in ('title', 'description'):
            text = value.get(field, '')
            if not isinstance(text, str):
                raise ValueError('Translation details are invalid')
            if text.strip():
                locale[field] = text.strip()
            else:
                locale.pop(field, None)
        if locale:
            translations[target_language] = locale
        else:
            translations.pop(target_language, None)
    result['translations'] = translations
    return result


def _persist_card_collections(cards):
    for kind, key, label in (('online', 'online_source_cards', 'online source'),
                             ('rss', 'rss_cards', 'RSS')):
        values = []
        for card in cards:
            if card['type'] != kind:
                continue
            field = 'links' if kind == 'online' else 'feeds'
            values.append({'id': card['id'], 'title': card['title'],
                           'description': card['description'], 'translations': card['translations'],
                           'source_language': card['source_language'],
                           'offline_display': card.get('offline_display', 'hide'), field: card.get('entries', [])})
        validated = _validate_card_list(values, label)
        g.db.execute('INSERT INTO site_setting(key,value) VALUES(?,?) '
                     'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                     (key, json.dumps(validated, ensure_ascii=False)))


@app.get('/api/admin/cards')
@admin_required
def admin_cards_list():
    restore_empty_default_police_feeds(configured_rss_cards())
    return jsonify(cards=_admin_card_records(), languages=SUPPORTED_LANGUAGES)


@app.post('/api/admin/cards')
@admin_required
@csrf_required
def admin_card_create():
    if request.content_length is not None and request.content_length > 1024 * 1024:
        return jsonify(error='Card configuration exceeds 1 MB'), 413
    body = request.get_json(silent=True)
    try:
        g.db.execute('BEGIN IMMEDIATE')
        card = _validate_card_metadata(_merge_card_locale_edit(body if isinstance(body, dict) else {}))
        if any(existing['id'] == card['id'] for existing in _admin_card_records()):
            return jsonify(error='That card ID already exists'), 409
        card['entries'] = body.get('entries', [])
        card['offline_display'] = body.get('offline_display', 'hide')
        _persist_card_collections([*_admin_card_records(), card])
        if card['type'] == 'subject':
            order = g.db.execute('SELECT COALESCE(MAX(display_order),-1)+1 FROM library_subject').fetchone()[0]
            g.db.execute('INSERT INTO library_subject(id,title,description,display_order,translations,source_language) VALUES(?,?,?,?,?,?)',
                         (card['id'], card['title'], card['description'], order,
                          json.dumps(card['translations'], ensure_ascii=False), card['source_language']))
        g.db.commit()
    except (ValueError, sqlite3.IntegrityError) as error:
        g.db.rollback()
        return jsonify(error=str(error) or 'Could not create card'), 400
    return jsonify(card=card), 201


@app.put('/api/admin/cards/<card_id>')
@admin_required
@csrf_required
def admin_card_update(card_id):
    if request.content_length is not None and request.content_length > 1024 * 1024:
        return jsonify(error='Card configuration exceeds 1 MB'), 413
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error='Card details must be a JSON object'), 400
    try:
        g.db.execute('BEGIN IMMEDIATE')
        existing_cards = _admin_card_records()
        previous = next((item for item in existing_cards if item['id'] == card_id), None)
        if not previous:
            g.db.rollback()
            return jsonify(error='Card not found'), 404
        card = _validate_card_metadata(_merge_card_locale_edit({**body, 'id': card_id}, previous))
        card['entries'] = body.get('entries', previous.get('entries', []))
        card['offline_display'] = body.get('offline_display', previous.get('offline_display', 'hide'))
        type_changed = card['type'] != previous['type']
        if type_changed and previous['child_count']:
            g.db.rollback()
            return jsonify(error='Card type cannot change while child data is connected'), 409
        if card['type'] != 'subject' and (not isinstance(card['offline_display'], str) or
                                          card['offline_display'] not in {'hide', 'inactive'}):
            raise ValueError('Choose a supported offline display setting')
        if card['type'] == 'subject':
            card['entries'] = []
            card['offline_display'] = 'hide'
        if type_changed and previous['type'] == 'subject':
            prefs = site_preferences()
            g.db.execute('DELETE FROM library_subject WHERE id=?', (card_id,))
            g.db.execute('INSERT INTO site_setting(key,value) VALUES(?,?) '
                         'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                         ('always_show_subjects', json.dumps([value for value in prefs['always_show_subjects']
                                                              if value != card_id])))
        if type_changed and card['type'] == 'subject':
            order = g.db.execute('SELECT COALESCE(MAX(display_order),-1)+1 FROM library_subject').fetchone()[0]
            g.db.execute('INSERT INTO library_subject(id,title,description,display_order,translations,source_language) VALUES(?,?,?,?,?,?)',
                         (card_id, card['title'], card['description'], order,
                          json.dumps(card['translations'], ensure_ascii=False), card['source_language']))
        elif card['type'] == 'subject':
            g.db.execute('UPDATE library_subject SET title=?,description=?,translations=?,source_language=? WHERE id=?',
                         (card['title'], card['description'], json.dumps(card['translations'], ensure_ascii=False),
                          card['source_language'], card_id))
        next_cards = [item for item in existing_cards if item['id'] != card_id] + [card]
        _persist_card_collections(next_cards)
        g.db.commit()
        if previous['type'] == 'rss' or card['type'] == 'rss':
            with _police_rss_state_lock:
                _police_rss_cache.clear()
    except (ValueError, sqlite3.IntegrityError) as error:
        g.db.rollback()
        return jsonify(error=str(error) or 'Could not save card'), 400
    return jsonify(card=card)


@app.post('/api/admin/cards/<card_id>/entries')
@admin_required
@csrf_required
def admin_card_entry_create(card_id):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error='Entry details must be a JSON object'), 400
    try:
        g.db.execute('BEGIN IMMEDIATE')
        cards = _admin_card_records()
        card = next((item for item in cards if item['id'] == card_id), None)
        if not card or card['type'] == 'subject':
            g.db.rollback()
            return jsonify(error='Online source or RSS card not found'), 404
        entry = {'id': body.get('id'), 'title': body.get('title'), 'url': body.get('url')}
        if card['type'] == 'online':
            entry['description'] = body.get('description', '')
        else:
            entry['enabled'] = body.get('enabled', True)
        card['entries'] = [*card['entries'], entry]
        _persist_card_collections(cards)
        g.db.commit()
        if card['type'] == 'rss':
            with _police_rss_state_lock:
                _police_rss_cache.clear()
    except (ValueError, sqlite3.IntegrityError) as error:
        g.db.rollback()
        return jsonify(error=str(error) or 'Could not add entry'), 400
    return jsonify(card=next(item for item in _admin_card_records() if item['id'] == card_id)), 201


@app.put('/api/admin/cards/<card_id>/entries/<entry_id>')
@admin_required
@csrf_required
def admin_card_entry_update(card_id, entry_id):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error='Entry details must be a JSON object'), 400
    try:
        g.db.execute('BEGIN IMMEDIATE')
        cards = _admin_card_records()
        card = next((item for item in cards if item['id'] == card_id), None)
        entry = next((item for item in card['entries'] if item['id'] == entry_id), None) if card else None
        if not card or card['type'] == 'subject' or not entry:
            g.db.rollback()
            return jsonify(error='Card entry not found'), 404
        target_card_id = body.get('card_id', card_id)
        target = next((item for item in cards if item['id'] == target_card_id), None)
        if not target or target['type'] != card['type']:
            g.db.rollback()
            return jsonify(error='Choose a card of the same type'), 400
        if target is not card:
            if any(item['id'] == entry_id for item in target['entries']):
                g.db.rollback()
                return jsonify(error='That card already has an entry with this ID'), 409
            card['entries'].remove(entry)
            target['entries'].append(entry)
        for key in ('title', 'url'):
            if key in body:
                entry[key] = body[key]
        if target['type'] == 'online' and 'description' in body:
            entry['description'] = body['description']
        if target['type'] == 'rss' and 'enabled' in body:
            entry['enabled'] = body['enabled']
        _persist_card_collections(cards)
        g.db.commit()
        if target['type'] == 'rss':
            with _police_rss_state_lock:
                _police_rss_cache.clear()
    except (ValueError, sqlite3.IntegrityError) as error:
        g.db.rollback()
        return jsonify(error=str(error) or 'Could not save entry'), 400
    return jsonify(card=next(item for item in _admin_card_records() if item['id'] == target_card_id))


@app.delete('/api/admin/cards/<card_id>/entries/<entry_id>')
@admin_required
@csrf_required
def admin_card_entry_remove(card_id, entry_id):
    try:
        g.db.execute('BEGIN IMMEDIATE')
        cards = _admin_card_records()
        card = next((item for item in cards if item['id'] == card_id), None)
        if not card or card['type'] == 'subject' or not any(item['id'] == entry_id for item in card['entries']):
            g.db.rollback()
            return jsonify(error='Card entry not found'), 404
        card['entries'] = [item for item in card['entries'] if item['id'] != entry_id]
        _persist_card_collections(cards)
        g.db.commit()
        if card['type'] == 'rss':
            with _police_rss_state_lock:
                _police_rss_cache.clear()
    except (ValueError, sqlite3.IntegrityError) as error:
        g.db.rollback()
        return jsonify(error=str(error) or 'Could not remove entry'), 400
    return jsonify(card=next(item for item in _admin_card_records() if item['id'] == card_id))


@app.delete('/api/admin/cards/<card_id>')
@admin_required
@csrf_required
def admin_card_remove(card_id):
    g.db.execute('BEGIN IMMEDIATE')
    cards = _admin_card_records()
    card = next((item for item in cards if item['id'] == card_id), None)
    if not card:
        g.db.rollback()
        return jsonify(error='Card not found'), 404
    if card['child_count']:
        g.db.rollback()
        return jsonify(error='Remove the connected child data before deleting this card'), 409
    try:
        if card['type'] == 'subject':
            prefs = site_preferences()
            g.db.execute('DELETE FROM library_subject WHERE id=?', (card_id,))
            g.db.execute('INSERT INTO site_setting(key,value) VALUES(?,?) '
                         'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                         ('always_show_subjects', json.dumps([value for value in prefs['always_show_subjects']
                                                              if value != card_id])))
        _persist_card_collections([item for item in cards if item['id'] != card_id])
        g.db.commit()
    except (ValueError, sqlite3.IntegrityError) as error:
        g.db.rollback()
        return jsonify(error=str(error) or 'Could not delete card'), 400
    return '', 204


@app.get('/api/admin/subjects')
@admin_required
def admin_subjects_list():
    subjects = []
    for slug, title, description in get_subjects():
        count = subject_assigned_count(slug)
        subjects.append({'id': slug, 'title': title, 'description': description,
                         'assigned_count': count, 'can_delete': count == 0})
    return jsonify(subjects)


@app.post('/api/admin/subjects')
@admin_required
@csrf_required
def admin_subject_create():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error='Subject details must be a JSON object'), 400
    slug = body.get('id')
    title = body.get('title')
    description = body.get('description')
    if not isinstance(slug, str) or len(slug) > 64 or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug):
        return jsonify(error='Subject ID must use lowercase letters, numbers, and hyphens'), 400
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > 80:
        return jsonify(error='Subject title must be 1 to 80 characters'), 400
    if not isinstance(description, str) or not description.strip() or len(description.strip()) > 300:
        return jsonify(error='Subject description must be 1 to 300 characters'), 400
    try:
        g.db.execute('BEGIN IMMEDIATE')
        order = g.db.execute('SELECT COALESCE(MAX(display_order),-1)+1 FROM library_subject').fetchone()[0]
        g.db.execute('INSERT INTO library_subject(id,title,description,display_order) VALUES(?,?,?,?)',
                     (slug, title.strip(), description.strip(), order))
        g.db.commit()
    except sqlite3.IntegrityError:
        return jsonify(error='That subject ID already exists'), 409
    return jsonify(id=slug), 201


@app.delete('/api/admin/subjects/<slug>')
@admin_required
@csrf_required
def admin_subject_delete(slug):
    g.db.execute('BEGIN IMMEDIATE')
    if not g.db.execute('SELECT 1 FROM library_subject WHERE id=?', (slug,)).fetchone():
        g.db.rollback()
        abort(404)
    count = subject_assigned_count(slug)
    if count is None:
        g.db.rollback()
        return jsonify(error='Cannot verify subject assignments; removal is blocked'), 409
    if count:
        g.db.rollback()
        return jsonify(error='Subject still has {count} assigned content record(s)',
                       error_params={'count': count}), 409
    prefs = site_preferences()
    g.db.execute('DELETE FROM library_subject WHERE id=?', (slug,))
    remaining_always_show = [item for item in prefs['always_show_subjects'] if item != slug]
    g.db.execute('INSERT INTO site_setting(key,value) VALUES(?,?) '
                 'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                 ('always_show_subjects', json.dumps(remaining_always_show)))
    g.db.commit()
    return '', 204


@app.put('/api/admin/settings')
@admin_required
@csrf_required
def admin_settings_update():
    body = request.get_json(silent=True) or {}
    current = site_preferences()
    pdf_open_mode = body.get('pdf_open_mode', current['pdf_open_mode'])
    subtitle = body.get('subtitle', current['subtitle'])
    home_columns = body.get('home_columns', current['home_columns'])
    display_timezone = body.get('display_timezone', current['display_timezone'])
    hide_empty_subjects = body.get('hide_empty_subjects', current['hide_empty_subjects'])
    always_show_subjects = body.get('always_show_subjects', current['always_show_subjects'])
    accent_color = body.get('accent_color', current['accent_color'])
    if not isinstance(pdf_open_mode, str) or pdf_open_mode not in {'same_tab', 'new_tab'}:
        return jsonify(error='Choose whether PDFs open in this tab or a new tab'), 400
    if not valid_timezone_name(display_timezone):
        return jsonify(error='Choose a valid IANA timezone such as Europe/Copenhagen'), 400
    if not isinstance(subtitle, str):
        return jsonify(error='Subtitle must be text'), 400
    subtitle = subtitle.strip()
    if not subtitle or len(subtitle) > 80 or any(ord(char) < 32 for char in subtitle):
        return jsonify(error='Subtitle must be 1–80 printable characters'), 400
    if not isinstance(accent_color, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', accent_color):
        return jsonify(error='Choose a six-digit hexadecimal accent color'), 400
    accent_color = accent_color.lower()
    if str(home_columns) not in {'3', '4', '5'} or isinstance(home_columns, bool):
        return jsonify(error='Choose 3, 4, or 5 subject columns'), 400
    home_columns = str(home_columns)
    subject_ids = {row[0] for row in get_subjects()}
    if not isinstance(hide_empty_subjects, bool):
        return jsonify(error='Hide empty subjects must be true or false'), 400
    if (not isinstance(always_show_subjects, list) or
            any(not isinstance(subject, str) or subject not in subject_ids
                for subject in always_show_subjects)):
        return jsonify(error='Always-show subjects must be valid subject IDs'), 400
    always_show_subjects = list(dict.fromkeys(always_show_subjects))
    g.db.executemany('INSERT INTO site_setting(key,value) VALUES(?,?) '
                     'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                     [('pdf_open_mode', pdf_open_mode), ('subtitle', subtitle),
                      ('accent_color', accent_color),
                      ('home_columns', home_columns),
                      ('display_timezone', display_timezone),
                      ('hide_empty_subjects', 'true' if hide_empty_subjects else 'false'),
                      ('always_show_subjects', json.dumps(always_show_subjects))])
    g.db.commit()
    return jsonify(settings=site_preferences())


def _save_card_definitions(key, kind):
    if request.content_length is not None and request.content_length > 1024 * 1024:
        return jsonify(error='Card configuration exceeds 1 MB'), 413
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or 'cards' not in body:
        return jsonify(error='Expected a card list'), 400
    try:
        cards = _validate_card_list(body['cards'], kind)
    except ValueError as error:
        return jsonify(error=str(error)), 400
    g.db.execute('INSERT INTO site_setting(key,value) VALUES(?,?) '
                 'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                 (key, json.dumps(cards, ensure_ascii=False)))
    g.db.commit()
    if key == 'rss_cards':
        with _police_rss_state_lock:
            _police_rss_cache.clear()
    return jsonify(cards=cards)


@app.get('/api/admin/online-source-cards')
@admin_required
def admin_online_source_cards():
    return jsonify(cards=configured_online_source_cards())


@app.put('/api/admin/online-source-cards')
@admin_required
@csrf_required
def admin_online_source_cards_update():
    return _save_card_definitions('online_source_cards', 'online source')


@app.get('/api/admin/rss-cards')
@admin_required
def admin_rss_cards():
    return jsonify(cards=configured_rss_cards())


@app.put('/api/admin/rss-cards')
@admin_required
@csrf_required
def admin_rss_cards_update():
    return _save_card_definitions('rss_cards', 'RSS')


@app.put('/api/admin/settings/accent')
@admin_required
@csrf_required
def admin_accent_update():
    body = request.get_json(silent=True)
    accent_color = body.get('accent_color') if isinstance(body, dict) else None
    if not isinstance(accent_color, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', accent_color):
        return jsonify(error='Choose a six-digit hexadecimal accent color'), 400
    accent_color = accent_color.lower()
    g.db.execute('INSERT INTO site_setting(key,value) VALUES(?,?) '
                 'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                 ('accent_color', accent_color))
    g.db.commit()
    saved_color = site_preferences()['accent_color']
    return jsonify(accent_color=saved_color)


@app.get('/api/admin/zims')
@admin_required
def zims_list():
    rows = [dict(row) for row in g.db.execute('SELECT * FROM zim ORDER BY title')]
    for row in rows:
        file_size = on_disk_file_size(DATA_ROOT, 'zim/' + row['filename'])
        if file_size is not None and row['status'] == 'ready':
            row['bytes'] = file_size
        if row['status'].startswith('pid:') and not zim_worker_alive(row['status'][4:], row['id']):
            g.db.execute('UPDATE zim SET status=? WHERE id=? AND status=?',
                         ('interrupted', row['id'], row['status']))
            row['status'] = g.db.execute('SELECT status FROM zim WHERE id=?', (row['id'],)).fetchone()[0]
        row['pause_requested'] = (row['status'].startswith('pid:') and zim_pause_path(row['id']).exists())
        row.update(zim_transfer_state(row['id'], row['filename'], row['status']))
    g.db.commit()
    known = {row['filename'] for row in rows}
    acquired = DATA_ROOT / 'acquired.json'
    if acquired.is_file():
        try:
            lock = json.loads(acquired.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            lock = {}
        for name, record in lock.items():
            if not name.startswith('zim/'):
                continue
            filename = Path(name).name
            if filename in known:
                continue
            asset = record.get('asset', {})
            file_size = on_disk_file_size(DATA_ROOT, 'zim/' + filename)
            rows.append({'id': 'file-' + filename, 'title': asset.get('title', filename),
                         'subject': asset.get('collection', 'general-reference'),
                         'filename': filename, 'source_url': asset.get('url', ''),
                         'bytes': file_size if file_size is not None else record.get('bytes'),
                         'sha256': record.get('sha256'),
                         'status': 'ready'})
    return jsonify(rows)


def zim_failure_reason(zid):
    try:
        if str(uuid.UUID(zid)) != zid:
            return ''
    except (ValueError, TypeError, AttributeError):
        return ''
    log_path = PRIVATE_ROOT / 'logs' / f'{zid}.log'
    if log_path.is_symlink() or not log_path.is_file():
        return ''
    try:
        with log_path.open('rb') as log:
            log.seek(0, os.SEEK_END)
            end = log.tell()
            log.seek(max(0, end - 8192))
            lines = log.read(8192).decode('utf-8', errors='replace').splitlines()
        errors = [line[7:].strip() for line in lines if line.startswith('ERROR: ')]
        return errors[-1][:500] if errors else ''
    except OSError:
        return ''


def zim_transfer_state(zid, filename, status):
    if status.startswith('failed'):
        reason = zim_failure_reason(zid)
        return {'failure_reason': reason} if reason else {}
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*\.zim', filename):
        return {}
    try:
        if str(uuid.UUID(zid)) != zid:
            return {}
    except (ValueError, TypeError, AttributeError):
        return {}
    manifest_path = PRIVATE_ROOT / 'requests' / f'{zid}.json'
    if manifest_path.is_symlink() or not manifest_path.is_file():
        return {}
    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if not isinstance(manifest, dict) or not isinstance(manifest.get('assets'), list):
            return {}
        asset = next((asset for asset in manifest['assets']
                      if isinstance(asset, dict) and asset.get('path') == f'zim/{filename}'), None)
        if asset is None:
            return {}
        expected = asset.get('expected_bytes')
        if type(expected) is not int or expected <= 0:
            return {}
    except (OSError, ValueError, TypeError):
        return {}

    archive = DATA_ROOT / 'zim' / filename
    partial = archive.with_name(archive.name + '.part')
    measured = partial if not partial.is_symlink() and partial.is_file() else archive
    received = 0
    activity_times = []
    if measured.is_file() and not measured.is_symlink():
        try:
            stat = measured.stat()
            received = min(stat.st_size, expected)
            activity_times.append(stat.st_mtime)
        except OSError:
            pass
    active = status.startswith('pid:') or status == 'downloading'
    if active:
        log_path = PRIVATE_ROOT / 'logs' / f'{zid}.log'
        if log_path.is_file() and not log_path.is_symlink():
            try:
                activity_times.append(log_path.stat().st_mtime)
            except OSError:
                pass
    age = max(0, int(time.time() - max(activity_times))) if activity_times else None
    if active:
        if received >= expected:
            phase = 'verifying'
        elif age is not None and age >= 120:
            phase = 'stalled'
        elif received == 0:
            phase = 'connecting'
        else:
            phase = 'downloading'
    else:
        phase = None
    return {'expected_bytes': expected, 'received_bytes': received,
            'progress_age_seconds': age, 'phase': phase}


def zim_worker_alive(pid, zid):
    if not pid.isdigit():
        return False
    try:
        command = Path('/proc') / pid / 'cmdline'
        args = command.read_bytes().decode(errors='replace').split('\0')
        return 'fetch-zim' in args and zid in args
    except OSError:
        return False


def safe_public_https_url(value):
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('ZIM source must be a public HTTPS URL without embedded credentials')
    if not re.fullmatch(r'[A-Za-z0-9.-]+', parsed.hostname):
        raise ValueError('Invalid source host')
    # Restrict direct downloads to the Kiwix publisher domain, avoiding SSRF and redirects.
    host = parsed.hostname.lower()
    if host not in KIWIX_DOWNLOAD_HOSTS | {KIWIX_FIRST_PARTY_MIRROR}:
        raise ValueError('Direct downloads are limited to the official Kiwix download domain')
    if parsed.port not in (None, 443):
        raise ValueError('Unexpected source port')
    return urllib.parse.urlunsplit(('https', parsed.netloc, parsed.path, parsed.query, ''))


def active_zim_reservations(db):
    """Return the unwritten bytes reserved by live ZIM workers."""
    rows = db.execute(
        "SELECT id,filename,status FROM zim WHERE status='downloading' OR status LIKE 'pid:%'"
    ).fetchall()
    reserved = 0
    for row in rows:
        status = row['status']
        if status.startswith('pid:') and not zim_worker_alive(status[4:], row['id']):
            continue
        manifest_path = PRIVATE_ROOT / 'requests' / f"{row['id']}.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise ValueError('Cannot safely calculate space reserved by an active ZIM download')
        try:
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            assets = manifest.get('assets') if isinstance(manifest, dict) else None
            asset = next((item for item in assets if isinstance(item, dict) and
                          item.get('path') == f"zim/{row['filename']}"), None)
            expected = asset.get('expected_bytes') if asset else None
        except (OSError, ValueError, TypeError):
            raise ValueError('Cannot safely calculate space reserved by an active ZIM download') from None
        if type(expected) is not int or expected <= 0:
            raise ValueError('Cannot safely calculate space reserved by an active ZIM download')
        reserved += zim_remaining_bytes(row['filename'], expected)
    return reserved


def zim_remaining_bytes(filename, expected):
    archive = library.safe_path(DATA_ROOT, f'zim/{filename}')
    partial = library.safe_path(DATA_ROOT, f'zim/{filename}.part')
    if archive.is_symlink() or partial.is_symlink():
        raise ValueError('Refusing a symlink in a ZIM download path')
    if archive.exists():
        if not archive.is_file():
            raise ValueError('Unexpected path for a ZIM download')
        return 0
    if partial.exists():
        if not partial.is_file():
            raise ValueError('Unexpected partial path for a ZIM download')
        received = partial.stat().st_size
        if received > expected:
            raise ValueError('ZIM partial exceeds its expected size')
        return expected - received
    return expected


def ensure_zim_capacity(db, additional_bytes, reserve_bytes=ZIM_DOWNLOAD_RESERVE_BYTES):
    """Check new bytes plus active transfer reservations against library storage."""
    if type(additional_bytes) is not int or additional_bytes < 0:
        raise ValueError('Invalid ZIM storage estimate')
    pending = active_zim_reservations(db)
    free = shutil.disk_usage(DATA_ROOT).free
    available = max(0, free - pending)
    required = additional_bytes + reserve_bytes
    if available < required:
        raise ValueError(
            f'Insufficient free library storage: {required:,} bytes required including reserve; '
            f'{available:,} bytes available after active downloads'
        )


def canonical_kiwix_download_url(value):
    """Avoid Kiwix's public load balancer redirecting downloads to external mirrors."""
    url = safe_public_https_url(value)
    parsed = urllib.parse.urlsplit(url)
    if parsed.hostname.lower() in KIWIX_DOWNLOAD_HOSTS:
        parsed = parsed._replace(netloc=KIWIX_FIRST_PARTY_MIRROR)
    return urllib.parse.urlunsplit(parsed)


def inspect_kiwix_asset(value):
    # Kiwix's lb.download.kiwix.org redirects to community mirrors, which the
    # acquisition policy correctly rejects. Pin these official entry points to
    # Kiwix's own mirror before inspecting size and checksum.
    url = canonical_kiwix_download_url(value)
    head = urllib.request.Request(url, method='HEAD', headers={'User-Agent': 'cyberdeck-library/1'})
    with urllib.request.urlopen(head, timeout=20) as response:
        final_url = safe_public_https_url(response.geturl())
        length = response.headers.get('Content-Length', '')
    if not length.isdigit() or int(length) <= 0:
        raise ValueError('Kiwix must publish a valid Content-Length so Hub can check available library storage')
    checksum = None
    checksum_url = None
    checksum_base = urllib.parse.urlsplit(url)._replace(netloc='download.kiwix.org', query='', fragment='')
    for suffix in ('.sha256', '.sha256sum'):
        candidate = urllib.parse.urlunsplit(checksum_base._replace(path=checksum_base.path + suffix))
        try:
            req = urllib.request.Request(candidate, headers={'User-Agent': 'cyberdeck-library/1'})
            with urllib.request.urlopen(req, timeout=10) as response:
                final_checksum_url = urllib.parse.urlsplit(safe_public_https_url(response.geturl()))
                if final_checksum_url.path != urllib.parse.urlsplit(candidate).path:
                    continue
                data = response.read(4096).decode('ascii', errors='strict')
            match = re.search(r'(?i)\b([0-9a-f]{64})\b', data)
            if match:
                checksum = match.group(1).lower()
                checksum_url = candidate
                break
        except (OSError, UnicodeError, ValueError):
            continue
    if not checksum:
        raise ValueError('This Kiwix archive has no readable SHA-256 sidecar; resumable acquisition requires a pinned checksum')
    # Preserve the vetted first-party URL. The acquisition worker independently
    # checks that any later redirect remains within the approved Kiwix hosts.
    return url, int(length), checksum, checksum_url


@app.get('/api/admin/catalog')
@admin_required
def zim_catalog():
    query = request.args.get('q', '').strip()[:120]
    if len(query) < 2:
        return jsonify(items=[])
    catalog_url = 'https://library.kiwix.org/catalog/v2/entries?' + urllib.parse.urlencode(
        {'count': 40, 'start': 0, 'q': query})
    request_obj = urllib.request.Request(catalog_url, headers={'Accept': 'application/atom+xml'})
    try:
        with urllib.request.urlopen(request_obj, timeout=15) as response:
            if response.status != 200 or int(response.headers.get('Content-Length', '0') or 0) > 5_000_000:
                raise ValueError('Kiwix catalog response is too large or unavailable')
            xml = response.read(5_000_001)
        if len(xml) > 5_000_000 or b'<!DOCTYPE' in xml.upper() or b'<!ENTITY' in xml.upper():
            raise ValueError('Rejected unsafe or oversized Kiwix catalog response')
        root = ET.fromstring(xml)
        if root.tag != '{http://www.w3.org/2005/Atom}feed':
            raise ValueError('Expected an Atom catalog feed')
        catalog_entries = root.findall('{http://www.w3.org/2005/Atom}entry')
        entries = []
        for entry in catalog_entries:
            title = entry.findtext('{http://www.w3.org/2005/Atom}title', default='').strip()
            download = None
            for link in entry.findall('{http://www.w3.org/2005/Atom}link'):
                href = link.get('href', '')
                if link.get('rel') in {'http://opds-spec.org/acquisition/open-access', 'http://opds-spec.org/acquisition'} or link.get('type') == 'application/x-zim':
                    try:
                        candidate = safe_public_https_url(urllib.parse.urljoin('https://library.kiwix.org', href))
                    except ValueError:
                        continue
                    parsed = urllib.parse.urlsplit(candidate)
                    # Kiwix acquisition feeds advertise Metalink descriptors at
                    # <archive>.zim.meta4. Hand the corresponding archive URL to
                    # our existing size/checksum inspection and download policy.
                    if parsed.path.lower().endswith('.zim.meta4'):
                        parsed = parsed._replace(path=parsed.path[:-6])
                    if not parsed.path.lower().endswith('.zim'):
                        continue
                    download = urllib.parse.urlunsplit(parsed)
                    size_text = link.get('length', '')
                    break
            if title and download:
                def entry_text(name, limit):
                    element = entry.find('{http://www.w3.org/2005/Atom}' + name)
                    return ''.join(element.itertext()).strip()[:limit] if element is not None else ''

                entries.append({'title': title[:200], 'url': download,
                                'filename': Path(urllib.parse.urlsplit(download).path).name,
                                'description': entry_text('summary', 4000),
                                'language': entry_text('language', 80),
                                'edition': entry_text('updated', 40).split('T')[0],
                                'flavour': entry_text('flavour', 100),
                                'bytes': int(size_text) if size_text.isdigit() and len(size_text) < 16 else None})
        if catalog_entries and not entries:
            raise ValueError('Kiwix returned catalog entries, but none had a supported download link')
        return jsonify(items=entries)
    except (OSError, ValueError, ET.ParseError) as error:
        return jsonify(error='Kiwix catalog unavailable: {error}',
                       error_params={'error': str(error)}), 502


def acquire_zim(title, subject, source_url):
    title = title.strip()[:200]
    if not title or subject not in {row[0] for row in get_subjects()}:
        raise ValueError('Title and a known subject are required')
    clean_url, expected_bytes, checksum, checksum_url = inspect_kiwix_asset(source_url)
    filename = secure_filename(Path(urllib.parse.urlsplit(clean_url).path).name)
    if not filename.lower().endswith('.zim'):
        raise ValueError('Source must name a .zim file')
    zid = str(uuid.uuid4())
    manifest_dir = PRIVATE_ROOT / 'requests'
    manifest_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    manifest_path = manifest_dir / f'{zid}.json'
    asset = {'path': f'zim/{filename}', 'title': title, 'collection': subject,
             'url': clean_url, 'max_bytes': expected_bytes, 'expected_bytes': expected_bytes,
             'sha256': checksum, 'checksum_url': checksum_url,
             'hash_provenance': 'Kiwix HTTPS SHA-256 sidecar inspected at acquisition time.'}
    g.db.execute('BEGIN IMMEDIATE')
    proc = None
    try:
        target = library.safe_path(DATA_ROOT, asset['path'])
        if target.exists() or g.db.execute('SELECT 1 FROM zim WHERE filename=?', (filename,)).fetchone():
            raise ValueError(f'{asset["path"]} already exists or is already registered')
        ensure_zim_capacity(g.db, expected_bytes)
        manifest_path.write_text(json.dumps({'id': zid, 'reserve_bytes': ZIM_DOWNLOAD_RESERVE_BYTES,
                                             'assets': [asset]}, indent=2), encoding='utf-8')
        g.db.execute('INSERT INTO zim(id,title,subject,filename,source_url,status) VALUES(?,?,?,?,?,?)',
                     (zid, title, subject, filename, clean_url, 'downloading'))
        # Start while the write lock is held. The child waits for this transaction
        # before reading the request, so no committed reservation can be orphaned
        # in a crash window between marking it downloading and starting the worker.
        proc = subprocess.Popen([sys.executable, str(APP_DIR / 'webapp.py'), 'fetch-zim', zid],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True)
        g.db.execute('UPDATE zim SET status=? WHERE id=? AND status=?',
                     (f'pid:{proc.pid}', zid, 'downloading'))
        g.db.commit()
    except Exception as error:
        g.db.rollback()
        if proc is not None:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        manifest_path.unlink(missing_ok=True)
        if isinstance(error, OSError):
            raise ValueError(f'Could not start the ZIM download worker: {error}') from error
        raise
    return zid


def zim_validator(log):
    bundled = Path('/usr/local/lib/cyberdeck/tools/zimcheck')
    checker = str(bundled) if bundled.is_file() else shutil.which('zimcheck')
    if not checker:
        raise ValueError('zimcheck is required; install a validator using libzim 9.4.0 or newer')
    version = subprocess.run([checker, '--version'], capture_output=True, text=True, timeout=15)
    output = (version.stdout or '') + (version.stderr or '')
    log.write(output + '\n')
    log.flush()
    match = re.search(r'(?m)^libzim\s+(\d+)\.(\d+)\.(\d+)', output)
    if version.returncode or not match:
        raise ValueError('Cannot determine zimcheck libzim version; no download started')
    if tuple(map(int, match.groups())) < (9, 4, 0):
        raise ValueError('Validator uses outdated libzim; install libzim 9.4.0 or newer '
                         '(upstream zim-tools issue 484). No download started')
    return checker


def retain_zim_for_retry(archive, manifest):
    # Reuse library.py's complete-partial recovery: the next fetch verifies
    # pinned bytes/hash locally before moving it back and running zimcheck.
    import library
    _, assets = library.load_manifest(manifest)
    asset = next((asset for asset in assets if asset['path'] == 'zim/' + archive.name), None)
    if asset is None or not library.resumable(asset):
        raise ValueError('Cannot retain archive without its pinned acquisition identity')
    partial = archive.with_name(archive.name + '.part')
    metadata = partial.with_name(partial.name + '.json')
    if archive.is_symlink() or partial.exists() or partial.is_symlink() or metadata.is_symlink():
        raise ValueError('Conflicting archive/resume paths; files preserved for inspection')
    if metadata.exists():
        library.resume_state(asset, partial)  # Interrupted after rename, before metadata cleanup.
    else:
        library.write_json(metadata, {'version': 1, 'asset': asset, 'etag': None})
    os.replace(archive, partial)


class ZimPaused(Exception):
    """A cooperative stop after the worker has reaped its child process."""


def zim_pause_path(zid):
    if str(uuid.UUID(zid)) != zid:
        raise ValueError('Invalid ZIM request ID')
    return PRIVATE_ROOT / 'requests' / (zid + '.pause')


def run_zim_step(command, log, pause):
    if pause.exists():
        raise ZimPaused()
    process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
    try:
        while True:
            try:
                code = process.wait(timeout=0.5)
                if pause.exists():
                    raise ZimPaused()
                return subprocess.CompletedProcess(command, code)
            except subprocess.TimeoutExpired:
                if pause.exists():
                    raise ZimPaused()
    finally:
        # Only this worker's direct child is terminated, never a stored PID or
        # shared process group. Do not expose Resume until the child has exited.
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def fetch_zim_worker(zid):
    with closing(connect_db()) as db:
        row = db.execute('SELECT filename FROM zim WHERE id=?', (zid,)).fetchone()
        if not row:
            raise ValueError('Unknown ZIM request')
        manifest = PRIVATE_ROOT / 'requests' / f'{zid}.json'
        pause = zim_pause_path(zid)
        archive = DATA_ROOT / 'zim' / row['filename']
        log_dir = PRIVATE_ROOT / 'logs'
        log_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        with (log_dir / f'{zid}.log').open('a', encoding='utf-8') as log:
            log.write('\n=== ZIM attempt ' + time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime()) + ' ===\n')
            log.flush()
            failure_status = 'failed: validator unavailable'
            try:
                checker = zim_validator(log)  # Fail before downloading with an incompatible checker.
                failure_status = 'failed: acquisition'
                result = run_zim_step([sys.executable, str(APP_DIR / 'library.py'), 'fetch',
                                         '--root', str(DATA_ROOT), '--manifest', str(manifest),
                                         '--missing-only'], log, pause)
                if result.returncode:
                    raise ValueError('ZIM acquisition or integrity validation failed; inspect its private log')
                archive = DATA_ROOT / 'zim' / row['filename']
                failure_status = 'failed: zimcheck'
                # No flags means all publisher-quality checks, including broken
                # article links and favicons. Those are not transfer corruption.
                log.write('Activation checks: archive integrity, internal checksum, main page, '
                          'and redirect loops. Publisher content-quality checks are not run.\n')
                log.flush()
                checked = run_zim_step([checker, '--checksum', '--integrity', '--main',
                                        '--redirect_loop', str(archive)], log, pause)
                if checked.returncode:
                    retain_zim_for_retry(archive, manifest)
                    failure_status = 'failed: zimcheck (download retained)'
                    # Keep the acquisition record: library.py recognizes this
                    # requested file as missing and recovers its complete partial.
                    # Do not rewrite shared acquired.json while other jobs run.
                    raise ValueError('ZIM validation failed; full download retained as .zim.part. '
                                     'Retry rechecks it without downloading. See validator output above')
                db.execute('UPDATE zim SET status=? WHERE id=?', ('ready', zid))
                db.commit()
            except ZimPaused:
                # A pause during hashing/validation may leave a complete archive.
                # Keep it out of Kiwix until all verification succeeds on resume.
                if archive.exists():
                    retain_zim_for_retry(archive, manifest)
                log.write('Paused by administrator; downloaded bytes retained.\n')
                log.flush()
                db.execute('UPDATE zim SET status=? WHERE id=?', ('paused', zid))
                db.commit()
                return
            except (ValueError, OSError, subprocess.SubprocessError) as error:
                log.write('ERROR: ' + str(error) + '\n')
                log.flush()
                db.execute('UPDATE zim SET status=? WHERE id=?', (failure_status, zid))
                db.commit()
                raise ValueError(str(error)) from error
        restart_kiwix()


@app.post('/api/admin/zims/<zid>/pause')
@admin_required
@csrf_required
def zim_pause(zid):
    row = g.db.execute('SELECT status FROM zim WHERE id=?', (zid,)).fetchone()
    if not row:
        abort(404)
    status = row['status']
    if status == 'paused':
        return jsonify(id=zid, status='paused')
    if not status.startswith('pid:') or not zim_worker_alive(status[4:], zid):
        return jsonify(error='This download is no longer running; refresh its status'), 409
    marker = zim_pause_path(zid)
    if marker.is_symlink():
        return jsonify(error='Unsafe pause request path'), 409
    marker.touch(exist_ok=True)
    return jsonify(id=zid, status='pausing'), 202


@app.post('/api/admin/zims/<zid>/retry')
@admin_required
@csrf_required
def zim_retry(zid):
    g.db.execute('BEGIN IMMEDIATE')  # Serialize competing Resume clicks.
    row = g.db.execute('SELECT status FROM zim WHERE id=?', (zid,)).fetchone()
    if not row:
        g.db.rollback()
        abort(404)
    status = row['status']
    if status == 'ready':
        g.db.rollback()
        return jsonify(error='This archive is already verified'), 409
    if status == 'downloading' or (status.startswith('pid:') and zim_worker_alive(status[4:], zid)):
        g.db.rollback()
        return jsonify(error='Download is still running or pausing'), 409
    manifest = PRIVATE_ROOT / 'requests' / f'{zid}.json'
    if manifest.is_symlink() or not manifest.is_file():
        g.db.rollback()
        return jsonify(error='The saved ZIM download request is missing or unsafe'), 409
    try:
        _, assets = library.load_manifest(manifest)
        asset = next((item for item in assets if item.get('path', '').startswith('zim/')), None)
        if asset is None or type(asset.get('expected_bytes')) is not int:
            raise ValueError('The saved ZIM request has no exact expected size')
        remaining = zim_remaining_bytes(Path(asset['path']).name, asset['expected_bytes'])
        ensure_zim_capacity(g.db, remaining)
    except (OSError, ValueError, KeyError, TypeError) as error:
        g.db.rollback()
        return jsonify(error=str(error)), 409
    try:
        zim_pause_path(zid).unlink(missing_ok=True)
        proc = subprocess.Popen([sys.executable, str(APP_DIR / 'webapp.py'), 'fetch-zim', zid],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True)
    except OSError as error:
        g.db.rollback()
        return jsonify(error=f'Could not start the ZIM download worker: {error}'), 503
    g.db.execute('UPDATE zim SET status=? WHERE id=?', (f'pid:{proc.pid}', zid))
    g.db.commit()
    return jsonify(id=zid, status='downloading'), 202


@app.post('/api/admin/zims')
@admin_required
@csrf_required
def zims_add():
    body = request.get_json(silent=True) or {}
    try:
        zid = acquire_zim(str(body.get('title', '')), str(body.get('subject', 'general-reference')),
                          str(body.get('url', '')))
    except (ValueError, sqlite3.IntegrityError) as error:
        return jsonify(error=str(error)), 400
    return jsonify(id=zid, status='downloading'), 202


@app.put('/api/admin/zims/<zid>')
@admin_required
@csrf_required
def zim_edit(zid):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error='Expected a title and subject'), 400
    title, subject = body.get('title'), body.get('subject')
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 200:
        return jsonify(error='Display title must contain 1 to 200 characters'), 400
    if not isinstance(subject, str) or subject not in {row[0] for row in get_subjects()}:
        return jsonify(error='Choose an existing subject'), 400
    row = g.db.execute('SELECT * FROM zim WHERE id=?', (zid,)).fetchone()
    if row is None and zid.startswith('file-'):
        filename = zid[5:]
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*\.zim', filename):
            abort(404)
        row = g.db.execute('SELECT * FROM zim WHERE filename=?', (filename,)).fetchone()
        if row is None:
            try:
                lock = json.loads((DATA_ROOT / 'acquired.json').read_text(encoding='utf-8'))
                record = lock.get('zim/' + filename) if isinstance(lock, dict) else None
            except (OSError, ValueError):
                return jsonify(error='Cannot read the acquisition record'), 409
            if not isinstance(record, dict) or not isinstance(record.get('asset'), dict):
                abort(404)
            path = DATA_ROOT / 'zim' / filename
            if not path.is_file() or path.is_symlink():
                return jsonify(error='The installed archive is missing or unavailable'), 409
            # Adopt display metadata in the app DB; immutable acquisition and
            # resume records remain unchanged, as do the archive's own metadata.
            zid = str(uuid.uuid4())
            g.db.execute('INSERT INTO zim(id,title,subject,filename,source_url,bytes,sha256,status) '
                         'VALUES(?,?,?,?,?,?,?,?)',
                         (zid, title.strip(), subject, filename, record['asset'].get('url', ''),
                          record.get('bytes'), record.get('sha256'), 'ready'))
    elif row is None:
        abort(404)
    if row is not None:
        zid = row['id']
        g.db.execute('UPDATE zim SET title=?,subject=? WHERE id=?', (title.strip(), subject, zid))
    g.db.commit()
    return jsonify(id=zid, title=title.strip(), subject=subject)


@app.delete('/api/admin/zims/<zid>')
@admin_required
@csrf_required
def zim_remove(zid):
    confirmation = (request.get_json(silent=True) or {}).get('confirm')
    row = g.db.execute('SELECT * FROM zim WHERE id=?', (zid,)).fetchone()
    if row is None and zid.startswith('file-'):
        # A second admin tab may still hold the pre-edit acquisition ID.
        row = g.db.execute('SELECT * FROM zim WHERE filename=?', (zid[5:],)).fetchone()
        if row is not None:
            zid = row['id']
    if row and row['status'].startswith('pid:'):
        if zim_worker_alive(row['status'][4:], zid):
            return jsonify(error='Wait for the active download to finish or stop it before removal'), 409
    if row:
        filename = row['filename']
    else:
        filename = zid.removeprefix('file-')
        if not zid.startswith('file-') or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*\.zim', filename):
            abort(404)
    if confirmation != filename:
        return jsonify(error='Confirm removal by sending the exact ZIM filename'), 400
    path = DATA_ROOT / 'zim' / filename
    if path.exists():
        path.unlink()
    for suffix in ('.part', '.part.json'):
        partial = path.with_name(path.name + suffix)
        if partial.exists():
            partial.unlink()
    lock_path = DATA_ROOT / 'acquired.json'
    if lock_path.exists():
        lock = json.loads(lock_path.read_text(encoding='utf-8'))
        lock.pop('zim/' + filename, None)
        lock_path.write_text(json.dumps(lock, indent=2) + '\n', encoding='utf-8')
    if row:
        zim_pause_path(zid).unlink(missing_ok=True)
        g.db.execute('DELETE FROM zim WHERE id=?', (zid,))
    g.db.commit()
    restart_kiwix()
    return '', 204


def file_signature(ext, data):
    if ext == '.pdf' and data.startswith(b'%PDF-'):
        return 'pdf'
    if ext == '.docx' and data.startswith(b'PK\x03\x04'):
        return 'docx'
    if ext == '.zip' and data.startswith(b'PK\x03\x04'):
        return 'html-zip'
    return None


def validate_public_attachment_url(value):
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise ValueError('Attachment URL is invalid') from error
    if (parsed.scheme.lower() != 'https' or not parsed.hostname or
            parsed.username or parsed.password or parsed.fragment or
            port not in (None, 443) or not re.fullmatch(r'[A-Za-z0-9.-]+', parsed.hostname)):
        raise ValueError('Attachment URL must be a public HTTPS URL on port 443')
    try:
        addresses = {ipaddress.ip_address(result[4][0])
                     for result in socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)}
    except (OSError, ValueError) as error:
        raise ValueError('Attachment URL host could not be resolved') from error
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError('Attachment URL must resolve only to public IP addresses')
    return urllib.parse.urlunsplit(('https', parsed.netloc, parsed.path or '/', parsed.query, ''))


class PublicAttachmentRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_public_attachment_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_public_attachment(value, destination):
    url = validate_public_attachment_url(value)
    opener = urllib.request.build_opener(PublicAttachmentRedirectHandler())
    request_obj = urllib.request.Request(url, headers={
        'User-Agent': 'cyberdeck-library/1', 'Accept-Encoding': 'identity'})
    with opener.open(request_obj, timeout=30) as response:
        if response.status != 200:
            raise ValueError('Attachment server did not return a complete file')
        final_url = validate_public_attachment_url(response.geturl())
        length = response.headers.get('Content-Length')
        if length is not None and (not length.isdigit() or int(length) > MAX_ITEM_UPLOAD):
            raise ValueError('Remote attachment exceeds the 2 GiB size limit')
        if response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
            raise ValueError('Encoded remote attachments are not accepted')
        total = 0
        with destination.open('xb') as output:
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_ITEM_UPLOAD:
                    raise ValueError('Remote attachment exceeds the 2 GiB size limit')
                output.write(chunk)
        if total == 0:
            raise ValueError('Remote attachment is empty')
        filename = (response.headers.get_filename() or
                    Path(urllib.parse.unquote(urllib.parse.urlsplit(final_url).path)).name)
    filename = secure_filename(filename or '')
    if Path(filename).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError('Remote file must be a PDF, DOCX, or ZIP HTML attachment')
    return filename


def inspect_html_archive(data):
    total = 0
    members = []
    seen = set()
    if hasattr(data, 'seek'):
        data.seek(0)
    with zipfile.ZipFile(data) as archive:
        for member in archive.infolist():
            name = member.filename.replace('\\', '/')
            path = PurePosixPath(name)
            normalized_name = path.as_posix().rstrip('/')
            mode = member.external_attr >> 16
            if (len(members) >= MAX_ZIP_FILES or path.is_absolute() or '..' in path.parts or
                    not normalized_name or normalized_name in seen or member.flag_bits & 1):
                raise ValueError('HTML archive contains too many or unsafe paths')
            if mode and (mode & 0o170000) == 0o120000:
                raise ValueError('Symbolic links are not allowed in HTML archives')
            if (member.file_size > MAX_ZIP_EXPANDED or
                    (member.file_size and not member.compress_size) or
                    (member.compress_size and member.file_size / member.compress_size > 200)):
                raise ValueError('HTML archive expansion ratio or entry size is too large')
            total += member.file_size
            if total > MAX_ZIP_EXPANDED:
                raise ValueError('HTML archive expands beyond the 512 MiB limit')
            seen.add(normalized_name)
            members.append((member, path))
        if not any(not member.is_dir() and path.as_posix() in {'index.html', 'index.htm'}
                   for member, path in members):
            raise ValueError('HTML archive must contain index.html or index.htm')
    if hasattr(data, 'seek'):
        data.seek(0)
    return total, members


def validate_and_extract_zip(data, output):
    total, members = inspect_html_archive(data)
    output.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(data) as archive:
        for member, path in members:
            target = output.joinpath(*path.parts).resolve()
            if not target.is_relative_to(output.resolve()):
                raise ValueError('HTML archive path escaped its directory')
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(member))
    if hasattr(data, 'seek'):
        data.seek(0)


@app.post('/api/admin/items')
@admin_required
@csrf_required
def item_create():
    title = request.form.get('title', '').strip()[:200]
    description = request.form.get('description', '').strip()[:5000]
    search_terms = request.form.get('search_terms', '').strip()
    subject = request.form.get('subject', '')
    attachment_url = request.form.get('attachment_url', '').strip()
    uploads = [upload for upload in request.files.getlist('attachments') if upload and upload.filename]
    if not title or subject not in {row[0] for row in get_subjects()}:
        return jsonify(error='Title and a known subject are required'), 400
    if (len(search_terms) > 1000 or
            any(ord(char) < 32 and char not in '\t\r\n' for char in search_terms)):
        return jsonify(error='Search terms must be at most 1000 characters of text'), 400
    if not uploads and not attachment_url:
        return jsonify(error='Upload at least one attachment or provide an HTTPS file URL'), 400
    if len(attachment_url) > 2048:
        return jsonify(error='Attachment URL must be no longer than 2048 characters'), 400
    item_id = str(uuid.uuid4())
    base = PRIVATE_ROOT / 'files' / item_id
    base.mkdir(parents=True, mode=0o700)
    cover = None
    g.db.execute('INSERT INTO item(id,title,description,subject,cover,search_terms) VALUES(?,?,?,?,NULL,?)',
                 (item_id, title, description, subject, search_terms))
    try:
        def save_attachment(filename, stream, content_length=None, source_url=None):
            filename = secure_filename(filename or '')
            ext = Path(filename).suffix.lower()
            if ext not in ALLOWED_EXTENSIONS:
                raise ValueError('Only PDF, DOCX, and ZIP HTML attachments are accepted')
            stream.seek(0)
            header = stream.read(8)
            stream.seek(0)
            if content_length and content_length > MAX_ITEM_UPLOAD:
                raise ValueError('Attachment is too large')
            kind = file_signature(ext, header)
            if not kind:
                raise ValueError(f'Attachment signature does not match {ext}')
            stored = str(uuid.uuid4()) + ext
            if kind == 'html-zip':
                validate_and_extract_zip(stream, base / (stored + '.html'))
            total = 0
            digest = hashlib.sha256()
            with (base / stored).open('xb') as output:
                while chunk := stream.read(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_ITEM_UPLOAD:
                        raise ValueError('Attachment is too large')
                    digest.update(chunk)
                    output.write(chunk)
            attachment_id = str(uuid.uuid4())
            g.db.execute('INSERT INTO attachment(id,item_id,filename,stored_path,kind) VALUES(?,?,?,?,?)',
                          (attachment_id, item_id, filename, stored, kind))
            if source_url:
                asset = {'path': 'public/' + stored, 'url': source_url,
                         'title': title + ' - ' + filename, 'collection': subject,
                         'description': description, 'search_terms': search_terms,
                         'filename': filename, 'kind': kind,
                         'max_bytes': total, 'expected_bytes': total, 'sha256': digest.hexdigest(),
                         'hash_provenance': 'Computed locally from the imported attachment; not a publisher-signed checksum.'}
                library.validate_asset(asset)
                g.db.execute('INSERT INTO attachment_source(attachment_id,asset) VALUES(?,?)',
                             (attachment_id, json.dumps(asset)))
        for upload in uploads:
            save_attachment(upload.filename, upload.stream, upload.content_length)
        if attachment_url:
            temporary = base / '.remote-attachment'
            remote_name = download_public_attachment(attachment_url, temporary)
            with temporary.open('rb') as remote_file:
                save_attachment(remote_name, remote_file, temporary.stat().st_size, attachment_url)
            temporary.unlink()
        image = request.files.get('cover')
        if image and image.filename:
            ext = Path(secure_filename(image.filename)).suffix.lower()
            raw = image.stream.read(10 * 1024**2 + 1)
            signatures = {'.jpg': raw.startswith(b'\xff\xd8\xff'), '.jpeg': raw.startswith(b'\xff\xd8\xff'),
                          '.png': raw.startswith(b'\x89PNG\r\n\x1a\n'), '.webp': raw.startswith(b'RIFF') and raw[8:12] == b'WEBP'}
            if ext not in IMAGE_MIMES or len(raw) > 10 * 1024**2 or not signatures.get(ext):
                raise ValueError('Cover must be a JPEG, PNG, or WebP image no larger than 10 MiB')
            cover = str(uuid.uuid4()) + ext
            (base / cover).write_bytes(raw)
        if g.db.execute('SELECT COUNT(*) FROM attachment WHERE item_id=?', (item_id,)).fetchone()[0] == 0:
            raise ValueError('Add at least one attachment')
        g.db.execute('UPDATE item SET cover=? WHERE id=?', (cover, item_id))
        g.db.commit()
    except (ValueError, zipfile.BadZipFile, OSError) as error:
        shutil.rmtree(base, ignore_errors=True)
        g.db.execute('DELETE FROM attachment WHERE item_id=?', (item_id,))
        g.db.execute('DELETE FROM item WHERE id=?', (item_id,))
        g.db.commit()
        return jsonify(error=str(error)), 400
    return jsonify(id=item_id), 201


@app.get('/api/admin/items')
@admin_required
def item_list():
    rows = g.db.execute('SELECT * FROM item ORDER BY created_at DESC').fetchall()
    result = []
    for row in rows:
        attachments = []
        for attachment in g.db.execute(
                '''SELECT a.id,a.filename,a.stored_path,a.kind,
                   CASE WHEN s.attachment_id IS NULL THEN 'upload' ELSE 'url' END AS source
                   FROM attachment a LEFT JOIN attachment_source s ON s.attachment_id=a.id
                   WHERE a.item_id=? ORDER BY a.filename''', (row['id'],)):
            item = dict(attachment)
            item['bytes'] = on_disk_file_size(
                PRIVATE_ROOT, f"files/{row['id']}/{item.pop('stored_path')}")
            attachments.append(item)
        result.append({'id': row['id'], 'title': row['title'],
                       'description': row['description'], 'search_terms': row['search_terms'],
                       'subject': row['subject'],
                       'cover_url': f"/private/{row['id']}/cover" if row['cover'] else None,
                       'attachments': attachments})
    return jsonify(result)


@app.delete('/api/admin/items/<item_id>')
@admin_required
@csrf_required
def item_delete(item_id):
    if not g.db.execute('SELECT 1 FROM item WHERE id=?', (item_id,)).fetchone():
        abort(404)
    g.db.execute('DELETE FROM item WHERE id=?', (item_id,))
    g.db.commit()
    shutil.rmtree(PRIVATE_ROOT / 'files' / item_id, ignore_errors=True)
    return '', 204


@app.put('/api/admin/items/<item_id>')
@admin_required
@csrf_required
def item_update(item_id):
    body = request.get_json(silent=True) or {}
    title = str(body.get('title', '')).strip()[:200]
    description = str(body.get('description', '')).strip()[:5000]
    search_terms = body.get('search_terms', '')
    subject = str(body.get('subject', ''))
    if not title or subject not in {row[0] for row in get_subjects()}:
        return jsonify(error='Title and a known subject are required'), 400
    if (not isinstance(search_terms, str) or len(search_terms) > 1000 or
            any(ord(char) < 32 and char not in '\t\r\n' for char in search_terms)):
        return jsonify(error='Search terms must be at most 1000 characters of text'), 400
    cursor = g.db.execute('UPDATE item SET title=?,description=?,search_terms=?,subject=? WHERE id=?',
                          (title, description, search_terms.strip(), subject, item_id))
    if not cursor.rowcount:
        abort(404)
    g.db.commit()
    return '', 204


@app.get('/private/<item_id>/<attachment_id>')
@admin_required
def private_file(item_id, attachment_id):
    row = g.db.execute('SELECT * FROM attachment WHERE item_id=? AND id=?', (item_id, attachment_id)).fetchone()
    if not row:
        abort(404)
    path = PRIVATE_ROOT / 'files' / item_id / row['stored_path']
    return send_file(path, as_attachment=True, download_name=row['filename'], conditional=True)


@app.get('/documents/<item_id>/<attachment_id>')
def public_document(item_id, attachment_id):
    row = g.db.execute('SELECT * FROM attachment WHERE item_id=? AND id=?',
                       (item_id, attachment_id)).fetchone()
    if not row:
        abort(404)
    path = PRIVATE_ROOT / 'files' / item_id / row['stored_path']
    if path.is_symlink() or not path.is_file():
        abort(404)
    return send_file(path, as_attachment=Path(row['filename']).suffix.lower() != '.pdf',
                     mimetype='application/pdf' if Path(row['filename']).suffix.lower() == '.pdf' else None,
                     download_name=row['filename'], conditional=True)


@app.get('/private/<item_id>/cover')
@admin_required
def private_cover(item_id):
    row = g.db.execute('SELECT cover FROM item WHERE id=?', (item_id,)).fetchone()
    if not row or not row['cover']:
        abort(404)
    path = PRIVATE_ROOT / 'files' / item_id / row['cover']
    if path.is_symlink() or not path.is_file():
        abort(404)
    return send_file(path, mimetype=IMAGE_MIMES.get(path.suffix.lower()), conditional=True)


@app.get('/documents/<item_id>/cover')
def public_cover(item_id):
    row = g.db.execute('SELECT cover FROM item WHERE id=?', (item_id,)).fetchone()
    if not row or not row['cover']:
        abort(404)
    path = PRIVATE_ROOT / 'files' / item_id / row['cover']
    if path.is_symlink() or not path.is_file():
        abort(404)
    return send_file(path, mimetype=IMAGE_MIMES.get(path.suffix.lower()), conditional=True)


@app.get('/private/<item_id>/<attachment_id>/html/<path:relative>')
@admin_required
def private_html(item_id, attachment_id, relative):
    row = g.db.execute('SELECT * FROM attachment WHERE item_id=? AND id=? AND kind=?',
                       (item_id, attachment_id, 'html-zip')).fetchone()
    if not row:
        abort(404)
    root = (PRIVATE_ROOT / 'files' / item_id / (row['stored_path'] + '.html')).resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        abort(404)
    response = make_response(send_file(target, conditional=True))
    response.headers['Content-Security-Policy'] = "sandbox allow-scripts; default-src 'self' data: blob:; connect-src 'none'; form-action 'none'; base-uri 'none'; object-src 'none'; frame-ancestors 'self'"
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    return response


@app.get('/documents/<item_id>/<attachment_id>/html/<path:relative>')
def public_html(item_id, attachment_id, relative):
    row = g.db.execute('SELECT * FROM attachment WHERE item_id=? AND id=? AND kind=?',
                       (item_id, attachment_id, 'html-zip')).fetchone()
    if not row:
        abort(404)
    root = (PRIVATE_ROOT / 'files' / item_id / (row['stored_path'] + '.html')).resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        abort(404)
    response = make_response(send_file(target, conditional=True))
    response.headers['Content-Security-Policy'] = "sandbox allow-scripts; default-src 'self' data: blob:; connect-src 'none'; form-action 'none'; base-uri 'none'; object-src 'none'; frame-ancestors 'self'"
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    return response


@app.get('/private/<item_id>/<attachment_id>/viewer')
@admin_required
def private_html_viewer(item_id, attachment_id):
    row = g.db.execute('SELECT stored_path FROM attachment WHERE item_id=? AND id=? AND kind=?',
                       (item_id, attachment_id, 'html-zip')).fetchone()
    if not row:
        abort(404)
    root = PRIVATE_ROOT / 'files' / item_id / (row['stored_path'] + '.html')
    entry = 'index.html' if (root / 'index.html').is_file() else 'index.htm'
    response = make_response(render_template('html-viewer.html',
                                             src=url_for('private_html', item_id=item_id,
                                                         attachment_id=attachment_id, relative=entry)))
    response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'none'; frame-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'"
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    return response


@app.get('/documents/<item_id>/<attachment_id>/viewer')
def public_html_viewer(item_id, attachment_id):
    row = g.db.execute('SELECT stored_path FROM attachment WHERE item_id=? AND id=? AND kind=?',
                       (item_id, attachment_id, 'html-zip')).fetchone()
    if not row:
        abort(404)
    root = PRIVATE_ROOT / 'files' / item_id / (row['stored_path'] + '.html')
    entry = 'index.html' if (root / 'index.html').is_file() else 'index.htm'
    response = make_response(render_template('html-viewer.html',
                                             src=url_for('public_html', item_id=item_id,
                                                         attachment_id=attachment_id, relative=entry)))
    response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'none'; frame-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'"
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    return response


def helper(action, payload=None):
    result = subprocess.run(['sudo', '-n', '/usr/local/lib/cyberdeck/admin-helper.py', action],
                            input=json.dumps(payload or {}), text=True, capture_output=True, timeout=30)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or 'Privileged operation failed')
    return json.loads(result.stdout or '{}')


def restart_kiwix():
    """Restart only the Kiwix reader process through the active runtime adapter."""
    if os.environ.get('CYBERDECK_RUNTIME_MODE') == 'container':
        return subprocess.run(['/usr/bin/supervisorctl', '-c', '/etc/supervisor/supervisord.conf',
                               'restart', 'kiwix'], check=False, capture_output=True,
                              text=True, timeout=30)
    return subprocess.run(['sudo', '-n', '/usr/bin/systemctl', 'restart', 'cyberdeck-kiwix.service'],
                          check=False, capture_output=True, text=True, timeout=30)


@app.get('/api/admin/modules')
@admin_required
def admin_module_status():
    return jsonify(hotspot_available=capability_available('hotspot'),
                   hotspot_enabled=hotspot_module_enabled())


@app.put('/api/admin/modules')
@admin_required
@csrf_required
def admin_module_update():
    if not capability_available('hotspot'):
        abort(404)
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or type(body.get('hotspot_enabled')) is not bool:
        return jsonify(error='Hotspot enabled must be true or false'), 400
    enabled = body['hotspot_enabled']
    try:
        helper('hotspot-module-enable' if enabled else 'hotspot-module-disable')
        g.db.execute('INSERT INTO site_setting(key,value) VALUES(?,?) '
                     'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                     ('hotspot_module_enabled', 'true' if enabled else 'false'))
        g.db.commit()
    except (RuntimeError, OSError, subprocess.SubprocessError, sqlite3.Error) as error:
        g.db.rollback()
        return jsonify(error=str(error) or 'Could not change the Hotspot module'), 503
    return jsonify(hotspot_enabled=enabled)


@app.get('/api/admin/hotspot')
@admin_required
def hotspot_status():
    if not capability_available('hotspot') or not hotspot_module_enabled():
        abort(404)
    try:
        response = jsonify(helper('hotspot-status'))
        response.headers['Cache-Control'] = 'no-store'
        return response
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        return jsonify(error=str(error)), 503


@app.get('/api/admin/hostname')
@admin_required
def hostname_status():
    if not capability_available('hostname'):
        abort(404)
    try:
        response = jsonify(helper('hostname-status'))
        response.headers['Cache-Control'] = 'no-store'
        return response
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        return jsonify(error=str(error)), 503


@app.post('/api/admin/hostname')
@admin_required
@csrf_required
def hostname_configure():
    if not capability_available('hostname'):
        abort(404)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error='Expected a hostname and confirmation'), 400
    hostname = body.get('hostname')
    if (not isinstance(hostname, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,61}[a-z0-9]|[a-z]', hostname)
            or hostname in {'localhost', 'localhost-localdomain'} or body.get('confirm') != hostname):
        return jsonify(error='Confirm a valid hostname: lowercase letters, digits and hyphens, starting with a letter.'), 400
    if g.db.execute("SELECT 1 FROM zim WHERE status LIKE 'pid:%' OR status='downloading' LIMIT 1").fetchone():
        return jsonify(error='Pause active downloads before changing the hostname.'), 409
    try:
        return jsonify(helper('hostname-configure', {'hostname': hostname, 'confirm': hostname})), 202
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        return jsonify(error=str(error)), 503


@app.get('/api/admin/hotspot/password')
@admin_required
def hotspot_password():
    if not capability_available('hotspot') or not hotspot_module_enabled():
        abort(404)
    try:
        response = jsonify(helper('hotspot-password'))
        response.headers['Cache-Control'] = 'no-store'
        return response
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        return jsonify(error=str(error)), 503


@app.post('/api/admin/hotspot')
@admin_required
@csrf_required
def hotspot_configure():
    if not capability_available('hotspot') or not hotspot_module_enabled():
        abort(404)
    body = request.get_json(silent=True) or {}
    action = body.get('action')
    try:
        if action == 'configure':
            result = helper('hotspot-configure', {'ssid': str(body.get('ssid', '')),
                                                    'password': str(body.get('password', '')),
                                                    'device': str(body.get('device', '')),
                                                    'upstream_ssids': body.get('upstream_ssids', []),
                                                    'redundancy_minutes': body.get('redundancy_minutes', 60),
                                                    'autostart': body.get('autostart') is True})
        elif action in {'start', 'stop'}:
            result = helper('hotspot-' + action)
        else:
            return jsonify(error='Unknown hotspot action'), 400
        return jsonify(result)
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        return jsonify(error=str(error)), 503


@app.post('/api/admin/power')
@admin_required
@csrf_required
def power_request():
    if not capability_available('power'):
        abort(404)
    body = request.get_json(silent=True) or {}
    action = body.get('action')
    if action not in {'reboot', 'poweroff'} or body.get('confirm') != action.upper():
        return jsonify(error='Confirmation must match the requested action'), 400
    try:
        if os.environ.get('CYBERDECK_RUNTIME_MODE', 'debian').lower() in {'debian', 'headless'}:
            command = '/usr/bin/systemctl'
            result = subprocess.run(['sudo', '-n', command, action], capture_output=True,
                                    text=True, timeout=30, check=False)
            if result.returncode:
                raise RuntimeError(result.stderr.strip() or 'Power operation failed')
            return jsonify(result='sent')
        return jsonify(helper('power-' + action))
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        return jsonify(error=str(error)), 503


def pdf_import_paths(request_id):
    if not isinstance(request_id, str) or not re.fullmatch(r'[a-f0-9]{32}', request_id):
        abort(404)
    return (library.safe_path(PRIVATE_ROOT, f'requests/import-pdfs-{request_id}.json'),
            library.safe_path(PRIVATE_ROOT, f'requests/import-pdfs-{request_id}.status.json'),
            library.safe_path(PRIVATE_ROOT, f'logs/import-pdfs-{request_id}.log'))


def pdf_import_removed_path(request_id, file_index):
    pdf_import_paths(request_id)  # Validate the request id before composing a marker path.
    if type(file_index) is not int or file_index < 0:
        raise ValueError('Invalid PDF import file index')
    return library.safe_path(PRIVATE_ROOT,
                             f'requests/import-pdfs-{request_id}-{file_index}.removed')


def read_pdf_import_status(request_id):
    _manifest, status_path, _log = pdf_import_paths(request_id)
    if status_path.is_symlink() or not status_path.is_file():
        raise FileNotFoundError('PDF import status is unavailable')
    status = json.loads(status_path.read_text(encoding='utf-8'))
    if (not isinstance(status, dict) or status.get('id') != request_id or
            not isinstance(status.get('files'), list)):
        raise ValueError('PDF import status is invalid')
    valid_states = {'queued', 'downloading', 'downloaded', 'failed', 'canceled', 'removed'}
    for item in status['files']:
        if (not isinstance(item, dict) or not isinstance(item.get('path'), str) or
                not isinstance(item.get('title'), str) or item.get('status') not in valid_states or
                not isinstance(item.get('error', ''), str) or
                not isinstance(item.get('subject', ''), str) or
                (item.get('expected_bytes') is not None and
                 (type(item['expected_bytes']) is not int or item['expected_bytes'] <= 0))):
            raise ValueError('PDF import status contains an invalid file record')
    return status


def refresh_pdf_import_liveness(status):
    changed = False
    for index, item in enumerate(status['files']):
        try:
            removed = pdf_import_removed_path(status['id'], index)
            if removed.exists() and item.get('status') != 'removed':
                item['status'], item['error'] = 'removed', ''
                changed = True
        except (OSError, ValueError):
            pass
        try:
            partial = library.safe_path(DATA_ROOT, item['path'] + '.part')
            item['received_bytes'] = partial.stat().st_size if partial.is_file() else 0
        except (OSError, ValueError):
            item['received_bytes'] = 0
    active = [item for item in status['files']
              if item.get('status') in {'queued', 'downloading'}]
    if not active:
        if changed:
            _manifest, status_path, _log = pdf_import_paths(status['id'])
            library.write_json(status_path, status)
        return status
    pid = status.get('worker_pid')
    alive = isinstance(pid, int) and not isinstance(pid, bool) and pid > 0
    if alive:
        try:
            os.kill(pid, 0)
        except PermissionError:
            pass
        except OSError:
            alive = False
    if alive:
        if changed:
            _manifest, status_path, _log = pdf_import_paths(status['id'])
            library.write_json(status_path, status)
        return status
    for item in active:
        item['status'] = 'failed'
        item['error'] = 'Download worker stopped before this file completed; retry is available.'
        item['updated_at'] = time.time()
    status['updated_at'] = time.time()
    _manifest, status_path, _log = pdf_import_paths(status['id'])
    library.write_json(status_path, status)
    return status


def start_pdf_import_worker(request_id):
    manifest_path, status_path, log_path = pdf_import_paths(request_id)
    if (not manifest_path.is_file() or status_path.is_symlink() or not status_path.is_file() or
            log_path.is_symlink()):
        raise FileNotFoundError('PDF import request is unavailable')
    with log_path.open('a', encoding='utf-8') as log:
        worker = subprocess.Popen([sys.executable, str(APP_DIR / 'webapp.py'),
                                   'fetch-import-pdfs', '--request-id', request_id],
                                  stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    status = read_pdf_import_status(request_id)
    status['worker_pid'] = worker.pid
    status['updated_at'] = time.time()
    try:
        library.write_json(status_path, status)
    except (OSError, ValueError):
        worker.terminate()
        raise


@app.get('/api/admin/import/pdf')
@admin_required
def admin_pdf_imports():
    requests_root = PRIVATE_ROOT / 'requests'
    if requests_root.is_symlink():
        return jsonify(error='PDF import status storage is unsafe'), 503
    if not requests_root.is_dir():
        return jsonify(imports=[])
    imports = []
    candidates = []
    for status_path in requests_root.glob('import-pdfs-*.status.json'):
        try:
            if status_path.is_symlink():
                continue
            candidates.append((status_path.lstat().st_mtime, status_path))
        except OSError:
            continue
    for _modified, status_path in sorted(candidates, key=lambda candidate: candidate[0], reverse=True):
        match = re.fullmatch(r'import-pdfs-([a-f0-9]{32})\.status\.json', status_path.name)
        if status_path.is_symlink() or not match:
            continue
        try:
            imports.append(refresh_pdf_import_liveness(read_pdf_import_status(match.group(1))))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if len(imports) >= 20:
            break
    return jsonify(imports=imports)


@app.get('/api/admin/import/pdf/<request_id>')
@admin_required
def admin_pdf_import_status(request_id):
    try:
        return jsonify(refresh_pdf_import_liveness(read_pdf_import_status(request_id)))
    except FileNotFoundError:
        abort(404)
    except (OSError, ValueError, json.JSONDecodeError):
        return jsonify(error='PDF import status is invalid'), 503


@app.post('/api/admin/import/pdf/<request_id>/retry')
@admin_required
@csrf_required
def admin_pdf_import_retry(request_id):
    try:
        status = read_pdf_import_status(request_id)
        if any(item.get('status') in {'queued', 'downloading'} for item in status['files']):
            return jsonify(error='Wait for this PDF import to finish before retrying'), 409
        failed = [item for item in status['files'] if item.get('status') == 'failed']
        if not failed:
            return jsonify(error='This import has no failed PDF downloads'), 409
        original = json.loads(json.dumps(status))
        for item in failed:
            item['status'], item['error'] = 'queued', ''
        status['updated_at'] = time.time()
        _manifest, status_path, _log = pdf_import_paths(request_id)
        library.write_json(status_path, status)
        try:
            start_pdf_import_worker(request_id)
        except (OSError, ValueError, subprocess.SubprocessError):
            library.write_json(status_path, original)
            raise
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return jsonify(error=str(error) or 'Could not retry PDF downloads'), 503
    return jsonify(status=status)


@app.post('/api/admin/import/pdf/<request_id>/files/<int:file_index>/retry')
@admin_required
@csrf_required
def admin_pdf_import_file_retry(request_id, file_index):
    try:
        status = read_pdf_import_status(request_id)
        if any(item.get('status') in {'queued', 'downloading'} for item in status['files']):
            return jsonify(error='Wait for active PDF downloads to finish before retrying one file'), 409
        if file_index >= len(status['files']):
            abort(404)
        item = status['files'][file_index]
        if item.get('status') not in {'failed', 'canceled'}:
            return jsonify(error='This PDF is not available to retry'), 409
        original = json.loads(json.dumps(status))
        item['status'], item['error'] = 'queued', ''
        status['updated_at'] = time.time()
        _manifest, status_path, _log = pdf_import_paths(request_id)
        library.write_json(status_path, status)
        try:
            start_pdf_import_worker(request_id)
        except (OSError, ValueError, subprocess.SubprocessError):
            library.write_json(status_path, original)
            raise
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return jsonify(error=str(error) or 'Could not retry this PDF download'), 503
    return jsonify(status=status)


@app.post('/api/admin/import/pdf/<request_id>/files/<int:file_index>/cancel')
@app.post('/api/admin/import/pdf/<request_id>/files/<int:file_index>/remove')
@admin_required
@csrf_required
def admin_pdf_import_file_remove(request_id, file_index):
    try:
        status = read_pdf_import_status(request_id)
        if file_index >= len(status['files']):
            abort(404)
        item = status['files'][file_index]
        if item.get('status') in {'downloaded', 'removed'}:
            return jsonify(error='This PDF is no longer an import-only document'), 409
        was_downloading = item.get('status') == 'downloading'
        removed_marker = pdf_import_removed_path(request_id, file_index)
        if removed_marker.is_symlink():
            return jsonify(error='Refusing a PDF removal marker symlink'), 409
        try:
            removed_marker.touch(exist_ok=True)
        except OSError as error:
            return jsonify(error=str(error) or 'Could not remove this PDF import'), 503
        item['status'], item['error'] = 'removed', ''
        item['updated_at'] = time.time()
        status['updated_at'] = time.time()
        _manifest, status_path, _log = pdf_import_paths(request_id)
        library.write_json(status_path, status)
        if not was_downloading:
            partial = library.safe_path(DATA_ROOT, item['path'] + '.part')
            partial.unlink(missing_ok=True)
            partial.with_name(partial.name + '.json').unlink(missing_ok=True)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return jsonify(error=str(error) or 'Could not cancel this PDF download'), 503
    return jsonify(status=status)


def fetch_import_pdfs(request_id):
    """Wait for active ZIM fetches, then acquire imported online PDFs safely."""
    manifest, status_path, _log_path = pdf_import_paths(request_id)

    def report(path, state, error):
        status = read_pdf_import_status(request_id)
        for index, item in enumerate(status['files']):
            if item.get('path') == path:
                removed = pdf_import_removed_path(request_id, index).exists()
                if (item.get('status') == 'removed' or removed) and state != 'downloaded':
                    return
                item['status'], item['error'] = state, error[:500]
                item['updated_at'] = time.time()
                break
        status['updated_at'] = time.time()
        library.write_json(status_path, status)

    def is_canceled(path):
        status = read_pdf_import_status(request_id)
        for index, item in enumerate(status['files']):
            if item.get('path') == path:
                return (item.get('status') == 'removed' or
                        pdf_import_removed_path(request_id, index).exists())
        return False

    while True:
        with closing(connect_db()) as db:
            active = [dict(row) for row in db.execute(
                "SELECT id,status FROM zim WHERE status LIKE 'pid:%'").fetchall()]
        if not any(zim_worker_alive(row['status'][4:], row['id']) for row in active):
            break
        time.sleep(2)
    # A publisher can reject one PDF (for example with HTTP 403). Keep
    # acquiring the other independently selected documents and leave failures
    # visible in this import's private log for a later retry.
    library.fetch(DATA_ROOT, manifest, missing_only=True, continue_on_error=True,
                  status_callback=report, cancel_check=is_canceled)


def create_admin(username, password):
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', username) or len(password) < 14:
        raise ValueError('Use a simple username and a password of at least 14 characters')
    with connect_db() as db:
        if db.execute('SELECT 1 FROM admin LIMIT 1').fetchone():
            raise ValueError('An administrator already exists; password reset is an offline operation')
        db.execute('INSERT INTO admin(username,password_hash) VALUES(?,?)',
                   (username, generate_password_hash(password)))


def build_cli():
    cli = argparse.ArgumentParser()
    commands = cli.add_subparsers(dest='command', required=True)
    admin = commands.add_parser('create-admin')
    admin.add_argument('username')
    worker = commands.add_parser('fetch-zim')
    worker.add_argument('zim_id')
    pdf_worker = commands.add_parser('fetch-import-pdfs')
    pdf_worker.add_argument('--request-id', required=True)
    return cli


if __name__ == '__main__':
    cli = build_cli()
    args = cli.parse_args()
    try:
        if args.command == 'create-admin':
            create_admin(args.username, __import__('getpass').getpass('New admin password: '))
            print('Admin account created.')
        elif args.command == 'fetch-zim':
            fetch_zim_worker(args.zim_id)
        else:
            fetch_import_pdfs(args.request_id)
    except (OSError, ValueError, sqlite3.IntegrityError) as error:
        cli.exit(1, f'ERROR: {error}\n')
