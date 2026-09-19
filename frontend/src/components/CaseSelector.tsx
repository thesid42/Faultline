import { Link } from 'react-router-dom'
import { useNavigate, useLocation } from 'react-router-dom'
import type { CaseSummary } from '../context/CaseContext'
import { formatCaseLabel, shortCaseId } from '../context/CaseContext'

function friendlyProfileLabel(value: string | null | undefined) {
  if (value === 'memory-conflict') return 'Conflicting policy information'
  if (value === 'amount-unit') return 'Refund amount mismatch'
  if (value === 'duplicate-refund') return 'Repeated refund request'
  return formatCaseLabel(value, null)
}

function friendlyStatusLabel(value: string | null | undefined) {
  if (value === 'complete') return 'Finished'
  if (value === 'investigating') return 'Running'
  if (value === 'queued') return 'Waiting'
  if (value === 'inconclusive') return 'Needs attention'
  return value ? formatCaseLabel(value, null) : 'Unknown'
}

function friendlyOriginLabel(value: string | null | undefined) {
  if (value === 'live') return 'Real AI'
  if (value === 'simulated') return 'Practice'
  return 'Unknown'
}

interface CaseSelectorProps {
  cases: CaseSummary[]
  selectedId?: string
  onChange: (caseId: string) => void
  unknownId?: string | null
}

/** Shared URL-backed investigation selection for evidence pages. */
export function CaseSelector({ cases, selectedId, onChange, unknownId }: CaseSelectorProps) {
  const selected = cases.find((item) => item.caseid === selectedId)
  return (
    <div className="panel case-selector">
      <div className="case-selector-row">
        <div className="case-selector-copy">
          <label className="label" htmlFor="investigation-select">Investigation</label>
          <div className="muted">Choose an investigation to review.</div>
        </div>
        <select
          id="investigation-select"
          aria-label="Investigation"
          className="case-select"
          value={selectedId ?? ''}
          onChange={(event) => onChange(event.target.value)}
          disabled={cases.length === 0}
        >
          <option value="" disabled>
            {cases.length === 0 ? 'No saved investigations' : 'Choose an investigation'}
          </option>
          {cases.map((item) => (
            <option key={item.caseid} value={item.caseid}>
              {friendlyProfileLabel(item.profile)} · {friendlyOriginLabel(item.evidence_origin)} · {shortCaseId(item.caseid)}
            </option>
          ))}
        </select>
      </div>
      {unknownId ? (
        <p className="empty-state case-selector-alert" role="alert">
          We couldn’t find investigation <span className="mono">{shortCaseId(unknownId)}</span>. Choose another investigation.
        </p>
      ) : null}
      {selected ? (
        <p className="muted case-selector-meta">
          {friendlyProfileLabel(selected.profile)} · <span className="mono" title={selected.caseid}>{shortCaseId(selected.caseid)}</span> · {friendlyOriginLabel(selected.evidence_origin)} · {friendlyStatusLabel(selected.status)}
          {selectedId ? (
            <>
              {' '}
              · <Link to={`/investigations/${selectedId}`}>View results</Link>
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
