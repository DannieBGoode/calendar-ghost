import { useIsMutating } from "@tanstack/react-query"

/** Names the save of a new rule's draft, so controls outside the builder can wait for it. */
export const CREATE_RULE_KEY = ["create-rule"]

/** Whether a new rule's draft is being saved. Closing the builder then would not stop the save. */
export function useRuleDraftSaving(): boolean {
  return useIsMutating({ mutationKey: CREATE_RULE_KEY }) > 0
}
