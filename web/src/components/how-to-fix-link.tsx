import { ExternalLink } from "lucide-react"

import { useI18n } from "@/i18n/provider"

/** "How to fix", opening the troubleshooting guide's section for an administrator's Cause. */
export function HowToFixLink({ href, label }: { href: string; label?: string }) {
  const { t } = useI18n()
  return (
    <a className="text-link inline-link how-to-fix" href={href} target="_blank" rel="noreferrer" aria-label={label}>
      {t("people.cause.howToFix")}
      <ExternalLink aria-hidden="true" />
      <span className="sr-only">{t("common.opensInNewTab")}</span>
    </a>
  )
}
