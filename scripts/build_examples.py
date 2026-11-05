"""Build site/examples.json: three validation cases shown on the site, as the systems saw them,
with the answer key and what a few systems answered.

Only validation cases are used (their labels are public). People's names are reduced to initials.
For the planted-issue example the company's name, number and address are withheld too, because
its application was altered for the benchmark and the page should not point at a real company.

    .venv/bin/python scripts/build_examples.py
"""

import json
import re
from pathlib import Path

CASES = Path("data/validation/cases.jsonl")
LABELS = Path("data/validation/labels.json")
SYSTEMS = [("grayson-workflow", "Grayson", "workflow"),
           ("jev-workflow", "Jev", "workflow"),
           ("llm-workflow-openrouter-anthropic-claude-sonnet-5.5", "Claude Sonnet 5.5", "workflow"),
           ("llm-prompt-openrouter-openai-gpt-6.1-sol", "GPT-6.1 Sol", "prompt")]

EXAMPLES = [
    {"case_id": "val-178", "title": "An ordinary shop", "withhold_company": False,
     "why": "Everything checks out. The application matches the Companies House record, the website "
            "names the company and its number, the one politically-exposed-person hit is a namesake "
            "with a different birth date, and a sports retailer needs no licence. Approve."},
    {"case_id": "val-192", "title": "A planted owner mismatch", "withhold_company": True,
     "why": "The application says the business is wholly owned by someone who is not on the register: "
            "Companies House lists the director as the only person with significant control. Undeclared "
            "or misdeclared ownership is a standard reason to stop an application. This issue was planted "
            "into a real, ordinary company's application, so the label is correct by construction. Decline."},
    {"case_id": "val-291", "title": "A real shutdown", "withhold_company": False,
     "why": "An 11-month-old company registered for crypto and investment activity, with no FCA "
            "registration, one director who is also the only owner, no website, and no search results. "
            "The registrar had moved its registered office, and the director's service address, to the "
            "Companies House default address because they were not valid. Three months after the case "
            "date the Insolvency Service had it wound up in the public interest. Decline."},
]

ROLE = {"director": "Director", "secretary": "Secretary"}


def initials(name):
    """'KHAN, Shoaib Ahmed, Dr' or 'Mr Shoaib Ahmed Khan' -> 'S. A. K.'"""
    if not name:
        return name
    if "," in name:
        parts = [p.strip() for p in name.split(",")]
        name = " ".join(parts[1:2] + parts[:1])
    words = [w for w in re.split(r"\s+", name) if w and w.strip(".").lower() not in {"mr", "mrs", "ms", "miss", "dr", "prof", "sir"}]
    return " ".join(w[0].upper() + "." for w in words)


def mask(text, case, withhold):
    if not withhold or not text:
        return text
    reg = case["registry"]
    for s, rep in ((reg["name"], "[company]"), (reg["name"].title(), "[company]"), (reg["company_number"], "[number]")):
        text = re.sub(re.escape(s), rep, text, flags=re.I)
    return text


def pep_note(case):
    dob = {initials(o["name"]): o.get("dob_month") for o in case["registry"].get("officers") or []}
    hits = [(s["screened"], c) for s in case["screening"]["pep"] for c in s["candidates"]]
    if not hits:
        return "No matches"
    same = [h for h in hits if (h[1].get("dob") or "")[:7] == dob.get(initials(h[0]))]
    return f"{len(hits)} name match{'es' if len(hits) > 1 else ''} in Wikidata" + \
        (", same birth month" if same else ", different birth date: a namesake")


