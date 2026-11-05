"""Reference harness: a minimal, provider-neutral tool-calling loop over the KYB tools.

The fixed harness used for model-to-model comparisons in agent mode. KYB_MODEL is
"provider:model" (anthropic, or any OpenAI-compatible provider in PROVIDERS).
"""

import json
import os
import sys
import time

sys.path.insert(0, "/opt/kyb")
import kyb_mcp  # noqa: E402  (loads /case/case.json)

MAX_TURNS = int(os.environ.get("KYB_MAX_TURNS", "30"))
PROVIDERS = {  # OpenAI-compatible: base URL, key variable
    "openai": (None, "OPENAI_API_KEY"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "deepseek": ("https://api.deepseek.com", "DEEPSEEK_API_KEY"),
    "moonshot": ("https://api.moonshot.ai/v1", "MOONSHOT_API_KEY"),
    "zai": ("https://api.z.ai/api/paas/v4", "ZAI_API_KEY"),
}
ISSUES = ["OWNER_MISMATCH", "DIRECTOR_MISMATCH", "DISQUALIFIED_DIRECTOR", "STATUS_MISMATCH", "SANCTIONS_HIT",
          "CLONED_WEBSITE", "ADDRESS_MASS_REG", "ADDRESS_REJECTED", "NEW_DOMAIN", "ACTIVITY_MISMATCH",
          "VOLUME_IMPLAUSIBLE"]


def _obj(props, required=None):
    return {"type": "object", "properties": props, "required": list(props) if required is None else required,
            "additionalProperties": False}


TOOLS = [
    ("registry_lookup", kyb_mcp.registry_lookup.__doc__,
     _obj({"section": {"type": "string", "enum": ["profile", "officers", "ownership", "filings"]}})),
    ("screen", kyb_mcp.screen.__doc__,
     _obj({"kind": {"type": "string", "enum": ["sanctions", "pep", "disqualified"]}, "name": {"type": "string"}})),
    ("licence_lookup", kyb_mcp.licence_lookup.__doc__, _obj({})),
    ("web_search", kyb_mcp.web_search.__doc__, _obj({})),
    ("fetch_website", kyb_mcp.fetch_website.__doc__, _obj({})),
    ("submit", kyb_mcp.submit.__doc__, _obj({
        "score": {"type": "number"},
        "decision": {"type": "string", "enum": ["approve", "review", "decline"]},
        "industry": {"type": "string"},
        "risk_rating": {"type": "string", "enum": ["prohibited", "high", "medium", "low"]},
        "issues": _obj({c: {"type": "number"} for c in ISSUES})})),
]
FUNCS = {**kyb_mcp.TOOLS, "submit": kyb_mcp.submit}


def call_tool(name, args):
    try:
        return FUNCS[name](**args), False
    except Exception as e:
        return f"Error: {e}", True


def first_message():
    c = kyb_mcp.CASE
    return f"Case date: {c['as_of']}\n\nApplication:\n{json.dumps(c['application'], indent=1)}"


def run_anthropic(model, system, usage):
    import anthropic
    client = anthropic.Anthropic(max_retries=4)
    tools = [{"name": n, "description": d, "input_schema": s, "strict": True} for n, d, s in TOOLS]
    messages = [{"role": "user", "content": first_message()}]
    for turn in range(MAX_TURNS):
        resp = client.messages.create(model=model, max_tokens=16000, system=system, tools=tools, messages=messages)
        usage["turns"] += 1
        usage["input_tokens"] += resp.usage.input_tokens
        usage["output_tokens"] += resp.usage.output_tokens
        if resp.stop_reason == "refusal":
            raise RuntimeError("refusal")
        messages.append({"role": "assistant", "content": resp.content})
        calls = [b for b in resp.content if b.type == "tool_use"]
        if not calls:
            messages.append({"role": "user", "content": "Call submit with your assessment."})
            continue
        results = []
        for b in calls:
            out, err = call_tool(b.name, b.input)
            usage["tool_calls"] += 1
            if b.name == "submit" and not err:
                return
            results.append({"type": "tool_result", "tool_use_id": b.id, "content": out, "is_error": err})
        messages.append({"role": "user", "content": results})


def run_openai_compatible(provider, model, system, usage):
    import openai
    base_url, key_env = PROVIDERS[provider]
    client = openai.OpenAI(base_url=base_url, api_key=os.environ[key_env], max_retries=4)
    tools = [{"type": "function", "function": {"name": n, "description": d, "parameters": s, "strict": True}}
             for n, d, s in TOOLS]
    messages = [{"role": "system", "content": system}, {"role": "user", "content": first_message()}]
    for turn in range(MAX_TURNS):
        resp = client.chat.completions.create(model=model, max_completion_tokens=16000, messages=messages, tools=tools)
        usage["turns"] += 1
        if resp.usage:
            usage["input_tokens"] += resp.usage.prompt_tokens
            usage["output_tokens"] += resp.usage.completion_tokens
        msg = resp.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))
        if not msg.tool_calls:
            messages.append({"role": "user", "content": "Call submit with your assessment."})
            continue
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
                out, err = call_tool(tc.function.name, args)
            except json.JSONDecodeError as e:
                out, err = f"Error: invalid JSON arguments: {e}", True
            usage["tool_calls"] += 1
            if tc.function.name == "submit" and not err:
                return
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": out})


def main():
    provider, _, model = os.environ["KYB_MODEL"].partition(":")
    system = open("/opt/kyb/instructions.md").read()
    usage = {"turns": 0, "tool_calls": 0, "input_tokens": 0, "output_tokens": 0}
    start, error = time.monotonic(), None
    try:
        if provider == "anthropic":
            run_anthropic(model, system, usage)
        elif provider in PROVIDERS:
            run_openai_compatible(provider, model, system, usage)
        else:
            raise ValueError(f"unknown provider {provider!r}")
    except Exception as e:
        error = f"{type(e).__name__}: {e}"[:400]
    with open("/out/trace.json", "w") as f:
        json.dump({"model": model, "duration_ms": int((time.monotonic() - start) * 1000), "cost_usd": None,
                   "error": error, **usage}, f)


if __name__ == "__main__":
    main()
