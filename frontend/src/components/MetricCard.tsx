import { Area, AreaChart, ResponsiveContainer } from 'recharts'

interface MetricCardProps {
  value: number
  label: string
  accent: 'blue' | 'purple' | 'green' | 'pink'
  sparkline: number[]
  delta: string
  color: string
}

export function MetricCard({ value, label, accent, sparkline, delta, color }: MetricCardProps) {
  const data = sparkline.map((v, i) => ({ i, v }))

  return (
    <div className={`metric-card accent-${accent}`}>
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      <div className="metric-footer">
        <span className="metric-delta">{delta}</span>
        <div style={{ width: 72, height: 28 }}>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 2, right: 0, left: 0, bottom: 0 }}>
              <Area type="monotone" dataKey="v" stroke={color} fill={color} fillOpacity={0.18} strokeWidth={1.5} isAnimationActive animationDuration={240} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  )
}
