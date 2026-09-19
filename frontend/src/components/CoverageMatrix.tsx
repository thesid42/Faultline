import type { CoverageData, MatrixCell } from '../data/mockData'

function cellSymbol(cell: MatrixCell) {
  if (cell === 'pass') return '✓'
  if (cell === 'fail') return '✕'
  return '◐'
}

export function CoverageMatrix({ data }: { data: CoverageData }) {
  return (
    <div className="gap-panel">
      <div className="eyebrow">DISCOVERED GAP</div>
      <h3>{data.gap.id}</h3>
      <div style={{ fontWeight: 600, color: 'var(--failure)', marginBottom: 8 }}>{data.gap.percent}% covered</div>
      <p style={{ margin: '0 0 8px', color: 'var(--text)', maxWidth: 520 }}>{data.gap.description}</p>

      <table className="matrix">
        <thead>
          <tr>
            <th />
            {data.matrixColumns.map((col) => (
              <th key={col}>{col}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.matrixRows.map((row) => (
            <tr key={row.label}>
              <td>{row.label}</td>
              {row.cells.map((cell, i) => (
                <td key={`${row.label}-${i}`} className={cell}>
                  {cellSymbol(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
