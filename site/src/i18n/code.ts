/** One run of a sentence: plain words, or a field name or path to show as code. */
export interface TextPart {
  text: string
  code: boolean
}

/** Splits copy at backticks, so a translation keeps field names as code without any markup. */
export function codeParts(text: string): TextPart[] {
  return text
    .split("`")
    .map((part, index) => ({ text: part, code: index % 2 === 1 }))
    .filter((part) => part.text !== "")
}
