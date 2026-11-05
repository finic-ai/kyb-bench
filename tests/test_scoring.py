import numpy as np
import pytest

from kybbench import harness, issue_catalogue, scoring
from kybbench.plant import clean_application, plant
from kybbench.schema import check_prediction


def _data(n=3000, seed=0):
    rng = np.random.default_rng(seed)
    labels = rng.choice(["good", "review", "bad"], size=n, p=[0.9, 0.07, 0.03])
    base = {"good": 0.1, "review": 0.4, "bad": 0.7}
    scores = np.clip([base[l] + rng.normal(0, 0.15) for l in labels], 0, 1)
    return labels, scores


def test_thresholds_beat_reference_policies():
    labels, scores = _data()
    t = scoring.choose_thresholds(scores, labels)
    assert t[0] <= t[1]
    cost = scoring.expected_cost(scores, labels, t)
    assert cost < scoring.expected_cost(np.zeros(len(labels)), labels, (0.5, 1.0))
    assert cost < scoring.expected_cost(np.zeros(len(labels)), labels, (0.0, 1.0))  # review everything


def test_thresholds_match_brute_force():
    labels, scores = _data(n=300, seed=1)
    t = scoring.choose_thresholds(scores, labels, grid=21)
    cands = np.unique(np.concatenate([[0.0, 1.0 + 1e-9], np.quantile(scores, np.linspace(0, 1, 21))]))
    brute = min(scoring.expected_cost(scores, labels, (lo, hi)) for lo in cands for hi in cands if hi >= lo)
    assert scoring.expected_cost(scores, labels, t) == pytest.approx(brute)


def test_ranking_metrics():
    y = np.array([0, 0, 1, 1])
    assert scoring.roc_auc(y, [0.1, 0.2, 0.8, 0.9]) == 1.0
    assert scoring.roc_auc(y, [0.5, 0.5, 0.5, 0.5]) == 0.5
    assert scoring.average_precision(y, [0.1, 0.2, 0.8, 0.9]) == 1.0
    assert scoring.calibration_error([0, 1], [0.0, 1.0]) == 0.0


def test_evaluate_end_to_end():
    labels, scores = _data()
    ids = [f"c{i}" for i in range(len(labels))]
    lab = {i: {"decision": l, "slice": "real"} for i, l in zip(ids, labels)}
    preds = {i: {"case_id": i, "score": float(s)} for i, s in zip(ids, scores)}
    t = scoring.choose_thresholds(scores, labels)
    out = scoring.evaluate(lab, preds, t, n_boot=50)
    assert out["expected_cost_ci"][0] <= out["expected_cost"] <= out["expected_cost_ci"][1]
    assert out["pr_auc"] > 0.5


def test_flip_rate():
    assert scoring.flip_rate([0.1, 0.9], [0.1, 0.1], (0.3, 0.6)) == 0.5


def _case():
    case = {
        "case_id": "kyb-1", "as_of": "2024-03-14", "jurisdiction": "GB",
        "registry": {"company_number": "01234567", "name": "Acme Ltd", "registered_address": {"postal_code": "AB1 2CD"},
                     "sic_codes": ["62020"],
                     "officers": [{"name": "SMITH, Jane", "role": "director"}],
                     "psc": [{"name": "Ms Jane Smith"}]},
        "web": {"url": "acme.example", "text": "We build software.", "domain_created": "2019-01-01"},
        "documents": [], "sanctions": {"matches": []},
    }
    case["application"] = clean_application(case)
    return case


def test_planting_labels_follow_catalogue():
    rng = np.random.default_rng(0)
    pool = {"names": ["DOE, John"], "disqualified": ["BLOGGS, Fred"], "sanctioned": ["Ivan X"],
            "sites": ["Copied text"], "industries": ["62020", "64999"]}
    case = _case()
    planted, label = plant(case, ["NEW_DOMAIN"], pool, rng)
    assert label == {"decision": "review", "issues": ["NEW_DOMAIN"], "slice": "planted"}
    assert planted["web"]["domain_created"] > "2024-02-14"
    assert case["web"]["domain_created"] == "2019-01-01"  # original untouched
    planted, label = plant(case, ["ACTIVITY_MISMATCH", "OWNER_MISMATCH"], pool, rng)
    assert label["decision"] == "bad"
    assert planted["application"]["stated_industry"] == "64999"


def test_harness_records_traces(tmp_path):
    codes = list(issue_catalogue())

    def predict(case):
        harness.llm_call("m", 100, 10, 5)
        return {"case_id": case["case_id"], "score": 0.2, "issues": {c: 0.0 for c in codes}}

    cases = [{"case_id": "a"}, {"case_id": "b"}]
    system = {"name": "t", "version": "1", "type": "llm", "mode": "direct"}
    preds, traces = harness.run(predict, cases, system, tmp_path)
    rows = [__import__("json").loads(l) for l in traces.read_text().splitlines()]
    assert [r["totals"]["input_tokens"] for r in rows] == [100, 100]
    assert not check_prediction({"case_id": "a", "score": 0.2, "issues": {c: 0.0 for c in codes}})
    # rerun resumes and does not duplicate
    harness.run(predict, cases, system, tmp_path)
    assert len(preds.read_text().splitlines()) == 2
