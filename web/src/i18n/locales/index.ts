import type { Catalog } from "@/i18n/types"

import en from "./en"

/** A shipped language: its tag and how to load its catalog. */
export type LocaleEntry = { tag: string; load: () => Promise<Catalog> }

/**
 * Languages the Web UI offers. English is bundled; register another with a lazy loader, such as
 * `{ tag: "de", load: () => import("./de").then((module) => module.default) }`.
 */
export const LOCALES: readonly LocaleEntry[] = [{ tag: "en", load: () => Promise.resolve(en) }]
