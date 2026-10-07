import { REPO_URL } from "../links"

/** The steps that are true today: there is no published image yet (see the spec). */
export const SELF_HOST_COMMANDS = [
  `git clone ${REPO_URL}.git && cd calendar-ghost`,
  "cp .env.example .env",
  "docker compose up -d --build",
] as const
