import type { RefObject } from "react"

import type { ProjectionHandling } from "@/lib/api"
import { plural, removalConsequence } from "@/lib/rule-change"

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
  return (
    <fieldset className="projection-choice" aria-describedby={`${name}-consequence`}>
      <legend>Projections this rule wrote</legend>
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
            <strong>
              Delete {plural(mappingCount, "projection")} from {destinationName} (recommended)
            </strong>
            <small>
              {deleteAvailable
                ? "Only events this rule manages are deleted."
                : "Reauthorize the destination account in Settings to delete projections."}
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
            <strong>Keep them as ordinary events</strong>
            <small>They stay in {destinationName} and are never updated or deleted again.</small>
          </span>
        </label>
      </div>
      <p id={`${name}-consequence`} className="consequence-text">
        {removalConsequence(value, mappingCount, destinationName)}
      </p>
    </fieldset>
  )
}
