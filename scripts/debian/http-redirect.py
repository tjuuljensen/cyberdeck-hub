#!/usr/bin/python3
"""Serve the untrusted certificate setup guide and redirect other HTTP requests."""
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, HTTPServer
import html
import ipaddress
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import urllib.parse

TARGET_HOST = os.environ.get('CYBERDECK_HOSTNAME', 'cyberdeck.local').strip().lower()
CA_FILE = Path(os.environ.get('CYBERDECK_CA_CERT_FILE', '/etc/cyberdeck/tls/ca.crt'))
HOST_RE = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*\Z')

if len(TARGET_HOST) > 253 or not HOST_RE.fullmatch(TARGET_HOST):
    raise ValueError('CYBERDECK_HOSTNAME must be a valid DNS name')

TEXT = {
    'en': {
        'eyebrow': 'CERTIFICATE SETUP',
        'title': 'Set up trusted access',
        'intro': 'Cyberdeck Hub uses a private certificate authority so the library can stay available on your local network and offline.',
        'language': 'Language',
        'addresses_title': 'This Hub on your local network',
        'addresses_copy': 'Share an address below with someone using the same local network. Wired LAN addresses are listed first, followed by Wi-Fi. These addresses can change when the network changes.',
        'addresses_empty': 'No wired LAN or Wi-Fi address is available right now. On the standard Cyberdeck hotspot, this Hub is at 10.42.0.1.',
        'lan_label': 'LAN',
        'wifi_label': 'Wi-Fi',
        'download_title': '1. Get the certificate',
        'download_copy': 'Download the public certificate authority file. Before installing it, ask the library owner to confirm its fingerprint from the server or a device they already trust.',
        'download': 'Download CA certificate',
        'verify_title': '2. Trust it on your device',
        'verify_copy': 'After the library owner confirms the fingerprint, install the certificate as a trusted root certificate on this device.',
        'fingerprint': 'SHA-256 fingerprint',
        'ios': 'iPhone or iPad',
        'ios_steps': ['Download the certificate in Safari and allow the profile download.', 'Open Settings > General > VPN & Device Management and install the downloaded certificate profile.', 'Open Settings > General > About > Certificate Trust Settings. Enable full trust for Cyberdeck Local Library CA.', 'Return to your browser and reopen the library.'],
        'ios_note': 'Installing the profile alone does not enable HTTPS trust. The full-trust step also matters when using Firefox on iPhone.',
        'windows': 'Windows',
        'windows_steps': ['Open the downloaded .cer file and choose Install Certificate.', 'Choose Current User, then Place all certificates in the following store.', 'Choose Trusted Root Certification Authorities and finish the import after checking the certificate.', 'Reopen the library. If Firefox still rejects it, check its certificate settings for trust in installed third-party roots.'],
        'other_devices': 'Other devices and managed browsers',
        'other_copy': 'Use your device or browser certificate settings to import the verified file as a trusted certificate authority (CA). The names and available controls vary. On a managed device, ask its administrator if certificate installation is restricted.',
        'open_title': '3. Open the library',
        'open_copy': 'After installing the certificate, open the secure library address. Your browser should show a trusted connection.',
        'open': 'Open secure library',
        'secure_link': 'Open HTTPS site',
        'trouble': 'If you have trouble opening the .local address over HTTP, try clearing your browser cache.',
        'ip_title': 'If this page will not open',
        'ip_copy': "Ask the library owner for the server's current IP address. On your normal network, open http://SERVER-IP/ in your browser, replacing SERVER-IP with that address. If your browser upgrades this page to HTTPS before the certificate is trusted, use the IP address instead of the server name.",
        'hotspot_title': 'Cyberdeck hotspot IP address',
        'hotspot_copy': 'The Cyberdeck hotspot IP address is 10.42.0.1. Anyone connected to the standard hotspot can open http://10.42.0.1/ to reach this Hub.',
        'footer': 'Cyberdeck Hub · Local library',
        'unavailable': 'The public certificate is not available. Contact the server administrator.',
    },
    'da': {
        'eyebrow': 'CERTIFIKATOPSÆTNING',
        'title': 'Konfigurer betroet adgang',
        'intro': 'Cyberdeck Hub bruger et privat certifikatcenter, så biblioteket kan være tilgængeligt på dit lokale netværk og offline.',
        'language': 'Sprog',
        'addresses_title': 'Denne Hub på dit lokale netværk',
        'addresses_copy': 'Del en af adresserne nedenfor med en person på det samme lokale netværk. Kablede LAN-adresser vises først, derefter Wi-Fi. Adresserne kan ændre sig, når netværket ændres.',
        'addresses_empty': 'Der er ingen kablet LAN- eller Wi-Fi-adresse lige nu. På Cyberdecks standard-hotspot findes denne Hub på 10.42.0.1.',
        'lan_label': 'LAN',
        'wifi_label': 'Wi-Fi',
        'download_title': '1. Hent certifikatet',
        'download_copy': 'Hent det offentlige certifikatcenter. Bed bibliotekets ejer om at bekræfte fingeraftrykket fra serveren eller en enhed, der allerede er betroet, før du installerer det.',
        'download': 'Hent CA-certifikat',
        'verify_title': '2. Stol på certifikatet på din enhed',
        'verify_copy': 'Når bibliotekets ejer har bekræftet fingeraftrykket, skal du installere certifikatet som et betroet rodcertifikat på denne enhed.',
        'fingerprint': 'SHA-256-fingeraftryk',
        'ios': 'iPhone eller iPad',
        'ios_steps': ['Hent certifikatet i Safari, og tillad overførslen af profilen.', 'Åbn Indstillinger > Generelt > VPN og enhedsadministration, og installer den hentede certifikatprofil.', 'Åbn Indstillinger > Generelt > Om > Indstillinger for certifikattillid. Slå fuld tillid til for Cyberdeck Local Library CA.', 'Gå tilbage til browseren, og åbn biblioteket igen.'],
        'ios_note': 'Det er ikke nok at installere profilen for at få HTTPS-tillid. Trinnet med fuld tillid er også nødvendigt, når du bruger Firefox på iPhone.',
        'windows': 'Windows',
        'windows_steps': ['Åbn den hentede .cer-fil, og vælg Installer certifikat.', 'Vælg Aktuel bruger, og vælg derefter Placer alle certifikater i følgende certifikatlager.', 'Vælg Betroede rodcertifikater, kontrollér certifikatet, og afslut importen.', 'Åbn biblioteket igen. Hvis Firefox stadig afviser det, skal du kontrollere, at browseren har tillid til installerede rodcertifikater fra tredjeparter.'],
        'other_devices': 'Andre enheder og administrerede browsere',
        'other_copy': 'Brug enhedens eller browserens certifikatindstillinger til at importere den bekræftede fil som en betroet certifikatudsteder (CA). Navne og valgmuligheder varierer. På en administreret enhed skal du spørge administratoren, hvis installation af certifikater er begrænset.',
        'open_title': '3. Åbn biblioteket',
        'open_copy': 'Åbn bibliotekets sikre adresse, når certifikatet er installeret. Browseren bør nu vise en betroet forbindelse.',
        'open': 'Åbn det sikre bibliotek',
        'secure_link': 'Åbn HTTPS-siden',
        'trouble': 'Hvis du har problemer med at åbne .local-adressen over HTTP, kan du prøve at rydde browserens cache.',
        'ip_title': 'Hvis denne side ikke vil åbne',
        'ip_copy': 'Bed bibliotekets ejer om serverens aktuelle IP-adresse. På dit normale netværk skal du åbne http://SERVER-IP/ i browseren og erstatte SERVER-IP med adressen. Hvis browseren opgraderer siden til HTTPS, før certifikatet er betroet, skal du bruge IP-adressen i stedet for servernavnet.',
        'hotspot_title': 'Cyberdeck-hotspottets IP-adresse',
        'hotspot_copy': 'Cyberdeck-hotspottets IP-adresse er 10.42.0.1. Alle, der er forbundet til standard-hotspottet, kan åbne http://10.42.0.1/ for at få adgang til denne Hub.',
        'footer': 'Cyberdeck Hub · Lokalt bibliotek',
        'unavailable': 'Det offentlige certifikat er ikke tilgængeligt. Kontakt serveradministratoren.',
    },
}

