import type { CaseFile } from '../context/CaseContext'
import { displayValue } from '../context/CaseContext'

interface CaseEvidenceSummaryProps {
  caseFile: CaseFile
}

function numberValue(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? String(value) : '—'
}

function moneyValue(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? `$${value.toFixed(6)}` : '—'
}

/** Read-only persisted evidence summary; it deliberately omits legacy paid_calls. */
export function CaseEvidenceSummary({ caseFile }: CaseEvidenceSummaryProps) {
  const budget = caseFile.budget ?? {}
  const heldOut = Array.isArray(caseFile.held_out_validation) ? caseFile.held_out_validation : []
  const suspectHeldOut = heldOut.filter((item) => String(item.configuration_id ?? '') === 'suspect').length
  const reviewedHeldOut = heldOut.filter((item) => String(item.configuration_id ?? '') === 'reviewed_good').length
  const triage = caseFile.triage
  const terminal = caseFile.status === 'complete' || caseFile.status === 'inconclusive'
  const live = caseFile.evidence_origin === 'live'
  return (
    <section className="panel" aria-label="Persisted evidence summary" style={{ marginBottom: 16 }}>
      <div className="section-head">
        <div>
          <h2 className="section-title" style={{ margin: 0 }}>Persisted evidence</h2>
          <p className="muted" style={{ margin: '4px 0 0' }}>Counts and limits are read from this case file; no progress is inferred.</p>
        </div>
        <span className="mono">{caseFile.evidence_origin ?? 'origin unknown'} · {caseFile.backend ?? 'backend unknown'}</span>
      </div>
      <div className="metrics-grid">
        <div className="metric-card accent-blue"><div className="metric-label">Target trials</div><div className="metric-value">{numberValue(budget.target_trials)}</div></div>
        <div className="metric-card accent-purple"><div className="metric-label">Investigator calls</div><div className="metric-value">{numberValue(budget.investigator_calls)}</div></div>
        <div className="metric-card accent-pink"><div className="metric-label">Optional Jev calls</div><div className="metric-value">{numberValue(budget.jev_calls)}</div></div>
      </div>
      <p className="muted">Limits: target ≤ {numberValue(budget.max_target_trials)} · investigator ≤ {numberValue(budget.max_investigator_calls)} · Jev ≤ {numberValue(budget.max_jev_calls)} · case ≤ {numberValue(budget.max_case_seconds)} seconds</p>
      <p><strong>Persisted stop reason:</strong> <span className="mono">{caseFile.stop_reason || 'not recorded'}</span></p>
      <p><strong>Held-out cells:</strong> suspect {suspectHeldOut} · reviewed-good {reviewedHeldOut} · total {heldOut.length}</p>
      {live && terminal ? <p><strong>Global budget snapshot (terminal):</strong> spent {moneyValue(budget.spent_usd)} · reserved {moneyValue(budget.reserved_usd)}. These values are global ledger snapshots, not case-local spend.</p> : live ? <p><strong>Global budget snapshot:</strong> final ledger snapshot pending while this case is running.</p> : <p><strong>Provider charges:</strong> simulated mode; no provider charge is recorded.</p>}
      <details>
        <summary>Held-out cell details</summary>
        {heldOut.length === 0 ? <p className="muted">No held-out rows were persisted.</p> : <div className="table-wrap"><table className="table"><thead><tr><th>Order</th><th>Configuration</th><th>Status</th><th>Checker</th></tr></thead><tbody>{heldOut.map((item, index) => { const row = item as Record<string, unknown>; const passed = row.checker_passed === true ? 'Passed' : row.checker_passed === false ? 'Failed' : 'Unknown'; return <tr key={String(row.trial_id ?? `${row.order_id ?? 'held-out'}-${index}`)}><td className="mono">{String(row.order_id ?? row.scenario_id ?? '—')}</td><td>{String(row.configuration_id ?? 'unknown')}</td><td>{String(row.status ?? 'unknown')}</td><td>{passed}</td></tr> })}</tbody></table></div>}
      </details>
      <details>
        <summary>Optional Jev triage payload (inspectable record, not proof)</summary>
        {triage ? <pre className="raw-json">{displayValue(triage)}</pre> : <p className="muted">No Jev triage payload was persisted.</p>}
      </details>
    </section>
  )
}
