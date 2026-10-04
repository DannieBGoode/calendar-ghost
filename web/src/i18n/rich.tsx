import { Fragment, type ReactNode } from "react"

const TAGGED = /<(\w+)>(.*?)<\/\1>/g

/** Turns `<strong>{name}</strong>`-style markup in a translated message into React nodes. */
export function rich(message: string, tags: Record<string, (text: string) => ReactNode>): ReactNode[] {
  const nodes: ReactNode[] = []
  let last = 0
  for (const match of message.matchAll(TAGGED)) {
    const [whole, tag = "", text = ""] = match
    if (match.index > last) nodes.push(message.slice(last, match.index))
    const render = tags[tag]
    nodes.push(<Fragment key={match.index}>{render ? render(text) : text}</Fragment>)
    last = match.index + whole.length
  }
  if (last < message.length) nodes.push(message.slice(last))
  return nodes
}

/** Renders a message's `<code>` tag, for setting names, paths, and addresses. */
export const codeTag = (text: string): ReactNode => <code>{text}</code>
