---
target: health hero ghost face contrast
total_score: 34
p0_count: 0
p1_count: 0
timestamp: 2026-10-02T23-43-13Z
slug: web-src-features-overview-tsx
---
# Focused critique: health hero ghost face

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 4/4 | Health state and next action are explicit. |
| 2 | Match System / Real World | 4/4 | The ghost illustration supports the product's calendar metaphor. |
| 3 | User Control and Freedom | 4/4 | The hero action leads to the affected rule without trapping the user. |
| 4 | Consistency and Standards | 4/4 | The mark uses shared brand tokens across surfaces. |
| 5 | Error Prevention | 3/4 | The setup state explains preview-before-write behavior clearly. |
| 6 | Recognition Rather Than Recall | 4/4 | State, summary facts, and the illustration are recognizable at a glance. |
| 7 | Flexibility and Efficiency | 2/4 | No keyboard accelerators were observed in this focused visual review. |
| 8 | Aesthetic and Minimalist Design | 3/4 | The composition is focused, but the face needs a readable contrast relationship. |
| 9 | Error Recovery | 3/4 | Attention states provide a review path; deeper recovery is handled on the rule page. |
| 10 | Help and Documentation | 3/4 | The callout gives useful context, though it is intentionally brief. |
| **Total** | | **34/40** | **Good, with one focused contrast fix applied.** |

## Anti-Patterns Verdict

The focused hero does not read as an obvious AI-generated composition. It has one expressive surface, a restrained palette, and a product-specific mark rather than a generic dashboard illustration.

The deterministic detector returned `[]` for `web/src/features/overview.tsx` and `web/src/components/ghost-mark.tsx`.

## Overall Impression

The hero has the right hierarchy and tone. The attached screenshot exposed a real flaw in the face: the eyes were assigned the adjacent surface token while the body used the muted token. That made the face visually dissolve into the body, especially in dark Twilight and Midnight.

## What's Working

- The ghost is a recognizable product cue, not decoration detached from the task.
- The callout and health copy communicate what the user should understand before taking action.
- Theme tokens keep the hero stateful instead of introducing one-off colors.

## Priority Issues

### [P2] Ghost eyes fail non-text contrast

**Why it matters:** The eye color was only about 1.1:1 against the body in the setup state, below the 3:1 non-text contrast target. The face was technically present but not visually legible.

**Fix applied:** `.health-hero` now maps `--brand-eyes` to `--health-ink`, so healthy, attention, and setup faces inherit the same state-aware contrast color as the supporting signal. `brand-contrast.test.ts` now verifies all three states in light, Twilight, and Midnight.

**Suggested command:** `/polish` for a final visual pass after the next browser capture.

## Persona Red Flags

### Sam, accessibility-dependent user

Before the fix, the face relied on a low-contrast visual detail to communicate the mark's expression. The outline remained visible, but the eyes did not meet a 3:1 graphical contrast relationship. The regression test now protects this across all themes.

### Alex, power user

No blocking efficiency issue surfaced in this focused review. The hero's review action is direct and does not add a redundant confirmation step.

## Minor Observations

- The outline and eyes now share the state ink role, which keeps the face coherent with the health signal.
- A post-fix browser screenshot would be useful for visual sign-off, but the static token test covers the exact contrast relationship and the previous cross-theme QA covered the surrounding layout.

## Questions to Consider

Questions skipped: the finding was specific and the correction was unambiguous. The remaining choice is only whether to make the face more expressive later, which is separate from the contrast defect.
