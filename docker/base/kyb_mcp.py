"""KYB tool server (MCP, stdio) run inside the agent container.

Every tool reads the single case mounted read-only at /case/case.json, the same frozen data the
prompt and workflow modes see. `submit` writes the prediction to /out/prediction.json. The case's
labels are never in the container.
"""

import difflib
import json
import re

from mcp.server.fastmcp import FastMCP

CASE = json.load(open("/case/case.json"))
OUT = "/out/prediction.json"
mcp = FastMCP("kyb")


def _similar(a, b):
    ta = sorted(t for t in re.sub(r"[^a-z ]", " ", a.lower()).split() if len(t) > 1)
    tb = sorted(t for t in re.sub(r"[^a-z ]", " ", b.lower()).split() if len(t) > 1)
    if ta and tb and (set(ta) <= set(tb) or set(tb) <= set(ta)):
        return 1.0
    return difflib.SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio()


@mcp.tool()
def registry_lookup(section: str) -> str:
    """Companies House record for the company as of the case date. section is one of: profile
    (status, incorporation, type, industry codes, registered address), officers, ownership (PSC
    register), filings."""
    reg = CASE["registry"]
    if section == "profile":
        keys = ("company_number", "name", "status", "incorporated", "type", "sic_codes", "registered_address",
                "address_company_count", "accounts_category")
        return json.dumps({k: reg.get(k) for k in keys})
    data = {"officers": reg.get("officers"), "ownership": reg.get("psc"), "filings": reg.get("filings")}
    if section not in data:
        return "Error: section must be profile, officers, ownership or filings"
    return json.dumps(data[section])


@mcp.tool()
def screen(kind: str, name: str) -> str:
    """Screen a person or company name. kind is one of: sanctions, pep (politically exposed
    persons), disqualified (UK disqualified directors). Returns candidate matches, which may be
    different people with the same name."""
    key = {"sanctions": "sanctions", "pep": "pep", "disqualified": "disqualified_directors"}.get(kind)
    if not key:
        return "Error: kind must be sanctions, pep or disqualified"
    hits = [h for h in CASE["screening"][key] if _similar(h["screened"], name) >= 0.9]
    return json.dumps(hits or {"screened": name, "candidates": []})


@mcp.tool()
def licence_lookup() -> str:
    """Licensing register results for the company (FCA; other registers where available)."""
    return json.dumps(CASE["licences"])


@mcp.tool()
def web_search() -> str:
    """First page of web search results for the company, published before the case date."""
    return json.dumps(CASE.get("search") or {"results": [], "note": "no search results available"})


@mcp.tool()
def fetch_website() -> str:
    """The company's website text as archived at or before the case date."""
    return json.dumps(CASE.get("web") or {"note": "no website available"})


@mcp.tool()
def submit(score: float, decision: str, industry: str, risk_rating: str, issues: dict[str, float]) -> str:
    """Submit the final assessment, once. score: probability the business should not be onboarded
    (0-1). decision: approve, review or decline. industry: a policy industry code. risk_rating:
    prohibited, high, medium or low. issues: probability (0-1) for every issue code."""
    pred = {"case_id": CASE["case_id"], "score": score, "decision": decision, "industry": industry,
            "risk_rating": risk_rating, "issues": issues}
    with open(OUT, "w") as f:
        json.dump(pred, f)
    return "Submitted."


TOOLS = {"registry_lookup": registry_lookup, "screen": screen, "licence_lookup": licence_lookup,
         "web_search": web_search, "fetch_website": fetch_website}


def cli(argv):
    """kyb-tool <tool> [json-args], e.g. kyb-tool screen '{"kind": "pep", "name": "Jane Smith"}'.
    submit takes the prediction as JSON."""
    import sys
    if not argv or argv[0] not in {*TOOLS, "submit"}:
        sys.exit(f"usage: kyb-tool {{{','.join([*TOOLS, 'submit'])}}} [json-args]")
    args = json.loads(argv[1]) if len(argv) > 1 else {}
    fn = submit if argv[0] == "submit" else TOOLS[argv[0]]
    print(fn(**args))


if __name__ == "__main__":
    import sys
    if "--cli" in sys.argv:
        cli(sys.argv[sys.argv.index("--cli") + 1:])
    else:
        mcp.run()
