import { cn } from "@/lib/utils"

// A calendar page on a 32-unit grid whose bottom edge is a three-scallop ghost hem.
const BODY = "M6 13a6 6 0 0 1 6-6h8a6 6 0 0 1 6 6v11q-2 3-4 0q-2-3-4 0q-2 3-4 0q-2-3-4 0q-2 3-4 0Z"

export type GhostExpression = "neutral" | "happy" | "concerned" | "crying" | "sleepy"

const FEATURE = { stroke: "var(--brand-eyes)", strokeWidth: 1.5, strokeLinecap: "round" } as const

/** Dot eyes, optionally lowered, under brows whose inner ends rise by `worry` units. */
function Eyes({ y = 15, worry = 0 }: { y?: number; worry?: number }) {
  return (
    <>
      <circle cx="13" cy={y} r="1.75" fill="var(--brand-eyes)" />
      <circle cx="19" cy={y} r="1.75" fill="var(--brand-eyes)" />
      {worry > 0 && (
        <path d={`M10.8 ${y - 3.2 + worry / 2}L14.2 ${y - 3.2 - worry / 2}M17.8 ${y - 3.2 - worry / 2}L21.2 ${y - 3.2 + worry / 2}`} {...FEATURE} />
      )}
    </>
  )
}

/** A drop hanging just below an eye centered at `x`. */
function tear(x: number): string {
  return `M${x} 18q1.3 1.8 1.3 2.7a1.3 1.3 0 0 1-2.6 0q0-.9 1.3-2.7Z`
}

function Face({ expression }: { expression: GhostExpression }) {
  switch (expression) {
    case "happy":
      return <path d="M11.5 15.5q1.5-2.2 3 0M17.5 15.5q1.5-2.2 3 0" {...FEATURE} />
    case "concerned":
      return <Eyes y={15.5} worry={1.2} />
    case "crying":
      return (
        <>
          <Eyes y={15.5} worry={2.2} />
          {/* A tear under each eye; the hero lets them fall. */}
          <path className="ghost-mark-tear" d={tear(12.4)} fill="var(--brand-eyes)" />
          <path className="ghost-mark-tear ghost-mark-tear-late" d={tear(19.6)} fill="var(--brand-eyes)" />
        </>
      )
    case "sleepy":
      return <path d="M11.5 15q1.5 1.6 3 0M17.5 15q1.5 1.6 3 0" {...FEATURE} />
    default:
      return <Eyes />
  }
}

/** The Calendar Ghost mark. Decorative unless given a title. */
export function GhostMark({ className, title, expression = "neutral" }: { className?: string; title?: string; expression?: GhostExpression }) {
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
      data-expression={expression}
    >
      <path d={BODY} fill="var(--brand-glow)" stroke="var(--brand-line)" strokeWidth="2" strokeLinejoin="round" />
      <path d="M12 4.5v4M20 4.5v4" stroke="var(--brand-line)" strokeWidth="2" strokeLinecap="round" />
      <Face expression={expression} />
    </svg>
  )
}
