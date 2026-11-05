# Harnesses

A harness is anything that takes a case and produces a prediction: Claude Code, Codex,
OpenHands, an in-house agent, a workflow engine. Any model can run inside any harness. Each
harness is a folder here with three files:

| File | What it is |
|---|---|
| `Dockerfile` | `FROM kybbench-base`, plus whatever the harness needs |
| `harness.json` | Name, image name, the hosts it may reach (its model provider's API), the environment variables it needs for auth, and a default model |
| entry script | Reads the case, runs the agent with `$KYB_MODEL`, ends by calling `submit` |

The base image (`docker/base/`) provides the contract every harness uses:

- `/case/case.json`: the case, read-only. Labels never enter the container.
- KYB tools, as an MCP server (`/opt/kyb/mcp.json`) or a CLI (`kyb-tool <tool> '<json args>'`).
- `/opt/kyb/instructions.md`: the task and policy text.
- `/out/prediction.json`: written by `submit`. A harness may also write `/out/trace.json`
  (`model`, `turns`, `input_tokens`, `output_tokens`, `cost_usd`, `duration_ms`).

The runner (`scripts/run_container.py`) starts a fresh container per case on a network whose
only exit is a proxy that allows the hosts in `harness.json` and nothing else, with a read-only
filesystem, no Linux capabilities and resource limits. Grading happens outside the container.

```bash
.venv/bin/python scripts/run_container.py build --harness claude-code
.venv/bin/python scripts/run_container.py check --harness claude-code
.venv/bin/python scripts/run_container.py run   --harness claude-code --model claude-haiku-5-5 --limit 10
```

To add a harness, copy `claude-code/`, change the three files, and run `check` before `run`.