STYLE = """
:root{color-scheme:dark;--bg:#10131b;--panel:#171c27;--panel2:#1c2331;--line:#30394a;--text:#f1f3f7;--muted:#a2adbe;--accent:#c4f36b;--cyan:#83d8d2;--font:Inter,ui-sans-serif,system-ui,-apple-system,'Segoe UI',sans-serif}
*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(ellipse at 75% 0%,#192333 0,transparent 35rem),var(--bg);color:var(--text);font:16px/1.6 var(--font)}a{color:inherit;text-decoration:none}.topbar{min-height:76px;padding:14px max(5vw,24px);display:flex;align-items:center;justify-content:space-between;gap:16px;border-bottom:1px solid #ffffff13;background:#10131bdb}.brand{font-weight:850;letter-spacing:.11em;font-size:15px}.brand span{display:block;color:var(--accent);font-size:9px;letter-spacing:.22em}.header-tools{display:flex;align-items:center;gap:20px}.language{display:flex;align-items:center;gap:8px;font-size:12px}.language a{padding:4px 7px;color:var(--muted);border:1px solid transparent}.language a:hover{color:var(--text);border-color:var(--line)}.language a[aria-current=page]{color:var(--accent);border-color:var(--line)}.badge{color:var(--cyan);font-size:10px;letter-spacing:.15em;font-weight:800}main{width:min(760px,90vw);margin:0 auto;padding:62px 0 48px}.eyebrow{font-size:10px;letter-spacing:.2em;font-weight:800;color:var(--accent);margin:0 0 14px}h1{font-size:clamp(38px,7vw,64px);letter-spacing:-.055em;line-height:1.02;margin:0 0 18px}.lede{color:#bcc5d2;font-size:17px;max-width:680px;line-height:1.65;margin:0 0 30px}.steps{display:grid;gap:12px}.step{background:linear-gradient(145deg,#1a202b,#151a24);border:1px solid var(--line);padding:22px 24px}.step h2{font-size:20px;letter-spacing:-.03em;margin:0 0 7px}.step p{color:var(--muted);font-size:13px;margin:0 0 15px}.button{min-height:45px;padding:10px 17px;border:1px solid #485366;border-radius:4px;color:var(--text);background:#1a202c;font:inherit;font-weight:650;font-size:13px;display:inline-flex;align-items:center;justify-content:center}.button:hover{border-color:var(--accent)}.button.primary{color:#10131b;background:var(--accent);border-color:var(--accent)}.fingerprint{display:block;overflow-wrap:anywhere;padding:12px 14px;background:#0e121a;border:1px solid var(--line);color:var(--text);font:12px/1.7 ui-monospace,SFMono-Regular,Consolas,monospace}.warning{border-left:3px solid var(--accent);padding:10px 13px;background:#1c2331;color:#c7d0dd;font-size:12px}.error{background:#49282a;border:1px solid #934b50;padding:10px 13px;color:#ffd4d0}.step details{border-top:1px solid var(--line);padding-top:12px;margin-top:12px}.step summary{cursor:pointer;color:var(--accent);font-weight:650;font-size:13px}.step li+li{margin-top:8px}.step ol{padding-left:22px;color:var(--muted);font-size:13px}.step .fingerprint{margin:8px 0 12px}.step>p:last-child{margin-bottom:0}footer{border-top:1px solid var(--line);padding:18px max(5vw,24px);color:#8994a4;font-size:11px;letter-spacing:.1em;text-transform:uppercase}@media(max-width:540px){.topbar{min-height:68px;flex-wrap:wrap}.header-tools{gap:8px;flex-wrap:wrap;justify-content:flex-end}.badge{font-size:9px}main{padding:42px 0 36px}.step{padding:18px}}
"""
STYLE += ".addresses{list-style:none;margin:0;padding:0}.addresses li{display:flex;align-items:center;justify-content:space-between;gap:12px;border-top:1px solid var(--line);padding:10px 0}.addresses li span{color:var(--muted);font-size:13px}.addresses code{color:var(--text);overflow-wrap:anywhere;font:14px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace}"
STYLE += ".language-picker{display:flex;align-items:center;gap:8px;margin:0}.language-picker label{display:flex;align-items:center;gap:6px;color:var(--muted);font-size:11px}.language-picker select{background:#1a202c;color:var(--text);border:1px solid #485366;border-radius:3px;padding:5px 7px;font:inherit;font-size:11px}.language-picker select:hover{border-color:var(--accent)}"


