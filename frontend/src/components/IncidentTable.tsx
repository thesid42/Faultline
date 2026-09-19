import { Link } from 'react-router-dom'
import { useState } from 'react'
import type { CaseSummary } from '../context/CaseContext'
import { formatCaseLabel, formatDate, shortCaseId, useCases } from '../context/CaseContext'
import { deleteCase, getCapabilities, InvestigationRequestError } from '../api/investigations'
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
  const { refresh } = useCases()
  const [pendingId, setPendingId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const rows = [...incidents].sort((left, right) => {
    const rightTime = Date.parse(right.createdtime ?? '')
    const leftTime = Date.parse(left.createdtime ?? '')
    if (Number.isNaN(rightTime) || Number.isNaN(leftTime)) return 0
    return rightTime - leftTime
  })
  const visibleRows = limit ? rows.slice(0, limit) : rows

  const onDelete = async (caseId: string, label: string) => {
    if (pendingId) return
    const confirmed = window.confirm(`Delete investigation ${label}? This removes the saved case and its evidence from the local database.`)
    if (!confirmed) return
    setPendingId(caseId)
    setError(null)
    try {
      const capabilities = await getCapabilities()
      if (!capabilities.csrf_token) throw new Error('Delete token unavailable')
      await deleteCase(caseId, capabilities.csrf_token)
      await refresh()
    } catch (cause) {
      const message = cause instanceof InvestigationRequestError
        ? cause.message
        : cause instanceof Error
          ? cause.message
          : 'Unable to delete this investigation'
      setError(message)
    } finally {
      setPendingId(null)
    }
  }

  return (
    <div className="panel table-panel">
      {error ? <p className="empty-state" role="alert" style={{ margin: 0, padding: 12 }}>{error}</p> : null}
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Investigation</th>
              <th>Evidence</th>
              <th>Status</th>
              <th>Last updated</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {visibleRows.map((incident) => {
              const running = incident.status === 'queued' || incident.status === 'investigating'
              const label = shortCaseId(incident.caseid)
              return (
                <tr key={incident.caseid}>
                  <td>
                    <strong>{friendlyProfileLabel(incident.profile)}</strong>
                    <div className="muted">Investigation {label}</div>
                  </td>
                  <td>
                    <StatusBadge label={friendlyOriginLabel(incident.evidence_origin)} tone={incident.evidence_origin === 'live' ? 'purple' : 'info'} />
                  </td>
                <td>
                    <div className="status-with-loader">
                      <StatusBadge
                        label={friendlyStatusLabel(incident.status)}
                        tone={incident.status === 'complete' ? 'success' : incident.status === 'inconclusive' ? 'failure' : 'investigating'}
                      />
                      {running ? <span className="status-spinner" aria-label="Running" /> : null}
                    </div>
                  </td>
                  <td className="muted cell-date">{formatDate(incident.createdtime)}</td>
                  <td>
                    <div className="table-actions">
                      <Link className="link-btn" to={`/investigations/${incident.caseid}`}>View results</Link>
                      <button
                        type="button"
                        className="link-btn link-btn-danger"
                        disabled={Boolean(pendingId) || running}
                        title={running ? 'Wait for the investigation to finish before deleting.' : 'Delete this saved investigation'}
                        onClick={() => void onDelete(incident.caseid, label)}
                      >
                        {pendingId === incident.caseid ? 'Deleting…' : 'Delete'}
                      </button>
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
