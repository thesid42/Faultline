# Faultline

Faultline is a small auditable harness for investigating agent failures and
turning reviewed findings into executable regression tests. The local slice
exercises a ReturnDesk refund agent, an independent checker, an adaptive
investigator, two-axis coverage, and a human-approved export gate.

## Quick start

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e ".[all]"
faultline smoke --db results/faultline.sqlite3
pytest
```

The smoke command writes JSON artifacts inside a SQLite case file under
`results/`. Fake observations are
explicitly labelled `evidence_origin=simulated`; the smoke path never calls a
remote model and uses a deterministic branching controller. Live autonomous
investigation is deferred.

## Real model configuration

Set `OPENROUTER_API_KEY` and configure the target model explicitly. The local
slice permits only an explicitly selected `:free` model with price `0`; paid
model execution is deferred until provider pricing/usage reconciliation is
verified. There is no silent fake fallback.

```powershell
$env:OPENROUTER_API_KEY = "..."
$env:FAULTLINE_TARGET_PRICE_USD = "0"
faultline run --target-model nvidia/nemotron-3-nano-30b-a3b:free
```

## UI

```powershell
streamlit run faultline/ui.py
```

The case-file UI reads persisted SQLite/JSON artifacts only. Refreshing it does
not schedule model calls. The view shows incident status, component timeline,
hypotheses, experiment outcomes, coverage, held-out validation, and proposals.

After reviewing the displayed proposal, export is an explicit action:

```powershell
faultline approve-export --db results/faultline.sqlite3 --approver alice --directory artifacts/regression
```

If the case file contains multiple saved proposals, also pass
`--proposal-id <id>`; export fails closed when selection is ambiguous.

## Honest limits

The local runner is the reference implementation. Daytona and Jev are exposed
as optional interfaces in this slice; remote connectivity is deferred. Paid
work is bounded by 40 target trials, 12 investigator/generator calls, one
optional Jev triage request, 120 seconds per trial, and the shared $15 / $20
soft and hard ceiling.

The offline smoke path exercises the full typed tool loop against a
deterministic fake target (`evidence_origin=simulated`), including an
unrelated-note control, coverage classification, held-out checks, and a
persisted `CaseFile`. Live adaptive investigation remains deferred until the
remote runner can reconcile child-process usage into the parent budget.
