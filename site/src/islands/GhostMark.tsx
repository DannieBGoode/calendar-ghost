// The application's mark (web/src/components/ghost-mark.tsx), for the small nav lockup. Everywhere
// the ghost acts, the page uses the character in Ghost.tsx instead.
const BODY = "M6 13a6 6 0 0 1 6-6h8a6 6 0 0 1 6 6v11q-2 3-4 0q-2-3-4 0q-2 3-4 0q-2-3-4 0q-2 3-4 0Z"

export function GhostMark({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 -1 32 32" fill="none" aria-hidden="true" focusable="false">
      <path d={BODY} fill="var(--brand-glow)" stroke="var(--brand-line)" strokeWidth="2" strokeLinejoin="round" />
      <path d="M12 4.5v4M20 4.5v4" stroke="var(--brand-line)" strokeWidth="2" strokeLinecap="round" />
      <circle cx="13" cy="15" r="1.75" fill="var(--brand-eyes)" />
      <circle cx="19" cy="15" r="1.75" fill="var(--brand-eyes)" />
    </svg>
  )
}
