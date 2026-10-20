#!/bin/sh
# Writes /etc/nginx/sp-real-ip.conf from TRUSTED_PROXY_CIDRS (comma list) for an external load balancer
# (PHASE2B 4.6/5.5). Unset: no file, $remote_addr is the direct peer. Run by the nginx image entrypoint.
set -eu
out=/etc/nginx/sp-real-ip.conf
rm -f "$out"
[ -n "${TRUSTED_PROXY_CIDRS:-}" ] || exit 0
{
  echo "# generated from TRUSTED_PROXY_CIDRS"
  echo "$TRUSTED_PROXY_CIDRS" | tr ',' '\n' | while read -r cidr; do
    cidr=$(echo "$cidr" | tr -d ' ')
    case "$cidr" in
      ""|*[!0-9a-fA-F:./]*) continue ;;   # skip empty / anything that is not an address or CIDR
    esac
    echo "set_real_ip_from $cidr;"
  done
  echo "real_ip_header X-Forwarded-For;"
  echo "real_ip_recursive on;"
} > "$out"
