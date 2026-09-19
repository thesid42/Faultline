// TODO: Connect Faultline backend — replace mock objects with ArtifactStore / API responses

export type Severity = 'High' | 'Medium' | 'Low'
export type IncidentStatus = 'Investigating' | 'Root cause found' | 'Regression added' | 'Open'

export interface Incident {
  id: string
  title: string
  severity: Severity
  status: IncidentStatus
  created: string
  model: string
  origin: 'Simulated' | 'Live'
}

export interface HomeMetrics {
  totalIncidents: number
  investigating: number
  rootCausesFound: number
  regressionTests: number
  sparklines: {
    incidents: number[]
    investigating: number[]
    rootCauses: number[]
    regression: number[]
  }
  deltas: {
    incidents: string
    investigating: string
    rootCauses: string
    regression: string
  }
}

export type TraceStepStatus = 'success' | 'failed' | 'downstream'

export interface TraceStep {
  id: string
  order: number
  name: string
  status: TraceStepStatus
  duration: string
  input?: string
  retrievedContext?: {
    title: string
    body: string
    source: string
    retrievedAt: string
  }
  policy?: {
    title: string
    body: string
    source: string
    version: string
  }
  output?: string
  keyFinding?: string
}

export interface ExecutionTrace {
  incidentId: string
  steps: TraceStep[]
  policyViolation: string
}

export type HypothesisStatus = 'Rejected' | 'Supported' | 'Open'

export interface HypothesisExperimentLink {
  label: string
  result: string
  kind: 'pass' | 'impact' | 'neutral'
}

export interface Hypothesis {
  id: string
  title: string
  status: HypothesisStatus
  statement: string
  confidence: number
  evidence: string
  experiments: HypothesisExperimentLink[]
}

export type ExperimentKind = 'Causal Test' | 'Control Test'
export type ExperimentTab = 'all' | 'causal' | 'control'

export interface ExperimentComparison {
  label: string
  orderAge?: string
  memory: string
  result: string
  outcome: 'violation' | 'safe'
}

export interface Experiment {
  id: string
  code: string
  title: string
  kind: ExperimentKind
  description: string
  before: ExperimentComparison
  after: ExperimentComparison
  runsPassed: number
  runsTotal: number
  signal: string
  signalPositive: boolean
}

export interface ExperimentChartRow {
  name: string
  safe: number
  violations: number
}

export interface CoverageBar {
  label: string
  percent: number
}

export type MatrixCell = 'pass' | 'fail' | 'partial'

export interface CoverageMatrixRow {
  label: string
  cells: MatrixCell[]
}

export interface CoverageData {
  bars: CoverageBar[]
  gap: {
    id: string
    percent: number
    description: string
  }
  matrixColumns: string[]
  matrixRows: CoverageMatrixRow[]
}

export interface RegressionCase {
  title: string
  accent: 'failure' | 'control'
  orderAge: string
  memory: string
  expected: string
  observed: string
  observedLabel: string
}

export interface RegressionProposal {
  status: 'Pending human review' | 'Approved'
  failure: RegressionCase
  control: RegressionCase
  heldOutPassed: number
  heldOutTotal: number
}

export type ProgressState = 'completed' | 'current' | 'future'

export interface ProgressStep {
  label: string
  state: ProgressState
}

export const currentUser = {
  name: 'Aarsh',
  initials: 'AA',
}

/** Rotating homepage hero copy — picked by day of week (stable for a session day). */
export const heroCopyOptions = [
  {
    title: 'Find the fault.\nFix the future.',
    subtitle: 'Autonomous investigation for AI agents that fail in the wild.',
  },
  {
    title: 'Trace every failure\nto its cause.',
    subtitle: 'From incident to root cause, coverage gap, and regression test.',
  },
  {
    title: 'Prove what broke.\nPrevent it next.',
    subtitle: 'Causal experiments that turn hypotheses into eval coverage.',
  },
  {
    title: 'Reliability starts\nwhere agents slip.',
    subtitle: 'Investigate incidents, run controlled tests, and ship stronger evals.',
  },
  {
    title: 'Where agents crack,\nFaultline holds.',
    subtitle: 'Evidence-backed findings ready for human review.',
  },
] as const

export function getHeroCopy(date = new Date()) {
  return heroCopyOptions[date.getDay() % heroCopyOptions.length]
}

export const homeMetrics: HomeMetrics = {
  totalIncidents: 12,
  investigating: 7,
  rootCausesFound: 4,
  regressionTests: 18,
  sparklines: {
    incidents: [4, 5, 6, 7, 8, 9, 10, 11, 12],
    investigating: [2, 3, 4, 5, 6, 5, 6, 7, 7],
    rootCauses: [0, 1, 1, 2, 2, 3, 3, 4, 4],
    regression: [8, 10, 11, 12, 14, 15, 16, 17, 18],
  },
  deltas: {
    incidents: '+2 this week',
    investigating: '+1 today',
    rootCauses: '+1 yesterday',
    regression: '+3 this week',
  },
}

