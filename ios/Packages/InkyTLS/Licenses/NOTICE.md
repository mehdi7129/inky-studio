# Third-party notices

InkyTLS links Mbed TLS 4.1.1 and the TF-PSA-Crypto dependency supplied by its
official release archive, under their Apache-2.0 option. Full upstream license
files are retained here. Keep these notices with distributed binaries.

- Mbed TLS / TF-PSA-Crypto: Copyright The Mbed TLS Contributors.
- Project Everest / HACL* portions: Copyright 2016–2018 INRIA and Microsoft
  Corporation; Apache-2.0. Generated KreMLin/F* portions retain attribution
  to INRIA and Microsoft Corporation.
- p256-m: Copyright The Mbed TLS Contributors; author Manuel Pégourié-Gonnard.
  Apache-2.0 option of the upstream dual license.
- mldsa-native portions supplied in TF-PSA-Crypto: upstream license and
  attributions preserved in MLDSA-Native-LICENSE.txt. Not a claim that this
  TLS client negotiates a post-quantum cipher suite.

Source: verified `mbedtls-4.1.1.tar.bz2`; SHA-256 is pinned by
`scripts/build-mbedtls-apple.sh`. No upstream source or binary is committed.
The bridge uses public APIs without patching cryptographic implementation.

## App distribution

`ios/InkyStudio/Resources/ThirdPartyNotices.txt` reproduces all three full license
files above and preserves the upstream driver attributions. The three texts
were compared byte-for-byte with the hash-pinned release archive on 27 September
2026. Regenerate the Xcode project after adding/changing resource membership;
XcodeGen's recursive `InkyStudio` source entry classifies the `.txt` file as an
app resource. The Swift package itself does not copy these notices into its
consumer's app bundle.

Before distributing an archive, check that `InkyStudio.app/ThirdPartyNotices.txt`
exists and matches the repository resource (for example with `cmp`). Keep this
resource synchronized whenever the pinned library version changes.
