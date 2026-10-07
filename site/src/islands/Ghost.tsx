import type { CSSProperties, ReactNode } from "react"

/**
 * The ghost as a character: the mark's silhouette (a calendar page with two binder tabs and a
 * three-scallop hem) filled with a tone, with the Overview's faces and a few landing-page ones.
 * Like the app's ghost it is flat (one fill, an outline a shade deeper, no shine) and has no
 * mouth: eyes, brows, and small props carry the feeling.
 *
 * Everything is drawn on a 64-unit grid. The body spans x 12 to 52 and y 8 to 54; the margin
 * around it holds what floats outside the body (sweat, "z"s).
 */
export type GhostFace = "neutral" | "happy" | "concerned" | "sleepy" | "wink"
/**
 * - `mist`: the default character: on dark pages the white ghost with a soft lantern glow around
 *   it; on light ones filled Lantern Indigo, since white reads as hollow on the light canvas.
 * - `lantern`: Lantern Indigo, for a few accents (How it works, the 404, the Why signature).
 * - `moss`: green, only where it means "healthy", as in the app (the Overview, a dashboard tile).
 */
export type GhostTone = "moss" | "lantern" | "mist"
/**
 * How the ghost idles by itself (blinking, floating, drifting "z"s).
 * - `loop`: keeps idling, only inside a demo, whose pause control (`[data-playing="false"]` on an
 *   ancestor) pauses it.
 * - `brief`: a few seconds after the ghost first scrolls into view, then still (no pause control
 *   is needed for motion that stops within five seconds).
 * - `still`: never moves by itself.
 */
export type GhostAlive = "loop" | "brief" | "still"

export const GHOST_FACES: readonly GhostFace[] = ["neutral", "happy", "concerned", "sleepy", "wink"]

const BODY = [
  "M12 27A13 13 0 0 1 25 14H39A13 13 0 0 1 52 27V48",
  // The hem, right to left: lobe, notch, lobe, notch, lobe.
  "C52 51.8 49.6 54 47 54C44.4 54 42 51.8 42 48",
  "C42 46 40.9 44.5 39.5 44.5C38.1 44.5 37 46 37 48",
  "C37 51.8 34.6 54 32 54C29.4 54 27 51.8 27 48",
  "C27 46 25.9 44.5 24.5 44.5C23.1 44.5 22 46 22 48",
  "C22 51.8 19.6 54 17 54C14.4 54 12 51.8 12 48Z",
].join("")
const TABS = [22.5, 36.5]
const EYE_X = [25, 39] as const
/** How far the pupils travel per unit of `look` (the mark's eye offset, see `eyeOffset`). */
const LOOK_SCALE = 1.8

const FEATURE = {
  fill: "none",
  stroke: "var(--ghost-ink)",
  strokeWidth: 2.6,
  strokeLinecap: "round",
  strokeLinejoin: "round",
} as const

function OpenEye({ x, y, rx = 3.6, ry = 4.3 }: { x: number; y: number; rx?: number; ry?: number }) {
  return <ellipse cx={x} cy={y} rx={rx} ry={ry} fill="var(--ghost-ink)" />
}

/** Two open eyes in one group, so a blink closes both together. */
function OpenEyes({ y = 32, rx, ry }: { y?: number; rx?: number; ry?: number }) {
  return (
    <g className="ghost-eyes">
      <OpenEye x={EYE_X[0]} y={y} rx={rx} ry={ry} />
      <OpenEye x={EYE_X[1]} y={y} rx={rx} ry={ry} />
    </g>
  )
}

/** Closed, smiling eyes (∩), as on the Overview's healthy ghost. */
const SMILE_EYES = "M21 33.5Q25 28 29 33.5M35 33.5Q39 28 43 33.5"

