import { ChevronDown, MoreHorizontal } from "lucide-react"
import { useEffect, useId, useRef, useState, type FocusEvent, type KeyboardEvent, type ReactNode } from "react"

import { Button } from "@/components/ui/button"

export type OverflowMenuItem = {
  id: string
  label: string
  description?: string
  /** A decorative mark before the label; the label still names the item. */
  icon?: ReactNode
  /** Where the item goes, as a link; `onSelect` still runs first. */
  href?: string
  /** Opens `href` in a new tab, so this page stays and the menu returns focus to its trigger. */
  newTab?: boolean
  disabled?: boolean
  onSelect: () => void
}

/** A visible trigger in place of the icon-only one, for a menu that is a page's main action. */
export type OverflowMenuTrigger = {
  icon: ReactNode
  variant: "default" | "outline"
}

const MENU_WIDTH = 336
const VIEWPORT_MARGIN = 16

/**
 * A menu button for secondary commands, or for choosing how to do one main action, following the WAI-ARIA menu button pattern: arrow
 * keys move between items, Escape and Tab close it, and focus returns to the trigger. Disabled
 * items stay focusable so a running command never strands keyboard focus.
 */
export function OverflowMenu({
  label,
  items,
  trigger: visibleTrigger,
}: {
  label: string
  items: OverflowMenuItem[]
  trigger?: OverflowMenuTrigger
}) {
  const [open, setOpen] = useState(false)
  const [placement, setPlacement] = useState<{ left: number; width: number } | null>(null)
  const root = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const itemRefs = useRef<(HTMLElement | null)[]>([])
  const menuId = useId()

  useEffect(() => {
    if (!open) return
    itemRefs.current[0]?.focus()
    const close = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener("pointerdown", close)
    return () => document.removeEventListener("pointerdown", close)
  }, [open])

  function show() {
    // Right-align under the trigger, then slide it back inside the viewport wherever the
    // trigger sits, so the menu is never clipped on a narrow screen.
    const box = root.current?.getBoundingClientRect()
    const viewport = document.documentElement.clientWidth
    const width = Math.min(MENU_WIDTH, viewport - VIEWPORT_MARGIN * 2)
    if (box) {
      const left = Math.min(Math.max(box.right - width, VIEWPORT_MARGIN), viewport - VIEWPORT_MARGIN - width)
      setPlacement({ left: left - box.left, width })
    }
    setOpen(true)
  }

  function close(returnFocus: boolean) {
    setOpen(false)
    if (returnFocus) trigger.current?.focus()
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape" && open) {
      event.preventDefault()
      close(true)
      return
    }
    if (!open) {
      if (event.target === trigger.current && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
        event.preventDefault()
        show()
      }
      return
    }
    const all = itemRefs.current.filter((item): item is HTMLElement => Boolean(item))
    const index = all.indexOf(document.activeElement as HTMLElement)
    const next = {
      ArrowDown: all[(index + 1) % all.length],
      ArrowUp: all[(index - 1 + all.length) % all.length],
      Home: all[0],
      End: all[all.length - 1],
    }[event.key]
    if (next) {
      event.preventDefault()
      next.focus()
    } else if (event.key === "Tab") {
      setOpen(false)
    }
  }

  function onBlur(event: FocusEvent<HTMLDivElement>) {
    if (open && !root.current?.contains(event.relatedTarget)) setOpen(false)
  }

  return (
    <div className="overflow-menu" ref={root} onKeyDown={onKeyDown} onBlur={onBlur}>
      <Button
        ref={trigger}
        variant={visibleTrigger?.variant ?? "ghost"}
        size={visibleTrigger ? "default" : "icon"}
        aria-label={visibleTrigger ? undefined : label}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => (open ? close(false) : show())}
      >
        {visibleTrigger ? (
          <>
            {visibleTrigger.icon}
            {label}
            <ChevronDown aria-hidden="true" />
          </>
        ) : (
          <MoreHorizontal aria-hidden="true" />
        )}
      </Button>
      {open && (
        <div
          className="overflow-menu-list"
          style={placement ? { left: placement.left, right: "auto", width: placement.width } : undefined}
          id={menuId}
          role="menu"
          aria-label={label}
        >
          {items.map((item, index) => (
            <OverflowMenuEntry
              key={item.id}
              item={item}
              descriptionId={`${menuId}-${item.id}`}
              entryRef={(element) => {
                itemRefs.current[index] = element
              }}
              onChosen={() => close(!item.href || Boolean(item.newTab))}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function OverflowMenuEntry({
  item,
  descriptionId,
  entryRef,
  onChosen,
}: {
  item: OverflowMenuItem
  descriptionId: string
  entryRef: (element: HTMLElement | null) => void
  onChosen: () => void
}) {
  const content = (
    <>
      {item.icon && <span className="overflow-menu-icon">{item.icon}</span>}
      <span className="overflow-menu-text">
        <span className="overflow-menu-label">{item.label}</span>
        {item.description && (
          <span className="overflow-menu-description" id={descriptionId}>
            {item.description}
          </span>
        )}
      </span>
    </>
  )
  const shared = {
    role: "menuitem",
    tabIndex: -1,
    className: "overflow-menu-item",
    "aria-disabled": item.disabled || undefined,
    "aria-describedby": item.description ? descriptionId : undefined,
  } as const
  if (item.href && !item.disabled) {
    return (
      <a
        {...shared}
        ref={entryRef}
        href={item.href}
        {...(item.newTab ? { target: "_blank", rel: "noopener" } : {})}
        onClick={() => {
          onChosen()
          item.onSelect()
        }}
      >
        {content}
      </a>
    )
  }
  return (
    <button
      {...shared}
      ref={entryRef}
      type="button"
      onClick={() => {
        if (item.disabled) return
        onChosen()
        item.onSelect()
      }}
    >
      {content}
    </button>
  )
}
