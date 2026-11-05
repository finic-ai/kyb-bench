"""The reference workflow (SPEC.md 6.1): frozen typed questions plus the policy as code.

Any system that answers the questions plugs in through `answer(case) -> answers`, where answers
maps each question to a probability (noul) or {"choice": option, "probabilities": {...}} (choice).
`decide(answers)` applies data/policy/v1.md and returns the prediction.
"""

from kybbench import issue_catalogue, load_json

QUESTIONS = load_json("workflows/v1/questions.json")["questions"]
INDUSTRIES = load_json("workflows/v1/industries.json")
CUT = 0.5


def questions():
    """Questions with choice criteria resolved, in the decide API's shape."""
    out = {}
    for key, q in QUESTIONS.items():
        q = dict(q)
        if q.get("criteria") == "industries.json":
            q["criteria"] = INDUSTRIES
        out[key] = q
    return out


def _choice(a):
    """(top option, probability distribution) from a choice answer."""
    probs = a.get("probabilities") or {a["choice"]: a.get("confidence", 1.0)}
    return max(probs, key=probs.get), probs


def decide(case_id, answers, decline_cut=CUT, review_cut=CUT):
    """Apply the policy to the answers. The cut-offs default to 0.5 (the reference workflow); the
    tuned track fits them per system on the validation split."""
    catalogue = issue_catalogue()
    industry, ind_probs = _choice(answers["industry"])
    activity, act_probs = _choice(answers["regulated_activity"])
    p_unlicensed = (1 - act_probs.get("none", 0.0)) * (1 - answers["licence_held"])
    if activity != "none" and answers["licence_held"] < decline_cut:
        industry = "P_UNLICENSED_GAMBLING" if activity == "gambling" else "P_UNLICENSED_FINANCIAL"
    tier = industry[0]

    issues = {code: float(answers[code]) for code in catalogue}
    decline_p = [sum(p for c, p in ind_probs.items() if c.startswith("P_")), p_unlicensed,
                 answers["fake_front"], answers["adverse_media"] * answers["adverse_media_own_conduct"]]
    decline_p += [p for c, p in issues.items() if catalogue[c]["decision"] == "bad"]
    review_hit = (tier == "H" or answers["pep_match"] >= review_cut or answers["adverse_media"] >= review_cut
                  or any(p >= review_cut for c, p in issues.items() if catalogue[c]["decision"] == "review"))

    score = 1.0
    for p in decline_p:
        score *= 1 - min(max(p, 0.0), 1.0)
    score = 1 - score

    if tier == "P" or any(p >= decline_cut for p in decline_p):
        decision, rating = "decline", "prohibited"
    elif review_hit:
        decision, rating = "review", "high"
    else:
        decision, rating = "approve", {"M": "medium", "L": "low"}.get(tier, "high")
    return {"case_id": case_id, "score": round(score, 4), "decision": decision, "industry": industry,
            "risk_rating": rating, "issues": issues}


def predict_with(answer):
    """Turn a question-answering function into a predict(case) function. The raw answers are kept
    in the prediction so cut-offs can be refitted later without rerunning the system."""
    def predict(case):
        answers = answer(case)
        return {**decide(case["case_id"], answers), "answers": answers}
    return predict
