/**
 * The Minos mark (hexagon with a decision flow) drawn as SVG, so it stays crisp at any size
 * and its navy strokes follow the theme (`--brand-ink`). The original artwork lives in
 * docs/brand/.
 */
export function BrandMark({ size = 32 }: { size?: number }) {
  return (
    <svg className="brand-mark" width={size} height={size} viewBox="0 0 100 100" aria-hidden="true">
      <path
        d="M50 6 L88 28 L88 72 L50 94 L12 72 L12 28 Z"
        fill="none"
        stroke="var(--brand-ink)"
        strokeWidth="5.5"
        strokeLinejoin="round"
      />
      <g stroke="var(--brand-ink)" strokeWidth="2.4" fill="none" strokeLinecap="round">
        <path d="M50 27 V34" />
        <path d="M26.4 53.6 V43.4 H73.6 V53.6" />
        <path d="M50 54 V65.5" />
        <circle cx="26.4" cy="59.7" r="5.2" strokeWidth="2.8" />
        <circle cx="73.6" cy="59.7" r="5.2" strokeWidth="2.8" />
      </g>
      <circle cx="50" cy="21.7" r="6.1" fill="var(--brand-teal)" />
      <path d="M50 33.1 L60.4 43.5 L50 53.9 L39.6 43.5 Z" fill="var(--brand-teal)" />
      <circle cx="50" cy="75.4" r="9.9" fill="var(--brand-green)" />
      <path
        d="M45.4 75.6 L48.7 78.9 L54.9 72.4"
        fill="none"
        stroke="#fff"
        strokeWidth="2.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

export function BrandLockup({ size = 30, tagline = 'Studio' }: { size?: number; tagline?: string }) {
  return (
    <span className="brand-lockup">
      <BrandMark size={size} />
      <span className="brand-word">MINOS</span>
      {tagline && <span className="brand-tag">{tagline}</span>}
    </span>
  )
}
