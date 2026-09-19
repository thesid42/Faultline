import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { capabilityOption, getCapabilities, InvestigationRequestError, startInvestigation, type Capabilities, type StartInvestigationPayload } from '../api/investigations'

interface NewInvestigationDialogProps {
  open: boolean
  onClose: () => void
}

function requestId() {
  return crypto.randomUUID()
}

export function NewInvestigationDialog({ open, onClose }: NewInvestigationDialogProps) {
  const navigate = useNavigate()
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null)
  const [loadingCapabilities, setLoadingCapabilities] = useState(false)
  const [capabilityError, setCapabilityError] = useState<string | null>(null)
  const [profile, setProfile] = useState('')
  const [mode, setMode] = useState('')
  const [jev, setJev] = useState(false)
  const [pending, setPending] = useState(false)
  const [retrying, setRetrying] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [activeCaseId, setActiveCaseId] = useState<string | null>(null)
  const retryPayload = useRef<StartInvestigationPayload | null>(null)
  const dialogRef = useRef<HTMLDivElement>(null)

  const advertisedProfiles = capabilities?.profiles ?? capabilities?.allowed_profiles ?? []
  const advertisedModes = capabilities?.modes ?? capabilities?.allowed_modes ?? []
  const profileOptions = advertisedProfiles.map(capabilityOption).filter((item): item is { value: string; label: string } => item !== null)
  const modeOptions = advertisedModes.map(capabilityOption).filter((item): item is { value: string; label: string } => item !== null)
  const liveMode = mode === 'live'
  const liveAvailable = capabilities?.live_available !== false

  useEffect(() => {
    if (!open) return
    let cancelled = false
    setLoadingCapabilities(true)
    setCapabilityError(null)
      setError(null)
      setActiveCaseId(null)
      setRetrying(false)
      setJev(false)
      retryPayload.current = null
    void getCapabilities().then((value) => {
      if (cancelled) return
      setCapabilities(value)
      const profiles = (value.profiles ?? value.allowed_profiles ?? []).map(capabilityOption).filter((item): item is { value: string; label: string } => item !== null)
      const modes = (value.modes ?? value.allowed_modes ?? []).map(capabilityOption).filter((item): item is { value: string; label: string } => item !== null)
      setProfile(profiles.find((item) => item.value === 'amount-unit')?.value ?? profiles[0]?.value ?? '')
      setMode(modes.find((item) => item.value === 'simulated')?.value ?? modes[0]?.value ?? '')
      if (value.active_case_id) setActiveCaseId(value.active_case_id)
    }).catch((cause) => {
      if (!cancelled) setCapabilityError(cause instanceof Error ? cause.message : 'Unable to load capabilities')
    }).finally(() => {
      if (!cancelled) setLoadingCapabilities(false)
    })
    return () => { cancelled = true }
  }, [open])

  useEffect(() => {
    if (!open) return
    const handleKeyboard = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !pending) {
        event.preventDefault()
        onClose()
        return
      }
      if (event.key !== 'Tab' || !dialogRef.current) return
      const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>('button:not([disabled]), select:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])'))
      if (focusable.length === 0) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    window.addEventListener('keydown', handleKeyboard)
    const firstFocusable = dialogRef.current?.querySelector<HTMLElement>('button:not([disabled]), select:not([disabled]), input:not([disabled])')
    firstFocusable?.focus()
    return () => window.removeEventListener('keydown', handleKeyboard)
  }, [open, pending, onClose])

  if (!open) return null

  const submit = async () => {
    if (!capabilities?.csrf_token || !profile || !mode || pending) return
    const payload = retryPayload.current ?? { profile, mode, jev: liveMode && jev, request_id: requestId() }
    retryPayload.current = payload
    setPending(true)
    setError(null)
    try {
      const result = await startInvestigation(payload, capabilities.csrf_token)
      if (!result || typeof result.case_id !== 'string' || !result.case_id) {
        throw new Error('Faultline API returned no queued case identifier')
      }
      retryPayload.current = null
      setRetrying(false)
      navigate(`/investigations/${encodeURIComponent(result.case_id)}`)
      onClose()
    } catch (cause) {
      setRetrying(true)
      if (cause instanceof InvestigationRequestError && cause.status === 409) {
        const payload = cause.payload
        const existing = payload && typeof payload === 'object' && typeof (payload as { active_case_id?: unknown }).active_case_id === 'string' ? (payload as { active_case_id: string }).active_case_id : capabilities.active_case_id
        setActiveCaseId(existing ?? null)
        setError('An active investigation is already running. Open it instead of starting a duplicate.')
      } else {
        // Preserve retryPayload and its request_id. A network failure is
        // ambiguous: retrying must reuse the exact same request envelope.
        setError(cause instanceof Error ? cause.message : 'Unable to start investigation')
      }
    } finally {
      setPending(false)
    }
  }

  return <div className="dialog-backdrop" role="presentation">
    <div ref={dialogRef} className="dialog investigation-dialog" role="dialog" aria-modal="true" aria-labelledby="new-investigation-title">
      <div className="section-head"><div><h3 id="new-investigation-title">New investigation</h3><p className="muted">Choose a registered Faultline profile and execution mode.</p></div><button type="button" className="icon-btn" onClick={onClose} disabled={pending} aria-label="Close">×</button></div>
      {loadingCapabilities ? <div className="dialog-loading">Loading registered capabilities…</div> : null}
      {capabilityError ? <div className="dialog-error">{capabilityError}</div> : null}
      {!loadingCapabilities && !capabilityError && capabilities ? <>
        <label className="dialog-field" htmlFor="new-profile">Profile<select id="new-profile" aria-label="Profile" value={profile} onChange={(event) => setProfile(event.target.value)} disabled={pending || retrying || profileOptions.length === 0}>{profileOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
        <fieldset className="dialog-fieldset"><legend>Execution mode</legend>{modeOptions.map((item) => <label className="dialog-choice" key={item.value}><input type="radio" name="investigation-mode" value={item.value} checked={mode === item.value} onChange={() => setMode(item.value)} disabled={pending || retrying || (item.value === 'live' && !liveAvailable)} /><span><strong>{item.value === 'live' ? `Live · ${capabilities.target_model ?? 'registered target'}` : item.label}</strong><small>{item.value === 'live' ? (liveAvailable ? 'Paid Groq target; bounded by the approved aggregate cap.' : (capabilities.live_unavailable_reason ?? 'Live credentials are unavailable.')) : 'Deterministic local run; no provider charge.'}</small></span></label>)}</fieldset>
        {liveMode ? <label className="dialog-checkbox"><input type="checkbox" checked={jev} onChange={(event) => setJev(event.target.checked)} disabled={pending || retrying || capabilities.jev_available === false} /> Optional Jev triage call{capabilities.jev_available === false ? ' (unavailable)' : ''}</label> : null}
        <div className="capability-note">{liveMode ? `Live guardrails: $0.10 aggregate target cap, $2 automatic pause, $10 hard ceiling, and $1 per-case ceiling. Runs continue in the background for up to 10 minutes; these limits cannot be changed here.${profile === 'memory-conflict' ? ' Memory-conflict is an experimental profile and may be inconclusive.' : ''}` : 'Simulated mode uses the local fixed worker and does not spend provider budget.'}</div>
      </> : null}
      {error ? <div className="dialog-error">{error}</div> : null}
      {activeCaseId ? <button type="button" className="btn btn-secondary" onClick={() => { navigate(`/investigations/${encodeURIComponent(activeCaseId)}`); onClose() }}>Open existing investigation</button> : null}
      <div className="dialog-actions"><button type="button" className="btn btn-secondary" onClick={onClose} disabled={pending}>Cancel</button><button type="button" className="btn btn-primary" onClick={() => void submit()} disabled={pending || loadingCapabilities || Boolean(capabilityError) || Boolean(activeCaseId) || !capabilities?.csrf_token || !profile || !mode}>{pending ? 'Starting…' : retrying ? 'Retry start' : 'Start investigation'}</button></div>
    </div>
  </div>
}
