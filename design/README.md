# Inky Studio design

The approved direction is the white/black bento in [the September 2026 explorations](explorations/2026-09-26/index.html). The other two directions remain reference concepts.

## Implementation

- White surfaces, near-black actions, thin neutral borders and 20 px cards.
- Small blue accents for adding photos, amber for scheduling, semantic status colors.
- Asymmetric dashboard with the current photo, next change, uploader, queue preview and detected display.
- Shared controls and line icons across the dashboard, queue, history, settings, conversion and login.
- A light theme on all devices, as explicitly selected; no automatic dark-mode override.
- Full source aspect ratios on the dashboard and conversion preview. Images and dates come from the API; no concept photos or invented scheduling data ship in the application.
- Real driver detection is labeled “Écran détecté”, not a live hardware health guarantee. Mock mode is explicit.

The frontend retains the API contracts and concurrency guards from the stabilization audit. Device installation, scheduling and color conversion are unchanged.

## Validation — 2026-09-26

- 23 existing frontend regression tests pass, including stale crop upload prevention, queue refresh and overlapping response protection.
- ESLint, TypeScript and Vite production build pass. The existing lazy HEIC decoder still produces a large-chunk warning.
- Safari visual checks at 320/375 px and a 1440 px desktop layout, using local mock hardware. Dashboard, queue, settings and crop preparation reviewed.
- Independent code review found three presentation issues: misleading connection wording, narrow navigation and low-contrast icon buttons. All were corrected.

Hardware was identified separately in read-only mode. This design has not been deployed to the Raspberry Pi or tested with a physical refresh.
