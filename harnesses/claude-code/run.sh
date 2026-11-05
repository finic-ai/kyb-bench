#!/bin/sh
# Claude Code harness: one headless session for /case/case.json. Built-in tools are disabled;
# only the KYB MCP tools are allowed. The model is $KYB_MODEL.
set -eu

python3 -c 'import json; c = json.load(open("/case/case.json")); print("Case date: " + c["as_of"] + "\n\nApplication:\n" + json.dumps(c["application"], indent=1))' \
  | claude -p \
      --model "$KYB_MODEL" \
      --max-turns "${KYB_MAX_TURNS:-30}" \
      --tools "" \
      --mcp-config /opt/kyb/mcp.json --strict-mcp-config \
      --allowedTools "mcp__kyb__registry_lookup,mcp__kyb__screen,mcp__kyb__licence_lookup,mcp__kyb__web_search,mcp__kyb__fetch_website,mcp__kyb__submit" \
      --setting-sources "" \
      --disable-slash-commands \
      --no-session-persistence \
      --append-system-prompt-file /opt/kyb/instructions.md \
      --output-format json \
  > /out/claude.json || true

# Normalise Claude Code's usage report into the harness-neutral trace file
python3 - <<'EOF'
import json, os
try:
    cc = json.load(open("/out/claude.json"))
except Exception:
    cc = {}
u = cc.get("usage") or {}
json.dump({"model": os.environ["KYB_MODEL"], "turns": cc.get("num_turns"), "duration_ms": cc.get("duration_ms"),
           "input_tokens": sum(u.get(k, 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")),
           "output_tokens": u.get("output_tokens", 0), "cost_usd": cc.get("total_cost_usd"),
           "error": cc.get("result") if cc.get("is_error") else None}, open("/out/trace.json", "w"))
EOF
