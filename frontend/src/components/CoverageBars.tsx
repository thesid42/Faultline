import type { CoverageBar } from '../data/mockData'

function tone(percent: number) {
  if (percent >= 80) return 'high'
  if (percent >= 40) return 'mid'
  return 'low'
}

export function CoverageBars({ bars }: { bars: CoverageBar[] }) {
  return (
    <div className="panel">
      <h2 className="section-title">Coverage by failure condition</h2>
      <div className="coverage-bars">
        {bars.map((bar) => (
          <div key={bar.label} className="cov-row">
            <div style={{ fontSize: 13.5, fontWeight: 500 }}>{bar.label}</div>
            <div className="cov-track">
              <div className={`cov-fill ${tone(bar.percent)}`} style={{ width: `${Math.max(bar.percent, 2)}%` }} />
            </div>
            <div style={{ fontWeight: 600, fontSize: 13, textAlign: 'right' }}>{bar.percent}%</div>
          </div>
        ))}
      </div>
    </div>
  )
}
