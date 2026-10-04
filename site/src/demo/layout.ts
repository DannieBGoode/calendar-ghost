import { DAY_END, DAY_START, DAYS, type DemoEvent } from "./week"

export interface WeekFrame {
  heightPx: number
  headerPx: number
  gapPx: number
}

export interface Box {
  leftPct: number
  widthPct: number
  topPx: number
  heightPx: number
}

export const TWO_LINE_MIN_PX = 34

/** Where an event sits in a five-day week whose day header is `headerPx` tall. */
export function eventBox(event: DemoEvent, frame: WeekFrame): Box {
  const hourPx = (frame.heightPx - frame.headerPx) / (DAY_END - DAY_START)
  return {
    leftPct: (event.day * 100) / DAYS,
    widthPct: 100 / DAYS,
    topPx: Math.round(frame.headerPx + (event.start - DAY_START) * hourPx),
    heightPx: Math.round((event.end - event.start) * hourPx - frame.gapPx),
  }
}

export function fitsTwoLines(box: Box): boolean {
  return box.heightPx >= TWO_LINE_MIN_PX
}
