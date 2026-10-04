---
target: web/src/features/settings.tsx (IntegrationsSection and the Settings page around it)
total_score: 26
p0_count: 0
p1_count: 2
timestamp: 2026-10-04T09-00-00Z
slug: web-src-features-settings-tsx-integrations
---
## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|---|---:|---|
| 1 | Visibility of System Status | 3/4 | No message after a revoke, and focus is lost when the Revoke button unmounts. |
| 2 | Match System / Real World | 2/4 | "Token", "plain HTTP", "Bearer", and "MCP" sit at the surface for a nontechnical administrator. |
| 3 | User Control and Freedom | 3/4 | The one-time reveal has no Done action; revoked rows can never be cleared. |
| 4 | Consistency and Standards | 2/4 | No single bordered group, token rows have no dividers, red is used for information. |
| 5 | Error Prevention | 3/4 | The warning says not to issue over HTTP, but issuing still works. |
| 6 | Recognition Rather Than Recall | 3/4 | Two tokens with the same name look identical; no prefix or creation date. |
| 7 | Flexibility and Efficiency | 3/4 | Examples are filled in, but have no copy buttons and need the token spliced by hand. |
| 8 | Aesthetic and Minimalist Design | 2/4 | Five visual treatments in one section; the red band is the loudest thing on the page. |
| 9 | Error Recovery | 2/4 | Load failure has no retry; issue and revoke errors render below the examples. |
| 10 | Help and Documentation | 3/4 | Good examples disclosure; nothing explains how to get HTTPS. |
| **Total** |  | **26/40** | Acceptable. The rest of Settings scored 37/40 on 2026-10-03; Integrations pulls it down. |

## Anti-Patterns Verdict

**LLM assessment:** The page does not read as AI-made, but the Integrations section reads as the generic developer "API tokens" block: a red banner, a form outside any group, raw monospace secret, a list of Revoke buttons. The tells are structural, not decorative; none of the absolute bans appear.

**Deterministic scan:** The detector returned no findings for `web/src/features/settings.tsx`, `web/src/features`, or `web/src/components`. The browser overlay was skipped because this detector version's live mode edits project source files.

## Priority Issues

1. **[P1] The plain-HTTP note uses destructive red and `role="alert"` for a condition that needs no action.** It fires on every visit over HTTP, including loopback, against DESIGN.md's rule that red means act now and that no-action conditions close their group as a quiet disclosure. Fix: a quiet footer note, exempt loopback, no live role. Command: /quieter.
2. **[P1] Integrations breaks the Settings Groups pattern.** The form and the reveal sit outside any bordered group, a stray hairline appears above the reveal, token rows lose their dividers because of a wrapper element, and errors render below the examples. Fix: one bordered group with an issue row, the reveal row, token rows, and a footer with the note and examples. Command: /normalize.
3. **[P2] The one-time reveal is the weakest element at the most important moment.** Bare text, Copy far away, the secret read aloud through `role="status"`, focus not moved, no Done. Fix: a read-only field with attached Copy, focus to the reveal heading, a short announcement, a Done action. Command: /polish.
4. **[P2] Integrations is always expanded.** Most administrators never use it, while Connected accounts collapses. Fix: a summary row that opens on demand, placed after Storage. Command: /distill.
5. **[P2] Revoke semantics and feedback.** Trash icon for a non-deleting action, no announcement, focus lost, revoked rows pile up. Fix: no trash icon, a status message, focus to the row, a "revoked" disclosure. Command: /harden.

## Settings structure

Sub-pages are not needed yet. With Integrations grouped and collapsed, the default page is four short groups. Split into URL-addressable sub-pages (Accounts, Storage, Integrations, Appearance) with a text tab row under the title when a fifth section arrives or the collapsed page passes about two desktop screens.
