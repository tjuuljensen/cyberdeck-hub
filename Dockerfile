FROM python:3.13-slim-trixie

ARG TARGETARCH

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CYBERDECK_RUNTIME_MODE=container \
    CYBERDECK_ROOT=/srv/cyberdeck \
    CYBERDECK_PRIVATE=/srv/cyberdeck-private \
    CYBERDECK_STARTER_MANIFEST=/usr/local/lib/cyberdeck/starter.json \
    CYBERDECK_CONFIG_PROFILES=/usr/local/lib/cyberdeck/profiles \
    TZ=Etc/UTC

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 cyberdeck \
    && useradd --uid 10001 --gid 10001 --home-dir /nonexistent --shell /usr/sbin/nologin cyberdeck \
    && install -d -o 10001 -g 10001 /srv/cyberdeck /srv/cyberdeck-private /usr/local/lib/cyberdeck/tools \
    && case "$TARGETARCH" in \
         amd64) validator_archive=zim-tools_linux-x86_64-3.8.0.tar.gz ;; \
         arm64) validator_archive=zim-tools_linux-aarch64-3.7.0.tar.gz ;; \
         *) echo "No pinned zimcheck build for Docker architecture: $TARGETARCH" >&2; exit 1 ;; \
       esac \
    && validator_url="https://download.openzim.org/release/zim-tools/$validator_archive" \
    && mkdir -p /tmp/zimcheck/unpacked \
    && curl --proto '=https' --proto-redir '=https' --fail --location "$validator_url" -o "/tmp/zimcheck/$validator_archive" \
    && curl --proto '=https' --proto-redir '=https' --fail --location "$validator_url.md5" -o "/tmp/zimcheck/$validator_archive.md5" \
    && (cd /tmp/zimcheck && md5sum --check "$validator_archive.md5") \
    && python -c "import pathlib,sys,tarfile; members=tarfile.open(sys.argv[1], 'r:gz').getmembers(); sys.exit(any(member.name.startswith('/') or '..' in pathlib.PurePosixPath(member.name).parts for member in members))" "/tmp/zimcheck/$validator_archive" \
    && tar --no-same-owner --no-same-permissions -xzf "/tmp/zimcheck/$validator_archive" -C /tmp/zimcheck/unpacked \
    && test "$(find /tmp/zimcheck/unpacked -type f -name zimcheck | wc -l)" -eq 1 \
    && validator_path=$(find /tmp/zimcheck/unpacked -type f -name zimcheck -print -quit) \
    && test -n "$validator_path" \
    && install -o root -g root -m 0755 "$validator_path" /usr/local/lib/cyberdeck/tools/zimcheck \
    && /usr/local/lib/cyberdeck/tools/zimcheck --version \
    && rm -rf /tmp/zimcheck

WORKDIR /usr/local/lib/cyberdeck/app
COPY requirements-container.txt /tmp/requirements-container.txt
RUN pip install --no-cache-dir --disable-pip-version-check -r /tmp/requirements-container.txt \
    && rm /tmp/requirements-container.txt

COPY --chown=10001:10001 app/ ./
COPY LICENSE /usr/local/share/licenses/cyberdeck-hub/LICENSE
COPY --chown=10001:10001 config/debian/starter.json /usr/local/lib/cyberdeck/starter.json
COPY --chown=10001:10001 config/debian/profiles/ /usr/local/lib/cyberdeck/profiles/
COPY --chown=10001:10001 --chmod=755 docker/hub-entrypoint.sh /usr/local/bin/cyberdeck-hub-entrypoint

USER 10001:10001
EXPOSE 8000
VOLUME ["/srv/cyberdeck", "/srv/cyberdeck-private"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)" || exit 1
ENTRYPOINT ["/usr/local/bin/cyberdeck-hub-entrypoint"]
CMD ["gunicorn", "--workers", "2", "--worker-class", "gthread", "--threads", "4", "--bind", "0.0.0.0:8000", "webapp:app"]
