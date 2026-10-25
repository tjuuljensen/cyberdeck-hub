FROM debian:trixie-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    CYBERDECK_RUNTIME_MODE=container \
    CYBERDECK_ROOT=/srv/cyberdeck \
    CYBERDECK_PRIVATE=/srv/cyberdeck/private \
    CYBERDECK_STARTER_MANIFEST=/opt/cyberdeck/starter.json \
    CYBERDECK_HOSTNAME=cyberdeck.local

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates openssl python3 python3-flask python3-gunicorn kiwix-tools supervisor \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system cyberdeck \
    && useradd --system --gid cyberdeck --home-dir /nonexistent --no-create-home \
         --shell /usr/sbin/nologin cyberdeck

WORKDIR /opt/cyberdeck/app
COPY app/webapp.py app/library.py app/kiwix_https.py ./
COPY app/serve-kiwix.sh /usr/local/bin/serve-cyberdeck-kiwix
COPY app/static ./static
COPY app/templates ./templates
COPY app/translations ./translations
COPY config/debian/starter.json /opt/cyberdeck/starter.json
COPY entrypoint.sh /usr/local/bin/cyberdeck-entrypoint
COPY supervisord.conf /etc/supervisor/supervisord.conf
RUN chmod 0755 /usr/local/bin/serve-cyberdeck-kiwix /usr/local/bin/cyberdeck-entrypoint \
    && mkdir -p /srv/cyberdeck/zim /srv/cyberdeck/public /srv/cyberdeck/private \
    && chown cyberdeck:cyberdeck /srv/cyberdeck /srv/cyberdeck/zim \
         /srv/cyberdeck/public /srv/cyberdeck/private

EXPOSE 8081
VOLUME ["/srv/cyberdeck"]
ENTRYPOINT ["/usr/local/bin/cyberdeck-entrypoint"]
