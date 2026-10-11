#!/usr/bin/env bash
# Native app channel -> production Python bootstrap TLS/GATT and durable ledger.
# Private synthetic pipes only; no radio, root, GPIO or installed runtime.
set -euo pipefail
umask 077
ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
PACKAGE="${ROOT}/ios/Packages/InkyTLS"
export INKY_TLS_TEST_PYTHON="${INKY_TLS_TEST_PYTHON:-$(command -v python3.13 || command -v python3)}"
export INKY_REPO_ROOT="${ROOT}"
if [[ ! -d "${PACKAGE}/Artifacts/MbedTLS.xcframework" ]]; then
  printf '%s\n' 'Build the pinned InkyTLS dependency first.' >&2
  exit 1
fi
WORK=$(mktemp -d /tmp/inky-bootstrap-channel.XXXXXX)
trap 'rm -rf -- "${WORK}"' EXIT
mkdir -p "${WORK}/Sources/InkyStudio" "${WORK}/Tests/InkyStudioTests"
for source in FrameIdentity PinnedFrameTrust BootstrapFrameTrust BootstrapWire BluetoothTransport SecureBluetoothChannel BootstrapBluetoothChannel; do
  cp "${ROOT}/ios/InkyStudio/Provisioning/${source}.swift" "${WORK}/Sources/InkyStudio/"
done
cp "${ROOT}/ios/InkyStudioTests/BootstrapChannelInteropTests.swift" "${WORK}/Tests/InkyStudioTests/"
"${INKY_TLS_TEST_PYTHON}" - "${PACKAGE}" "${WORK}" <<'PY'
import json, pathlib, sys
package, work = map(pathlib.Path, sys.argv[1:])
(work / 'Package.swift').write_text('''// swift-tools-version: 6.0
import PackageDescription
let package = Package(name: "InkyBootstrapChannelQualification", platforms: [.macOS(.v15)],
 dependencies: [.package(path: %s)],
 targets: [.target(name: "InkyStudio", dependencies: [.product(name: "InkyTLS", package: "InkyTLS")]),
           .testTarget(name: "InkyStudioTests", dependencies: ["InkyStudio"])])
''' % json.dumps(str(package), ensure_ascii=False))
PY
COPYFILE_DISABLE=1 swift test --package-path "${WORK}" "$@"
