import type { CaseFile } from '../context/CaseContext'

type RecordValue = Record<string, unknown>

export interface InvestigationSummary {
  happened: string
  happenedDetail: string
  findings: string[]
  experimentCounts: Record<string, number>
  nextSteps: string[]
  progress: string
  evidenceNote: string
  status: string
}

export function friendlyCaseTitle(profile: unknown): string {
  const value = text(profile)
  if (value === 'memory-conflict') return 'Conflicting policy information'
  if (value === 'amount-unit') return 'Refund amount mismatch'
  if (value === 'duplicate-refund') return 'Repeated refund request'
  return 'Investigation case'
}

function records(value: unknown): RecordValue[] {
  return Array.isArray(value) ? value.filter((item): item is RecordValue => Boolean(item && typeof item === 'object')) : []
}

function record(value: unknown): RecordValue {
  return value && typeof value === 'object' ? value as RecordValue : {}
}

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function recoveryMessage(observation: RecordValue): string {
  return text(observation.message) || text(observation.reason) || 'The investigator recorded a test-plan problem.'
}

function recoveryContract(observation: RecordValue): string {
  const value = observation.correction_contract
  if (typeof value === 'string') return value.trim()
  if (Array.isArray(value)) return value.filter((item): item is string => typeof item === 'string').join('; ')
  if (value && typeof value === 'object') {
    const contract = value as Record<string, unknown>
    const detail = (item: unknown): string => text(item) || (Array.isArray(item)
      ? item.filter((entry): entry is string | number | boolean => typeof entry === 'string' || typeof entry === 'number' || typeof entry === 'boolean').map(String).join(', ')
      : typeof item === 'number' || typeof item === 'boolean' ? String(item) : '')
    const parts: string[] = []
    if (detail(contract.description)) parts.push(detail(contract.description))
    if (detail(contract.value_type)) parts.push(`value must be ${detail(contract.value_type)}`)
    if (detail(contract.allowed_values)) parts.push(`allowed values: ${detail(contract.allowed_values)}`)
    if (detail(contract.range)) parts.push(`range: ${detail(contract.range)}`)
    if (detail(contract.accepted_aliases)) parts.push(`accepted aliases: ${detail(contract.accepted_aliases)}`)
    return parts.join('; ')
  }
  return ''
}

function sourceRun(caseFile: CaseFile): RecordValue | null {
  const runs = records(caseFile.runs)
  const incidentRunId = text(record(caseFile.incident).run_id)
  const sourceRunId = text(caseFile.source_run_id) || incidentRunId
  if (!sourceRunId) return null
  const selected = runs.find((item) => text(item.run_id) === sourceRunId)
  return selected && text(selected.run_id) ? selected : null
}

function outcomeCounts(results: RecordValue[]): Record<string, number> {
  return results.reduce<Record<string, number>>((counts, result) => {
    const status = text(result.status) || 'unknown'
    counts[status] = (counts[status] ?? 0) + 1
    return counts
  }, {})
}

function reviewState(proposal: RecordValue | null): 'none' | 'pending' | 'approved' | 'stale' {
  if (!proposal) return 'none'
  const digest = text(proposal.digest)
  const approvalDigest = text(proposal.approval_digest)
  if (proposal.reviewed === true && digest && approvalDigest === digest) return 'approved'
  if (proposal.reviewed === true && approvalDigest && approvalDigest !== digest) return 'stale'
  return 'pending'
}

function money(value: unknown): number | null {
  const amount = typeof value === 'number' ? value : typeof value === 'string' && value.trim() ? Number(value) : NaN
  return Number.isFinite(amount) ? amount : null
}

function moneyLabel(value: number): string {
  return `$${value.toFixed(2)}`
}

