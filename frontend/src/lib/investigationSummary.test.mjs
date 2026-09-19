import { strict as assert } from 'node:assert'
import { test } from 'node:test'
import { summarizeInvestigation } from './investigationSummary.ts'

function baseCase(overrides = {}) {
  return {
    case_id: 'case-1',
    status: 'complete',
    evidence_origin: 'simulated',
    source_run_id: 'source-1',
    runs: [{
      run_id: 'source-1',
      status: 'completed',
      execution_status: 'completed',
      checker_status: 'completed',
      checker_passed: false,
      scenario: { expected_eligible: true, amount: 60, order_id: 'order-1' },
      actual_ledger: [{ kind: 'refund', amount: 0.6, order_id: 'order-1' }],
    }],
    hypotheses: [],
    experiment_results: [],
    coverage: [],
    ...overrides,
  }
}

test('does not invent a cause for a complete case without supported hypotheses', () => {
  const summary = summarizeInvestigation(baseCase())
  assert.match(summary.happened, /recorded \$0\.60 instead of the expected \$60\.00/)
  assert.match(summary.findings[0], /No hypothesis evidence has been recorded yet/)
})

test('inconclusive case cannot claim a stale supported hypothesis or proposal as final', () => {
  const summary = summarizeInvestigation(baseCase({
    status: 'inconclusive',
    stop_reason: 'inconclusive:provider_error',
    hypotheses: [{ status: 'supported', statement: 'A stale note changes the decision.' }],
    proposal: { digest: 'new', reviewed: true, approval_digest: 'old' },
  }))
  assert.equal(summary.happened, 'Unable to confirm this investigation.')
  assert.ok(summary.happenedDetail.includes('incomplete'))
  assert.ok(summary.nextSteps.some((step) => step.includes('provider or infrastructure failure')))
  assert.ok(summary.nextSteps.some((step) => step.includes('changed after approval')))
})

test('shows an invalid experiment plan and its correction without claiming a cause', () => {
  const summary = summarizeInvestigation(baseCase({
    status: 'investigating',
    observations: [{
      kind: 'invalid_experiment_plan',
      reason: 'the control arm was not paired with the incident fixture',
      message: 'The requested comparison cannot be interpreted.',
      correction_contract: { operator: 'policy_notes', value_type: 'non-empty string', accepted_aliases: ['reviewed_policy'], description: 'replace the selected policy result with a reviewed policy string' },
    }],
  }))
  assert.match(summary.progress, /correcting the test plan/)
  assert.ok(summary.findings.some((finding) => finding.includes('could not use its test plan')))
  assert.ok(summary.findings.some((finding) => finding.includes('replace the selected policy result')))
  assert.ok(summary.nextSteps.some((step) => step.includes('correcting its test plan; wait')))
  assert.doesNotMatch(summary.findings.join(' '), /dollars-versus-cents|duplicate refunds/)
})

test('controller no progress is an explicit inconclusive stop', () => {
  const summary = summarizeInvestigation(baseCase({
    status: 'inconclusive',
    stop_reason: 'inconclusive:controller_no_progress',
    observations: [{ kind: 'controller_recovery', status: 'warning', reason: 'repeated_no_progress' }],
  }))
  assert.match(summary.happenedDetail, /could not correct its test plan/)
  assert.ok(summary.findings.some((finding) => finding.includes('No cause is proven')))
  assert.ok(summary.nextSteps.some((step) => step.includes('Correct the investigator test plan')))
})

test('step, money, and provider stops remain distinguishable', () => {
  const step = summarizeInvestigation(baseCase({ status: 'inconclusive', stop_reason: 'inconclusive:max_investigator_steps_exhausted' }))
  assert.match(step.happenedDetail, /step limit/)
  assert.ok(step.nextSteps.some((next) => next.includes('step limit')))

  const money = summarizeInvestigation(baseCase({ status: 'inconclusive', stop_reason: 'inconclusive:target_trial_budget_exhausted' }))
  assert.match(money.happenedDetail, /budget or trial limit/)
  assert.ok(money.nextSteps.some((next) => next.includes('budget or trial limit')))

  const provider = summarizeInvestigation(baseCase({ status: 'inconclusive', stop_reason: 'inconclusive:provider_error' }))
  assert.match(provider.happenedDetail, /provider or infrastructure failure/)
  assert.ok(provider.nextSteps.some((next) => next.includes('provider or infrastructure failure')))
})

test('reviewed-good held-out failure is not presented as a confirmed fix', () => {
  const summary = summarizeInvestigation(baseCase({
    status: 'inconclusive',
    stop_reason: 'inconclusive:held_out_reviewed_good_failed',
  }))
  assert.match(summary.happenedDetail, /comparison version also failed its checks/)
  assert.match(summary.happenedDetail, /not confirmed as a fix/)
  assert.ok(summary.nextSteps.some((step) => step.includes('compare the suspect and reviewed configurations')))
  assert.doesNotMatch(summary.happenedDetail, /provider|budget|infrastructure/)
})

