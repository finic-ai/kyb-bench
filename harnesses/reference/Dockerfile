# Reference harness: minimal provider-neutral tool loop (Anthropic or any OpenAI-compatible API).
FROM kybbench-base

USER root
RUN /opt/kyb/venv/bin/pip install --no-cache-dir "anthropic>=2.3,<3" "openai>=3.40,<4"
COPY agent.py /opt/harness/agent.py
RUN chmod -R a-w /opt/harness
USER agent
ENTRYPOINT ["/opt/kyb/venv/bin/python", "/opt/harness/agent.py"]