function Face({ face, look }: { face: GhostFace; look: { x: number; y: number } }) {
  switch (face) {
    case "happy":
      return <path d={SMILE_EYES} {...FEATURE} />
    case "concerned":
      return (
        <>
          <path d="M20.5 26.8L28.5 24.4M35.5 24.4L43.5 26.8" {...FEATURE} strokeWidth={2.2} />
          <g className="ghost-glance">
            <OpenEyes y={33} rx={3.1} ry={3.7} />
          </g>
          <path
            className="ghost-sweat"
            d="M56.5 20.5C58.4 23.1 59.2 24.6 59.2 26A2.7 2.7 0 0 1 53.8 26C53.8 24.6 54.6 23.1 56.5 20.5Z"
            fill="var(--ghost-sweat)"
          />
        </>
      )
    case "sleepy":
      return (
        <>
          <path d="M21 32.5Q25 36 29 32.5M35 32.5Q39 36 43 32.5" {...FEATURE} />
          <g className="ghost-zs" {...FEATURE} stroke="var(--ghost-aside)" strokeWidth={1.9}>
            <path className="ghost-z ghost-z-one" d="M47 8.5H51.5L47 13.5H51.5" />
            <path className="ghost-z ghost-z-two" d="M54 1.5H57.4L54 5.3H57.4" />
          </g>
        </>
      )
    case "wink":
      return (
        <>
          <g className="ghost-eyes">
            <OpenEye x={EYE_X[0]} y={32} />
          </g>
          <path d="M35 33Q39 28.5 43 33" {...FEATURE} />
        </>
      )
    default:
      return (
        <g transform={`translate(${look.x * LOOK_SCALE} ${look.y * LOOK_SCALE})`}>
          <OpenEyes />
        </g>
      )
  }
}

export interface GhostProps {
  face?: GhostFace
  /** A face to change to; when it happens is the surrounding CSS's choice (see ghost.css). */
  then?: GhostFace
  tone?: GhostTone
  /** Where a neutral ghost looks, in the mark's eye units (see `eyeOffset`). */
  look?: { x: number; y: number }
  alive?: GhostAlive
  float?: boolean
  /** Rendered width in CSS pixels; the default comes from `--ghost-size`. */
  size?: number
  /** A soft radial lantern glow behind the ghost (on by default for the mist tone). It breathes
   * with the ghost's idle life (`alive`), so it is still when the ghost is. */
  glow?: boolean
  className?: string
}

/** The Calendar Ghost character. Always decorative: the copy beside it says what matters. */
export function Ghost({
  face = "neutral",
  then,
  tone = "mist",
  look = { x: 0, y: 0 },
  alive = "still",
  float = false,
  size,
  glow = tone === "mist",
  className,
}: GhostProps) {
  // The glow reaches about a fifth of the ghost's size past its body (ghost.css).
  const style = size
    ? ({ "--ghost-size": `${size}px`, ...(glow ? { "--ghost-glow-r": `${Math.round(size * 0.2)}px` } : {}) } as CSSProperties)
    : undefined
  return (
    <span
      className={className ? `ghost ${className}` : "ghost"}
      data-tone={tone}
      data-face={then ?? face}
      data-sequence={then ? "" : undefined}
      data-alive={alive}
      data-float={float ? "" : undefined}
      data-glow={glow ? "" : undefined}
      style={style}
      aria-hidden="true"
    >
      <svg viewBox="0 0 64 64" focusable="false">
        {float && <ellipse className="ghost-shadow" cx="32" cy="60.5" rx="13" ry="2.2" />}
        <g className="ghost-float">
          <g className="ghost-pose">
            <g className="ghost-cutout">
              {TABS.map((x) => (
                <rect key={x} x={x} y="8.5" width="5" height="9" rx="2.5" />
              ))}
              <path d={BODY} />
            </g>
            {TABS.map((x) => (
              <rect key={x} className="ghost-tab" x={x} y="8.5" width="5" height="9" rx="2.5" />
            ))}
            <path className="ghost-body" d={BODY} />
            {then ? (
              <>
                <g className="ghost-face ghost-face-first">
                  <Face face={face} look={look} />
                </g>
                <g className="ghost-face ghost-face-then">
                  <Face face={then} look={look} />
                </g>
              </>
            ) : (
              <g className="ghost-face">
                <Face face={face} look={look} />
              </g>
            )}
          </g>
        </g>
      </svg>
    </span>
  )
}

export type BubbleSide = "right" | "top"

/** A speech bubble whose tail points at the ghost it sits beside. Place both in `.ghost-stage`. */
export function SpeechBubble({
  side = "right",
  className,
  children,
}: {
  side?: BubbleSide
  className?: string
  children: ReactNode
}) {
  return (
    <span className={className ? `speech-bubble ${className}` : "speech-bubble"} data-side={side}>
      {children}
    </span>
  )
}
