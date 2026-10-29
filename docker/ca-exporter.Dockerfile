FROM alpine:3.22
RUN install -d -m 0755 /public-ca
COPY --chmod=755 docker/ca-exporter.sh /usr/local/bin/ca-exporter
ENTRYPOINT ["/usr/local/bin/ca-exporter"]
