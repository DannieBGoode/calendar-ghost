import { Trash2 } from "lucide-react"
import { useEffect, useRef, type ReactNode } from "react"

import { Button } from "@/components/ui/button"
import { scrollFullyIntoView } from "@/components/ui/keep-in-window"
import { cn } from "@/lib/utils"

/**
 * A destructive change confirmed inline: its title, which takes focus, its consequence, and a
 * neutral way back beside the button that names the effect. It scrolls fully into view as it opens. While the change is on its way both
 * buttons stay focusable but ignore presses, so focus never falls to the page; `confirmDisabled`
 * holds the confirm button back until a prerequisite, such as a password, is met.
 */
export function DestructiveConfirmation({
  id,
  title,
  body,
  cancelLabel,
  confirmLabel,
  pendingLabel,
  pending,
  confirmDisabled,
  confirmIcon = <Trash2 aria-hidden="true" />,
  onConfirm,
  onCancel,
  children,
}: {
  id: string
  title: string
  body: string
  cancelLabel: string
  confirmLabel: string
  pendingLabel: string
  pending: boolean
  confirmDisabled?: boolean
  /** The icon on the destructive button; a trash can by default, none when nothing is deleted. */
  confirmIcon?: ReactNode
  onConfirm: () => void
  onCancel: () => void
  /** Choices the confirmation needs, such as a password, shown between the body and the buttons. */
  children?: ReactNode
}) {
  const group = useRef<HTMLDivElement>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    heading.current?.focus({ preventScroll: true })
    if (group.current) scrollFullyIntoView(group.current)
  }, [])
  return (
    <div
      ref={group}
      className={cn("disconnect-confirmation delete-confirmation", children !== undefined && "confirmation-with-fields")}
      id={id}
      role="group"
      aria-labelledby={`${id}-title`}
    >
      <div>
        <h3 id={`${id}-title`} ref={heading} tabIndex={-1}>
          {title}
        </h3>
        <p>{body}</p>
      </div>
      {children}
      <div className="confirmation-actions">
        <Button type="button" variant="outline" aria-disabled={pending || undefined} onClick={() => !pending && onCancel()}>
          {cancelLabel}
        </Button>
        <Button
          type="button"
          variant="destructive"
          aria-disabled={pending || undefined}
          aria-busy={pending || undefined}
          onClick={() => !pending && onConfirm()}
          disabled={confirmDisabled}
        >
          {confirmIcon}
          {pending ? pendingLabel : confirmLabel}
        </Button>
      </div>
    </div>
  )
}
