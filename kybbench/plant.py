"""Planted-issue cases (SPEC.md section 4.2).

Start from a clean case whose application exactly matches the registry, then apply 1–3 planters.
Each planter changes the application (and, where the issue needs it, the web section) and
returns the issue code it planted. Planters never touch registry facts except where the issue is
defined by the company we pick (STATUS_MISMATCH and ADDRESS_MASS_REG are chosen by sampling
companies that have them, not planted).

`pool` supplies realistic replacement material, so planted values look like real ones:
    names:         real person names from other registry records
    disqualified:  names from the disqualified directors register
    sanctioned:    names from sanctions lists
    sites:         website texts from other, unrelated companies
    industries:    industry codes with descriptions
"""

import copy
import datetime as dt

from kybbench import issue_catalogue


def clean_application(case):
    """An application that matches the registry exactly: the starting point for every case."""
    reg = case["registry"]
    return {
        "company_name": reg["name"],
        "company_number": reg["company_number"],
        "registered_address": reg["registered_address"],
        "trading_address": reg["registered_address"],
        "directors": [{"name": o["name"], "dob_month": o.get("dob_month"), "nationality": o.get("nationality")}
                      for o in reg.get("officers") or [] if o.get("role") == "director"],
        "owners": [{"name": p["name"], "share_pct": None} for p in reg.get("psc") or []],
        "website": (case.get("web") or {}).get("url"),
        "stated_industry": (reg.get("sic_codes") or [None])[0],
        "expected_monthly_volume": None,
    }


def owner_mismatch(case, pool, rng):
    if not case["registry"].get("psc"):
        return None
    case["application"]["owners"] = [{"name": rng.choice(pool["names"]), "share_pct": 100}]
    return "OWNER_MISMATCH"


def director_mismatch(case, pool, rng):
    dirs = case["application"]["directors"]
    if not dirs:
        return None
    dirs[rng.integers(len(dirs))]["name"] = rng.choice(pool["names"])
    return "DIRECTOR_MISMATCH"


def disqualified_director(case, pool, rng):
    case["application"]["directors"].append({"name": rng.choice(pool["disqualified"]), "dob_month": None, "nationality": None})
    return "DISQUALIFIED_DIRECTOR"


def sanctions_hit(case, pool, rng):
    case["application"]["owners"].append({"name": rng.choice(pool["sanctioned"]), "share_pct": 25})
    return "SANCTIONS_HIT"


def cloned_website(case, pool, rng):
    if not case.get("web"):
        return None
    case["web"]["text"] = rng.choice(pool["sites"])
    return "CLONED_WEBSITE"


def new_domain(case, pool, rng):
    if not case.get("web"):
        return None
    as_of = dt.date.fromisoformat(case["as_of"])
    case["web"]["domain_created"] = (as_of - dt.timedelta(days=int(rng.integers(2, 29)))).isoformat()
    return "NEW_DOMAIN"


def activity_mismatch(case, pool, rng):
    registered = set(case["registry"].get("sic_codes") or [])
    choices = [c for c in pool["industries"] if c not in registered]
    case["application"]["stated_industry"] = rng.choice(choices)
    return "ACTIVITY_MISMATCH"


def volume_implausible(case, pool, rng):
    # tens of millions a month for a company with no filed accounts is implausible
    case["application"]["expected_monthly_volume"] = {
        "amount": int(rng.integers(20, 200)) * 1_000_000,
        "currency": "GBP" if case["jurisdiction"] == "GB" else "USD",
    }
    return "VOLUME_IMPLAUSIBLE"


PLANTERS = {
    "OWNER_MISMATCH": owner_mismatch,
    "DIRECTOR_MISMATCH": director_mismatch,
    "DISQUALIFIED_DIRECTOR": disqualified_director,
    "SANCTIONS_HIT": sanctions_hit,
    "CLONED_WEBSITE": cloned_website,
    "NEW_DOMAIN": new_domain,
    "ACTIVITY_MISMATCH": activity_mismatch,
    "VOLUME_IMPLAUSIBLE": volume_implausible,
}


def label_for(issues):
    catalogue = issue_catalogue()
    decisions = {catalogue[i]["decision"] for i in issues}
    return "bad" if "bad" in decisions else "review" if "review" in decisions else "good"


def plant(case, codes, pool, rng):
    """A copy of `case` with the given issues planted, and its label. Skips codes that don't apply."""
    catalogue = issue_catalogue()
    case = copy.deepcopy(case)
    country = "GB" if case["jurisdiction"] == "GB" else "US"
    planted = []
    for code in codes:
        if country not in catalogue[code]["jurisdictions"]:
            continue
        got = PLANTERS[code](case, pool, rng)
        if got:
            planted.append(got)
    return case, {"decision": label_for(planted), "issues": planted, "slice": "planted"}
