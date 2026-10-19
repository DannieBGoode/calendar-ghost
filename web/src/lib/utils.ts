import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** A copy of `record` without `key`, for state updates that must not mutate the previous value. */
export function withoutKey<T>(record: Readonly<Record<string, T>>, key: string): Record<string, T> {
  return Object.fromEntries(Object.entries(record).filter(([entryKey]) => entryKey !== key))
}

/** The ids an element's aria-describedby names, leaving out those not shown. */
export function describedBy(...ids: (string | false | null | undefined)[]): string | undefined {
  return ids.filter(Boolean).join(" ") || undefined
}
