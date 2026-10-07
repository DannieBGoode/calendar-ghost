const ACCENTED: Partial<Record<string, string>> = Object.fromEntries(
  Array.from("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ").map((letter, index) => [
    letter,
    Array.from("áƀçðéƒĝĥíĵķļɱñóþǫŕšţüṽŵẋýžÁƁÇÐÉƑĜĤÍĴĶĻṀÑÓÞǪŔŠŢÜṼŴẊÝŽ")[index],
  ]),
)
const TAG = /^<\/?\w+>$/

/**
 * Accents every letter and adds about 35% length inside brackets, keeping rich-text tags intact
 * (placeholders never reach it; the translator only transforms literal text).
 */
export function pseudoize(text: string): string {
  if (!text) return text
  const body = text
    .split(/(<\/?\w+>)/)
    .map((part) => (TAG.test(part) ? part : Array.from(part, (character) => ACCENTED[character] ?? character).join("")))
    .join("")
  return `[${body}${"·".repeat(Math.ceil(text.length * 0.35))}]`
}
