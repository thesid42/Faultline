import { useEffect, useState } from 'react'
import { PageHeader } from '../components/PageHeader'
import { StatusBadge } from '../components/StatusBadge'
import { capabilityOption, getCapabilities, type Capabilities } from '../api/investigations'
import { formatCaseLabel, shortCaseId } from '../context/CaseContext'

function friendlyProfileLabel(value: string) {
  if (value === 'memory-conflict') return 'Conflicting policy information'
  if (value === 'amount-unit') return 'Refund amount mismatch'
  if (value === 'duplicate-refund') return 'Repeated refund request'
  return formatCaseLabel(value, null)
}

function configuredLabel(value: boolean | undefined) {
  if (value === true) return 'Key found · connection not tested'
  if (value === false) return 'Missing or unavailable'
  return 'Unknown · restart API'
}

function configuredTone(value: boolean | undefined) {
  return value === true ? 'success' as const : value === false ? 'failure' as const : 'warning' as const
}

function friendlyModeLabel(value: string) {
  if (value === 'simulated') return 'Practice'
  if (value === 'live') return 'Real AI'
  return value
}

export function SettingsPage() {
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    void getCapabilities().then((value) => {
      if (!cancelled) {
        setCapabilities(value)
        setError(null)
      }
    }).catch((cause) => {
      if (!cancelled) setError(cause instanceof Error ? cause.message : 'Unable to load capabilities')
    }).finally(() => {
      if (!cancelled) setLoading(false)
    })
    return () => { cancelled = true }
  }, [])

  const profiles = (capabilities?.profiles ?? capabilities?.allowed_profiles ?? []).map(capabilityOption).filter((item): item is { value: string; label: string } => item !== null)
  const modes = (capabilities?.modes ?? capabilities?.allowed_modes ?? []).map(capabilityOption).filter((item): item is { value: string; label: string } => item !== null)
  const liveConfigured = capabilities?.openrouter_configured ?? capabilities?.live_available
  const jevConfigured = capabilities?.jev_configured ?? capabilities?.jev_available

  return <div className="page-shell">
    <PageHeader title="Connections" subtitle="How this local UI connects to Faultline." />
    {loading ? <div className="panel empty-state">Loading integration capabilities…</div> : null}
    {!loading && error ? <div className="panel empty-state"><strong>Capabilities unavailable.</strong><br />{error}</div> : null}
    {!loading && !error && capabilities ? <div className="settings-stack">
      <section className="panel">
        <div className="section-head"><div><h2 className="section-title" style={{ margin: 0 }}>Faultline API</h2><p className="muted">The API is running locally. It keeps provider keys on the server and supplies case data and launch options to this UI.</p></div><StatusBadge label="API connected" tone="success" /></div>
        <div className="case-meta-grid">
          <div><span className="metric-label">Practice runner</span><strong>Local worker</strong></div>
          <div><span className="metric-label">Live target</span><strong className="mono cell-id" title={capabilities.target_model ?? ''}>{capabilities.target_model ?? 'not advertised'}</strong></div>
          <div><span className="metric-label">Active job</span><strong className="mono">{capabilities.active_case_id ? shortCaseId(capabilities.active_case_id) : 'none'}</strong></div>
          <div><span className="metric-label">Daytona</span><StatusBadge label={capabilities.daytona_configured === true ? 'CLI only' : capabilities.daytona_configured === false ? 'Not configured' : 'Unknown'} tone={capabilities.daytona_configured === true ? 'info' : capabilities.daytona_configured === false ? 'warning' : 'warning'} /></div>
        </div>
      </section>
      <section className="panel">
        <h2 className="section-title">Server configuration</h2>
        <div className="stack-list">
          <div><span>OpenRouter access</span><StatusBadge label={configuredLabel(liveConfigured)} tone={configuredTone(liveConfigured)} /></div>
          <div><span>Optional second opinion (Jev)</span><StatusBadge label={configuredLabel(jevConfigured)} tone={configuredTone(jevConfigured)} /></div>
        </div>
        <p className="muted" style={{ marginBottom: 0 }}>Configured means a backend setting is present. This page does not test provider connectivity. Keep secrets in the repository `.env` on the server; use `.env.example` as the safe template and never paste keys into the browser.</p>
      </section>
      <section className="panel">
        <h2 className="section-title">Registered launch options</h2>
        <div className="case-meta-grid">
          <div><span className="metric-label">Profiles</span><strong>{profiles.length ? profiles.map((item) => friendlyProfileLabel(item.value)).join(' · ') : 'none advertised'}</strong></div>
          <div><span className="metric-label">Modes</span><strong>{modes.length ? modes.map((item) => friendlyModeLabel(item.value)).join(' · ') : 'none advertised'}</strong></div>
        </div>
        <p className="muted" style={{ marginBottom: 0 }}>You can try the synthetic ReturnDesk demo now. Practice runs use the local worker; live runs use the registered target and limits. Daytona launches are CLI-only. To use your own agent, a developer must add a Python adapter and an independent checker.</p>
      </section>
    </div> : null}
  </div>
}
