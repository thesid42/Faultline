import { useMemo, useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { FaultlineHeroVisual } from '../components/FaultlineHeroVisual'
import { IncidentTable } from '../components/IncidentTable'
import { MetricCard } from '../components/MetricCard'
import { featuredIncident, getHeroCopy, homeMetrics, incidents } from '../data/mockData'

export function HomePage() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const heroCopy = useMemo(() => getHeroCopy(), [])

  useEffect(() => {
    const t = window.setTimeout(() => setLoading(false), 280)
    return () => window.clearTimeout(t)
  }, [])

  if (loading) {
    return (
      <div>
        <div className="skeleton" style={{ height: 360, marginBottom: 20, borderRadius: 16 }} />
        <div className="metrics-grid">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="skeleton" style={{ height: 110 }} />
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="tab-panel">
      <section className="hero-card">
        <FaultlineHeroVisual />

        <button type="button" className="hero-avatar" aria-label="Profile">
          A
        </button>

        <div className="hero-content">
          <div className="hero-copy">
            <h1 className="greeting">{heroCopy.title}</h1>
            <p className="greeting-sub">{heroCopy.subtitle}</p>
          </div>
          <div className="hero-actions">
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => navigate(`/investigations/${featuredIncident.id}`)}
            >
              View latest incident
            </button>
            <button
              type="button"
              className="btn btn-secondary hero-btn-secondary"
              onClick={() => navigate(`/investigations/${featuredIncident.id}`)}
            >
              New investigation
            </button>
          </div>
        </div>
      </section>

      <div className="metrics-grid">
        <MetricCard
          value={homeMetrics.totalIncidents}
          label="Total incidents"
          accent="blue"
          sparkline={homeMetrics.sparklines.incidents}
          delta={homeMetrics.deltas.incidents}
          color="#5865F2"
        />
        <MetricCard
          value={homeMetrics.investigating}
          label="Investigating"
          accent="purple"
          sparkline={homeMetrics.sparklines.investigating}
          delta={homeMetrics.deltas.investigating}
          color="#7C5CFC"
        />
        <MetricCard
          value={homeMetrics.rootCausesFound}
          label="Root causes found"
          accent="green"
          sparkline={homeMetrics.sparklines.rootCauses}
          delta={homeMetrics.deltas.rootCauses}
          color="#22C55E"
        />
        <MetricCard
          value={homeMetrics.regressionTests}
          label="Regression tests"
          accent="pink"
          sparkline={homeMetrics.sparklines.regression}
          delta={homeMetrics.deltas.regression}
          color="#F45B69"
        />
      </div>

      <div className="section-head">
        <h2 className="section-title" style={{ margin: 0 }}>
          Recent Incidents
        </h2>
        <button type="button" className="link-btn" onClick={() => navigate('/incidents')}>
          View all →
        </button>
      </div>
      <IncidentTable incidents={incidents} limit={3} />
    </div>
  )
}
