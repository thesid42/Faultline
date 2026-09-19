import { useEffect, useState } from 'react'
import { PageHeader } from '../components/PageHeader'
import { StatusBadge } from '../components/StatusBadge'
import { capabilityOption, getCapabilities, type Capabilities } from '../api/investigations'

function configuredLabel(value: boolean | undefined) {
  if (value === true) return 'Configured · connectivity not verified'
  if (value === false) return 'Missing or unavailable'
  return 'Unknown · restart API'
}

function configuredTone(value: boolean | undefined) {
  return value === true ? 'success' as const : value === false ? 'failure' as const : 'warning' as const
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

  return <div>
    <PageHeader title="Settings" subtitle="Runtime integration status from the local capabilities API." />
    {loading ? <div className="panel empty-state">Loading integration capabilities…</div> : null}
    {!loading && error ? <div className="panel empty-state"><strong>Capabilities unavailable.</strong><br />{error}</div> : null}
    {!loading && !error && capabilities ? <div className="settings-stack">
      <section className="panel">
        <div className="section-head"><div><h2 className="section-title" style={{ margin: 0 }}>Local runtime</h2><p className="muted">The UI reads capabilities and case evidence; it never receives provider secrets.</p></div><StatusBadge label="API connected" tone="success" /></div>
        <div className="case-meta-grid">
          <div><span className="metric-label">Execution backend</span><strong>{capabilities.execution_backend ?? 'local-subprocess'}</strong></div>
          <div><span className="metric-label">Fixed target model</span><strong className="mono">{capabilities.target_model ?? 'not advertised'}</strong></div>
          <div><span className="metric-label">Active job</span><strong className="mono">{capabilities.active_case_id ?? 'none'}</strong></div>
          <div><span className="metric-label">Daytona</span><StatusBadge label={configuredLabel(capabilities.daytona_configured)} tone={configuredTone(capabilities.daytona_configured)} /></div>
        </div>
      </section>
      <section className="panel">
        <h2 className="section-title">Provider configuration</h2>
        <div className="stack-list">
          <div><span>OpenRouter key</span><StatusBadge label={configuredLabel(liveConfigured)} tone={configuredTone(liveConfigured)} /></div>
          <div><span>Jev key</span><StatusBadge label={configuredLabel(jevConfigured)} tone={configuredTone(jevConfigured)} /></div>
        </div>
        <p className="muted" style={{ marginBottom: 0 }}>Configured indicators come from the backend environment only; no provider connectivity test is performed here.</p>
      </section>
      <section className="panel">
        <h2 className="section-title">Registered launch options</h2>
        <div className="case-meta-grid">
          <div><span className="metric-label">Profiles</span><strong>{profiles.length ? profiles.map((item) => item.label).join(' · ') : 'none advertised'}</strong></div>
          <div><span className="metric-label">Modes</span><strong>{modes.length ? modes.map((item) => item.label).join(' · ') : 'none advertised'}</strong></div>
        </div>
        <p className="muted" style={{ marginBottom: 0 }}>Launch a queued run from New investigation. Approval, export, and provider tests remain outside this dashboard.</p>
      </section>
    </div> : null}
  </div>
}
