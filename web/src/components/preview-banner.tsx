import { Eye, LayoutDashboard } from "lucide-react"

import { isPlainLeftClick, type AppView, type ViewChange } from "@/lib/navigation"
import { previewPathForView, previewSearchForView } from "@/lib/preview-mode"

const previewViews: { id: AppView; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "rules", label: "Rules" },
  { id: "activity", label: "Activity" },
  { id: "settings", label: "Settings" },
]

export function PreviewBanner({ current, onViewChange }: { current: AppView; onViewChange: ViewChange }) {
  return (
    <section className="preview-banner page-card" aria-labelledby="preview-banner-title">
      <div className="preview-banner-copy">
        <div className="preview-banner-label">
          <Eye aria-hidden="true" />
          <strong id="preview-banner-title">Mock data preview</strong>
        </div>
        <p>Read-only sample data is shown across the app so you can review the full design language.</p>
      </div>
      <nav className="preview-banner-nav" aria-label="Preview pages">
        {previewViews.map((item) => (
          <a
            key={item.id}
            className="preview-banner-link"
            href={previewPathForView(item.id)}
            aria-current={item.id === current ? "page" : undefined}
            onClick={(event) => {
              if (!isPlainLeftClick(event)) return
              event.preventDefault()
              onViewChange(item.id, { search: previewSearchForView(item.id) })
            }}
          >
            {item.id === "overview" && <LayoutDashboard aria-hidden="true" />}
            {item.label}
          </a>
        ))}
      </nav>
    </section>
  )
}