def build(spec, case, label):
    w = spec["withhold_company"]
    reg, app = case["registry"], case["application"]
    officers = [o for o in reg.get("officers") or [] if o.get("role") == "director"]
    company = "[withheld]" if w else reg["name"]
    number = "[withheld]" if w else reg["company_number"]
    address = "[withheld]" if w else reg["registered_address"]

    def same(a, b):
        return (a or "").strip().lower() == (b or "").strip().lower()

    reg_owners = ", ".join(initials(p["name"]) for p in reg.get("psc") or []) or "None registered"
    app_owners = ", ".join(initials(o["name"]) for o in app["owners"]) or "None given"
    reg_dirs = ", ".join(initials(o["name"]) for o in officers) or "None"
    app_dirs = ", ".join(initials(d["name"]) for d in app["directors"]) or "None given"
    rows = [
        ["Company name", company, company, same(app["company_name"], reg["name"])],
        ["Company number", number, number, app["company_number"] == reg["company_number"]],
        ["Registered address", address, address, same(app["registered_address"], reg["registered_address"])],
        ["Directors", app_dirs, reg_dirs, app_dirs == reg_dirs],
        ["Owners", app_owners, reg_owners, app_owners == reg_owners],
        ["Industry (SIC)", app["stated_industry"], ", ".join(reg["sic_codes"]), app["stated_industry"] in reg["sic_codes"]],
        ["Website", app["website"] or "None given", "", True],
    ]
    filings = [{"date": f["date"], "type": f.get("type"), "what": (f.get("description") or "").replace("-", " ")}
               for f in (reg.get("filings") or [])[:5]]
    web = case.get("web")
    search = [{"title": mask(" ".join((r.get("title") or "").split()), case, w),
               "snippet": mask(" ".join((r.get("snippet") or "").split())[:260], case, w),
               "url": "[withheld]" if w else r.get("url"), "date": r.get("published")}
              for r in ((case.get("search") or {}).get("results") or [])[:2]]
    if w and search:  # a snippet quotes the company's address, which would identify it
        search = [{"title": "Business directory listing", "url": "[withheld]", "date": search[0]["date"],
                   "snippet": "A directory of doctors in the company's town, listing the company at its registered address."}]
    answers = []
    for run, name, mode in SYSTEMS:
        p = next((json.loads(l) for l in open(f"runs/validation/{run}/predictions.jsonl")
                  if json.loads(l)["case_id"] == spec["case_id"]), None)
        if p:
            flagged = sorted(((k, v) for k, v in (p.get("issues") or {}).items() if v and v >= 0.5), key=lambda kv: -kv[1])
            answers.append({"system": name, "mode": mode, "decision": p.get("decision"), "score": round(p.get("score", 0), 2),
                            "issues": [k for k, _ in flagged[:3]]})
    want = {"good": "approve", "review": "review", "bad": "decline"}[label["decision"]]
    return {
        "case_id": spec["case_id"], "title": spec["title"], "as_of": case["as_of"],
        "company": company, "withheld": w,
        "comparison": rows,
        "registry": {"status": reg["status"].title() if reg.get("status") else "Unknown", "incorporated": reg["incorporated"],
                     "type": reg.get("type"), "officers": [{"name": initials(o["name"]), "role": ROLE.get(o.get("role"), o.get("role")),
                                                             "nationality": o.get("nationality"), "residence": o.get("country_of_residence")} for o in officers],
                     "filings": filings, "n_filings": len(reg.get("filings") or [])},
        "web": {"url": "[withheld]" if w else web["url"], "domain_created": web.get("domain_created"),
                "text": mask(" ".join((web.get("text") or "").split())[:320], case, w)} if web else None,
        "search": search,
        "screening": {"Sanctions (UK, OFAC)": "No matches" if not any(s["candidates"] for s in case["screening"]["sanctions"]) else "Match",
                      "Politically exposed persons": pep_note(case),
                      "Disqualified directors": "No matches" if not any(s["candidates"] for s in case["screening"]["disqualified_directors"]) else "Match",
                      "FCA register": "No entry" if not case["licences"].get("fca") else "Listed"},
        "answer": {"decision": want, "issues": label.get("issues") or [], "why": spec["why"],
                   "source": label.get("source"), "outcome_date": label.get("exposed_on")},
        "answers": answers,
    }


def main():
    cases = {c["case_id"]: c for c in map(json.loads, open(CASES))}
    labels = json.load(open(LABELS))
    out = [build(s, cases[s["case_id"]], labels[s["case_id"]]) for s in EXAMPLES]
    Path("site/examples.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    for e in out:
        print(e["case_id"], e["title"], "|", e["answer"]["decision"], "|", [(a["system"], a["decision"]) for a in e["answers"]])


if __name__ == "__main__":
    main()