def public_certificate():
    certificate_path = Path(os.environ.get('CYBERDECK_CA_CERT_FILE', str(CA_FILE)))
    pem = certificate_path.read_bytes()
    if len(pem) > 65536:
        raise ValueError('Certificate too large')
    der = ssl.PEM_cert_to_DER_cert(pem.decode('ascii'))
    return pem, der


def host_addresses():
    """List assigned IPv4 addresses on wired and Wi-Fi host interfaces, wired first."""
    try:
        result = subprocess.run(
            ['nmcli', '--terse', '--escape', 'no', '--fields', 'DEVICE,TYPE', 'device', 'status'],
            text=True, capture_output=True, timeout=3, check=True,
            env={**os.environ, 'LC_ALL': 'C'},
        )
        kinds = {}
        for line in result.stdout.splitlines():
            name, kind = line.split(':', 1)
            if name and kind == 'ethernet':
                kinds[name] = 'lan'
            elif name and kind == 'wifi':
                kinds[name] = 'wifi'
    except (OSError, subprocess.SubprocessError, ValueError):
        kinds = {}
        for entry in Path('/sys/class/net').glob('*'):
            if entry.name == 'lo':
                continue
            if (entry / 'wireless').exists():
                kinds[entry.name] = 'wifi'
            else:
                try:
                    physical = (entry / 'device').exists()
                    ethernet = (entry / 'type').read_text(encoding='ascii').strip() == '1'
                except OSError:
                    physical = ethernet = False
                if physical and ethernet:
                    kinds[entry.name] = 'lan'
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


