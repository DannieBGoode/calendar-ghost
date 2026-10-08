// Sam's portraits, one per part of life, the same images the README screenshots use. They are
// imported from the app's own folder (not copied), so the site and the app never drift, and
// astro:assets turns them into small webp files at build time.
import type { ImageMetadata } from "astro"
import { getImage } from "astro:assets"
import family from "../../../web/public/avatars/sam-family.png"
import personal from "../../../web/public/avatars/sam-personal.png"
import work from "../../../web/public/avatars/sam-work.png"

export type Calendar = "personal" | "family" | "work"

export const AVATARS: Record<Calendar, ImageMetadata> = { personal, family, work }

/** Three times the largest size an avatar is shown at (the hero's portraits, about 54px wide), so
 * it stays sharp on dense screens. The originals are 256px, so this stays well within them. */
export const AVATAR_PX = 160

export type AvatarUrls = Record<Calendar, string>

/** The built avatar files' addresses, for islands, which cannot use the Image component. */
export async function avatarUrls(): Promise<AvatarUrls> {
  const entries = await Promise.all(
    (Object.keys(AVATARS) as Calendar[]).map(async (calendar) => {
      const image = await getImage({ src: AVATARS[calendar], width: AVATAR_PX, height: AVATAR_PX, format: "webp" })
      return [calendar, image.src] as const
    }),
  )
  return Object.fromEntries(entries) as AvatarUrls
}
