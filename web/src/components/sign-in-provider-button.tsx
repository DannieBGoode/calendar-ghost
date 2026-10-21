import googleLight from "@/assets/sign-in/google-light.png"
import googleDark from "@/assets/sign-in/google-dark.png"
import microsoft from "@/assets/sign-in/microsoft.svg"
import { useI18n } from "@/i18n/provider"
import { SIGN_IN_LABELS, type SignInProvider } from "@/lib/sign-in-providers"

/** Official identity assets, kept local. Calendar product marks do not identify sign-in. */
export function SignInProviderButton({ provider, pending, unavailable = false, onClick }: {
  provider: SignInProvider; pending: boolean; unavailable?: boolean; onClick: () => void
}) {
  const { t } = useI18n()
  return <button type="button" className={`sign-in-provider sign-in-provider-${provider}`} aria-disabled={pending || unavailable} aria-busy={pending} onClick={() => { if (!pending && !unavailable) onClick() }}>
    <span className="sign-in-mark" aria-hidden="true">{provider === "google"
      ? <><img className="google-mark-light" src={googleLight} alt="" /><img className="google-mark-dark" src={googleDark} alt="" /></>
      : <img src={microsoft} alt="" />}</span>
    <span>{t(SIGN_IN_LABELS[provider])}</span>
  </button>
}
