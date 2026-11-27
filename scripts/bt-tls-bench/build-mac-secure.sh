#!/usr/bin/env bash
set -euo pipefail
repo=$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd)
umask 077
bench_dir="$(mktemp -d /tmp/inky-secure-qualification.XXXXXX)"
mkdir -p "$bench_dir/Sources/InkySecureBench"
cp "$repo/scripts/bt-tls-bench/MacSecureQualification.swift" "$bench_dir/Sources/InkySecureBench/"
for source in FrameIdentity PinnedFrameTrust BluetoothTransport SecureBluetoothChannel; do
  cp "$repo/ios/InkyStudio/Provisioning/$source.swift" "$bench_dir/Sources/InkySecureBench/"
done
python3 - "$repo" "$bench_dir" <<'PY'
import json, pathlib, sys
repo, work = map(pathlib.Path, sys.argv[1:])
manifest = '''// swift-tools-version: 6.0
import PackageDescription
let package = Package(name: "InkySecureQualification", platforms: [.macOS(.v13)],
 dependencies: [.package(path: %s)],
 targets: [.executableTarget(name: "InkySecureBench", dependencies: [.product(name: "InkyTLS", package: "InkyTLS")])])
''' % json.dumps(str(repo / 'ios/Packages/InkyTLS'), ensure_ascii=False)
(work / 'Package.swift').write_text(manifest)
PY
COPYFILE_DISABLE=1 swift build --package-path "$bench_dir" -c release > "$bench_dir/build.log" 2>&1 || { tail -60 "$bench_dir/build.log"; exit 1; }
app="$bench_dir/Inky Secure BLE Bench.app"
mkdir -p "$app/Contents/MacOS"
cp "$bench_dir/.build/release/InkySecureBench" "$app/Contents/MacOS/InkySecureBench"
cat > "$app/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>fr.mehdiguiard.InkySecureBLEBench</string>
<key>CFBundleExecutable</key><string>InkySecureBench</string>
<key>CFBundleName</key><string>Inky Secure BLE Bench</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleVersion</key><string>1</string>
<key>NSBluetoothAlwaysUsageDescription</key><string>Tester un échange Bluetooth TLS synthétique avec le cadre, sans modifier son Wi-Fi.</string>
<key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
codesign --force --sign - "$app" > "$bench_dir/codesign.log" 2>&1
printf '%s\n' "$app"
