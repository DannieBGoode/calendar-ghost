import { useContext, useEffect, useLayoutEffect, useRef, type ReactNode } from "react"

import { ToastLayerContext } from "./toast-context"

type DrawerProps = {
  children: ReactNode
  onClose: () => void
  "aria-label"?: string
  "aria-labelledby"?: string
}

/** A full-height modal drawer. The browser keeps focus inside and makes the page inert. */
export function Drawer({ children, onClose, ...label }: DrawerProps) {
  const ref = useRef<HTMLDialogElement>(null)
  const setToastLayer = useContext(ToastLayerContext)
  useLayoutEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    const overflow = document.body.style.overflow
    dialog.showModal()
    document.body.style.overflow = "hidden"
    setToastLayer?.(dialog)
    return () => {
      setToastLayer?.(null)
      document.body.style.overflow = overflow
      dialog.close()
    }
  }, [setToastLayer])

  const labelledBy = label["aria-labelledby"]
  useEffect(() => {
    const title = labelledBy ? document.getElementById(labelledBy) : null
    if (title && ref.current?.contains(title)) title.focus({ preventScroll: true })
  }, [labelledBy])

  return (
    <dialog
      ref={ref}
      className="detail-drawer"
      tabIndex={-1}
      {...label}
      onCancel={(event) => {
        event.preventDefault()
        onClose()
      }}
      onKeyDown={(event) => {
        if (event.key !== "Escape" || event.defaultPrevented) return
        event.preventDefault()
        onClose()
      }}
      onPointerDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      {children}
    </dialog>
  )
}
