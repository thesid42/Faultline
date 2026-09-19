import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { ExperimentChartRow } from '../data/mockData'

export function ExperimentChart({ data }: { data: ExperimentChartRow[] }) {
  return (
    <div className="panel" style={{ height: 340 }}>
      <h2 className="section-title">Experiment Results</h2>
      <ResponsiveContainer width="100%" height="85%">
        <BarChart data={data} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#E5EAF1" vertical={false} />
          <XAxis dataKey="name" tick={{ fill: '#64748B', fontSize: 12 }} axisLine={{ stroke: '#E5EAF1' }} tickLine={false} />
          <YAxis allowDecimals={false} tick={{ fill: '#64748B', fontSize: 12 }} axisLine={false} tickLine={false} />
          <Tooltip
            contentStyle={{
              borderRadius: 10,
              border: '1px solid #E5EAF1',
              boxShadow: '0 4px 12px rgba(17,24,39,0.08)',
              fontSize: 13,
            }}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Bar dataKey="safe" name="Safe outcomes" fill="#22C55E" radius={[4, 4, 0, 0]} animationDuration={240} />
          <Bar dataKey="violations" name="Violations" fill="#F45B69" radius={[4, 4, 0, 0]} animationDuration={240} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
