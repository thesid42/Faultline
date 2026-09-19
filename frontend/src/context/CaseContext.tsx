import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

export interface CaseSummary {
  caseid: string
  status: string | null
  profile: string | null
  evidence_origin: string | null
  createdtime: string | null
}

export interface CaseFile {
  case_id: string
  demo_profile?: string | null
  status?: string | null
  stop_reason?: string | null
  incident?: Record<string, unknown> | null
  source_run_id?: string | null
  scenarios?: Record<string, unknown>[]
  runs?: Record<string, unknown>[]
  hypotheses?: Record<string, unknown>[]
  experiments?: Record<string, unknown>[]
  experiment_results?: Record<string, unknown>[]
  observations?: Record<string, unknown>[]
  coverage?: Record<string, unknown>[]
  held_out_validation?: Record<string, unknown>[]
  proposal?: Record<string, unknown> | null
  triage?: Record<string, unknown> | null
  budget?: Record<string, unknown> | null
  backend?: string | null
  evidence_origin?: string | null
  [key: string]: unknown
}

interface CaseContextValue {
  cases: CaseSummary[]
  loading: boolean
  refreshing: boolean
  error: string | null
  refresh: () => Promise<void>
}

interface CaseDetailValue {
  caseFile: CaseFile | null
  loading: boolean
  refreshing: boolean
  error: string | null
  refresh: () => Promise<void>
}

const CaseContext = createContext<CaseContextValue | null>(null)

async function readJson<T>(url: string): Promise<T> {
  const response = await fetch(url, { headers: { Accept: 'application/json' } })
  if (!response.ok) {
    throw new Error(`Faultline API returned ${response.status}`)
  }
  return response.json() as Promise<T>
}

export function CaseProvider({ children }: { children: ReactNode }) {
  const [cases, setCases] = useState<CaseSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refresh = async () => {
    setRefreshing(true)
    try {
      const payload = await readJson<{ cases?: CaseSummary[] }>('/api/cases')
      setCases(Array.isArray(payload.cases) ? payload.cases : [])
      setError(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Unable to reach the Faultline API')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  useEffect(() => {
    void refresh()
    const interval = window.setInterval(() => void refresh(), 4000)
    return () => window.clearInterval(interval)
  }, [])

  const value = useMemo(() => ({ cases, loading, refreshing, error, refresh }), [cases, loading, refreshing, error])
  return <CaseContext.Provider value={value}>{children}</CaseContext.Provider>
}

export function useCases() {
  const value = useContext(CaseContext)
  if (!value) throw new Error('useCases must be used within CaseProvider')
  return value
}

export function useCase(caseId: string | undefined): CaseDetailValue {
  const [caseFile, setCaseFile] = useState<CaseFile | null>(null)
  const [loading, setLoading] = useState(Boolean(caseId))
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const requestVersion = useRef(0)

  const refresh = async () => {
    if (!caseId) {
      setCaseFile(null)
      setLoading(false)
      return
    }
    const version = ++requestVersion.current
    setRefreshing(true)
    try {
      const payload = await readJson<CaseFile>(`/api/cases/${encodeURIComponent(caseId)}`)
      if (version !== requestVersion.current) return
      setCaseFile(payload)
      setError(null)
    } catch (cause) {
      if (version !== requestVersion.current) return
      setError(cause instanceof Error ? cause.message : 'Unable to load this case')
    } finally {
      if (version === requestVersion.current) {
        setLoading(false)
        setRefreshing(false)
      }
    }
  }

  useEffect(() => {
    requestVersion.current += 1
    setCaseFile(null)
    setError(null)
    setLoading(Boolean(caseId))
    void refresh()
    if (!caseId) return
    const interval = window.setInterval(() => void refresh(), 4000)
    return () => window.clearInterval(interval)
  }, [caseId])

  return { caseFile, loading, refreshing, error, refresh }
}

export function formatCaseLabel(value: string | null | undefined) {
  if (!value) return 'Untitled case'
  return value.replace(/[-_]+/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
}

export function formatDate(value: unknown) {
  if (!value) return '—'
  const raw = String(value)
  // ArtifactStore timestamps are SQLite UTC values without an offset.
  const normalized = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(raw) ? `${raw.replace(' ', 'T')}Z` : raw
  const date = new Date(normalized)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString()
}

export function displayValue(value: unknown) {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'string') return value
  return JSON.stringify(value, null, 2)
}
