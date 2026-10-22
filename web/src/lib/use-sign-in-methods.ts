import { useQuery, useQueryClient } from "@tanstack/react-query"
import { api, type SessionStatus } from "@/lib/api"

export function useSignInMethods(userId: string) {
  const client = useQueryClient()
  const methods = useQuery({ queryKey: ["sign-in-methods", userId], queryFn: api.signInMethods, staleTime: 0 })
  const current = () => client.getQueryData<SessionStatus>(["session"])?.user?.id === userId
  const refresh = () => client.invalidateQueries({ queryKey: ["sign-in-methods", userId] })
  return { methods, current, refresh }
}
