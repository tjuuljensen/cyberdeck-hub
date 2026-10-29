FROM ghcr.io/kiwix/kiwix-tools:3.8.2
COPY --chmod=755 docker/kiwix-entrypoint.sh /usr/local/bin/cyberdeck-kiwix-entrypoint
ENTRYPOINT ["/usr/local/bin/cyberdeck-kiwix-entrypoint"]
