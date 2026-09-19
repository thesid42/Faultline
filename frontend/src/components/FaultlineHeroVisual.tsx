import { useEffect, useRef } from 'react'

interface FaultlineHeroVisualProps {
  className?: string
}

interface WaveLayer {
  baseY: number
  amplitude: number
  frequency: number
  secondary: number
  speed: number
  fill: string
  opacity?: number
}

const WIDTH = 1200
const HEIGHT = 420
const SEGMENTS = 96

const LAYERS: WaveLayer[] = [
  { baseY: 268, amplitude: 42, frequency: 0.0036, secondary: 0.0068, speed: 0.48, fill: 'url(#ridge1)' },
  { baseY: 302, amplitude: 36, frequency: 0.0044, secondary: 0.0082, speed: 0.66, fill: 'url(#ridge2)' },
  { baseY: 338, amplitude: 28, frequency: 0.0052, secondary: 0.0096, speed: 0.84, fill: 'url(#ridge3)' },
  { baseY: 372, amplitude: 20, frequency: 0.0062, secondary: 0.0115, speed: 1.05, fill: 'url(#ridge4)', opacity: 0.94 },
]

function waveY(x: number, layer: WaveLayer, time: number): number {
  const phase = time * layer.speed
  return (
    layer.baseY +
    Math.sin(x * layer.frequency + phase) * layer.amplitude +
    Math.sin(x * layer.secondary + phase * 1.45) * layer.amplitude * 0.45 +
    Math.cos(x * layer.frequency * 0.55 - phase * 0.85) * layer.amplitude * 0.28 +
    Math.sin(x * layer.secondary * 1.7 + phase * 0.6) * layer.amplitude * 0.12
  )
}

function buildWavePath(layer: WaveLayer, time: number): string {
  const step = WIDTH / SEGMENTS
  const firstY = waveY(0, layer, time)
  let d = `M0 ${HEIGHT} L0 ${firstY.toFixed(2)}`
  for (let i = 1; i <= SEGMENTS; i++) {
    const x = i * step
    const y = waveY(x, layer, time)
    d += ` L${x.toFixed(2)} ${y.toFixed(2)}`
  }
  d += ` L${WIDTH} ${HEIGHT} Z`
  return d
}

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/** Pastel landscape with undulating wave ridges. */
export function FaultlineHeroVisual({ className }: FaultlineHeroVisualProps) {
  const pathRefs = useRef<Array<SVGPathElement | null>>([])

  useEffect(() => {
    const reduced = prefersReducedMotion()
    const apply = (time: number) => {
      LAYERS.forEach((layer, index) => {
        const node = pathRefs.current[index]
        if (node) node.setAttribute('d', buildWavePath(layer, time))
      })
    }

    apply(0)
    if (reduced) return

    let frame = 0
    const started = performance.now()
    const tick = (now: number) => {
      apply((now - started) / 1000)
      frame = window.requestAnimationFrame(tick)
    }
    frame = window.requestAnimationFrame(tick)
    return () => window.cancelAnimationFrame(frame)
  }, [])

  return (
    <div className={className ?? 'hero-landscape'} aria-hidden>
      <svg
        className="hero-landscape-svg"
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        preserveAspectRatio="xMidYMid slice"
        fill="none"
      >
        <defs>
          <linearGradient id="skyFade" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#FFFFFF" stopOpacity="0" />
            <stop offset="40%" stopColor="#F5F7FC" stopOpacity="0.5" />
            <stop offset="100%" stopColor="#EEF1FA" stopOpacity="0.85" />
          </linearGradient>
          <linearGradient id="ridge1" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#D8DCF2" stopOpacity="0.55" />
            <stop offset="100%" stopColor="#C8CEE8" stopOpacity="0.72" />
          </linearGradient>
          <linearGradient id="ridge2" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#B8C0E8" stopOpacity="0.78" />
            <stop offset="100%" stopColor="#A7B0DE" stopOpacity="0.92" />
          </linearGradient>
          <linearGradient id="ridge3" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#9AA4D9" stopOpacity="0.88" />
            <stop offset="100%" stopColor="#8893CF" stopOpacity="0.96" />
          </linearGradient>
          <linearGradient id="ridge4" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#7E89C9" />
            <stop offset="100%" stopColor="#6F7ABF" />
          </linearGradient>
        </defs>

        <rect width={WIDTH} height={HEIGHT} fill="url(#skyFade)" />

        {LAYERS.map((layer, index) => (
          <path
            key={layer.fill}
            ref={(node) => {
              pathRefs.current[index] = node
            }}
            className={`hero-wave hero-wave-${index + 1}`}
            fill={layer.fill}
            opacity={layer.opacity ?? 1}
          />
        ))}
      </svg>
    </div>
  )
}