test('derives the reviewed-good failure from the historical generic stop only with a failed held-out cell', () => {
  const summary = summarizeInvestigation(baseCase({
    status: 'inconclusive',
    stop_reason: 'inconclusive:evidence_phase:RuntimeError',
    held_out_validation: [{
      configuration_id: 'reviewed_good',
      status: 'completed',
      checker_passed: false,
      run: { status: 'completed', checker_status: 'completed', checker_passed: false },
    }],
  }))
  assert.match(summary.happenedDetail, /comparison version also failed its checks/)
  assert.ok(summary.nextSteps.some((step) => step.includes('compare the suspect and reviewed configurations')))
})

test('completed cases describe recovered plan warnings without downgrading the result', () => {
  const summary = summarizeInvestigation(baseCase({
    observations: [
      { kind: 'invalid_experiment_plan', message: 'an early plan was incomplete' },
      { kind: 'controller_recovery', status: 'warning', reason: 'repeated_no_progress' },
    ],
  }))
  assert.ok(summary.findings.some((finding) => finding.includes('recovered from an earlier test-plan warning')))
  assert.ok(summary.findings.some((finding) => finding.includes('investigation continued')))
  assert.doesNotMatch(summary.findings.join(' '), /No cause is proven/)
})

test('infrastructure checker failure is unknown even when checker_passed is false', () => {
  const summary = summarizeInvestigation(baseCase({
    runs: [{ run_id: 'source-1', status: 'infrastructure_error', checker_status: 'infrastructure_error', checker_passed: false }],
  }))
  assert.match(summary.happened, /checker outcome is unknown/)
  assert.doesNotMatch(summary.happened, /found a failure/)
})

test('a failed arbitrary run is ignored when source_run_id is missing', () => {
  const summary = summarizeInvestigation(baseCase({
    source_run_id: null,
    runs: [{ run_id: 'unselected', status: 'completed', checker_status: 'completed', checker_passed: false }],
  }))
  assert.match(summary.happened, /No source run is linked/)
})

test('proposal review requires a matching digest and simulated evidence is disclosed', () => {
  const pending = summarizeInvestigation(baseCase({ proposal: { digest: 'same', reviewed: true, approval_digest: 'same' } }))
  assert.ok(pending.nextSteps.some((step) => step.includes('matching human approval')))
  assert.match(pending.evidenceNote, /Practice run/)
  const stale = summarizeInvestigation(baseCase({ proposal: { digest: 'new', reviewed: true, approval_digest: 'old' } }))
  assert.ok(stale.nextSteps.some((step) => step.includes('changed after approval')))
  const live = summarizeInvestigation(baseCase({ evidence_origin: 'live' }))
  assert.match(live.evidenceNote, /real AI model/)
})

test('does not claim an amount or duplicate when ledger evidence is incomplete or mixed-order', () => {
  const missingLedger = summarizeInvestigation(baseCase({ runs: [{
    run_id: 'source-1', status: 'completed', execution_status: 'completed', checker_status: 'completed', checker_passed: false,
    scenario: { expected_eligible: true, amount: 60, order_id: 'order-1' },
  }] }))
  assert.match(missingLedger.happened, /independent check found a failure/)

  const unknownAmount = summarizeInvestigation(baseCase({ runs: [{
    run_id: 'source-1', status: 'completed', execution_status: 'completed', checker_status: 'completed', checker_passed: false,
    scenario: { expected_eligible: true, amount: 60, order_id: 'order-1' },
    actual_ledger: [{ kind: 'refund', amount: 'not-recorded', order_id: 'order-1' }],
  }] }))
  assert.doesNotMatch(unknownAmount.happened, /instead of the expected/)

  const mixedOrders = summarizeInvestigation(baseCase({ runs: [{
    run_id: 'source-1', status: 'completed', execution_status: 'completed', checker_status: 'completed', checker_passed: false,
    scenario: { expected_eligible: true, amount: 60, order_id: 'order-1' },
    actual_ledger: [
      { kind: 'refund', amount: 60, order_id: 'order-1' },
      { kind: 'refund', amount: 60, order_id: 'order-2' },
    ],
  }] }))
  assert.doesNotMatch(mixedOrders.happened, /refunds for one order/)
})

test('unknown or empty source identifiers never select an arbitrary run', () => {
  for (const overrides of [
    { source_run_id: '', runs: [{ run_id: 'source-1', status: 'completed', checker_status: 'completed', checker_passed: false }] },
    { source_run_id: 'missing', runs: [{ run_id: 'source-1', status: 'completed', checker_status: 'completed', checker_passed: false }] },
  ]) {
    const summary = summarizeInvestigation(baseCase(overrides))
    assert.match(summary.happened, /No source run is linked/)
  }
})

test('supported hypotheses are hidden as final causes for incomplete checks', () => {
  const summary = summarizeInvestigation(baseCase({
    status: 'investigating',
    hypotheses: [{ status: 'supported', predicates: { family: 'amount_units' }, statement: 'amount statement' }],
  }))
  assert.ok(summary.findings[0].includes('Earlier evidence suggested'))
  assert.doesNotMatch(summary.findings[0], /dollars-versus-cents/)
})
