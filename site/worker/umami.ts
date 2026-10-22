// Worker entry-point value exports are treated as RPC entry points by workerd, so endpoint
// constants shared with tests live in an imported module instead.
export const UMAMI_TRACKER = "https://cloud.umami.is/script.js"
export const UMAMI_COLLECT = "https://gateway.umami.is/api/send"
