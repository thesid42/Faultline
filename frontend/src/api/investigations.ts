export interface Capabilities {
  profiles?: unknown[]
  modes?: unknown[]
  /** Transitional aliases accepted while older local API processes restart. */
  allowed_profiles?: unknown[]
  allowed_modes?: unknown[]
  target_model: string | null
  csrf_token: string | null
  active_case_id: string | null
  live_available?: boolean
  live_unavailable_reason?: string | null
  jev_available?: boolean
  openrouter_configured?: boolean
  jev_configured?: boolean
  daytona_configured?: boolean
  execution_backend?: string | null
}

export interface StartInvestigationPayload {
  profile: string
  mode: string
  jev: boolean
  request_id: string
}

export interface StartInvestigationResponse {
  case_id: string
  status: string
}

export class InvestigationRequestError extends Error {
  status: number
  payload: unknown

  constructor(status: number, payload: unknown) {
    super(typeof payload === 'object' && payload && 'error' in payload ? String((payload as { error?: unknown }).error) : `Faultline API returned ${status}`)
    this.name = 'InvestigationRequestError'
    this.status = status
    this.payload = payload
  }
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  const text = await response.text()
  let payload: unknown = null
  try {
    payload = text ? JSON.parse(text) : null
  } catch {
    payload = { error: 'invalid_api_response' }
  }
  if (!response.ok) throw new InvestigationRequestError(response.status, payload)
  return payload as T
}

export async function getCapabilities() {
  const payload = await requestJson<unknown>('/api/capabilities', { headers: { Accept: 'application/json' } })
  if (!payload || typeof payload !== 'object') throw new Error('Faultline API returned malformed capabilities')
  const value = payload as Record<string, unknown>
  const profiles = value.profiles ?? value.allowed_profiles
  const modes = value.modes ?? value.allowed_modes
  if (!Array.isArray(profiles) || !Array.isArray(modes) || typeof value.csrf_token !== 'string' || !value.csrf_token) {
    throw new Error('Faultline API returned incomplete capabilities')
  }
  return { ...value, profiles, modes, csrf_token: value.csrf_token } as Capabilities
}

export function startInvestigation(payload: StartInvestigationPayload, csrfToken: string) {
  return requestJson<StartInvestigationResponse>('/api/investigations', {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      'X-Faultline-Token': csrfToken,
    },
    body: JSON.stringify(payload),
  })
}

export function deleteCase(caseId: string, csrfToken: string) {
  return requestJson<{ deleted: boolean; case_id: string }>(`/api/cases/${encodeURIComponent(caseId)}`, {
    method: 'DELETE',
    headers: {
      Accept: 'application/json',
      'X-Faultline-Token': csrfToken,
    },
  })
}

export function capabilityOption(value: unknown): { value: string; label: string } | null {
  if (typeof value === 'string' && value) return { value, label: value }
  if (!value || typeof value !== 'object') return null
  const item = value as Record<string, unknown>
  const id = item.id ?? item.value ?? item.name ?? item.profile ?? item.mode
  if (typeof id !== 'string' || !id) return null
  const label = item.label ?? item.title ?? item.name ?? id
  return { value: id, label: typeof label === 'string' ? label : id }
}