def page(language):
    text = TEXT[language]
    host_ip_addresses = host_addresses()
    try:
        _, der = public_certificate()
        fingerprint = ':'.join(f'{byte:02X}' for byte in sha256(der).digest())
        fingerprint_markup = '<code class="fingerprint">' + html.escape(fingerprint) + '</code>'
    except (OSError, ValueError, UnicodeError):
        fingerprint_markup = '<p class="error">' + html.escape(text['unavailable']) + '</p>'
    host = html.escape(TARGET_HOST, quote=True)
    secure_url = 'https://' + host + '/'
    return f'''<!doctype html>
<html lang="{language}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark"><title>{html.escape(text['title'])} · Cyberdeck Hub</title><style>{STYLE}</style><script src="/language.js" defer></script></head>
<body><header class="topbar"><div class="brand">CYBERDECK<span>OFFLINE LIBRARY</span></div><div class="header-tools"><form class="language-picker" action="/" method="get"><label><span>{html.escape(text['language'])}</span><select name="lang" aria-label="{html.escape(text['language'], quote=True)}"><option value="en"{' selected' if language == 'en' else ''}>English</option><option value="da"{' selected' if language == 'da' else ''}>Dansk</option></select></label></form><a class="button primary secure-link" href="{secure_url}">{html.escape(text['secure_link'])}</a><span class="badge">{html.escape(text['eyebrow'])}</span></div></header>
<main><p class="eyebrow">{html.escape(text['eyebrow'])}</p><h1>{html.escape(text['title'])}</h1><p class="lede">{html.escape(text['intro'])}</p>
<section class="step"><h2>{html.escape(text['addresses_title'])}</h2><p>{html.escape(text['addresses_copy'])}</p>{'<ul class="addresses">' + ''.join('<li><span>' + html.escape(text['lan_label'] if item['kind'] == 'lan' else text['wifi_label']) + ' · ' + html.escape(item['device']) + '</span><a href="http://' + html.escape(item['address'], quote=True) + '/"><code>' + html.escape(item['address']) + '</code></a></li>' for item in host_ip_addresses) + '</ul>' if host_ip_addresses else '<p class="warning">' + html.escape(text['addresses_empty']) + '</p>'}</section>
<div class="steps"><section class="step"><h2>{html.escape(text['download_title'])}</h2><p>{html.escape(text['download_copy'])}</p><a class="button primary" href="/trust/ca.cer">{html.escape(text['download'])}</a><details><summary>{html.escape(text['fingerprint'])}</summary>{fingerprint_markup}</details></section>
<section class="step"><h2>{html.escape(text['verify_title'])}</h2><p>{html.escape(text['verify_copy'])}</p>
<details><summary>{html.escape(text['ios'])}</summary><ol>{''.join('<li>' + html.escape(item) + '</li>' for item in text['ios_steps'])}</ol><p>{html.escape(text['ios_note'])}</p></details>
<details><summary>{html.escape(text['windows'])}</summary><ol>{''.join('<li>' + html.escape(item) + '</li>' for item in text['windows_steps'])}</ol></details>
<details><summary>{html.escape(text['other_devices'])}</summary><p>{html.escape(text['other_copy'])}</p></details></section>
<section class="step"><h2>{html.escape(text['open_title'])}</h2><p>{html.escape(text['open_copy'])}</p><a class="button" href="{secure_url}">{html.escape(text['open'])}</a></section>
<p class="warning">{html.escape(text['trouble'])}</p><section class="step"><h2>{html.escape(text['ip_title'])}</h2><p>{html.escape(text['ip_copy'])}</p></section><section class="step"><h2>{html.escape(text['hotspot_title'])}</h2><p>{html.escape(text['hotspot_copy'])}</p></section></div></main><footer>{html.escape(text['footer'])}</footer></body></html>'''


