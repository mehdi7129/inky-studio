# Inky Studio public website

Three static French pages with local CSS and images. No JavaScript, external font,
analytics integration, forms, or build dependencies are included.

- `index.html`: product overview and private TestFlight beta status.
- `support.html`: setup, troubleshooting, and the authorized public contact.
- `confidentialite.html`: app, Raspberry, website, and support data practices.

Public origin: `https://inky-studio.netlify.app`.

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
