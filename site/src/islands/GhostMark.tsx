// The application's mark (web/src/components/ghost-mark.tsx), with eyes that can look around.
const BODY = "M6 13a6 6 0 0 1 6-6h8a6 6 0 0 1 6 6v11q-2 3-4 0q-2-3-4 0q-2 3-4 0q-2-3-4 0q-2 3-4 0Z"

export type GhostFace = "neutral" | "sleepy"

export function GhostMark({
  className,
  eyes = { x: 0, y: 0 },
  face = "neutral",
}: {
  className?: string
  eyes?: { x: number; y: number }
  face?: GhostFace
}) {
  return (
    <svg className={className} viewBox="0 -1 32 32" fill="none" aria-hidden="true" focusable="false">
      <path d={BODY} fill="var(--brand-glow)" stroke="var(--brand-line)" strokeWidth="2" strokeLinejoin="round" />
      <path d="M12 4.5v4M20 4.5v4" stroke="var(--brand-line)" strokeWidth="2" strokeLinecap="round" />
      {face === "sleepy" ? (
        <path
          d="M11.5 15q1.5 1.6 3 0M17.5 15q1.5 1.6 3 0"
          stroke="var(--brand-eyes)"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
      ) : (
        <g transform={`translate(${eyes.x} ${eyes.y})`}>
          <circle cx="13" cy="15" r="1.75" fill="var(--brand-eyes)" />
          <circle cx="19" cy="15" r="1.75" fill="var(--brand-eyes)" />
        </g>
      )}
    </svg>
  )
}
