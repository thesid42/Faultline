import type { IncidentStatus, Severity } from '../data/mockData'

type BadgeTone = 'high' | 'medium' | 'low' | 'investigating' | 'success' | 'failure' | 'warning' | 'info' | 'purple' | 'teal'

const severityMap: Record<Severity, BadgeTone> = {
  High: 'high',
  Medium: 'medium',
  Low: 'low',
}

const statusMap: Record<IncidentStatus, BadgeTone> = {
  Investigating: 'investigating',
  'Root cause found': 'success',
  'Regression added': 'purple',
  Open: 'info',
}

interface StatusBadgeProps {
  label: string
  tone?: BadgeTone
}

export function StatusBadge({ label, tone = 'info' }: StatusBadgeProps) {
  return <span className={`badge badge-${tone}`}>{label}</span>
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  return <StatusBadge label={severity} tone={severityMap[severity]} />
}

export function IncidentStatusBadge({ status }: { status: IncidentStatus }) {
  return <StatusBadge label={status} tone={statusMap[status]} />
}
