import type { CSSProperties, ReactNode } from "react"

/**
 * The ghost as a character: the mark's silhouette (a calendar page with two binder tabs and a
 * three-scallop hem) filled with a tone, with the Overview's faces and a few landing-page ones.
 * Like the app's ghost it has no mouth: eyes, brows, cheeks, and small props carry the feeling.
 *
 * Everything is drawn on a 64-unit grid. The body spans x 12 to 52 and y 8 to 54; the margin
 * around it holds what floats outside the body (sparkles, sweat, "z"s, startle rays).
 */
export type GhostFace = "neutral" | "happy" | "proud" | "surprised" | "concerned" | "sleepy" | "wink"
export type GhostTone = "moss" | "lantern" | "mist"
/**
 * How the ghost idles by itself (blinking, floating, drifting "z"s).
 * - `loop`: for ghosts inside a demo that has its own pause control (`[data-playing="false"]` on
 *   an ancestor pauses them).
 * - `brief`: a few seconds after the ghost first scrolls into view, then still (no pause control
 *   is needed for motion that stops within five seconds).
 * - `still`: never moves by itself.
 */
export type GhostAlive = "loop" | "brief" | "still"

export const GHOST_FACES: readonly GhostFace[] = ["neutral", "happy", "proud", "surprised", "concerned", "sleepy", "wink"]

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
  return (
    <>
      <ellipse cx={x} cy={y} rx={rx} ry={ry} fill="var(--ghost-ink)" />
      <circle cx={x + rx * 0.36} cy={y - ry * 0.38} r={Math.max(1, rx * 0.36)} fill="var(--ghost-shine)" />
    </>
  )
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

function Cheeks() {
  return (
    <g className="ghost-cheeks" fill="var(--ghost-blush)">
      <ellipse cx="18.5" cy="38.5" rx="3.3" ry="2" />
      <ellipse cx="45.5" cy="38.5" rx="3.3" ry="2" />
    </g>
  )
}

/** A four-point sparkle centered on (x, y): four concave arcs that meet in sharp points. */
function sparkle(x: number, y: number, r: number): string {
  const c = `${x} ${y}`
  return `M${x} ${y - r}Q${c} ${x + r} ${y}Q${c} ${x} ${y + r}Q${c} ${x - r} ${y}Q${c} ${x} ${y - r}Z`
}

function Face({ face, look }: { face: GhostFace; look: { x: number; y: number } }) {
  switch (face) {
    case "happy":
      return (
        <>
          <Cheeks />
          <path d={SMILE_EYES} {...FEATURE} />
        </>
      )
    case "proud":
      // Chin up, eyes shut with satisfaction, a little sparkle: look what I carried.
      return (
        <>
          <Cheeks />
          <path d="M21 32.5Q25 28.2 29 32.5M35 32.5Q39 28.2 43 32.5" {...FEATURE} />
          <g className="ghost-sparkles" fill="var(--ghost-spark)">
            <path d={sparkle(53, 9, 5)} />
            <path d={sparkle(10, 18, 3)} />
          </g>
        </>
      )
    case "surprised":
      return (
        <>
          <path d="M20.5 23.6Q25 20 29.5 23.6M34.5 23.6Q39 20 43.5 23.6" {...FEATURE} strokeWidth={2.2} />
          <OpenEyes y={32.5} rx={3.9} ry={4.7} />
          <path className="ghost-rays" d="M14 11.5L10.5 8M50 11.5L53.5 8M32 10.5V5.5" {...FEATURE} stroke="var(--ghost-aside)" strokeWidth={2.2} />
        </>
      )
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
          <Cheeks />
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
  className?: string
}

/** The Calendar Ghost character. Always decorative: the copy beside it says what matters. */
export function Ghost({
  face = "neutral",
  then,
  tone = "moss",
  look = { x: 0, y: 0 },
  alive = "still",
  float = false,
  size,
  className,
}: GhostProps) {
  const style = size ? ({ "--ghost-size": `${size}px` } as CSSProperties) : undefined
  return (
    <span
      className={className ? `ghost ${className}` : "ghost"}
      data-tone={tone}
      data-face={then ?? face}
      data-sequence={then ? "" : undefined}
      data-alive={alive}
      data-float={float ? "" : undefined}
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
            <path className="ghost-shine" d="M17.2 31C17.2 25 19.6 20.6 24 18.8" />
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

export type BubbleSide = "right" | "left" | "top"

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
