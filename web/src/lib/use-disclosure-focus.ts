import { useEffect, useRef, type RefObject } from "react"

/** Focuses the first field when a form opens and returns focus to its toggle when it closes. */
export function useDisclosureFocus(
  open: boolean,
  first: RefObject<HTMLElement | null>,
  toggle: RefObject<HTMLElement | null>,
) {
  const wasOpen = useRef(open)
  useEffect(() => {
    if (open) first.current?.focus()
    else if (wasOpen.current) toggle.current?.focus()
    wasOpen.current = open
  }, [open, first, toggle])
}
