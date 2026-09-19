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
