"""The question harness (SPEC.md 6.1): the same frozen questions and logistic layer for every
system that answers questions, so only the answering model differs.

`answer(case) -> {question key: P(yes)}` is supplied per model (Grayson, Jev, or an LLM).
"""

import numpy as np
from sklearn.linear_model import LogisticRegression

from kybbench import load_json

QUESTIONS = load_json("questions/v1.json")
ISSUE_KEYS = list(QUESTIONS["issues"])
GENERAL_KEYS = list(QUESTIONS["general"])
ALL_QUESTIONS = {**QUESTIONS["issues"], **QUESTIONS["general"]}


def _logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


class QuestionSystem:
    """Fit on validation answers, then predict from answers. Never fit on test."""

    def __init__(self, answer):
        self.answer = answer
        self.layer = None

    def fit(self, val_answers, val_bad):
        X = _logit([[a[k] for k in ALL_QUESTIONS] for a in val_answers])
        self.layer = LogisticRegression(C=1.0, max_iter=1000).fit(X, np.asarray(val_bad, dtype=int))
        return self

    def from_answers(self, case_id, answers):
        score = float(self.layer.predict_proba(_logit([[answers[k] for k in ALL_QUESTIONS]]))[0, 1])
        return {"case_id": case_id, "score": score, "issues": {k: float(answers[k]) for k in ISSUE_KEYS}}

    def predict(self, case):
        return self.from_answers(case["case_id"], self.answer(case))
