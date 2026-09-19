import { Link } from 'react-router-dom'
import type { CaseSummary } from '../context/CaseContext'
import { formatCaseLabel, formatDate, shortCaseId } from '../context/CaseContext'
import { StatusBadge } from './StatusBadge'

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

interface IncidentTableProps {
  incidents: CaseSummary[]
  limit?: number
}

export function IncidentTable({ incidents, limit }: IncidentTableProps) {
  const rows = [...incidents].sort((left, right) => {
    const rightTime = Date.parse(right.createdtime ?? '')
    const leftTime = Date.parse(left.createdtime ?? '')
    if (Number.isNaN(rightTime) || Number.isNaN(leftTime)) return 0
    return rightTime - leftTime
  })
  const visibleRows = limit ? rows.slice(0, limit) : rows

  return (
    <div className="panel table-panel">
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Investigation</th>
              <th>Evidence</th>
              <th>Status</th>
              <th>Last updated</th>
              <th>Results</th>
            </tr>
          </thead>
          <tbody>
            {visibleRows.map((incident) => (
              <tr key={incident.caseid}>
                <td>
                  <strong>{friendlyProfileLabel(incident.profile)}</strong>
                  <div className="muted">Investigation {shortCaseId(incident.caseid)}</div>
                </td>
                <td>
                  <StatusBadge label={friendlyOriginLabel(incident.evidence_origin)} tone={incident.evidence_origin === 'live' ? 'purple' : 'info'} />
                </td>
                <td>
                  <StatusBadge
                    label={friendlyStatusLabel(incident.status)}
                    tone={incident.status === 'complete' ? 'success' : incident.status === 'inconclusive' ? 'failure' : 'investigating'}
                  />
                </td>
                <td className="muted cell-date">{formatDate(incident.createdtime)}</td>
                <td><Link className="link-btn" to={`/investigations/${incident.caseid}`}>View results</Link></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
