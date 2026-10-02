import { cn } from "@/lib/utils"

// A calendar page on a 32-unit grid whose bottom edge is a three-scallop ghost hem.
const BODY = "M6 13a6 6 0 0 1 6-6h8a6 6 0 0 1 6 6v11q-2 3-4 0q-2-3-4 0q-2 3-4 0q-2-3-4 0q-2 3-4 0Z"

/** The Calendar Ghost mark. Decorative unless given a title. */
export function GhostMark({ className, title }: { className?: string; title?: string }) {
  return (
    <svg
      className={cn("ghost-mark", className)}
      width="32"
      height="32"
      viewBox="0 -1 32 32"
      fill="none"
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
    >
      <path d={BODY} fill="var(--brand-glow)" stroke="var(--brand-line)" strokeWidth="2" strokeLinejoin="round" />
      <path d="M12 4.5v4M20 4.5v4" stroke="var(--brand-line)" strokeWidth="2" strokeLinecap="round" />
      <circle cx="13" cy="15" r="1.75" fill="var(--brand-eyes)" />
      <circle cx="19" cy="15" r="1.75" fill="var(--brand-eyes)" />
    </svg>
  )
}
