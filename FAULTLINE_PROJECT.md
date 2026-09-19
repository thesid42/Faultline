# Faultline — autonomous agent failure investigator

**An agent that investigates failed workflows, discovers the conditions behind them, and turns uncovered failure cases into reviewed regression tests.**

Draft v0.5 · Project plan · Implementation in progress.

## 1. Product

Faultline connects to an application's execution traces, existing eval suite, and resettable test environment. When a workflow violates a known requirement, it opens an investigation automatically.

The user supplies the application integration and correctness rules—not the diagnosis. Faultline forms competing hypotheses, chooses experiments, revises its explanation from results, and proposes tests that address the demonstrated coverage gap.

Its distinguishing feature is the connection between **experimental diagnosis and eval coverage**: the conditions that explain an incident become the conditions it checks for in the test suite. The interface is a live investigation case file, not a form asking the user what went wrong.

## 2. Agentic workflow

1. **Receive an incident.** An application adapter emits a completed run. An independent outcome check flags a violation and queues an investigation. Human-reported incidents can use the same entry point. The incident includes observed behavior, not a supplied root cause.
2. **Form and triage competing hypotheses.** The investigator inspects component inputs, model decisions, tool calls, and final state. For example: incorrect policy retrieval, conflicting customer memory, or incorrect tool execution. An optional Jev call checks narrow semantic questions against relevant evidence to help prioritise experiments.
3. **Choose and run experiments.** Reproduce the unchanged case, then select a permitted intervention that distinguishes the leading explanations. Inspect the results before choosing the next action. Failed hypotheses are revised or rejected.
4. **Find the failure conditions.** Remove irrelevant context or vary supported scenario fields to look for a smaller failing case and a nearby successful control. This is a bounded search, not a claim to find a mathematically minimal example.
5. **Check the existing suite.** Determine whether those conditions are represented, then run the existing graders against independently verified outcomes. Separate missing scenarios from graders that miss violations.
6. **Propose a regression pair.** Validate a failure-exposing case and a legitimate-behavior control against suspect and reviewed good configurations. Ask a human to approve the expected outcomes before exporting fixtures and pytest tests.

One LLM investigator controls this loop through typed tools: `inspect_trace`, `triage_hypotheses`, `run_experiment`, `probe_case`, `check_suite`, and `propose_tests`. It chooses the sequence within fixed limits; it does not execute arbitrary generated code.

If evidence is insufficient, replay state is missing, or the budget is exhausted, it stops with an explicit incomplete or inconclusive finding.

## 3. Demo application: ReturnDesk

ReturnDesk is a small support agent that decides whether to refund an order.

Its actual pipeline reads an order, retrieves current policy and customer notes, asks a real model for a structured decision, and executes `issue_refund` or `escalate_case` against a simulated service.

The controlled incident:

- Current return policy permits ordinary refunds within 14 days.
- An obsolete customer note mentions a 30-day window.
- A customer requests a refund for a 21-day-old order.
- The agent may follow the obsolete note and issue an invalid refund.

The offline showcase exposes three named profiles through the same orchestration
contract: `memory-conflict` (obsolete note precedence), `amount-unit` (minor vs
major refund units), and `duplicate-refund` (idempotency/attempt handling).
Each profile has distinct stream, suite, and fresh held-out IDs. The profile
name is case metadata only; it is never passed to the investigator as a
ground-truth diagnosis. A model that does not expose the seeded failure, or a
worker/budget/timeout error, produces an explicit inconclusive case.

The simulated refund service validates identifiers, amounts, and idempotency, but deliberately delegates eligibility to the agent. This disclosed design permits the failure; no real payments are involved.

A separate deterministic checker evaluates the final ledger against reviewed policy fixtures. The investigator cannot edit this checker or its authoritative rules.

Start with six ordinary eval cases that omit the conflicting-memory boundary condition. Faultline investigates the incident, probes other orders, and proposes a denied/allowed pair: the 21-day order must not receive an ordinary refund, while a qualifying 7-day order must still receive one. Reserve separate orders for held-out validation.

All data is synthetic. Fault-injection labels remain outside the investigator's inputs. The failure must be observed in real model runs; neither outcomes nor supporting experiment counts are fabricated.

## 4. Architecture and components

The application emits incidents to a local worker. The worker hosts the investigator loop and dispatches experiments to Daytona. Results return to local storage and the case-file interface.

| Component | Responsibility |
|---|---|
| Application adapter | Expose the real run entry point, resettable fixtures, named intervention boundaries, and component traces |
| Incident worker | Deduplicate incident events, persist investigation state, and enforce execution limits |
| Investigator | Maintain hypotheses, choose the next tool action, and interpret evidence |
| Jev triage tool | Check focused semantic questions and return typed judgments to inform experiment priority; not a second investigator |
| Experiment runner | Validate interventions, execute isolated trials through Daytona or the local fallback, and collect results |
| Verification and coverage | Apply independent requirements, run existing graders unchanged, and classify observed gaps |
| Case file and exporter | Show decisions, evidence, limitations, and proposed tests; export only after review |

SQLite stores investigation state and artifact references; JSON files retain full traces and experiment results. Record application, fixture, grader, model, provider, and intervention versions with each run.

The UI displays persisted state; refreshing it never starts another experiment. Independent experiment jobs allow bounded parallel execution later without changing the investigator's tool contract.

## 5. Daytona integration

