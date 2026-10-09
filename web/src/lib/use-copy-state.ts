import { useEffect, useState } from "react"

// How long a Copy button says "Copied" before it offers to copy again.
const COPIED_FOR_MS = 2000

export type CopyState = "idle" | "copied" | "unavailable"

/** Whether a secret shown once was just copied; "copied" returns to "idle" after a moment. */
export function useCopyState() {
  const [copyState, setCopyState] = useState<CopyState>("idle")
  useEffect(() => {
    if (copyState !== "copied") return
    const timer = window.setTimeout(() => setCopyState("idle"), COPIED_FOR_MS)
    return () => window.clearTimeout(timer)
  }, [copyState])
  return [copyState, setCopyState] as const
}
