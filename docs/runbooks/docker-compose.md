# Docker Compose deployment

This deployment runs the Cyberdeck Hub web app, Kiwix, and Caddy as separate
containers. The Hub and Kiwix containers are not published directly to the
host. Caddy provides HTTPS with a local certificate authority (CA); each client
must trust that CA before using the Hub. Docker mode does not manage host Wi-Fi,
firewall, power, hostname, or storage devices.

## Prepare the host

Install Docker Engine with the Compose plugin on a Linux host. Ensure ports 80
and 443 are available. Configure local DNS (or the clients' hosts files) so the
name in `CYBERDECK_HOSTNAME` resolves to this Docker host. The default is
`cyberdeck.local`; Docker Compose does not publish `.local` names through mDNS.
The pinned ZIM validator supports `linux/amd64` and `linux/arm64` builds.

From the repository checkout, create a private `.env` file and set a unique
session secret:

```sh
cp .env.example .env
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Paste the generated value after `CYBERDECK_SESSION_KEY=` in `.env`. Keep this
file private and retain the same value across container recreations; changing
it signs out existing sessions. Set `CYBERDECK_HOSTNAME` to the configured
local DNS name if you are not using the default.

## Start the stack

Build and start the services:

```sh
docker compose up --build -d
docker compose ps
```

Compose creates named volumes for public library content, private metadata,
Caddy state, and a public-only copy of Caddy's root certificate. An isolated
exporter has read-only access to Caddy state and copies the public certificate
to the separate volume used by Hub's trust page. The Hub never mounts Caddy's
CA volume or private signing keys. The Hub image runs as an unprivileged user.
Kiwix receives the public content volume read-only; the Hub updates a shared
index after verified ZIM downloads or removals, and Kiwix reloads that index
automatically.

## Trust Caddy's local CA

On each client, open `http://cyberdeck.local/help/certificate` (replace the
hostname if configured differently). That page and the CA download are
available over HTTP for certificate bootstrap; other HTTP requests redirect to
HTTPS. Compare the page's SHA-256 fingerprint with a value obtained through a
trusted channel before installing the downloaded root certificate. To inspect
the certificate directly on the Docker host:

```sh
docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt ./caddy-root.crt
openssl x509 -noout -fingerprint -sha256 -in ./caddy-root.crt
```

Install the certificate as a trusted root CA on each client, then open
`https://cyberdeck.local/setup` and create the administrator account. See the
[certificate trust guide](../certificate-trust.md) for device-specific steps
and removal instructions.

## Data and addons

The `hub_data` volume stores acquired public documents and ZIM files;
`hub_private` stores the database, credentials, and private uploads. `caddy_data`
contains Caddy's CA and private signing material; `caddy_ca` contains only the
public root certificate. Back up all five named volumes before replacing or
removing them. Do not distribute `caddy_data` or the `.env` file.

The `cyberdeck` network is shared by the services and can be extended with
separate addon containers and Caddy routes. This stack does not install or
integrate CyberChef, FlatNotes, or other addons. Container mode intentionally
does not expose Debian host controls.

To stop without deleting persistent data:

```sh
docker compose down
```

Do not add `--volumes` unless you intend to erase the persistent Hub data and
Caddy CA.
