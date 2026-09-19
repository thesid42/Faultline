import { useNavigate } from 'react-router-dom'
import type { CaseSummary } from '../context/CaseContext'
import { formatCaseLabel, formatDate, shortCaseId } from '../context/CaseContext'
import { StatusBadge } from './StatusBadge'

interface IncidentTableProps {
  incidents: CaseSummary[]
  limit?: number
}

export function IncidentTable({ incidents, limit }: IncidentTableProps) {
  const navigate = useNavigate()
  const rows = limit ? incidents.slice(0, limit) : incidents

  return (
    <div className="panel table-panel">
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Case</th>
              <th>Profile</th>
              <th>Origin</th>
              <th>Status</th>
              <th>Last updated</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((incident) => (
              <tr key={incident.caseid} onClick={() => navigate(`/investigations/${incident.caseid}`)}>
                <td>
                  <span className="mono cell-id" title={incident.caseid}>
                    #{shortCaseId(incident.caseid)}
                  </span>
                </td>
                <td>{formatCaseLabel(incident.profile, incident.caseid)}</td>
                <td>
                  <StatusBadge label={incident.evidence_origin ?? 'unknown'} tone="info" />
                </td>
                <td>
                  <StatusBadge
                    label={incident.status ?? 'unknown'}
                    tone={incident.status === 'complete' ? 'success' : incident.status === 'inconclusive' ? 'failure' : 'investigating'}
                  />
                </td>
                <td className="muted cell-date">{formatDate(incident.createdtime)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
