"""Provider-neutral model calls for prompt and workflow modes.

A model is named "provider:model", e.g. "anthropic:claude-opus-5-5", "openai:gpt-6-luna",
"gemini:gemini-3.8-flash", "openrouter:qwen/qwen3.8-max", "deepseek:deepseek-v4-flash".
Anthropic uses its own SDK; every other provider here exposes an OpenAI-compatible chat API.

`complete_json(model, system, user, schema)` returns the parsed JSON object and records the
call's tokens and latency in the current trace.
"""

import json
import os
import threading
import time

from kybbench import harness

# OpenAI-compatible providers: base URL and the environment variable holding the key
OPENAI_COMPATIBLE = {
    "openai": (None, "OPENAI_API_KEY"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "deepseek": ("https://api.deepseek.com", "DEEPSEEK_API_KEY"),
    "moonshot": ("https://api.moonshot.ai/v1", "MOONSHOT_API_KEY"),
    "zai": ("https://api.z.ai/api/paas/v4", "ZAI_API_KEY"),
}
_clients = {}
# On OpenRouter, send each model to its maker's own service (no fallback to resellers), and opt out
# of providers that train on prompts. The provider that answered is recorded in the trace.
OPENROUTER_FIRST_PARTY = {"anthropic/": "Anthropic", "openai/": "OpenAI", "google/": "Google AI Studio"}


# Per-model request pacing: OpenRouter limits new accounts to 20 requests a minute per premium model
RPM = float(os.environ.get("KYB_RPM", "18"))
_pace_lock, _next_slot = threading.Lock(), {}


def _pace(model_id):
    with _pace_lock:
        now = time.monotonic()
        slot = max(_next_slot.get(model_id, now), now)
        _next_slot[model_id] = slot + 60 / RPM
    time.sleep(max(0.0, slot - time.monotonic()))


class Refused(RuntimeError):
    pass


def parse(model):
    provider, _, name = model.partition(":")
    if not name:  # bare Claude model IDs stay accepted
        provider, name = "anthropic", provider
    if provider != "anthropic" and provider not in OPENAI_COMPATIBLE:
        raise ValueError(f"unknown provider {provider!r}")
    return provider, name


def _client(provider):
    if provider not in _clients:
        if provider == "anthropic":
            import anthropic
            _clients[provider] = anthropic.Anthropic(max_retries=4)
        else:
            import openai
            base_url, key_env = OPENAI_COMPATIBLE[provider]
            _clients[provider] = openai.OpenAI(base_url=base_url, api_key=os.environ[key_env], max_retries=4)
    return _clients[provider]


def complete_json(model, system, user, schema, name="answer"):
    provider, model_id = parse(model)
    start = time.monotonic()
    if provider == "anthropic":
        resp = _client(provider).messages.create(
            model=model_id, max_tokens=16000, system=system, messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema", "schema": schema}})
        harness.llm_call(model_id, resp.usage.input_tokens, resp.usage.output_tokens, (time.monotonic() - start) * 1000)
        if resp.stop_reason == "refusal":
            raise Refused(getattr(resp.stop_details, "category", None))
        return json.loads(next(b.text for b in resp.content if b.type == "text"))

    _pace(model_id)
    extra = {}
    if provider == "openrouter":
        routing = {"data_collection": "deny", "require_parameters": True}
        maker = next((v for k, v in OPENROUTER_FIRST_PARTY.items() if model_id.startswith(k)), None)
        if maker:
            routing.update(order=[maker], allow_fallbacks=False)
        extra = {"extra_body": {"provider": routing}}
    resp = _client(provider).chat.completions.create(
        model=model_id, max_completion_tokens=16000,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format={"type": "json_schema", "json_schema": {"name": name, "schema": schema, "strict": True}}, **extra)
    usage = resp.usage
    harness.llm_call(model_id, usage.prompt_tokens if usage else 0, usage.completion_tokens if usage else 0,
                     (time.monotonic() - start) * 1000)
    served_by = getattr(resp, "provider", None) or (resp.model_extra or {}).get("provider")
    if served_by:
        harness._spans.get()[-1]["provider"] = served_by
    msg = resp.choices[0].message
    if getattr(msg, "refusal", None):
        raise Refused(msg.refusal)
    return json.loads(msg.content)
