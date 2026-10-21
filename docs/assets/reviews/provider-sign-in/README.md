# Provider sign-in review screenshots

These before/after captures use only the local development preview's synthetic people and
provider responses. The final captures show source `b3edf8b2dbf7d9698f65279f9bf834637400aebc`
after the provider UI repair pass. No personal calendar data, live provider credentials, or live
Google/Microsoft sign-in is represented. Images are unchanged copies of the review originals.

| Surface | Theme | Browser viewport | Before | After |
| --- | --- | --- | --- | --- |
| Sign-in | Light | 1440 × 1000 | [Before](before-sign-in-light-1440.png) | [After](final-sign-in-light-1440.png) |
| Sign-in | Dark | 1440 × 1000 | [Before](before-sign-in-dark-1440.png) | [After](final-sign-in-dark-1440.png) |
| Sign-in | Light | 390 × 844 | [Before](before-sign-in-light-390.png) | [After](final-sign-in-light-390.png) |
| Sign-in | Dark | 390 × 844 | [Before](before-sign-in-dark-390.png) | [After](final-sign-in-dark-390.png) |
| Your account | Light | 390 × 844 | [Before](before-account-light-390.png) | [After](final-account-light-390.png) |
| Administration | Dark | 1440 × 1000 | [Before](before-administration-dark-1440.png) | [After](final-administration-dark-1440.png) |

The final live recheck exercised synthetic Microsoft password linking, single-binding removal
and keyboard focus recovery, provider Off/On controls, keyboard setup disclosure, and Invitation
ready/unavailable/pending states. Final document widths matched the recorded viewport widths.
Long full-page captures may be downscaled, so PNG pixel dimensions need not equal browser geometry.

Physical touch was not tested: the coarse-pointer target fix was checked in source and served
CSS. Multiple bindings, an actor change during removal, and deliberately moved focus rely on
unit regressions rather than live fixtures. Screen-reader speech, native zoom, complete WCAG AA
conformance, real provider infrastructure, and final whole-branch delivery are outside this
evidence. Screenshots show the stated source revision and do not certify later changes.

See [development preview instructions](../../../development.md#provider-sign-in-preview).
