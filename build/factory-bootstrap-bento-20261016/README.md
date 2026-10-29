# Factory Bento display candidate

Factory-only Pillow renderer: white background, three simple cards, a large QR,
large French copy and the existing admission/display lifecycle. At 800×480 the
synthetic QR is 305×305 pixels: 61 modules including the four-module quiet zone,
with each module exactly 5×5 pixels. At 1600×960 it is 610×610 pixels, 10×10 per
module. There is no fractional resampling, cropping, IP/password or demo copy.

The 800×480 and larger layout says “Connecter mon cadre.”, “Scannez ce QR avec
l’app.” and “Le Wi-Fi ensuite.” / “Choisissez votre réseau dans l’app, après le
scan.” Associated/expired pages use the same light style without inventing a
network state. Smaller panels preserve the existing compact renderer.

All preview credentials are deliberate fixtures, never generated device data:
QRv2/bootstrap, UUID `00000000-0000-4000-8000-000000000001`, public pin equal to
64 `1` characters and token equal to 64 `a` characters. Exact payload is retained
in `synthetic-payload.json`. No real device key, Wi-Fi setting or owner is used.

Previews:

- `factory-qr-800x480-synthetic.png`
- `factory-qr-1600x960-synthetic.png`
- `factory-associe-800x480-synthetic.png`
- `factory-associe-1600x960-synthetic.png`
- `factory-expire-800x480-synthetic.png`
- `factory-expire-1600x960-synthetic.png`

Validation: 186 focused cases PASS across bootstrap screen, runtime, wire and
admission; Ruff PASS for the two changed Python files. The image tests compare
the entire QR including its quiet zone, require integer modules, check actual
glyph bounds and separate cards, exercise installed/bundled font fallbacks and
preserve the exact protocol payload. The 800×480 QR and associated previews were
visually inspected. Optical decoding by the coordinator and physical e-ink
readability remain separate checks; this is a source preview, not a deployment.

No normal welcome, auth, protocol, display driver, radio, iOS, Pi, SD or OS
runtime is changed. No dependency is added. Admission checks, display reservation,
private `_push` and release/shutdown behavior are unchanged.
