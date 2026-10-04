import type { RefObject } from "react"

import { useI18n } from "@/i18n/provider"
import type { ProjectionHandling } from "@/lib/api"
import { removalConsequence } from "@/lib/rule-change"

/** What Rule Removal and Rule Replacement do with the projections a rule wrote. */
export function ProjectionChoice({
  name,
  value,
  onChange,
  firstField,
  mappingCount,
  destinationName,
  deleteAvailable,
}: {
  name: string
  value: ProjectionHandling
  onChange: (value: ProjectionHandling) => void
  firstField?: RefObject<HTMLInputElement | null>
  mappingCount: number
  destinationName: string
  deleteAvailable: boolean
}) {
  const i18n = useI18n()
  const { t } = i18n
  return (
    <fieldset className="projection-choice" aria-describedby={`${name}-consequence`}>
      <legend>{t("ruleDetails.projections.legend")}</legend>
      <div className="radio-options">
        <label className="radio-row">
          <input
            ref={value === "delete" ? firstField : undefined}
            type="radio"
            name={name}
            value="delete"
            checked={value === "delete"}
            disabled={!deleteAvailable}
            onChange={() => onChange("delete")}
          />
          <span>
            <strong>{t("ruleDetails.projections.delete", { count: mappingCount, destination: destinationName })}</strong>
            <small>
              {deleteAvailable ? t("ruleDetails.projections.deleteHint") : t("ruleDetails.projections.deleteUnavailable")}
            </small>
          </span>
        </label>
        <label className="radio-row">
          <input
            ref={value === "detach" ? firstField : undefined}
            type="radio"
            name={name}
            value="detach"
            checked={value === "detach"}
            onChange={() => onChange("detach")}
          />
          <span>
            <strong>{t("ruleDetails.projections.keep")}</strong>
            <small>{t("ruleDetails.projections.keepHint", { destination: destinationName })}</small>
          </span>
        </label>
      </div>
      <p id={`${name}-consequence`} className="consequence-text">
        {removalConsequence(i18n, value, mappingCount, destinationName)}
      </p>
    </fieldset>
  )
}