function sourceFailureText(run: RecordValue): string | null {
  const scenario = record(run.scenario)
  const expectedEligible = scenario.expected_eligible
  const expectedAmount = money(scenario.amount)
  const ledger = run.actual_ledger
  const expectedOrderId = text(scenario.order_id)
  if (!Array.isArray(ledger) || !expectedOrderId) return null
  const ledgerRows = records(ledger)
  if (ledgerRows.length !== ledger.length) return null
  const refunds = ledgerRows.filter((item) => text(item.kind).toLowerCase() === 'refund')
  if (refunds.some((item) => money(item.amount) === null)) return null
  const matchingRefunds = refunds.filter((item) => text(item.order_id) === expectedOrderId)
  const unrelatedRefunds = refunds.some((item) => text(item.order_id) !== expectedOrderId)
  const totalRefunded = matchingRefunds.reduce((total, item) => total + (money(item.amount) as number), 0)
  if (expectedEligible === true && expectedAmount !== null && matchingRefunds.length > 1) {
    return `The agent recorded ${matchingRefunds.length} refunds for one order instead of one ${moneyLabel(expectedAmount)} refund.`
  }
  if (expectedEligible === true && expectedAmount !== null && !unrelatedRefunds && matchingRefunds.length > 0 && Math.abs(totalRefunded - expectedAmount) > 0.000001) {
    return `The agent recorded ${moneyLabel(totalRefunded)} instead of the expected ${moneyLabel(expectedAmount)}.`
  }
  if (expectedEligible === true && expectedAmount !== null && refunds.length === 0) {
    return `The agent did not record the expected ${moneyLabel(expectedAmount)} refund.`
  }
  return null
}

function hasFailedReviewedGoodHeldout(caseFile: CaseFile): boolean {
  return records(caseFile.held_out_validation).some((row) => {
    if (text(row.configuration_id).toLowerCase() !== 'reviewed_good' || text(row.status).toLowerCase() !== 'completed') return false
    const nestedRun = record(row.run)
    const checkerPassed = typeof row.checker_passed === 'boolean' ? row.checker_passed : nestedRun.checker_passed
    return text(nestedRun.status).toLowerCase() === 'completed'
      && text(nestedRun.checker_status).toLowerCase() === 'completed'
      && checkerPassed === false
  })
}

function friendlyFinding(hypothesis: RecordValue): string {
  const predicates = record(hypothesis.predicates)
  const family = text(predicates.family).toLowerCase()
  const statement = text(hypothesis.statement)
  if (family === 'amount_units') return 'The tests point to a dollars-versus-cents mix-up.'
  if (family === 'idempotency') return 'Repeated requests can create duplicate refunds.'
  return statement
}

function friendlyMissingCondition(condition: string): string {
  const normalized = condition.toLowerCase()
  if (normalized === 'refund_minor_units') return 'The old tests did not cover refunds recorded in cents. Add a test for that situation.'
  if (normalized === 'redelivery') return 'The old tests did not cover repeated requests. Add a test that sends the same refund request twice.'
  if (normalized === 'memory_conflict') return 'The old tests did not cover conflicting customer notes. Add a test for that situation.'
  return 'Add an original-suite test for this uncovered condition.'
}

/**
 * Turn persisted evidence into plain language. This function intentionally
 * never uses profile names or terminal status as a causal conclusion.
 */
