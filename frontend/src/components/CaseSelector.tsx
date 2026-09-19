import { useNavigate, useLocation } from 'react-router-dom'
import type { CaseSummary } from '../context/CaseContext'
import { formatCaseLabel } from '../context/CaseContext'

interface CaseSelectorProps {
  cases: CaseSummary[]
  selectedId?: string
  onChange: (caseId: string) => void
  unknownId?: string | null
}

/** Shared URL-backed case selection for read-only evidence pages. */
export function CaseSelector({ cases, selectedId, onChange, unknownId }: CaseSelectorProps) {
  const selected = cases.find((item) => item.caseid === selectedId)
  return (
    <div className="panel" style={{ marginBottom: 16 }}>
      <div className="section-head" style={{ alignItems: 'center', marginBottom: 8 }}>
        <div>
          <div className="label">Selected case</div>
          <div className="muted">The URL `?case=` selection is preserved while the API refreshes.</div>
        </div>
        <select
          aria-label="Select case"
          value={selectedId ?? ''}
          onChange={(event) => onChange(event.target.value)}
          disabled={cases.length === 0}
          style={{ minWidth: 300, padding: '9px 12px', border: '1px solid var(--border)', borderRadius: 8, background: 'var(--surface)', color: 'var(--text)' }}
        >
          <option value="" disabled>{cases.length === 0 ? 'No persisted cases' : 'Select a case'}</option>
          {cases.map((item) => (
            <option key={item.caseid} value={item.caseid}>
              {formatCaseLabel(item.profile)} · {item.caseid} · {item.evidence_origin ?? 'origin unknown'} · {item.status ?? 'status unknown'}
            </option>
          ))}
        </select>
      </div>
      {unknownId ? <p className="empty-state" role="alert" style={{ margin: '10px 0 0', padding: 12 }}>Requested case <span className="mono">{unknownId}</span> was not returned by the API. No latest-case fallback was selected.</p> : null}
      {selected ? <p className="muted" style={{ margin: 0 }}>Profile: {formatCaseLabel(selected.profile)} · ID: <span className="mono">{selected.caseid}</span> · Origin: {selected.evidence_origin ?? 'unknown'} · Status: {selected.status ?? 'unknown'}</p> : null}
    </div>
  )
}

export function useCaseSelection(cases: CaseSummary[]) {
  const location = useLocation()
  const navigate = useNavigate()
  const params = new URLSearchParams(location.search)
  const requestedId = params.get('case')
  const latestId = cases[cases.length - 1]?.caseid
  const selectedId = requestedId ?? latestId
  const unknownId = requestedId && !cases.some((item) => item.caseid === requestedId) ? requestedId : null

  const selectCase = (caseId: string) => {
    const next = new URLSearchParams(location.search)
    next.set('case', caseId)
    navigate({ pathname: location.pathname, search: `?${next.toString()}` })
  }

  return { selectedId, requestedId, unknownId, selectCase }
}
