# Claude Code harness: Claude Code CLI on top of the KYB-Bench base image.
FROM kybbench-base

USER root
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm ca-certificates \
 && rm -rf /var/lib/apt/lists/*
ARG CLAUDE_CODE_VERSION=2.1.312
RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION} && npm cache clean --force
COPY run.sh /opt/harness/run.sh
RUN chmod 555 /opt/harness/run.sh

# No telemetry, error reporting or auto-update traffic
ENV CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 DISABLE_TELEMETRY=1 DISABLE_ERROR_REPORTING=1 DISABLE_AUTOUPDATER=1
USER agent
ENTRYPOINT ["/opt/harness/run.sh"]
