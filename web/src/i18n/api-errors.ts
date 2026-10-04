import { ApiError, UnreadableResponseError } from "@/lib/api"

import type { I18n } from "./translator"

/** What to tell the administrator about a failed request; the server's detail is English. */
export function apiErrorMessage(i18n: I18n, error: unknown): string {
  if (error instanceof UnreadableResponseError) return i18n.t("common.apiError.unreadableResponse")
  if (error instanceof ApiError) return error.detail ?? i18n.t("common.apiError.generic")
  if (error instanceof TypeError) return i18n.t("common.apiError.network")
  return i18n.t("common.apiError.generic")
}
