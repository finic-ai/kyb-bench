"""LLMs in prompt and workflow modes (SPEC.md 6.1, 6.2), for any provider in kybbench.models.

Agent mode runs in containers through a harness (harnesses/, scripts/run_container.py).

Refusal fallbacks are deliberately not enabled: a fallback would let a different model answer
for the one being benchmarked. A refusal is recorded and scored as a failed case.
"""

import json

from kybbench import ROOT, issue_catalogue, models, workflow

MODEL = "anthropic:claude-opus-5-5"
POLICY = (ROOT / "data/policy/v1.md").read_text()

INSTRUCTIONS = """You are a KYB analyst at a business account provider. Apply the onboarding policy
below to the case and return your assessment. Issue values and the score are probabilities
between 0 and 1. The issue codes mean:
{issues}

<policy>
{policy}
</policy>"""

AGENT_INSTRUCTIONS = """

You start with the application only. Use the tools to check it against the registry, screening,
licence registers, web search and the website, then call submit with your assessment."""


def system_prompt():
    issues = "\n".join(f"- {c}: {v['description']}" for c, v in issue_catalogue().items())
    return INSTRUCTIONS.format(issues=issues, policy=POLICY)


def prediction_schema():
    codes = list(issue_catalogue())
    return {
        "type": "object",
        "properties": {
            "score": {"type": "number", "description": "Probability the business should not be onboarded, 0 to 1"},
            "decision": {"type": "string", "enum": ["approve", "review", "decline"]},
            "industry": {"type": "string", "enum": list(workflow.INDUSTRIES)},
            "risk_rating": {"type": "string", "enum": ["prohibited", "high", "medium", "low"]},
            "issues": {"type": "object", "properties": {c: {"type": "number"} for c in codes},
                       "required": codes, "additionalProperties": False},
        },
        "required": ["score", "decision", "industry", "risk_rating", "issues"],
        "additionalProperties": False,
    }


def _case_message(case):
    return f"<case>\n{json.dumps(case)}\n</case>"


def prompt_mode(model=MODEL):
    def predict(case):
        out = models.complete_json(model, system_prompt(), _case_message(case), prediction_schema(), "assessment")
        return {"case_id": case["case_id"], **out}
    return predict


def answers_schema():
    props = {}
    for key, q in workflow.questions().items():
        if q["type"] == "noul":
            props[key] = {"type": "number", "description": q["instructions"]}
        else:
            props[key] = {"type": "object", "description": q["instructions"],
                          "properties": {"choice": {"type": "string", "enum": list(q["criteria"])},
                                         "confidence": {"type": "number"}},
                          "required": ["choice", "confidence"], "additionalProperties": False}
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


WORKFLOW_INSTRUCTIONS = """Answer each question about the KYB case. For yes/no questions give the
probability that the answer is yes, between 0 and 1. For choice questions pick one option and give
your confidence. Answer only from the case. The options for each choice question are:
{options}"""


def workflow_answer(model=MODEL):
    opts = "\n".join(f"{k}: " + "; ".join(f"{c} = {d}" for c, d in q["criteria"].items())
                     for k, q in workflow.questions().items() if q["type"] == "choice")

    def answer(case):
        out = models.complete_json(model, WORKFLOW_INSTRUCTIONS.format(options=opts), _case_message(case),
                                   answers_schema(), "answers")
        for k, q in workflow.questions().items():
            if q["type"] == "choice":
                out[k] = {"choice": out[k]["choice"], "probabilities": {out[k]["choice"]: out[k]["confidence"]}}
        return out
    return answer
