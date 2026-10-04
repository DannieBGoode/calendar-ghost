export type CrossingMode = "busy" | "details"

export interface CrossingFields {
  title: boolean
  location: boolean
  guests: boolean
  link: boolean
}

/** What reaches the destination: Busy-Only Projection or Details Projection (CONTEXT.md). */
export function crossingFields(mode: CrossingMode): CrossingFields {
  const details = mode === "details"
  return { title: details, location: details, guests: false, link: false }
}
