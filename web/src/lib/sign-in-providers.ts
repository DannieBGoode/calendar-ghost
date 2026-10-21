import type { MessageKey } from "@/i18n/types"

export const SIGN_IN_PROVIDERS = ["google", "microsoft"] as const
export type SignInProvider = typeof SIGN_IN_PROVIDERS[number]
export function isSignInProvider(provider: string): provider is SignInProvider {
  return SIGN_IN_PROVIDERS.some(value => value === provider)
}
export const SIGN_IN_NAMES: Record<SignInProvider, MessageKey> = {
  google: "auth.provider.google.name", microsoft: "auth.provider.microsoft.name",
}
export const SIGN_IN_LABELS: Record<SignInProvider, MessageKey> = {
  google: "auth.provider.google.signIn", microsoft: "auth.provider.microsoft.signIn",
}

export function enabledSignInProviders(data: { providers: string[] } | undefined): SignInProvider[] {
  return data && Array.isArray(data.providers) ? data.providers.filter(isSignInProvider) : []
}
