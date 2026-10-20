# Password recovery UI evidence

Synthetic development preview, checked with the keyboard at 1,440 and 390 pixels in light and
dark appearances. The before UI is the exact compiled frontend from `origin/main` at `4da18b83`.
The after UI is `bad33b25`. No real account, SMTP server, provider, or event data was used.

The request, generic confirmation, retry, usable link, completed reset, used link, and unavailable
recovery states were checked live. Request confirmation receives focus; retry restores the retained
email field. Password reset removes its URL fragment, keeps the user signed out, and offers sign-in.
Reopening the used link offers another request when configured. No horizontal overflow or browser
console error was found. Recovery actions reach 44 pixels in height.

| Width and appearance | Before sign-in | After sign-in | Request form |
| --- | --- | --- | --- |
| 1,440 light | [Before](before-sign-in-1440-light.png) | [After](after-sign-in-1440-light.png) | [Request](after-request-1440-light.png) |
| 1,440 dark | [Before](before-sign-in-1440-dark.png) | [After](after-sign-in-1440-dark.png) | |
| 390 light | [Before](before-sign-in-390-light.png) | [After](after-sign-in-390-light.png) | [Request](after-request-390-light.png) |
| 390 dark | [Before](before-sign-in-390-dark.png) | [After](after-sign-in-390-dark.png) | [Request](after-request-390-dark.png) |

These are unmodified browser screenshots. The headless browser sometimes omitted the unchanged
intro panel from a full-page capture. An element capture forced its paint before the selected
full-page captures. The selected images were opened and checked; no DOM or CSS was altered.
