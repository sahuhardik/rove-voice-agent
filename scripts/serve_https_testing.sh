#!/usr/bin/env bash
# TESTING ONLY. Serves the client over HTTPS with a self-signed certificate so a
# browser treats the page as a secure context (getUserMedia needs one off
# localhost) and the signalling goes out as wss:// through the /lk relay.
#
# The certificate and key are generated on first run into server/testing-tls/
# (gitignored). They are NOT trusted by any browser, are NOT for production, and
# the key must never be reused anywhere. In production use a real certificate
# via ROVE_TLS_CERT / ROVE_TLS_KEY.
#
#   scripts/serve_https_testing.sh [extra-SAN-host-or-ip ...]
#   PORT=8443 scripts/serve_https_testing.sh
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
dir="$root/server/testing-tls"
ca="$dir/TESTING-ONLY-ca.pem"
cakey="$dir/TESTING-ONLY-ca-key.pem"
cert="$dir/TESTING-ONLY-cert.pem"
key="$dir/TESTING-ONLY-key.pem"
port="${PORT:-8443}"
mkdir -p "$dir"

# A throwaway test CA plus a leaf (CA:FALSE) signed by it. A self-signed leaf
# that is its own CA is rejected by rustls, i.e. by the livekit SDK's peer.
# Trust it for a headless peer with SSL_CERT_FILE=$ca.
if [[ ! -f "$cert" || ! -f "$key" || ! -f "$ca" ]]; then
  san="DNS:localhost,IP:127.0.0.1"
  for extra in "$@"; do
    if [[ "$extra" =~ ^[0-9.]+$ ]]; then san+=",IP:$extra"; else san+=",DNS:$extra"; fi
  done
  openssl req -x509 -newkey rsa:2048 -nodes -days 30 \
    -subj "/CN=rove TESTING ONLY CA" \
    -addext "basicConstraints=critical,CA:TRUE" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -keyout "$cakey" -out "$ca" 2>/dev/null
  openssl req -newkey rsa:2048 -nodes -subj "/CN=rove TESTING ONLY leaf" \
    -keyout "$key" -out "$dir/leaf.csr" 2>/dev/null
  printf 'basicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectAltName=%s\n' "$san" > "$dir/leaf.ext"
  openssl x509 -req -in "$dir/leaf.csr" -CA "$ca" -CAkey "$cakey" -CAcreateserial \
    -days 30 -extfile "$dir/leaf.ext" -out "$cert" 2>/dev/null
  rm -f "$dir/leaf.csr" "$dir/leaf.ext" "$dir/TESTING-ONLY-ca.srl"
  chmod 600 "$key" "$cakey"
  echo "generated TESTING-ONLY CA + certificate ($san), valid 30 days: $cert" >&2
fi

export ROVE_TLS_CERT="$cert" ROVE_TLS_KEY="$key"
export ROVE_WEB_PORT="$port" ROVE_WEB_HOST="${HOST:-127.0.0.1}"
exec "$root/.venv/bin/python" -m server
