# Inky Studio — iPhone design review

Status: approved by Mehdi on 2026-09-27. These boards remain the design reference; the native implementation lives in `ios/`.

## Scope

A native iPhone companion for the existing Inky Studio Raspberry Pi server. Initial distribution is personal use, then TestFlight. The first version connects over the same local Wi-Fi network, using a manually entered and remembered address.

The proposed four tabs are Cadre, File, Historique and Réglages. Connection is outside the tab navigation; crop preparation is a modal flow without a tab bar. Apple's photo picker retains its native interface.

Open `index.html` for the review gallery. The two PNG boards cover six screens; they are visual references, not a working app.

## Visual direction

- Preserve the approved light bento direction: white surfaces, near-black controls and thin neutral borders.
- Suggested implementation tokens: background #F5F5F3, surface #FFFFFF, text #111111, secondary text #65656B, border #E3E3E5, blue #2F79EE, amber #B77900.
- System typography; 34 pt large navigation titles, 17 pt body and controls, 13–15 pt supporting labels.
- 16 pt outer gutters and gaps; 20 pt card corners; touch areas at least 44 × 44 pt.
- Blue emphasizes adding photos; amber identifies scheduling. Color is accompanied by text or a symbol.
- Bottom navigation has four consistently labeled icons and a clearly selected tab. Respect safe areas and Dynamic Type.
- The current photo keeps the panel's aspect ratio. Photos, filenames, counts, times and addresses in the boards are illustrative.

## Screen behavior

1. **Cadre**: current photo, previous/next controls, next scheduled change, queue summary and primary add action. Distinguish the Raspberry connection from actual physical display health.
2. **File**: ordered photo cards, first-item designation, visible reorder handles, add and edit controls. Edit includes deletion and an accessible alternative to dragging. Adding a photo does not imply immediate physical display.
3. **Historique**: photos grouped by display date, with an explicit Remettre dans la file action.
4. **Connexion**: the illustrated screen is a returning user with an already paired frame. Face ID is the primary action, with an explicit password fallback. First pairing uses a manually entered frame address and password, followed by an optional offer to enable Face ID. No automatic discovery promise.
5. **Cadrage**: preview, pan/pinch, reset and Ajouter à la file. The preview represents composition; the Pi adapts colors to the e-ink panel.
6. **Réglages**: daily/interval/manual schedule, time, saturation, optional Face ID connection, frame information, Pi update and sign out. Schedule times refer to the Pi's local time.

## Face ID connection proposal

The user explicitly requested Face ID for easy login. After a successful first password login, offer to save the frame credential in the iPhone Keychain, with access protected by Apple's LocalAuthentication. Face ID authorizes access to that saved credential; the Raspberry still authenticates with its existing password mechanism. No face image is collected by the app and no Apple/cloud account is required.

Suggested opt-in explanation: **« Face ID autorise l’utilisation du mot de passe enregistré sur cet iPhone. »** In Settings, use **« Connexion avec Face ID »**. The board abbreviates this row to Face ID.

Keep **« Utiliser le mot de passe »** available when Face ID is cancelled, unavailable, refused or unsuccessful. Adapt to device capabilities during implementation, including the native Face ID usage explanation. If the Pi password changes, ask for the new password and update the saved credential only after successful authentication. Disabling this option removes the saved credential. Signing out ends the current session; a separate forget-frame action removes the saved address and credential.

This is a proposed convenience login flow, not a requirement to lock the app every time it returns to the foreground. Exact session and Keychain behavior will be validated during development.

Apple references: [LocalAuthentication](https://developer.apple.com/documentation/localauthentication), [Face ID / Touch ID login](https://developer.apple.com/documentation/localauthentication/logging-a-user-into-your-app-with-face-id-or-touch-id), [Keychain biometric access](https://developer.apple.com/documentation/localauthentication/accessing-keychain-items-with-face-id-or-touch-id).

## States to implement after design approval

- Empty queue/history with a useful add-photo action.
- Raspberry unreachable, old cached state identified, and manual reconnect.
- Local-network permission denied and session expired.
- Face ID opt-in declined, cancelled, unavailable, or saved password rejected.
- iCloud photo loading, cancellation, upload progress and readable errors.
- Success: Photo ajoutée à la file. Display refresh remains a separate operation.
- Display refresh busy state; prevent duplicate commands and resync after a timeout.
- Long photo names wrapping to two lines and Dynamic Type layouts.

## Review

Validate overall hierarchy, dashboard density, card style, bottom tabs and the crop flow before beginning SwiftUI implementation. These image-generated boards are visual references; final text layout, contrast and accessibility will be checked in the native UI.

Both boards received a separate visual review with no blocking issue for design approval. Copy refinements for implementation: use **« Heure d’affichage »** (Pi local time) instead of « Heure du cadre », and **« Utiliser le mot de passe enregistré »** as the Face ID row's explanatory text.

Generated with the built-in ImageGen tool. The approved desktop bento mockup was used as the style reference; no private photo was provided. The accompanying prompts record the visual specification.
