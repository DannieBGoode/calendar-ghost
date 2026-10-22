# Provider identity assets

Downloaded from the providers' official identity branding pages on 2026-10-21.
These are identity marks, separate from the Google Calendar and Outlook product marks.

- `google-light.png` and `google-dark.png`: unchanged Android + Web, 2x, no-text square assets from https://developers.google.com/static/identity/images/signin-assets.zip, linked by https://developers.google.com/identity/branding-guidelines. CSS displays the central 20px identity mark from each 40px asset without redrawing or distorting it. Google marks remain subject to Google's branding guidelines and trademark rights.
- `microsoft.svg`: unchanged https://learn.microsoft.com/en-us/entra/identity-platform/media/howto-add-branding-in-apps/ms-symbollockup_mssymbol_19.svg, linked by https://learn.microsoft.com/en-us/entra/identity-platform/howto-add-branding-in-apps. Microsoft marks remain subject to Microsoft's branding guidelines and trademark rights.
- `google-sans-latin-500.woff2`: Google Fonts' Latin Google Sans Medium webfont, downloaded from the `fonts.googleapis.com/css2?family=Google+Sans:wght@500&display=swap` stylesheet. SIL Open Font License 1.1 is included and shipped as `web/public/licenses/google-sans-OFL.txt`, from https://github.com/google/fonts/blob/main/ofl/googlesans/OFL.txt. The font is used only for the Google sign-in button; future non-Latin translations should include their matching local subset.

All runtime assets are bundled locally. No fonts, scripts, or images are fetched from providers by these controls.
