interface FaultlineHeroVisualProps {
  className?: string
}

/** Pastel rolling landscape — smooth hills, peach sun (matches reference). */
export function FaultlineHeroVisual({ className }: FaultlineHeroVisualProps) {
  return (
    <div className={className ?? 'hero-landscape'} aria-hidden>
      <svg
        className="hero-landscape-svg"
        viewBox="0 0 1200 420"
        preserveAspectRatio="xMidYMax slice"
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
            <stop offset="100%" stopColor="#C8CEE8" stopOpacity="0.7" />
          </linearGradient>
          <linearGradient id="ridge2" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#B8C0E8" stopOpacity="0.75" />
            <stop offset="100%" stopColor="#A7B0DE" stopOpacity="0.9" />
          </linearGradient>
          <linearGradient id="ridge3" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#9AA4D9" stopOpacity="0.85" />
            <stop offset="100%" stopColor="#8893CF" stopOpacity="0.95" />
          </linearGradient>
          <linearGradient id="ridge4" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#7E89C9" />
            <stop offset="100%" stopColor="#6F7ABF" />
          </linearGradient>
          <radialGradient id="sunCore" cx="0.5" cy="0.5" r="0.5">
            <stop offset="0%" stopColor="#FFD9C0" stopOpacity="1" />
            <stop offset="55%" stopColor="#F5C4A4" stopOpacity="0.95" />
            <stop offset="100%" stopColor="#F5C4A4" stopOpacity="0" />
          </radialGradient>
        </defs>

        <rect width="1200" height="420" fill="url(#skyFade)" />

        {/* Full peach sun — clear of ridges so it stays a complete circle */}
        <circle cx="980" cy="88" r="58" fill="#F6C8AB" opacity="0.95" />
        <circle cx="980" cy="88" r="78" fill="url(#sunCore)" />

        {/* Far soft ridge */}
        <path
          d="M0 280
             C120 250 200 235 300 255
             C420 280 480 220 580 210
             C700 198 760 245 860 235
             C960 225 1040 210 1200 235
             L1200 420 L0 420 Z"
          fill="url(#ridge1)"
        />

        {/* Mid-back rolling mountains */}
        <path
          d="M0 310
             C100 275 180 265 280 290
             C390 318 450 255 560 248
             C680 240 740 285 850 275
             C960 265 1050 255 1200 275
             L1200 420 L0 420 Z"
          fill="url(#ridge2)"
        />

        {/* Mid-front */}
        <path
          d="M0 340
             C90 310 160 300 250 320
             C360 345 420 295 530 290
             C650 284 720 330 820 318
             C930 305 1020 300 1200 320
             L1200 420 L0 420 Z"
          fill="url(#ridge3)"
        />

        {/* Foreground foothills */}
        <path
          d="M0 375
             C80 350 150 345 240 360
             C340 378 400 345 500 348
             C620 352 690 375 800 365
             C920 354 1020 350 1200 360
             L1200 420 L0 420 Z"
          fill="url(#ridge4)"
          opacity="0.92"
        />
      </svg>
    </div>
  )
}
