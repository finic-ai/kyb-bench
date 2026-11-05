"""Grading (SPEC.md section 5).

Every system is turned into decisions the same way: two thresholds on its score, chosen on the
validation split to minimise expected cost, then applied unchanged to test. Below the lower
threshold is approve, at or above the upper is decline, in between is review.
"""

import numpy as np

from kybbench import cost_matrix, issue_catalogue

DECISIONS = ("approve", "review", "decline")


def _cost_table(costs=None):
    costs = costs or cost_matrix()
    # rows: decision (approve, review, decline); columns: truth (good, review, bad)
    return np.array([[costs[d][t] for t in ("good", "review", "bad")] for d in DECISIONS], dtype=float)


def _truth_index(labels):
    order = {"good": 0, "review": 1, "bad": 2}
    return np.array([order[l] for l in labels])


def decide(scores, thresholds):
    lo, hi = thresholds
    scores = np.asarray(scores, dtype=float)
    return np.where(scores >= hi, 2, np.where(scores >= lo, 1, 0))


def expected_cost(scores, labels, thresholds, costs=None):
    """Mean cost per application, in the cost matrix's currency."""
    table = _cost_table(costs)
    return float(table[decide(scores, thresholds), _truth_index(labels)].mean())


def prevalence_weights(labels, target):
    """Per-case weights that make the label mix match `target` ({good, review, bad} shares), so
    thresholds fitted on a split rich in bad cases behave as at a realistic rate."""
    labels = list(labels)
    share = {k: labels.count(k) / len(labels) for k in target}
    return np.array([target[l] / share[l] if share[l] else 0.0 for l in labels])


def choose_thresholds(scores, labels, costs=None, grid=201, weights=None):
    """The (lower, upper) pair minimising expected cost on these cases. Use validation only.
    `weights` (one per case) reweights the cost, e.g. prevalence_weights for a realistic mix."""
    scores = np.asarray(scores, dtype=float)
    table = _cost_table(costs)
    truth = _truth_index(labels)
    w = np.ones(len(scores)) if weights is None else np.asarray(weights, dtype=float)
    cands = np.unique(np.concatenate([[0.0, 1.0 + 1e-9], np.quantile(scores, np.linspace(0, 1, grid))]))
    # cost of each decision for every case, then prefix sums over cases sorted by score
    order = np.argsort(scores)
    s, per = scores[order], (table[:, truth[order]] * w[order]).T  # per: n x 3, weighted
    cum = np.vstack([np.zeros(3), np.cumsum(per, axis=0)])
    idx = np.searchsorted(s, cands, side="left")  # cases with score < cand
    best, best_pair = np.inf, (cands[0], cands[-1])
    for i, lo in enumerate(cands):
        a = cum[idx[i], 0]
        j = np.arange(i, len(cands))
        review = cum[idx[j], 1] - cum[idx[i], 1]
        decline = cum[-1, 2] - cum[idx[j], 2]
        total = a + review + decline
        k = int(np.argmin(total))
        if total[k] < best:
            best, best_pair = total[k], (float(lo), float(cands[j[k]]))
    return best_pair


def average_precision(y, scores):
    y, scores = np.asarray(y, dtype=bool), np.asarray(scores, dtype=float)
    if not y.any():
        return float("nan")
    order = np.argsort(-scores, kind="mergesort")
    hits = y[order]
    precision = np.cumsum(hits) / np.arange(1, len(hits) + 1)
    return float(precision[hits].mean())


