#!/bin/bash
set -euo pipefail

source_dir="$(cd "$(dirname "$0")" && pwd)"
bundle="${1:-/tmp/inky-ble-bench-build/InkyBLEBench.app}"
mkdir -p "$bundle/Contents/MacOS"
cat > "$bundle/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>fr.mehdiguiard.inkystudio.blebench</string>
<key>CFBundleName</key><string>Inky BLE Bench</string>
<key>CFBundleDisplayName</key><string>Inky BLE Bench</string>
<key>CFBundleExecutable</key><string>InkyBLEBench</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleVersion</key><string>1</string>
<key>LSMinimumSystemVersion</key><string>13.0</string>
<key>NSBluetoothAlwaysUsageDescription</key><string>Tester la liaison Bluetooth avec le cadre Inky sans modifier son réseau Wi-Fi.</string>
</dict></plist>
PLIST
xcrun swiftc -swift-version 5 -O -framework AppKit -framework CoreBluetooth "$source_dir/MacBLEBench.swift" -o "$bundle/Contents/MacOS/InkyBLEBench"
codesign --force --sign - --identifier fr.mehdiguiard.inkystudio.blebench "$bundle"
printf '%s\n' "$bundle"
