#!/bin/sh
set -eu

cat > /usr/share/nginx/html/app-config.js <<EOF
window.__APP_CONFIG__ = {
  API_BASE_URL: "${API_BASE_URL:-/api}"
};
EOF