def roc_auc(y, scores):
    y, scores = np.asarray(y, dtype=bool), np.asarray(scores, dtype=float)
    pos, neg = scores[y], scores[~y]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    ranks = _rankdata(np.concatenate([pos, neg]))
    return float((ranks[: len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def _rankdata(x):
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(len(x))
    ranks[order] = np.arange(1, len(x) + 1)
    # average ranks over ties
    _, inv, counts = np.unique(x, return_inverse=True, return_counts=True)
    sums = np.bincount(inv, weights=ranks)
    return sums[inv] / counts[inv]


def recall_at_fpr(y, scores, fpr=0.01):
    y, scores = np.asarray(y, dtype=bool), np.asarray(scores, dtype=float)
    if not y.any() or y.all():
        return float("nan")
    cut = np.quantile(scores[~y], 1 - fpr, method="higher")
    return float((scores[y] > cut).mean())


def calibration_error(y, scores, bins=10):
    """Expected calibration error with equal-width bins."""
    y, scores = np.asarray(y, dtype=float), np.asarray(scores, dtype=float)
    which = np.minimum((scores * bins).astype(int), bins - 1)
    err = 0.0
    for b in range(bins):
        m = which == b
        if m.any():
            err += m.mean() * abs(scores[m].mean() - y[m].mean())
    return float(err)


def issue_metrics(pred_issues, true_issues, cutoff=0.5):
    """Per-issue precision and recall, and macro F1, over planted-issue cases.

    pred_issues: list of {code: probability}; true_issues: list of sets of codes.
    """
    out = {}
    f1s = []
    for code in issue_catalogue():
        p = np.array([d[code] >= cutoff for d in pred_issues])
        t = np.array([code in s for s in true_issues])
        tp = int((p & t).sum())
        precision = tp / p.sum() if p.sum() else float("nan")
        recall = tp / t.sum() if t.sum() else float("nan")
        f1 = 2 * precision * recall / (precision + recall) if tp else 0.0
        if t.sum():
            f1s.append(f1)
        out[code] = {"precision": precision, "recall": recall, "f1": f1, "support": int(t.sum())}
    out["macro_f1"] = float(np.mean(f1s)) if f1s else float("nan")
    return out


def flip_rate(original_scores, perturbed_scores, thresholds):
    """Share of perturbed cases whose decision differs from the original case's decision."""
    return float((decide(original_scores, thresholds) != decide(perturbed_scores, thresholds)).mean())


def bootstrap(metric, *arrays, n=1000, seed=0):
    """95% interval for metric(*arrays), resampling cases with replacement."""
    rng = np.random.default_rng(seed)
    arrays = [np.asarray(a) for a in arrays]
    size = len(arrays[0])
    stats = []
    for _ in range(n):
        i = rng.integers(0, size, size)
        v = metric(*(a[i] for a in arrays))
        if not np.isnan(v):
            stats.append(v)
    if not stats:
        return (float("nan"), float("nan"))
    return tuple(float(q) for q in np.quantile(stats, [0.025, 0.975]))


def evaluate(labels, preds, thresholds, n_boot=1000):
    """Score one system on one split.

    labels: {case_id: {"decision": ..., "issues": [...], "slice": ...}}
    preds:  {case_id: prediction}
    thresholds: chosen on validation with choose_thresholds.
    """
    missing = set(labels) - set(preds)
    if missing:
        raise ValueError(f"{len(missing)} cases have no prediction")
    ids = sorted(labels)
    truth = np.array([labels[i]["decision"] for i in ids])
    scores = np.array([preds[i]["score"] for i in ids], dtype=float)
    bad = truth == "bad"

    def cost(t, s):
        return expected_cost(s, t, thresholds)

    result = {
        "n": len(ids),
        "thresholds": list(thresholds),
        "expected_cost": cost(truth, scores),
        "expected_cost_ci": bootstrap(cost, truth, scores, n=n_boot),
        "pr_auc": average_precision(bad, scores),
        "pr_auc_ci": bootstrap(average_precision, bad, scores, n=n_boot),
        "recall_at_1pct_fpr": recall_at_fpr(bad, scores),
        "roc_auc": roc_auc(bad, scores),
        "calibration_error": calibration_error(bad, scores),
        "reference": {
            "approve_all": expected_cost(np.zeros(len(ids)), truth, (0.5, 1.0)),
            "review_all": expected_cost(np.full(len(ids), 0.5), truth, (0.0, 1.0 + 1e-9)),
        },
    }
    planted = [i for i in ids if labels[i].get("slice") == "planted" and preds[i].get("issues")]
    if planted:
        result["issues"] = issue_metrics([preds[i]["issues"] for i in planted],
                                         [set(labels[i].get("issues", [])) for i in planted])
    return result
