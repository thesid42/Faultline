interface RunningCaseLoaderProps {
  status: string
  progress?: string
  refreshing?: boolean
}

/** Visible progress panel while a queued/investigating case is still running. */
export function RunningCaseLoader({ status, progress, refreshing }: RunningCaseLoaderProps) {
  const waiting = status === 'queued'
  const title = waiting ? 'Waiting to start' : 'Investigation in progress'
  const detail = progress
    || (waiting
      ? 'Your investigation is queued. This page updates automatically when work begins.'
      : 'Faultline is checking the failure and saving evidence. This page refreshes automatically.')

  return (
    <section className="running-loader" aria-live="polite" aria-busy="true">
      <div className="running-loader-orbit" aria-hidden>
        <span className="running-loader-spinner" />
      </div>
      <div className="running-loader-copy">
        <div className="running-loader-title">
          <span className="running-loader-pulse" aria-hidden />
          {title}
        </div>
        <p className="running-loader-detail">{detail}</p>
        <p className="muted running-loader-meta">
          {refreshing ? 'Checking for new evidence…' : 'Listening for updates…'} · Leave this page open or come back later.
        </p>
      </div>
    </section>
  )
}
