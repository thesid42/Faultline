# Faultline

Faultline is an auditable incident-to-regression workflow for the synthetic
ReturnDesk refund agent. It streams application traces, uses an independent
ledger checker to queue a failed case, lets one typed investigator choose
bounded interventions, joins scenario/grader coverage, and writes a
human-approved regression proposal.

## Quick start (Windows PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[all,live]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m faultline.cli smoke
```

`smoke` is fully offline and labels every run `evidence_origin=simulated`.
It persists the case under `results/faultline.sqlite3`, including the raw
timeline, hypotheses, interventions, coverage, held-out checks, and digest.

The default `memory-conflict` profile is joined by two independently seeded
profiles that use the same typed workflow and limits:

```powershell
.\.venv\Scripts\python.exe -m faultline.cli smoke --profile amount-unit
.\.venv\Scripts\python.exe -m faultline.cli smoke --profile duplicate-refund
.\.venv\Scripts\python.exe -m faultline.cli smoke --profile all
```

The seeded demo faults are disclosed inputs, not diagnoses: the model must
still produce a real observed violation and the independent checker must
confirm it. Safe model output, malformed output, or an upstream/boundary
failure is retained and reported as `inconclusive`.

## Live demo

Copy `.env.example` to `.env`, set credentials, then run one explicit live
workflow:

### React investigation UI (read-only case data)

The React UI reads persisted case files through the local read-only API. Start
the API against the case database you want to review, then start Vite in a
second PowerShell window. The UI refreshes persisted cases and investigation
evidence only; it cannot start trials, approve a proposal, or mutate SQLite.
Refreshing the page rereads the persisted live cases; it performs no model
calls. Use the CLI against the same `--db` path for a new case or explicit
human approval/export.

The API requires the selected SQLite case database to exist. On a fresh clone,
create an offline simulated case first (no key or network required), or run
the live rehearsal below before starting the API:

```powershell
.\.venv\Scripts\python.exe -m faultline.cli smoke --profile all `
  --db results/llama-live-validation.sqlite3
```

Recorded live costs and case databases are local artifacts and are not
committed.

```powershell
.\.venv\Scripts\python.exe -m faultline.api --db results/llama-live-validation.sqlite3
```

In a second PowerShell window:

```powershell
cd frontend
npm ci
npm run dev
```

### Recorded capped rehearsal

```powershell
.\.venv\Scripts\python.exe -m faultline.cli demo --live --backend local `
  --profile amount-unit --jev `
  --target-model meta-llama/llama-3.1-8b-instruct `
  --db results/llama-live-validation.sqlite3
```

The target is pinned to `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`
by default; the investigator is pinned to `deepseek/deepseek-v4.1-flash`.
Provider routing has no fallback or retry. All live calls share
`results/budget.sqlite3` by default: global ceiling $10, automatic cap $2,
per-case cap $1, max 40 target trials, 12 investigator calls, and one
optional Jev request. The current application and provider receipts, not saved
output, are the evidence. Use `--approve-budget` only when you explicitly
authorize spend above the automatic $2 cap.

`--backend daytona` requires a configured Daytona worker and reports an
infrastructure/inconclusive case when that boundary is unavailable; it never
silently substitutes fake evidence. A rerun starts a new case; this MVP does
not claim checkpoint resume or production monitoring.
The free target is conservatively paced at one dispatch every 3.1 seconds, so
run one live demo at a time. The recorded capped rehearsal command above uses
the registered Groq route and its persistent worker cap.

Recorded result for that database: 37 target trials, 10 investigator calls,
one Jev request, six original-suite passes, a supported hypothesis, three
repetitions per matched matrix cell, and four held-out validations. This does
not claim the other profiles passed live. Memory-conflict is confirmed offline;
its live Llama run remains inconclusive because the model did not confirm the
21-day versus 14-day numeric comparison.
The separately recorded `duplicate-refund` rehearsal also completed live with
36 target trials, 8 investigator calls, one Jev request, and four held-out
validations; its redelivery condition was missing from the original suite and
detected by the independent checker. Thus two profiles are live-confirmed;
memory-conflict remains explicitly unconfirmed live.

## Review and export

Review the persisted proposal, then explicitly bind your approval to its
current digest and export executable pytest:

```powershell
.\.venv\Scripts\python.exe -m faultline.cli approve-export `
  --db results/faultline.sqlite3 --approver alice `
  --directory artifacts/regression
```

The generated test invokes the configured current application
(`FAULTLINE_LIVE_TARGET`) and skips rather than passing when no live target is
configured. It never asserts stored model output or a model-supplied
diagnosis.

## Architecture and limits

`workflow.py` owns orchestration; `investigator.py` owns typed controller
tools; `trials.py` validates supported interventions in isolated repetitions;
`coverage.py` joins independent checker evidence; `storage.py` and `session.py`
persist checkpointed audit state; `export.py` enforces digest-bound approval.

The demo is one synthetic application and one investigator. It does not patch
production, run arbitrary model-generated code, or claim production-wide
coverage. Timeouts, malformed model JSON, missing usage, budget exhaustion,
and unavailable remote infrastructure remain explicit `inconclusive` outcomes.
Checkpoints are for audit/UI progress only: this MVP does not resume a partial
case, and each rerun starts a new stable case identity.

The optional read-only case view is:

```powershell
.\.venv\Scripts\python.exe -m streamlit run faultline/ui.py
```
