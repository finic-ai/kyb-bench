# Egress proxy for agent containers. Agent containers sit on an internal Docker network with no
# route out; this proxy is the only thing on both networks, and it only forwards HTTPS to the
# hosts in `allow`.
FROM alpine:3.20
RUN apk add --no-cache tinyproxy
COPY tinyproxy.conf /etc/tinyproxy/tinyproxy.conf
COPY allow /etc/tinyproxy/allow
USER nobody
EXPOSE 8888
ENTRYPOINT ["tinyproxy", "-d", "-c", "/etc/tinyproxy/tinyproxy.conf"]
