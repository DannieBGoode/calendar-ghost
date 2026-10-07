---
target: Compatible calendars animated redesign
total_score: 31
p0_count: 0
p1_count: 0
timestamp: 2026-10-07T13-58-15Z
slug: site-src-sections-compatiblecalendars-astro
---
# Compatible calendars critique

Target: `site/src/sections/CompatibleCalendars.astro`. Independent assessments of the original section informed the animated redesign.

## Anti-pattern verdict
No strong AI-generated tells. The original strip was interchangeable: two small logos and badges on an oversized horizontal band. The deterministic detector returned zero findings. The redesign retains the established typography and tokens, makes the marks a visual scene, emphasizes available Google support, and keeps future providers explicitly labelled.

## Design health
| Heuristic | Original score /4 | Finding |
|---|---:|---|
| Visibility of status | 3 | Explicit compatibility badges |
| Match to real world | 4 | Familiar provider names |
| User control | 3 | Informational surface, no trapped flow |
| Consistency | 4 | Existing typography and tokens |
| Error prevention | 3 | Coming soon distinguishes availability |
| Recognition over recall | 4 | Names, marks, and status visible |
| Flexibility and efficiency | 3 | Easy to scan |
| Aesthetic and minimalist | 2 | Weak focal point |
| Error recovery | 3 | No error flow, neutral score |
| Help and documentation | 2 | Supported scope could be clearer |
| Total | 31/40 | Informational scope; neutral scores do not establish application usability |

## What's working
Literal support claims, recognizable bundled marks, and accessible textual status. Existing Besley/Figtree typography and lavender tokens provide continuity.

## Priority issues and implemented response
1. **P2: No visual focal point.** Tiny marks in a long band understate the section. Replaced with larger floating marks over orbital rings and a ghost beside Google. Motion is limited to a single 4.8-second run on arrival.
2. **P2: Available and planned providers have equal emphasis.** Google now has a larger mark, active orbit color, ghost, and green Compatible label. Outlook and iCloud remain Coming soon. No line claims synchronization with future providers.
3. **P2: Repetitive mobile rows consume space.** All three providers fit a compact shelf at mobile width, with fixed labels below the moving marks. Google scope moves into one introductory sentence.

## Cognitive load and emotional journey
Low cognitive load: three provider chunks, no choice burden. The original section was a visual valley between the setup and week demonstration. The short playful scene provides character while fixed labels preserve reassurance.

## Persona red flags
First-time visitors need Google availability distinguished from future providers. Trust-focused visitors must never see a completed connection into unsupported calendars. Mobile visitors need a compact scene. Reduced-motion visitors need complete static information. These concerns are addressed in the redesign and browser tests.

## Minor observations
Provider marks retain their identity colors. Small status badges use contrast-tested tokens. Text and status never animate.

## Questions
Questions skipped: the user already selected animated redesign and requested Google compatible, Outlook and iCloud coming soon.

## Final technical audit

Score: **19/20**, no P0, P1, or P2 issues. One optional P3: mobile badges use 12px text, readable with verified contrast but compact at 320px.

| Dimension | Score /4 | Evidence |
|---|---:|---|
| Accessibility | 4 | Named region, semantic list, decorative scenes hidden, textual status |
| Performance | 4 | Five transform/opacity tracks, 4.8 seconds, one iteration, no added client JavaScript |
| Responsive | 3 | No overflow at 320, 390, 768, 1024, 1280; compact mobile badge text |
| Theming | 4 | Token-based UI colors; authentic provider identity colors |
| Anti-patterns | 4 | Detector returns zero findings |

Contrast light/dark: headings 16.83/16.60, intro 7.28/8.59, Compatible 10.64/8.03, Coming soon 6.51/7.02. Reduced-motion runtime check returns zero animations. Normal motion finishes within five seconds. Status labels never animate. No real screen-reader or text-zoom session was performed.
