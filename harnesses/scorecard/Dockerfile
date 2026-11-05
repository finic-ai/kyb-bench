# Rules scorecard harness: the no-model baseline, run in the same locked-down container as any
# agent. Built from the repo root (see harness.json "context"); .dockerignore keeps secrets,
# labels and caches out of the image.
FROM kybbench-base

USER root
RUN /opt/kyb/venv/bin/pip install --no-cache-dir "requests>=2.31"
COPY kybbench /opt/kybbench/kybbench
COPY data/issue_catalogue.json data/cost_matrix.json /opt/kybbench/data/
COPY workflows /opt/kybbench/workflows
COPY harnesses/scorecard/run.py /opt/harness/run.py
RUN chmod -R a-w /opt/kybbench /opt/harness
USER agent
ENTRYPOINT ["/opt/kyb/venv/bin/python", "/opt/harness/run.py"]
