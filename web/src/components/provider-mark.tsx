import type { ReactElement, ReactNode } from "react"

import { cn } from "@/lib/utils"

/**
 * Each provider's mark, drawn as the landing page draws it (site/src/marks). A mark only helps the
 * eye: the text beside it always names the provider too (DESIGN.md, Provider Mark Rule).
 */
const MARKS: Readonly<Record<string, ReactElement>> = {
  google: (
    <>
      <path fill="#fff" d="M10 10h28v28H10z" />
      <path fill="#1a73e8" d="M38 10H10v28H4V7a3 3 0 0 1 3-3h31z" />
      <path fill="#4285f4" d="M10 4h28v6H10z" />
      <path fill="#34a853" d="M10 38h28v6H10z" />
      <path fill="#fbbc04" d="M38 10h6v28l-6 6z" />
      <path fill="#ea4335" d="M38 38h6l-6 6z" />
      <path fill="#188038" d="M4 38h6v6H7a3 3 0 0 1-3-3z" />
      <path fill="#1967d2" d="M38 4h3a3 3 0 0 1 3 3v3h-6z" />
      <path
        fill="#1a73e8"
        d="M15 18c1.1-1.2 2.5-1.8 4.1-1.8 2.5 0 4.2 1.5 4.2 3.5 0 1.4-.7 2.3-1.8 2.8 1.4.5 2.2 1.6 2.2 3.1 0 2.4-1.9 4-4.6 4-1.8 0-3.3-.7-4.4-2.2l1.7-1.5c.7 1 1.5 1.5 2.7 1.5 1.5 0 2.4-.7 2.4-1.9 0-1.3-1-1.9-2.7-1.9h-1v-2.1h1c1.4 0 2.3-.6 2.3-1.7 0-.9-.8-1.5-2-1.5-.9 0-1.7.4-2.4 1.1zm11.3.5 3.6-2.1h1.8v13h-2.4V19.2l-2 1.2z"
      />
    </>
  ),
  outlook: (
    <>
      <path fill="#0078d4" d="M19 5h23v29H19z" />
      <path fill="#28a8ea" d="M19 5h23v10H19z" />
      <path fill="#50d9ff" d="M19 15h11v9H19z" />
      <path fill="#1490df" d="M30 15h12v9H30z" />
      <path fill="#0364b8" d="M19 24h11v10H19z" />
      <path fill="#0078d4" d="m17 23 27-1v19a3 3 0 0 1-3 3H20a3 3 0 0 1-3-3z" />
      <path fill="#28a8ea" d="m17 23 14 11 13-12v19a3 3 0 0 1-3 3H20a3 3 0 0 1-3-3z" />
      <path fill="#0364b8" d="m3 12 23-4v32L3 36z" />
      <ellipse cx="14.5" cy="24" rx="6" ry="8" fill="#fff" />
      <ellipse cx="14.5" cy="24" rx="3.2" ry="5.2" fill="#0364b8" />
    </>
  ),
}

/** The provider's mark, decorative only; `fallback` for a provider this version has no mark for. */
export function ProviderMark({
  provider,
  className,
  fallback = null,
}: {
  provider: string | null | undefined
  className?: string
  fallback?: ReactNode
}) {
  const mark = provider ? MARKS[provider] : undefined
  if (!mark) return fallback
  return (
    <svg
      className={cn("provider-mark", className)}
      data-provider={provider}
      viewBox="0 0 48 48"
      aria-hidden="true"
    >
      {mark}
    </svg>
  )
}
