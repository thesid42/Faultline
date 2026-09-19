import { useNavigate } from 'react-router-dom'
import type { Incident } from '../data/mockData'
import { IncidentStatusBadge, SeverityBadge } from './StatusBadge'

interface IncidentTableProps {
  incidents: Incident[]
  limit?: number
}

export function IncidentTable({ incidents, limit }: IncidentTableProps) {
  const navigate = useNavigate()
  const rows = limit ? incidents.slice(0, limit) : incidents

  return (
    <div className="panel" style={{ padding: 0 }}>
      <table className="table">
        <thead>
          <tr>
            <th>ID</th>
            <th>Incident</th>
            <th>Severity</th>
            <th>Status</th>
            <th>Created</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((incident) => (
            <tr key={incident.id} onClick={() => navigate(`/investigations/${incident.id}`)}>
              <td className="mono">#{incident.id}</td>
              <td>{incident.title}</td>
              <td>
                <SeverityBadge severity={incident.severity} />
              </td>
              <td>
                <IncidentStatusBadge status={incident.status} />
              </td>
              <td className="muted">{incident.created}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
