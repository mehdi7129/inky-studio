#!/bin/sh
# Synthetic, local memory-buffer bench. No sockets, BLE, Pi or Wi-Fi changes.
set -eu
umask 077
source_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
python_bin=${INKY_BENCH_PYTHON:-}
if [ -z "$python_bin" ]; then
  if command -v python3.13 >/dev/null 2>&1; then python_bin=$(command -v python3.13)
  else python_bin=$(command -v python3); fi
fi
openssl_bin=${INKY_BENCH_OPENSSL:-}
if [ -z "$openssl_bin" ]; then
  if [ -x /opt/homebrew/opt/openssl@3/bin/openssl ]; then
    openssl_bin=/opt/homebrew/opt/openssl@3/bin/openssl
  elif [ -x /usr/local/opt/openssl@3/bin/openssl ]; then
    openssl_bin=/usr/local/opt/openssl@3/bin/openssl
  else openssl_bin=$(command -v openssl); fi
fi
command -v cmake >/dev/null
command -v clang >/dev/null
command -v strip >/dev/null
"$python_bin" -c 'import platform,ssl,sys; assert sys.version_info >= (3,12), "Python >=3.12 required for safe extraction"; assert platform.system() == "Darwin", "macOS bench only"; assert ssl.HAS_TLSv1_3 and ssl.OPENSSL_VERSION.startswith("OpenSSL "), ssl.OPENSSL_VERSION'
work_dir=$(mktemp -d "${TMPDIR:-/tmp}/inky-c2-tls-bench.XXXXXX")
report_exit() {
  result_code=$?
  if [ "$result_code" -ne 0 ]; then
    printf 'Bench failed; local artifacts: %s\n' "$work_dir" >&2
  fi
}
trap report_exit EXIT
cp "$source_dir/client.c" "$source_dir/run.py" "$work_dir/"
cd "$work_dir"
printf 'Local artifacts: %s\n' "$work_dir"
"$python_bin" - <<'PY'
import hashlib,json,pathlib,tarfile,urllib.request
base=pathlib.Path.cwd()
url='https://github.com/Mbed-TLS/mbedtls/releases/download/mbedtls-4.1.1/mbedtls-4.1.1.tar.bz2'
expected='3359a349e23db3d5536fcee032ae7b2ecbfc08972fab643089b5cbf2a375c98c'
with urllib.request.urlopen(url,timeout=30) as response: data=response.read()
digest=hashlib.sha256(data).hexdigest()
if digest != expected: raise SystemExit('Archive SHA-256 mismatch; refusing extraction/build')
archive=base/'mbedtls-4.1.1.tar.bz2'; archive.write_bytes(data)
with tarfile.open(archive) as tf: tf.extractall(base,filter='data')
(base/'source.json').write_text(json.dumps({'url':url,'sha256':digest,'bytes':len(data)},indent=2)+'\n')
PY
cmake -S mbedtls-4.1.1 -B build -DCMAKE_BUILD_TYPE=MinSizeRel \
  -DENABLE_PROGRAMS=OFF -DENABLE_TESTING=OFF \
  -DUSE_SHARED_MBEDTLS_LIBRARY=OFF -DUSE_STATIC_MBEDTLS_LIBRARY=ON \
  -DCMAKE_POSITION_INDEPENDENT_CODE=ON > configure.log 2>&1
cmake --build build -j 4 > build.log 2>&1
clang -Os -fvisibility=hidden -dynamiclib -Wl,-dead_strip \
  -I mbedtls-4.1.1/include -I mbedtls-4.1.1/tf-psa-crypto/include \
  -I mbedtls-4.1.1/tf-psa-crypto/drivers/builtin/include \
  client.c build/library/libmbedtls.a build/library/libmbedx509.a \
  build/tf-psa-crypto/core/libtfpsacrypto.a -o libinky_c2_bench.dylib
strip -x libinky_c2_bench.dylib
"$openssl_bin" req -new -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes \
  -keyout ca.key -out ca.pem -days 2 -subj '/CN=Inky Synthetic Bench CA' \
  -addext 'basicConstraints=critical,CA:TRUE' \
  -addext 'keyUsage=critical,keyCertSign,cRLSign' > certificates.log 2>&1
"$openssl_bin" req -new -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes \
  -keyout server.key -out server.csr -subj '/CN=inky-bench.test' >> certificates.log 2>&1
cat > leaf.ext <<'EOF'
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature
extendedKeyUsage=serverAuth
subjectAltName=DNS:inky-bench.test
EOF
"$openssl_bin" x509 -req -in server.csr -CA ca.pem -CAkey ca.key -CAcreateserial \
  -out server.pem -days 1 -sha256 -extfile leaf.ext >> certificates.log 2>&1
"$openssl_bin" x509 -in server.pem -pubkey -noout -out server-public.pem
"$openssl_bin" pkey -pubin -in server-public.pem -outform DER -out server-spki.der
"$python_bin" run.py
printf 'Result JSON: %s/result.json\n' "$work_dir"
