# KYB-Bench

A benchmark for deciding whether to onboard a business. Every case is the same task: a UK company
applies to open an account, frozen at a date, and the system decides **approve**, **review** or
**decline** under a published onboarding policy. Decision models, LLMs and LLM agents are scored
on the same cases: how well they rank risk, the decisions they make, and what each decision costs to make.

Leaderboard and downloads: **https://www.kyb-bench.com**. The design is in [SPEC.md](SPEC.md).

## What a case contains

- **The application:** claimed name, number, addresses, directors, owners, website, industry and
  expected volume.
- **The Companies House record as of the case date:** status, officers, persons with significant
  control and filings, rebuilt from filing history.
- **Web evidence from that date:** Google search results and website text, taken only from
  archived captures made on or before the case date.
- **Screening:** UK and US sanctions lists, politically exposed persons (Wikidata), disqualified
  directors, and the FCA, Gambling Commission and HMRC registers.
- **The policy:** [data/policy/v1.md](data/policy/v1.md), with industry risk tiers and licence
  rules.

Labels come from real outcomes (companies the Insolvency Service later wound up in the public
interest), planted issues (an ordinary company's application altered in a known way, such as an
owner missing from the register or a sanctioned director), policy cases (high-risk and prohibited
industries, missing licences, politically exposed people) and a future-risk slice (registered
addresses the registrar later rejected), which is scored as a ranking only. Industry and licence
labels were researched by model agents and checked against official registers; they have not been
audited by people.

## Splits

| Split | Cases | Labels |
|---|---|---|
| `pilot` | 100 | public |
| `validation` | 276 | public; the only labelled data a system may tune on |
| `test_fresh` | 333 | hidden; outcomes made public on or after 3 August 2026 |
| `test_historical` | 1,831 | hidden; older outcomes |

## Grading

Systems are ranked by **PR-AUC** of their risk score: how well it puts the businesses that should be
stopped (real shutdowns, planted issues that warrant a decline, prohibited or unlicensed
activity) above the rest. It needs no cost assumptions or thresholds. Also reported: accuracy of
the approve / review / decline decision against the answer key, bad cases declined, good customers
stopped, real shutdowns declined, ROC-AUC on the future-risk slice, and the model cost per case
priced from each case's trace. All with 95% bootstrap intervals on the leaderboard.

## Run and submit

```bash
pip install kybbench
kybbench download                      # pilot and validation with labels, test splits without

kybbench run --cases data/validation/cases.jsonl --system my_module:predict \
    --name my-system --type llm --mode prompt --out runs/my-system
kybbench eval --labels data/validation/labels.json --preds runs/my-system/predictions.jsonl

KYB_SUBMIT_KEY=... kybbench submit --split test_fresh \
    --preds runs/my-system/predictions.jsonl --name my-system
```

A system is any Python function `predict(case) -> {"case_id", "decision", "score", "issues", ...}`
(see [kybbench/schema.py](kybbench/schema.py)). Record what it spends with
`kybbench.harness.llm_call(...)` or `harness.model_infer(...)` inside the function. Test scoring
happens on our server and returns aggregate metrics only. To get a submitter key, open an issue.

Three modes are supported:

- **prompt:** one model call per case ([kybbench/llm.py](kybbench/llm.py)).
- **workflow:** fixed typed questions ([workflows/v1](workflows/v1)), answered by the system, with
  fixed policy code turning the answers into a decision ([kybbench/workflow.py](kybbench/workflow.py)).
- **agent:** any harness in a locked-down container with an egress allowlist
  ([harnesses/](harnesses), [docker/](docker), [scripts/run_container.py](scripts/run_container.py)).

## Development

```bash
python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev,llm]'
.venv/bin/pytest
```

Building cases needs a Companies House API key (`COMPANIES_HOUSE_API_KEY`); the builders in
[scripts/](scripts) also read candidate lists that are kept private because they would reveal test
labels. The scoring service is [kybbench/server.py](kybbench/server.py), deployed as an AWS Lambda.

## Disclaimer

Cases are built from public records of real UK companies, but every application is constructed for
the benchmark, and some contain deliberately altered details. Nothing in this repository or the
data implies wrongdoing by any named company or person beyond existing public records.

KYB-Bench is maintained by [Finic](https://finic.ai), which also builds Grayson, one of the
evaluated systems. Every system is scored by the same grader on the same hidden labels.
