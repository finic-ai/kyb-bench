"""Checks for the three files every run exchanges: cases, predictions and traces (SPEC.md 3, 5.1, 7).

Deliberately dependency-free. Each check returns a list of problems; an empty list means valid.
"""

from kybbench import issue_catalogue

CASE_SECTIONS = ["case_id", "as_of", "jurisdiction", "application", "registry", "web", "documents",
                 "screening", "licences", "search"]
LABELS = ("good", "review", "bad")
SYSTEM_TYPES = ("decision_model", "classical", "llm")
MODES = ("direct", "questions", "trained")
SPAN_TYPES = ("llm_call", "tool_call", "model_infer", "other")


def check_case(case):
    problems = [f"missing {k}" for k in CASE_SECTIONS if k not in case]
    j = case.get("jurisdiction", "")
    if j and j != "GB" and not j.startswith("US-"):
        problems.append(f"jurisdiction {j!r} is not GB or US-<state>")
    return problems


def check_label(label):
    problems = []
    if label.get("decision") not in LABELS:
        problems.append(f"decision must be one of {LABELS}")
    unknown = set(label.get("issues", [])) - set(issue_catalogue())
    if unknown:
        problems.append(f"unknown issue codes {sorted(unknown)}")
    return problems


def check_prediction(pred):
    problems = []
    if "case_id" not in pred:
        problems.append("missing case_id")
    s = pred.get("score")
    if not isinstance(s, (int, float)) or not 0 <= s <= 1:
        problems.append("score must be a number in [0, 1]")
    issues = pred.get("issues")
    if issues is not None:
        codes = set(issue_catalogue())
        if set(issues) != codes:
            problems.append("issues must give a probability for every catalogue code, or be omitted")
        elif any(not isinstance(p, (int, float)) or not 0 <= p <= 1 for p in issues.values()):
            problems.append("issue probabilities must be numbers in [0, 1]")
    return problems


def check_trace(trace):
    problems = [f"missing {k}" for k in ("case_id", "run_id", "system", "spans", "totals") if k not in trace]
    system = trace.get("system", {})
    if system.get("type") not in SYSTEM_TYPES:
        problems.append(f"system.type must be one of {SYSTEM_TYPES}")
    if system.get("mode") not in MODES:
        problems.append(f"system.mode must be one of {MODES}")
    for i, span in enumerate(trace.get("spans", [])):
        if span.get("type") not in SPAN_TYPES:
            problems.append(f"spans[{i}].type must be one of {SPAN_TYPES}")
    return problems
