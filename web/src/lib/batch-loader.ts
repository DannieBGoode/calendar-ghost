/**
 * Collects loads requested in the same moment and answers them with as few bounded requests as
 * possible. Keys the fetcher does not return resolve to null.
 */
export function createBatchLoader<V>(
  fetchMany: (keys: number[]) => Promise<Map<number, V>>,
  maxBatch: number,
) {
  let waiting = new Map<number, { resolve: (value: V | null) => void; reject: (error: unknown) => void }[]>()
  let scheduled = false

  function flush() {
    const batch = waiting
    waiting = new Map()
    scheduled = false
    const keys = [...batch.keys()]
    for (let start = 0; start < keys.length; start += maxBatch) {
      const chunk = keys.slice(start, start + maxBatch)
      fetchMany(chunk).then(
        (values) => {
          for (const key of chunk) for (const waiter of batch.get(key) ?? []) waiter.resolve(values.get(key) ?? null)
        },
        (error: unknown) => {
          for (const key of chunk) for (const waiter of batch.get(key) ?? []) waiter.reject(error)
        },
      )
    }
  }

  return {
    load(key: number): Promise<V | null> {
      return new Promise((resolve, reject) => {
        waiting.set(key, [...(waiting.get(key) ?? []), { resolve, reject }])
        if (!scheduled) {
          scheduled = true
          // Rows mount across several effects; a short delay lets them share one request.
          setTimeout(flush, 10)
        }
      })
    },
  }
}