export function summarizeInvestigation(caseFile: CaseFile): InvestigationSummary {
  const status = text(caseFile.status) || 'unknown'
  const run = sourceRun(caseFile)
  const stopReason = text(caseFile.stop_reason).toLowerCase()
  const runStatus = text(run?.status).toLowerCase()
  const executionStatus = text(run?.execution_status).toLowerCase()
  const checkerPassed = run?.checker_passed
  const runIsUsable = Boolean(run) && runStatus === 'completed' && text(run?.checker_status).toLowerCase() === 'completed' && executionStatus !== 'infrastructure_error'
  const observations = records(caseFile.observations)
  const invalidPlanEvents = observations.filter((item) => text(item.kind).toLowerCase() === 'invalid_experiment_plan')
  const noProgressEvents = observations.filter((item) => {
    const kind = text(item.kind).toLowerCase()
    return kind === 'no_progress' || (kind === 'controller_recovery' && text(item.reason).toLowerCase() === 'repeated_no_progress')
  })
  const controllerNoProgress = stopReason === 'inconclusive:controller_no_progress'
  const heldoutFailureStop = stopReason === 'inconclusive:held_out_reviewed_good_failed'
  const historicalHeldoutFailure = stopReason === 'inconclusive:evidence_phase:runtimeerror' && hasFailedReviewedGoodHeldout(caseFile)
  const reviewedGoodHeldoutFailed = heldoutFailureStop || historicalHeldoutFailure
  const stepLimitStopped = stopReason.includes('max_investigator_steps_exhausted')
  const callLimitStopped = stopReason.includes('investigator_call_budget_exhausted')
  const moneyLimitStopped = /(budget|ceiling|target_trial_budget_exhausted|automation_cap)/.test(stopReason)
  const providerStopped = /(provider|infrastructure|timeout|unavailable|error|failure)/.test(stopReason)
  const failureStoppedCase = status === 'inconclusive' && (providerStopped || moneyLimitStopped)

  let happened = 'What happened is unknown from the persisted evidence.'
  let happenedDetail = 'A source run and an independent checker result are needed before drawing a conclusion.'
  if (status === 'inconclusive') {
    happened = 'Unable to confirm this investigation.'
    happenedDetail = controllerNoProgress
      ? 'The investigator could not correct its test plan. The saved evidence is incomplete, so no cause or fix is claimed.'
      : reviewedGoodHeldoutFailed
        ? 'The comparison version also failed its checks, so this change is not confirmed as a fix.'
      : stepLimitStopped
        ? 'The investigator reached its step limit before finishing. No cause or fix is claimed.'
        : callLimitStopped
          ? 'The investigator reached its call limit before finishing. No cause or fix is claimed.'
          : failureStoppedCase
            ? moneyLimitStopped && !providerStopped
              ? 'A budget or trial limit stopped the run. The saved evidence is incomplete, so no cause or fix is claimed.'
              : 'A provider or infrastructure failure stopped the run. The saved evidence is incomplete, so no cause or fix is claimed.'
            : 'The investigation ended inconclusively. Any earlier evidence is provisional, so no final cause or fix is claimed.'
  } else if (run && runIsUsable && typeof checkerPassed === 'boolean') {
    happened = checkerPassed ? 'The independent check passed this run.' : sourceFailureText(run) ?? 'The independent check found a failure in this run.'
    happenedDetail = checkerPassed
      ? 'This is an observed check, not proof that the application is permanently fixed.'
      : 'This records an observed failure; it does not identify the cause by itself.'
  } else if (run) {
    happened = 'A source run is recorded, but its checker outcome is unknown.'
    happenedDetail = 'The run was incomplete, invalid, or did not produce a usable independent checker result.'
  } else if (!run) {
    happened = status === 'queued' ? 'Waiting to start.' : status === 'investigating' ? 'Checking the reported failure.' : 'No source run is linked to this case.'
    happenedDetail = status === 'queued' || status === 'investigating'
      ? 'The saved evidence will become clearer as the investigation records its source run and independent check.'
      : 'The case may contain other records, but they cannot establish what happened without the selected source run.'
  }

  const hypotheses = records(caseFile.hypotheses)
  const supported = hypotheses.filter((item) => text(item.status).toLowerCase() === 'supported' && text(item.statement))
  const results = records(caseFile.experiment_results ?? caseFile.experiments)
  const counts = outcomeCounts(results)
  const canReportCause = status === 'complete' && runIsUsable && checkerPassed === false
  const findings: string[] = canReportCause ? supported.map((item) => friendlyFinding(item)) : []
  if (!canReportCause) {
    findings.push(supported.length > 0 && status !== 'complete' ? 'Earlier evidence suggested a possible cause, but this run did not confirm a cause.' : supported.length > 0 ? 'A possible cause is recorded, but the independent check did not confirm it.' : hypotheses.length === 0 ? 'No hypothesis evidence has been recorded yet.' : 'No recorded hypothesis is currently supported.')
  } else if (supported.length === 0) {
    findings.push(hypotheses.length === 0 ? 'No hypothesis evidence has been recorded yet.' : 'No recorded hypothesis is currently supported.')
  }
  if (results.length === 0) {
    findings.push('No experiment outcomes have been recorded yet.')
  } else {
    const countText = Object.entries(counts).map(([name, count]) => `${count} ${name.replaceAll('_', ' ')}`).join(', ')
    findings.push(`Recorded experiment outcomes: ${countText}.`)
  }
  if (invalidPlanEvents.length > 0) {
    const latest = invalidPlanEvents[invalidPlanEvents.length - 1]
    const correction = recoveryContract(latest)
    if (status === 'complete') {
      findings.push('The investigator recovered from an earlier test-plan warning before finishing.')
    } else {
      findings.push(`The investigator could not use its test plan: ${recoveryMessage(latest)}${correction ? ` Correction required: ${correction}.` : ' It must correct the plan before drawing conclusions.'}`)
    }
  }
  if (noProgressEvents.length > 0 || controllerNoProgress) {
    findings.push(status === 'complete'
      ? 'Recovered from an earlier repeated-step warning; the investigation continued.'
      : 'The investigator made no progress on a usable test plan. No cause is proven.')
  }

  const coverage = records(caseFile.coverage)
  const missingConditions = [...new Set(coverage.filter((item) => text(item.original_suite).toLowerCase() === 'missing').map((item) => text(item.condition)).filter(Boolean))]
  const proposal = caseFile.proposal ? record(caseFile.proposal) : null
  const proposalStatus = reviewState(proposal)
  const nextSteps: string[] = []
  if (status === 'investigating' && (noProgressEvents.length > 0 || invalidPlanEvents.length > 0)) {
    nextSteps.push('The investigator is correcting its test plan; wait for the saved result before rerunning.')
  } else if (controllerNoProgress) {
    nextSteps.push('Correct the investigator test plan, then rerun before relying on the evidence.')
  } else if (reviewedGoodHeldoutFailed) {
    nextSteps.push('Inspect the target decision and compare the suspect and reviewed configurations; do not treat this change as a confirmed fix.')
  } else if (stepLimitStopped) {
    nextSteps.push('The investigator reached its step limit; rerun with a corrected or smaller test plan before relying on the evidence.')
  } else if (callLimitStopped) {
    nextSteps.push('The investigator reached its call limit; inspect the saved plan and rerun within the allowed call budget.')
  } else if (moneyLimitStopped && !providerStopped) {
    nextSteps.push('A budget or trial limit stopped the run; wait for approval or budget availability before rerunning.')
  } else if (failureStoppedCase) {
    nextSteps.push('Resolve the provider or infrastructure failure, then rerun the investigation before relying on its findings.')
  } else if (status !== 'complete' && (noProgressEvents.length > 0 || invalidPlanEvents.length > 0)) {
    nextSteps.push('Correct the investigator test plan, then rerun before relying on the evidence.')
  }
  if (missingConditions.length > 0) {
    missingConditions.forEach((condition) => nextSteps.push(friendlyMissingCondition(condition)))
  } else if (coverage.length === 0) {
    nextSteps.push('Wait for or run a coverage assessment; missing conditions are currently unknown.')
  }
  if (proposalStatus === 'none') nextSteps.push('No suggested regression test is recorded yet.')
  if (proposalStatus === 'pending') nextSteps.push('Review the suggested test before adding it. Nothing has been changed automatically.')
  if (proposalStatus === 'stale') nextSteps.push('The suggested test changed after approval. Review the current version again before adding it.')
  if (proposalStatus === 'approved') nextSteps.push('The suggested test has matching human approval; export or execute it through the reviewed workflow.')
  if (nextSteps.length === 0) nextSteps.push('No further action is recorded; inspect Technical details for the evidence supporting this state.')

  const runs = records(caseFile.runs)
  const progressParts = [`${runs.length} recorded run${runs.length === 1 ? '' : 's'}`, `${results.length} experiment result${results.length === 1 ? '' : 's'}`]
  if (observations.length > 0) {
    const latest = observations[observations.length - 1]
    const latestKind = text(latest.kind).toLowerCase()
    const checkpoint = `${text(latest.stage)} ${latestKind}`.toLowerCase()
    const latestIsRecovery = latestKind === 'invalid_experiment_plan' || latestKind === 'no_progress' || (latestKind === 'controller_recovery' && text(latest.reason).toLowerCase() === 'repeated_no_progress')
    const label = status === 'investigating' && latestIsRecovery
      ? 'correcting the test plan'
      : checkpoint.includes('experiment') ? 'testing possible causes' : checkpoint.includes('hypothes') || checkpoint.includes('triage') ? 'checking possible causes' : checkpoint.includes('coverage') || checkpoint.includes('proposal') || checkpoint.includes('propose') || checkpoint.includes('test') ? 'preparing results' : 'collecting evidence'
    progressParts.push(label)
  }
  const progress = status === 'queued'
    ? `Waiting to start — ${progressParts.join('; ')}.`
    : status === 'investigating'
      ? `Checking the reported failure — ${progressParts.join('; ')}.`
      : status === 'inconclusive'
        ? `Investigation stopped inconclusively — ${progressParts.join('; ')}.`
        : status === 'complete'
          ? `Finished. ${runs.length} test run${runs.length === 1 ? '' : 's'} completed.`
          : `Status ${status} — ${progressParts.join('; ')}.`

  const evidenceNote = text(caseFile.evidence_origin).toLowerCase() === 'simulated'
    ? 'Practice run: simulated responses, no real AI calls.'
    : text(caseFile.evidence_origin).toLowerCase() === 'live'
      ? 'This run used a real AI model. The result describes this test, not a guarantee about every future run.'
      : 'Evidence origin is unknown; treat this case as unverified until the source records are inspected.'

  return { happened, happenedDetail, findings, experimentCounts: counts, nextSteps, progress, evidenceNote, status }
}
