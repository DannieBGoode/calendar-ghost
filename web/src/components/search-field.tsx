import { Search, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"

const SEARCH_DELAY_MS = 300

/**
 * Searches as the person types, pausing briefly so each keystroke does not replace the results.
 * Enter searches at once; Escape clears. A query cleared elsewhere, such as from an empty state,
 * empties the field too.
 */
export function SearchField({
  id,
  label,
  placeholder,
  clearLabel,
  query,
  onSearch,
}: {
  id: string
  label: string
  placeholder: string
  clearLabel: string
  query: string
  onSearch: (query: string) => void
}) {
  const [text, setText] = useState(query)
  const [shownQuery, setShownQuery] = useState(query)
  const input = useRef<HTMLInputElement>(null)
  const search = useRef(onSearch)
  useEffect(() => {
    search.current = onSearch
  })
  if (query !== shownQuery) {
    setShownQuery(query)
    if (text.trim() !== query) setText(query)
  }

  useEffect(() => {
    if (text.trim() === query) return
    const timer = window.setTimeout(() => search.current(text.trim()), SEARCH_DELAY_MS)
    return () => window.clearTimeout(timer)
  }, [text, query])

  function clear() {
    setText("")
    onSearch("")
    input.current?.focus()
  }

  return (
    <div className="field-stack">
      <Label htmlFor={id}>{label}</Label>
      <div className="search-field">
        <Search aria-hidden="true" className="search-field-icon" />
        <Input
          ref={input}
          id={id}
          type="search"
          value={text}
          placeholder={placeholder}
          autoComplete="off"
          spellCheck={false}
          maxLength={200}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault()
              if (text.trim() !== query) onSearch(text.trim())
            } else if (event.key === "Escape" && text) {
              event.preventDefault()
              clear()
            }
          }}
        />
        {text && (
          <button type="button" className="search-field-clear" aria-label={clearLabel} title={clearLabel} onClick={clear}>
            <X aria-hidden="true" />
          </button>
        )}
      </div>
    </div>
  )
}