Daytona is the experiment execution environment, not the dashboard host. Its [Python SDK](https://www.daytona.io/docs/en/python-sdk/) provides sandbox creation and process execution; [snapshots](https://www.daytona.io/docs/en/persistence/) provide reusable prepared environments.

The runner will:

- Prepare one clean snapshot containing the trusted demo application and dependencies.
- Create experiment sandboxes from that baseline, with at most two active at once.
- Rebuild the simulated tool database and fixed scenario clock before every trial; never share mutable trial state.
- Run the same application code with either the original condition or a validated intervention.
- Retrieve traces, final state, and execution status before cleaning up sandboxes.

Use whole-workflow reruns. Live VM forks and mid-execution checkpoints are outside the MVP; environment copies do not rewind external model APIs or production services.

The initial integration check must verify sandbox creation, model-endpoint access, and artifact retrieval. Daytona has [tier-dependent network restrictions](https://www.daytona.io/docs/en/troubleshooting/). Retain a local subprocess runner behind the same interface if remote execution is unavailable; label the backend used.

Only synthetic fixtures and trusted demo code go into Daytona. Keep credentials out of snapshots and trace artifacts. Runtime limits and cleanup are enforced by the runner.

## 6. Technology stack

| Layer | Choice |
|---|---|
| Language and dependencies | Python 3.12, uv |
| Agent controller and contracts | Small Python tool loop, Pydantic schemas |
| Model access | HTTPX with a thin OpenRouter client; TypeSafe Python SDK for Jev |
| Experiment infrastructure | Daytona Python SDK; local subprocess fallback |
| State and artifacts | SQLite and JSON |
| Case-file interface | Streamlit |
| Verification and test export | Deterministic Python checks, existing grader adapter, pytest |

Models: [free Nemotron Nano Omni](https://openrouter.ai/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free) for ReturnDesk; [DeepSeek V4.1 Flash](https://openrouter.ai/deepseek/deepseek-v4.1-flash) for the investigator. Provider and model routing are pinned with no automatic fallback or retry. The investigator receives selected evidence rather than every stored trace. A separate, explicitly selected rehearsal route is `meta-llama/llama-3.1-8b-instruct` through Groq; it is not an automatic fallback.

Pin model configurations during comparisons. Provider availability and quotas are checked before running; no silent paid fallback or model switching.

### Jev hypothesis triage

Use TypeSafe's `jev-1.13.0` for one optional batched triage call after hypotheses are proposed. Ask atomic questions such as whether a customer note contradicts current policy or describes historical guidance rather than a current exception. Jev returns typed judgments and probabilities, not hypotheses or explanations; application code decides how to use them. Questions in a batch are independent. See [TypeSafe's introduction](https://docs.typesafe.ai/introduction).

Send selected trace excerpts within its documented 32K state-plus-longest-question limit. Preserve question definitions, event IDs, outputs, and model version in the case file. If Jev is unavailable or uncertain, continue with investigator-led inspection without discarding alternatives. Compare triage-enabled and investigator-only runs on a small labelled set before relying on its routing. [Model reference](https://docs.typesafe.ai/models).

## 7. MVP boundaries and measurement rules

**Included:** one investigator with optional Jev triage, one application adapter, one demonstrated failure family, adaptive experiments, coverage-gap assessment, Daytona execution, and human-reviewed test export.

The initial intervention set supports replacing a selected policy/notes tool result, removing an irrelevant note, and varying order age within reviewed fixtures. These are implemented operators with validated parameters; the investigator chooses where and when to apply them. It cannot rewrite agent code or invent new executable operators.

Measurement rules:

- Run repeated baseline/intervention trials, initially three per condition, and retain all outcomes.
- Include an unrelated-note edit as a control when testing a memory explanation.
- Verify that the intended intervention actually took effect.
- Report raw counts and evidence supporting or weakening each hypothesis, not causal certainty.
- Jev probabilities guide investigation priority, not root-cause confidence or final verdicts. Exact field comparisons remain deterministic; experiments establish support.
- Classify scenario coverage as present, missing, or unknown; classify observed violations as detected or missed by existing graders.
- Keep invalid experiments, infrastructure errors, and no-observed-violation results separate. Do not claim overall production coverage.
- Derive expected test outcomes from reviewed application rules, not the investigator's opinion.

Bound each investigation to 40 target-agent trials, 12 investigator/generator calls, and one optional Jev triage request, with a 120-second trial limit. All live calls share a parent-owned persistent $10 ceiling, a $2 automatic cap requiring explicit approval beyond it, and a $1 per-case cap, including in-flight usage. Daytona uses its separate credit allowance, with bounded sandbox concurrency and lifecycle cleanup.

**Excluded:** production auto-fixes, automatic commits, arbitrary uploaded code, multiple investigator agents, live sandbox forks, general-purpose production monitoring integrations, and a universal zero-configuration adapter.

The engine is reusable, but each new application must supply fixtures, supported intervention boundaries, and independent correctness rules.

## 8. Demo and completion criteria

Feed a small stream of real ReturnDesk runs through the adapter. A violated requirement automatically opens a case. The audience sees Faultline inspect competing explanations, choose an experiment, respond to its result, and check the eval suite.

The case file shows:

- The observed incident and component timeline.
- Hypotheses, chosen experiments, and supporting or contradicting results.
- A demonstrated scenario gap, grader gap, or explicit inconclusive outcome.
- Proposed regression tests with validation evidence and an approval/export action.

A successful showcase demonstrates an observed failure, evidence supporting its mechanism, a genuine gap in the original suite, and an exported test pair that distinguishes invalid from legitimate behavior. A completed investigation may instead be inconclusive; it must never manufacture the showcase result.

The product does not change production behavior. Its deliverable is an auditable investigation and reviewed tests that the organization can add to its existing release process.
