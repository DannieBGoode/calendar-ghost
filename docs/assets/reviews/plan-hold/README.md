# Plan Hold UI review captures

Synthetic development preview only. Before: merged main262e8efd. After: PR3b implementation d011b084, with the chooser refreshed after the final review fix bbb14234. Light and Twilight dark,1440 and390px. Your plan and Preview use section captures; Rules and Overview use viewport captures.

The baseline has a Household Plan with capacity1 and two held rules. The after fixture has a Small Plan with capacity1, two held rules and the first marked kept. Account/token allowances and plan names differ between fixtures. Dates and names are synthetic.

Files are named `<before|after>-<surface>-<width>-<light|dark>.png`. Surfaces: `your-plan`, `rules`, `overview`, `preview-footer`.

The refreshed chooser includes account identities to distinguish calendars with the same name. Its390px and200% text probes pass after that change. Other surfaces retain the same source and captures.

The after keyboard flow reaches Your plan from Preview, focuses the heading, opens the chooser and focuses its legend. Choice and unchanged-save flows were also checked. Preview still shows17 results:14 writes and3 skipped.

Additional checks covered grace, reserved-only grace, mixed holds, Midnight, pseudo-locale and200% root text. The new form passes the200% geometry assertion; pre-existing Settings shell overflow also occurs on merged main and remains outside this change. These captures do not certify the entire application for WCAG.

PR review regression: `onboarding-<before|after>-<1440|390>-<light|dark>.png` uses the same isolated synthetic all-held fixture with Robin's successful run records removed. Before serves the committed471afdf3 bundle; after serves the onboarding repair. The backend reports setup, two held rules and no successful sync in both. The repair replaces Step0 with Step3 and an actionable Review rules link. Tab and Enter reach `/rules` in all four after configurations. The hero has no action in setup, so the onboarding link provides recovery. This fixture is separate from the earlier captures and the owner's port8001 preview.
