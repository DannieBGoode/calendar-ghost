import { Trash2 } from "lucide-react"
import { useEffect, useRef, type ReactNode } from "react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

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
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    heading.current?.focus()
  }, [])
  return (
    <div
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
        <Button type="button" variant="outline" onClick={onCancel} disabled={pending}>
          {cancelLabel}
        </Button>
        <Button
          type="button"
          variant="destructive"
          onClick={onConfirm}
          disabled={pending || confirmDisabled}
        >
          {confirmIcon}
          {pending ? pendingLabel : confirmLabel}
        </Button>
      </div>
    </div>
  )
}
