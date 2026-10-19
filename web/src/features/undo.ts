import type { Toast, Toasts } from "@/components/ui/toast-context"
import { apiErrorMessage } from "@/i18n/api-errors"
import type { I18n } from "@/i18n/translator"

/**
 * Says in the next toast what Undo, pressed in a toast, did, or why it was refused. A toast
 * outlives the view that made the change, so Undo answers from its own request, never through the
 * view's mutation, whose callbacks stop once the view is gone.
 */
export function answerUndo<T>(toasts: Toasts, i18n: I18n, undone: Promise<T>, done: (answer: T) => Toast): void {
  void undone.then(
    (answer) => toasts.show(done(answer)),
    (error: unknown) => toasts.show({ message: apiErrorMessage(i18n, error), refused: true }),
  )
}
