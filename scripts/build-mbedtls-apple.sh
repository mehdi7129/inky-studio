#!/usr/bin/env bash
# Build the pinned upstream release for the local InkyTLS package. No global install.
set -euo pipefail
ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
PACKAGE="${ROOT}/ios/Packages/InkyTLS"
WORK="${PACKAGE}/.build/mbedtls-apple"
ARTIFACTS="${PACKAGE}/Artifacts"
PYTHON="${INKY_TLS_PYTHON:-$(command -v python3.13 || command -v python3)}"
JOBS="${INKY_TLS_BUILD_JOBS:-4}"
command -v cmake >/dev/null
command -v xcrun >/dev/null
"${PYTHON}" -c 'import sys; assert sys.version_info >= (3,12), "Python >=3.12 required for filtered extraction"'
mkdir -p "${WORK}" "${ARTIFACTS}"
"${PYTHON}" - "${WORK}" <<'PY'
import hashlib,json,pathlib,shutil,tarfile,urllib.request,sys
base=pathlib.Path(sys.argv[1])
url='https://github.com/Mbed-TLS/mbedtls/releases/download/mbedtls-4.1.1/mbedtls-4.1.1.tar.bz2'
expected='3359a349e23db3d5536fcee032ae7b2ecbfc08972fab643089b5cbf2a375c98c'
archive=base/'mbedtls-4.1.1.tar.bz2'
if not archive.exists():
    with urllib.request.urlopen(url,timeout=30) as response: archive.write_bytes(response.read())
if hashlib.sha256(archive.read_bytes()).hexdigest()!=expected:
    raise SystemExit('Mbed TLS archive hash mismatch; refusing build')
# Re-extract verified source; remove extra files left in an edited source cache.
source_dir=base/'mbedtls-4.1.1'
if source_dir.is_symlink(): source_dir.unlink()
elif source_dir.exists(): shutil.rmtree(source_dir)
with tarfile.open(archive) as source: source.extractall(base,filter='data')
(base/'source.json').write_text(json.dumps({'version':'4.1.1','url':url,'sha256':expected},indent=2)+'\n')
PY
SOURCE="${WORK}/mbedtls-4.1.1"
build_slice() {
  local name="$1" sdk="$2" arch="$3" platform="$4" minimum="$5"
  local sdk_path build
  sdk_path=$(xcrun --sdk "${sdk}" --show-sdk-path)
  build="${WORK}/${name}"
  printf 'Building Mbed TLS %s (%s)…\n' "${name}" "${sdk}"
  cmake -S "${SOURCE}" -B "${build}" \
    -DCMAKE_SYSTEM_NAME="${platform}" -DCMAKE_SYSTEM_PROCESSOR="${arch}" \
    -DCMAKE_C_COMPILER="$(xcrun --sdk "${sdk}" --find clang)" \
    -DCMAKE_OSX_SYSROOT="${sdk_path}" -DCMAKE_OSX_ARCHITECTURES="${arch}" \
    -DCMAKE_OSX_DEPLOYMENT_TARGET="${minimum}" -DCMAKE_BUILD_TYPE=MinSizeRel \
    -DCMAKE_POSITION_INDEPENDENT_CODE=ON -DENABLE_PROGRAMS=OFF -DENABLE_TESTING=OFF \
    -DUSE_SHARED_MBEDTLS_LIBRARY=OFF -DUSE_STATIC_MBEDTLS_LIBRARY=ON \
    -DCMAKE_INSTALL_PREFIX="${build}/install" > "${WORK}/${name}-configure.log" 2>&1
  cmake --build "${build}" -j "${JOBS}" > "${WORK}/${name}-build.log" 2>&1
  cmake --install "${build}" > "${WORK}/${name}-install.log" 2>&1
  xcrun libtool -static -o "${build}/libMbedTLS.a" \
    "${build}/library/libmbedtls.a" "${build}/library/libmbedx509.a" \
    "${build}/tf-psa-crypto/core/libtfpsacrypto.a" 2> "${WORK}/${name}-libtool.log"
}
build_slice iphoneos-arm64 iphoneos arm64 iOS 18.0
build_slice simulator-arm64 iphonesimulator arm64 iOS 18.0
build_slice simulator-x86_64 iphonesimulator x86_64 iOS 18.0
build_slice macos-arm64 macosx arm64 Darwin 13.0
build_slice macos-x86_64 macosx x86_64 Darwin 13.0
mkdir -p "${WORK}/simulator" "${WORK}/macos" "${WORK}/headers"
xcrun lipo -create "${WORK}/simulator-arm64/libMbedTLS.a" "${WORK}/simulator-x86_64/libMbedTLS.a" -output "${WORK}/simulator/libMbedTLS.a"
xcrun lipo -create "${WORK}/macos-arm64/libMbedTLS.a" "${WORK}/macos-x86_64/libMbedTLS.a" -output "${WORK}/macos/libMbedTLS.a"
cp -R "${WORK}/iphoneos-arm64/install/include/." "${WORK}/headers/"
cat > "${WORK}/headers/MbedTLS.h" <<'HEADER'
#include <mbedtls/ssl.h>
#include <mbedtls/x509_crt.h>
#include <mbedtls/pk.h>
#include <mbedtls/error.h>
#include <mbedtls/platform_util.h>
#include <psa/crypto.h>
HEADER
cat > "${WORK}/headers/module.modulemap" <<'MODULE'
module MbedTLS [system] {
  umbrella header "MbedTLS.h"
  export *
}
MODULE
rm -rf "${WORK}/MbedTLS.xcframework"
xcodebuild -create-xcframework \
  -library "${WORK}/iphoneos-arm64/libMbedTLS.a" -headers "${WORK}/headers" \
  -library "${WORK}/simulator/libMbedTLS.a" -headers "${WORK}/headers" \
  -library "${WORK}/macos/libMbedTLS.a" -headers "${WORK}/headers" \
  -output "${WORK}/MbedTLS.xcframework"
rm -rf "${ARTIFACTS}/MbedTLS.xcframework"
mv "${WORK}/MbedTLS.xcframework" "${ARTIFACTS}/MbedTLS.xcframework"
cp "${WORK}/source.json" "${ARTIFACTS}/source.json"
{
  xcodebuild -version
  xcrun clang --version
  cmake --version
  printf 'Configuration: MinSizeRel; iOS18/macOS13; upstream default crypto; static; no programs/tests\n'
} > "${ARTIFACTS}/toolchain.txt"
printf 'Generated %s/MbedTLS.xcframework\n' "${ARTIFACTS}"
