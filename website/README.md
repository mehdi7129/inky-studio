# Inky Studio public website

Three static French pages with local CSS and images. No JavaScript, external font,
analytics integration, forms, or build dependencies are included.

- `index.html`: product overview and private TestFlight beta status.
- `support.html`: setup, troubleshooting, and the authorized public contact.
- `confidentialite.html`: app, Raspberry, website, and support data practices.

Public origin: `https://inky-studio.netlify.app`.

Product-status copy was refreshed on **2026-10-09** against
[`TESTFLIGHT-DELIVERY.md`](../docs/ios/TESTFLIGHT-DELIVERY.md) and the iOS views:

- Internal TestFlight build **1.0.0 (9)** has been distributed. The local demo,
  getting-started guide, camera capture and Bluetooth setup are included.
- QR adoption and a real Wi-Fi transition still require physical qualification;
  the demo does not configure hardware or prove physical display behavior.
- Apple approved encryption compliance on **2026-10-08**. This is not public
  App Review approval; the app has not been released publicly.

The privacy-page refresh changes feature availability wording only. Data flows,
retention periods and user-rights commitments are unchanged.

Published on **2026-10-09**, Netlify deploy **6ac8afec8db6a703ee84da1c**. At
**09:12 UTC**, all three public pages and five assets returned HTTP 200; page
text and asset bytes matched this source, and the configured security headers
were present. The preview's home and support sections were visually checked in
Chrome. CSS and screenshots were unchanged. Deployment receipts and checks live
under ignored `build/ios/release-readiness-2026-10-09/` at the repository root.

The three screenshots in `assets/` are unmodified copies of the authentic beta
captures in `docs/ios/screenshots/`. They contain synthetic test images and a
loopback test-server address. Their origin is disclosed next to the screenshots.

For a local preview, run `python3 -m http.server 8877` from this directory.
The site needs no build step. When deploying this folder to Netlify, use the
included `netlify.toml` as the configuration and `.` as its publish directory
(or set the repository base directory to `website`). The security headers must
be applied by Netlify; a plain Python preview does not add them.

The published support-retention policy commits to retaining resolved support
messages for up to one year, except for overriding legal requirements. This is
an operational policy for the maintainer; this static website does not automate
mailbox deletion.

Before changing the beta status or adding analytics, remote demo services, or
forms, update the product and privacy copy to reflect the actual behavior.