export const incidents: Incident[] = [
  {
    id: '021',
    title: 'Unauthorized refund issued',
    severity: 'High',
    status: 'Investigating',
    created: 'Sep 19, 10:42 AM',
    model: 'gpt-4o',
    origin: 'Simulated',
  },
  {
    id: '020',
    title: 'Incorrect order status',
    severity: 'Medium',
    status: 'Root cause found',
    created: 'Sep 18, 4:21 PM',
    model: 'gpt-4o',
    origin: 'Simulated',
  },
  {
    id: '019',
    title: 'Policy bypass via note',
    severity: 'High',
    status: 'Regression added',
    created: 'Sep 17, 2:11 PM',
    model: 'gpt-4o',
    origin: 'Simulated',
  },
  {
    id: '018',
    title: 'Duplicate tool call on cancel',
    severity: 'Low',
    status: 'Open',
    created: 'Sep 16, 11:05 AM',
    model: 'gpt-4o-mini',
    origin: 'Simulated',
  },
  {
    id: '017',
    title: 'Stale shipping estimate',
    severity: 'Medium',
    status: 'Root cause found',
    created: 'Sep 15, 9:30 AM',
    model: 'gpt-4o',
    origin: 'Simulated',
  },
]

export const featuredIncident = incidents[0]

export const executionTrace: ExecutionTrace = {
  incidentId: '021',
  steps: [
    {
      id: 'step-1',
      order: 1,
      name: 'retrieve_order',
      status: 'success',
      duration: '1.2s',
      input: '{"order_id": "ORD-88421"}',
      output: '{"age_days": 21, "status": "delivered"}',
    },
    {
      id: 'step-2',
      order: 2,
      name: 'retrieve_policy',
      status: 'success',
      duration: '0.8s',
      input: '{"policy": "refunds"}',
      output: '{"window_days": 14, "version": "v2.3"}',
      policy: {
        title: 'Current Policy',
        body: 'Refunds allowed within 14 days of order date.',
        source: 'policy_store',
        version: 'v2.3',
      },
    },
    {
      id: 'step-3',
      order: 3,
      name: 'retrieve_notes',
      status: 'failed',
      duration: '1.4s',
      input: '{"order_id": "ORD-88421", "note_type": "customer"}',
      retrievedContext: {
        title: 'Customer Note (retrieved)',
        body: 'Customer is eligible for 30-day refund window.\nVIP customer, be flexible.',
        source: 'customer_notes_db',
        retrievedAt: 'Sep 19, 10:42:01 AM',
      },
      policy: {
        title: 'Current Policy',
        body: 'Refunds allowed within 14 days of order date.',
        source: 'policy_store',
        version: 'v2.3',
      },
      output: '{"notes": [{"text": "30-day refund window", "obsolete": true}]}',
      keyFinding: 'A retrieved customer note conflicts with the current 14-day policy.',
    },
    {
      id: 'step-4',
      order: 4,
      name: 'choose_action',
      status: 'downstream',
      duration: '0.6s',
      input: '{"candidates": ["REFUND", "DENY"]}',
      output: '{"action": "REFUND", "reason": "VIP note override"}',
    },
    {
      id: 'step-5',
      order: 5,
      name: 'issue_refund',
      status: 'downstream',
      duration: '0.3s',
      input: '{"order_id": "ORD-88421", "amount": 89.0}',
      output: '{"status": "issued", "refund_id": "RF-9912"}',
    },
  ],
  policyViolation: 'Refund issued for an ineligible order.',
}

export const hypotheses: Hypothesis[] = [
  {
    id: 'H-01',
    title: 'Policy mismatch',
    status: 'Rejected',
    statement: 'The agent used an outdated policy version.',
    confidence: 18,
    evidence: '0/3 experiments',
    experiments: [],
  },
  {
    id: 'H-03',
    title: 'Memory Conflict',
    status: 'Supported',
    statement: 'A retrieved customer note changes the decision.',
    confidence: 87,
    evidence: '3/3 experiments',
    experiments: [
      { label: 'Remove obsolete note', result: '3/3 pass', kind: 'pass' },
      { label: 'Change unrelated note', result: '0/3 impact', kind: 'impact' },
    ],
  },
  {
    id: 'H-02',
    title: 'Execution/tool failure',
    status: 'Open',
    statement: 'A tool returned malformed data that skewed the action.',
    confidence: 34,
    evidence: '1/3 experiments',
    experiments: [],
  },
]

