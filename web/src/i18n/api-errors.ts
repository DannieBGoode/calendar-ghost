import { ApiError, UnreadableResponseError } from "@/lib/api"

import type { I18n } from "./translator"
import type { MessageParams } from "./types"

type ServerParams = Readonly<Record<string, string | number | null>>

/** How a message names a calendar provider; an unknown or missing one gets a neutral phrase. */
export function providerName(i18n: I18n, provider: string | number | null | undefined): string {
  const key = `common.provider.${String(provider)}`
  return typeof provider === "string" && i18n.has(key) ? i18n.t(key) : i18n.t("common.provider.unknown")
}

/** The provider's name at the start of a sentence. */
function providerNameStart(i18n: I18n, provider: string | number | null | undefined): string {
  const key = `common.provider.${String(provider)}`
  return typeof provider === "string" && i18n.has(key) ? i18n.t(key) : i18n.t("common.provider.unknownStart")
}

/** Server params ready for a translated message, with display names for the provider. */
export function messageParams(i18n: I18n, params: ServerParams): MessageParams {
  const present = Object.fromEntries(
    Object.entries(params).filter((entry): entry is [string, string | number] => entry[1] !== null),
  )
  return { ...present, provider: providerName(i18n, params.provider), Provider: providerNameStart(i18n, params.provider) }
}

/** A server-coded message, or null when there is none or the server left out one of its params. */
function coded(i18n: I18n, key: string, params: MessageParams): string | null {
  if (!i18n.has(key)) return null
  try {
    const text = i18n.t(key, params)
    // Outside tests a missing param stays as `{name}`; the server's detail reads better.
    return /\{\w+\}/.test(text) ? null : text
  } catch {
    // Under test a missing param throws.
    return null
  }
}

/** A validation error's length limit, as the `count` its plural message selects a form by. */
function lengthLimit(params: ServerParams): MessageParams {
  const limit = params.min_length ?? params.max_length
  return typeof limit === "number" ? { count: limit } : {}
}

function serverMessage(i18n: I18n, error: ApiError): string | null {
  if (!error.code) return null
  const params = { ...messageParams(i18n, error.params), ...lengthLimit(error.params) }
  const reason = error.params.reason
  const specific = typeof reason === "string" ? coded(i18n, `common.apiError.${error.code}_${reason}`, params) : null
  return specific ?? coded(i18n, `common.apiError.${error.code}`, params)
}

/** What to tell the administrator about a failed request: the code's message, else the server's detail. */
export function apiErrorMessage(i18n: I18n, error: unknown): string {
  if (error instanceof UnreadableResponseError) return i18n.t("common.apiError.unreadableResponse")
  if (error instanceof ApiError) return serverMessage(i18n, error) ?? error.detail ?? i18n.t("common.apiError.generic")
  if (error instanceof TypeError) return i18n.t("common.apiError.network")
  return i18n.t("common.apiError.generic")
}
