import { Trash2 } from "lucide-react"
import { useEffect, useRef } from "react"

import { Button } from "@/components/ui/button"

export function DestructiveConfirmation({
  id,
  title,
  body,
  cancelLabel,
  confirmLabel,
  pendingLabel,
  pending,
  confirmDisabled,
  onConfirm,
  onCancel,
}: {
  id: string
  title: string
  body: string
  cancelLabel: string
  confirmLabel: string
  pendingLabel: string
  pending: boolean
  confirmDisabled?: boolean
  onConfirm: () => void
  onCancel: () => void
}) {
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    heading.current?.focus()
  }, [])
  return (
    <div className="disconnect-confirmation delete-confirmation" id={id} role="group" aria-labelledby={`${id}-title`}>
      <div>
        <h3 id={`${id}-title`} ref={heading} tabIndex={-1}>
          {title}
        </h3>
        <p>{body}</p>
      </div>
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
          <Trash2 aria-hidden="true" />
          {pending ? pendingLabel : confirmLabel}
        </Button>
      </div>
    </div>
  )
}
