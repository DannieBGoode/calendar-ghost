import { ExternalLink } from "lucide-react"

import { useI18n } from "@/i18n/provider"

/** "Learn why", opening the section of the Instant Sync guide that explains a reason and its fix. */
export function LearnWhyLink({ href }: { href: string }) {
  const { t } = useI18n()
  return (
    <a className="text-link inline-link" href={href} target="_blank" rel="noreferrer">
      {t("common.learnWhy")}
      <ExternalLink aria-hidden="true" />
      <span className="sr-only">{t("common.opensInNewTab")}</span>
    </a>
  )
}