export const experiments: Experiment[] = [
  {
    id: 'exp-01',
    code: 'E01',
    title: 'Remove obsolete memory',
    kind: 'Causal Test',
    description: 'Remove the outdated 30-day note from context.',
    before: {
      label: 'BEFORE',
      orderAge: '21 days',
      memory: '"30-day rule"',
      result: 'REFUND ✕',
      outcome: 'violation',
    },
    after: {
      label: 'AFTER',
      orderAge: '21 days',
      memory: '[removed]',
      result: 'DENY ✓',
      outcome: 'safe',
    },
    runsPassed: 3,
    runsTotal: 3,
    signal: 'Causal signal found',
    signalPositive: true,
  },
  {
    id: 'exp-02',
    code: 'E02',
    title: 'Unrelated note change',
    kind: 'Control Test',
    description: 'Swap an unrelated preference note while keeping the obsolete refund note.',
    before: {
      label: 'BEFORE',
      memory: '"prefers email"',
      result: 'REFUND ✕',
      outcome: 'violation',
    },
    after: {
      label: 'AFTER',
      memory: '"prefers phone"',
      result: 'REFUND ✕',
      outcome: 'violation',
    },
    runsPassed: 0,
    runsTotal: 3,
    signal: 'Violation persists',
    signalPositive: false,
  },
  {
    id: 'exp-03',
    code: 'E03',
    title: 'Policy version pin',
    kind: 'Causal Test',
    description: 'Force policy v2.3 and re-run the refund decision.',
    before: {
      label: 'BEFORE',
      orderAge: '21 days',
      memory: '"30-day rule"',
      result: 'REFUND ✕',
      outcome: 'violation',
    },
    after: {
      label: 'AFTER',
      orderAge: '21 days',
      memory: '"30-day rule"',
      result: 'REFUND ✕',
      outcome: 'violation',
    },
    runsPassed: 0,
    runsTotal: 3,
    signal: 'No causal effect',
    signalPositive: false,
  },
  {
    id: 'exp-04',
    code: 'E04',
    title: 'Fresh note only',
    kind: 'Control Test',
    description: 'Provide only a current VIP courtesy note without refund language.',
    before: {
      label: 'BEFORE',
      orderAge: '21 days',
      memory: '"30-day rule"',
      result: 'REFUND ✕',
      outcome: 'violation',
    },
    after: {
      label: 'AFTER',
      orderAge: '21 days',
      memory: '"VIP courtesy"',
      result: 'DENY ✓',
      outcome: 'safe',
    },
    runsPassed: 2,
    runsTotal: 3,
    signal: 'Partial support',
    signalPositive: true,
  },
]

export const experimentChartData: ExperimentChartRow[] = [
  { name: 'E01', safe: 3, violations: 0 },
  { name: 'E02', safe: 0, violations: 3 },
  { name: 'E03', safe: 0, violations: 3 },
  { name: 'E04', safe: 2, violations: 1 },
]

export const experimentKeyFinding = {
  confidence: 87,
  title: 'Obsolete customer memory changes the decision.',
  subtext:
    'Removing the outdated 30-day note eliminates the violation, while unrelated note changes do not.',
}

export const coverageData: CoverageData = {
  bars: [
    { label: 'Order age ≤ 14 days', percent: 100 },
    { label: 'Customer note present', percent: 100 },
    { label: 'Memory conflict', percent: 0 },
    { label: 'Policy change', percent: 67 },
    { label: 'Multi-turn context', percent: 33 },
  ],
  gap: {
    id: 'MEMORY_CONFLICT',
    percent: 0,
    description: 'A retrieved obsolete note conflicts with the current policy.',
  },
  matrixColumns: ['Normal', 'Stale Memory', 'Policy Change'],
  matrixRows: [
    { label: '≤14 days', cells: ['pass', 'pass', 'pass'] },
    { label: '15–30 days', cells: ['pass', 'fail', 'partial'] },
    { label: '>30 days', cells: ['pass', 'fail', 'partial'] },
  ],
}

export const regressionProposal: RegressionProposal = {
  status: 'Pending human review',
  failure: {
    title: 'FAILURE CASE',
    accent: 'failure',
    orderAge: '21 days',
    memory: 'Obsolete 30-day rule',
    expected: 'DENY_REFUND',
    observed: 'REFUND',
    observedLabel: 'Previously observed',
  },
  control: {
    title: 'CONTROL CASE',
    accent: 'control',
    orderAge: '7 days',
    memory: 'none',
    expected: 'REFUND',
    observed: 'REFUND',
    observedLabel: 'Observed',
  },
  heldOutPassed: 2,
  heldOutTotal: 2,
}

export const investigationProgress: ProgressStep[] = [
  { label: 'Incident Detected', state: 'completed' },
  { label: 'Hypotheses Generated', state: 'completed' },
  { label: 'Experiments Run', state: 'completed' },
  { label: 'Root Cause Identified', state: 'current' },
  { label: 'Coverage Gap Found', state: 'future' },
  { label: 'Regression Proposed', state: 'future' },
  { label: 'Human Review', state: 'future' },
]

export function getIncidentById(id: string): Incident | undefined {
  return incidents.find((incident) => incident.id === id)
}
