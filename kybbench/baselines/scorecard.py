"""Rules scorecard: a reference line, not a competitor. Answers the workflow questions from
structured fields alone, the way a basic hand-written KYB rules engine would. No model involved.

Frozen. Every rule comes from the policy or the issue catalogue, never from looking at labels:
- ownership and director mismatches: exact name comparison against the PSC and officer registers
- disqualified director, PEP: a screening hit whose month and year of birth match the officer's;
  for a stated director who is not a registered officer (no date of birth), any disqualified-register
  name match
- sanctions: a near-exact name match on a stated party
- status, address rejected, mass registration, activity mismatch, volume: the catalogue definitions
- industry and regulated activity: a fixed table of SIC codes, and the FCA register lookup
- questions that need reading or judgement (fake or front, adverse media, cloned website) are
  always answered no: a rules engine cannot answer them
Changed 2026-10-28: an earlier version answered "fake or front" yes for the Companies House
default address, a rule written after seeing pilot labels. It was removed; the address is now the
ADDRESS_REJECTED issue, which every system is asked about.
"""

from kybbench import screening

FINANCIAL_SIC = {"64999", "66190", "66300", "66120", "64921", "64929", "64910", "64920"}
SIC_INDUSTRY = {"92000": "H_GAMBLING", "64921": "H_LENDING", "64929": "H_LENDING", "47910": "M_ECOMMERCE",
                "46900": "M_WHOLESALE", "56101": "M_HOSPITALITY", "68100": "M_PROPERTY", "68209": "M_PROPERTY",
                "41100": "M_CONSTRUCTION", "62020": "L_SOFTWARE", "62012": "L_SOFTWARE", "70229": "L_PROFESSIONAL"}


def _key(name):
    return " ".join(sorted(screening.normalise(name)))


def _same_person(name, others):
    return any(screening.similar(name, o) >= 0.9 for o in others)


def answer(case):
    app, reg, scr = case["application"], case["registry"], case["screening"]
    officers = [o["name"] for o in reg.get("officers") or []]
    pscs = [p["name"] for p in reg.get("psc") or []]
    dob = {_key(o["name"]): o.get("dob_month") for o in reg.get("officers") or []}
    sic = (reg.get("sic_codes") or ["99999"])[0]

    def dob_hit(hits, field):
        for h in hits:
            key = _key(h["screened"])
            for c in h["candidates"]:
                if dob.get(key) and str(c.get(field) or "")[:7] == dob[key]:
                    return True
        return False

    sanctions = any(c["similarity"] >= 0.95 for h in scr["sanctions"] for c in h["candidates"]
                    if h["screened"] in {d["name"] for d in app["directors"] + app["owners"]} | {reg["name"]})
    regulated = "gambling" if sic == "92000" else "financial" if sic in FINANCIAL_SIC else "none"
    industry = SIC_INDUSTRY.get(sic, "H_INVESTMENT" if sic in FINANCIAL_SIC else "L_OTHER")
    address = str(reg.get("registered_address") or "")
    no_accounts = not any((f.get("type") or "").startswith("AA") for f in reg.get("filings") or [])
    volume = (app.get("expected_monthly_volume") or {}).get("amount") or 0

    return {
        "industry": {"choice": industry, "probabilities": {industry: 1.0}},
        "regulated_activity": {"choice": regulated, "probabilities": {regulated: 1.0}},
        "licence_held": 1.0 if any(m.get("Status") == "Authorised" for m in case["licences"].get("fca") or []) else 0.0,
        "OWNER_MISMATCH": float(bool(pscs) and any(not _same_person(o["name"], pscs) for o in app["owners"])),
        "DIRECTOR_MISMATCH": float(any(not _same_person(d["name"], officers) for d in app["directors"])),
        "DISQUALIFIED_DIRECTOR": float(dob_hit(scr["disqualified_directors"], "date_of_birth")
                                       or any(c for h in scr["disqualified_directors"] for c in h["candidates"]
                                              if not _same_person(h["screened"], officers))),
        "STATUS_MISMATCH": float(reg.get("status") not in ("active", None)),
        "SANCTIONS_HIT": float(sanctions),
        "CLONED_WEBSITE": 0.0,
        "ADDRESS_MASS_REG": float((reg.get("address_company_count") or 0) > 500),
        "ADDRESS_REJECTED": float("CF14 8LH" in address or "DEFAULT ADDRESS" in address.upper()),
        "NEW_DOMAIN": 0.0,
        "ACTIVITY_MISMATCH": float(bool(app.get("stated_industry")) and app["stated_industry"] not in (reg.get("sic_codes") or [])),
        "VOLUME_IMPLAUSIBLE": float(volume > 5_000_000 and no_accounts),
        "pep_match": float(dob_hit(scr["pep"], "dob")),
        "adverse_media": 0.0,
        "adverse_media_own_conduct": 0.0,
        "fake_front": 0.0,
    }
