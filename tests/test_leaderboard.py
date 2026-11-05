from kybbench import leaderboard


def _labels():
    out = {}
    for i in range(30):
        out[f"g{i}"] = {"decision": "good", "channel": "none", "issues": []}
    for i in range(12):
        out[f"b{i}"] = {"decision": "bad", "channel": "planted", "issues": ["X"]}
    out["p0"] = {"decision": "review", "channel": "industry", "issues": [], "pending": "labels"}
    return out


def test_pack_roundtrip():
    labels = _labels()
    packed = leaderboard.unpack(leaderboard.pack(labels))
    assert packed.keys() == labels.keys() and packed["b0"] == {"d": "bad", "c": "planted", "i": ["X"], "p": False}


def test_perfect_and_malformed():
    labels = leaderboard.unpack(leaderboard.pack(_labels()))
    perfect = {c: {"decision": "decline" if c[0] == "b" else "approve", "score": 1.0 if c[0] == "b" else 0.0} for c in labels}
    m = leaderboard.score(labels, perfect)
    assert m["accuracy"] == 1.0 and m["pr_auc"] == 1.0 and m["n_scored"] == 42
    assert set(m["by_group"]) == {"none", "planted"}  # pending cases are not scored
    broken = dict(perfect, b0={"decision": "maybe"}, b1={"decision": "decline", "score": "x"}, g0={"score": 2})
    m = leaderboard.score(labels, broken)
    assert m["bad_declined"] == round(10 / 12, 3) and m["good_wrongly_stopped"] == round(1 / 30, 3)
