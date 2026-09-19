import { Link } from 'react-router-dom'
import { useNavigate, useLocation } from 'react-router-dom'
import type { CaseSummary } from '../context/CaseContext'
import { formatCaseLabel, shortCaseId } from '../context/CaseContext'

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
    <div className="panel case-selector">
      <div className="case-selector-row">
        <div className="case-selector-copy">
          <div className="label">Selected case</div>
          <div className="muted">URL selection is preserved while the API refreshes.</div>
        </div>
        <select
          aria-label="Select case"
          className="case-select"
          value={selectedId ?? ''}
          onChange={(event) => onChange(event.target.value)}
          disabled={cases.length === 0}
        >
          <option value="" disabled>
            {cases.length === 0 ? 'No persisted cases' : 'Select a case'}
          </option>
          {cases.map((item) => (
            <option key={item.caseid} value={item.caseid}>
              {formatCaseLabel(item.profile, item.caseid)} · {shortCaseId(item.caseid)} · {item.evidence_origin ?? 'unknown'} · {item.status ?? 'unknown'}
            </option>
          ))}
        </select>
      </div>
      {unknownId ? (
        <p className="empty-state case-selector-alert" role="alert">
          Requested case <span className="mono">{shortCaseId(unknownId)}</span> was not returned by the API.
        </p>
      ) : null}
      {selected ? (
        <p className="muted case-selector-meta">
          {formatCaseLabel(selected.profile, selected.caseid)} · <span className="mono" title={selected.caseid}>{shortCaseId(selected.caseid)}</span> · {selected.evidence_origin ?? 'unknown'} · {selected.status ?? 'unknown'}
          {selectedId ? (
            <>
              {' '}
              · <Link to={`/investigations/${selectedId}`}>Open case</Link>
            </>
          ) : null}
        </p>
      ) : null}
    </div>
  )
}

export function useCaseSelection(cases: CaseSummary[]) {
  const location = useLocation()
  const navigate = useNavigate()
  const params = new URLSearchParams(location.search)
  const requestedId = params.get('case')
  const latestId = cases[cases.length - 1]?.caseid
  const selectedId = requestedId && cases.some((item) => item.caseid === requestedId) ? requestedId : requestedId ? undefined : latestId
  const unknownId = requestedId && !cases.some((item) => item.caseid === requestedId) ? requestedId : null

  const selectCase = (caseId: string) => {
    const next = new URLSearchParams(location.search)
    next.set('case', caseId)
    navigate({ pathname: location.pathname, search: `?${next.toString()}` })
  }

  return { selectedId: selectedId ?? (unknownId ? undefined : latestId), requestedId, unknownId, selectCase }
}