class Redirect(BaseHTTPRequestHandler):
    def do_GET(self):
        self.handle_request(head=False)

    def do_HEAD(self):
        self.handle_request(head=True)

    def handle_request(self, *, head):
        if (not self.path.startswith('/') or self.path.startswith('//') or
                any(ord(character) < 32 or ord(character) == 127 for character in self.path)):
            self.send_error(400, 'Invalid path')
            return
        parsed = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        if parsed.path == '/language.js' and not parsed.query:
            body = (b"document.querySelector('.language-picker select')?.addEventListener('change', event => "
                    b"event.currentTarget.form?.requestSubmit());")
            self.send_response(200)
            self.send_header('Content-Type', 'application/javascript; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            if not head:
                self.wfile.write(body)
            return
        if parsed.path == '/' and (not parsed.query or set(query) == {'lang'}):
            selected = query.get('lang', ['en'])
            language = selected[0] if len(selected) == 1 and selected[0] in TEXT else 'en'
            body = page(language).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
            self.end_headers()
            if not head:
                self.wfile.write(body)
            return
        if parsed.path in {'/trust/ca.cer', '/trust/ca.crt'}:
            try:
                pem, der = public_certificate()
            except (OSError, ValueError, UnicodeError):
                self.send_error(404, 'Library certificate unavailable')
                return
            extension = 'cer' if parsed.path.endswith('.cer') else 'crt'
            data = der if extension == 'cer' else pem
            self.send_response(200)
            self.send_header('Content-Type', 'application/x-x509-ca-cert')
            self.send_header('Content-Disposition', f'attachment; filename="cyberdeck-local-ca.{extension}"')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            if not head:
                self.wfile.write(data)
            return
        target = 'https://' + TARGET_HOST + self.path
        destination = urllib.parse.urlsplit(target)
        if destination.scheme != 'https' or destination.netloc != TARGET_HOST:
            self.send_error(400, 'Invalid redirect target')
            return
        self.send_response(308)
        self.send_header('Location', target)
        self.send_header('Content-Length', '0')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()

    def log_message(self, _format, *_args):
        pass


if __name__ == '__main__':
    HTTPServer(('0.0.0.0', 80), Redirect).serve_forever()
