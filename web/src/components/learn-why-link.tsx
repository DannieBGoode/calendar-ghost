import { ExternalLink } from "lucide-react"

import { useI18n } from "@/i18n/provider"

/** "Learn why", opening the section of the Instant Sync guide that explains a reason and its fix.
 * `describedBy` names the sentence that states the reason, where the link stands apart from it. */
export function LearnWhyLink({ href, describedBy }: { href: string; describedBy?: string }) {
  const { t } = useI18n()
  return (
    <a className="text-link inline-link" href={href} target="_blank" rel="noreferrer" aria-describedby={describedBy}>
      {t("common.learnWhy")}
      <ExternalLink aria-hidden="true" />
      <span className="sr-only">{t("common.opensInNewTab")}</span>
    </a>
  )
}
