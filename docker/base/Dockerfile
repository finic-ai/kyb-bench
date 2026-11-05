# KYB-Bench base image: the harness-neutral part of every agent container.
#
# Contract for any harness built FROM this image:
#   /case/case.json        the one case, mounted read-only (never its label)
#   /opt/kyb/instructions.md   the task and policy text
#   /opt/kyb/mcp.json      MCP config for the KYB tool server (stdio)
#   /opt/kyb/bin/kyb-tool  the same tools as a CLI, for harnesses without MCP
#   /out/prediction.json   written by the `submit` tool; the harness may also write /out/trace.json
#   KYB_MODEL              the model to use, passed by the runner
# The container has no network except an egress proxy that allows only the hosts the harness
# declares in harness.json.
FROM python:3.12-slim-bookworm

RUN python -m venv /opt/kyb/venv && /opt/kyb/venv/bin/pip install --no-cache-dir "mcp>=1.2,<2"
COPY kyb_mcp.py mcp.json instructions.md /opt/kyb/
RUN mkdir -p /opt/kyb/bin \
 && printf '#!/bin/sh\nexec /opt/kyb/venv/bin/python /opt/kyb/kyb_mcp.py --cli "$@"\n' > /opt/kyb/bin/kyb-tool \
 && chmod 555 /opt/kyb/bin/kyb-tool && chmod -R a-w /opt/kyb \
 && useradd --create-home --uid 1000 agent

ENV PATH="/opt/kyb/bin:${PATH}"
USER agent
WORKDIR /home/agent
