#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Bootstraps Forgejo for local dev: creates admin user, org, and API token.
# Runs as a one-shot init container sharing /data with the Forgejo service.
set -eu

ADMIN_USER="${FORGEJO_ADMIN_USER:-phiacta-admin}"
ADMIN_PASS="${FORGEJO_ADMIN_PASSWORD:-phiacta-dev-password}"
ADMIN_EMAIL="${FORGEJO_ADMIN_EMAIL:-admin@phiacta.local}"
ORG_NAME="${FORGEJO_ORG:-phiacta}"
TOKEN_NAME="phiacta-service"
TOKEN_FILE="/run/secrets/forgejo-token"
FORGEJO_API="http://forgejo:3000/api/v1"

echo "[forgejo-init] Waiting for Forgejo API..."
until wget -qO- "${FORGEJO_API}/version" >/dev/null 2>&1; do
    sleep 2
done
echo "[forgejo-init] Forgejo is ready."

# --- Create admin user via CLI (needs /data volume with DB) ---------------
echo "[forgejo-init] Creating admin user '${ADMIN_USER}'..."
forgejo admin user create \
    --admin \
    --username "${ADMIN_USER}" \
    --password "${ADMIN_PASS}" \
    --email "${ADMIN_EMAIL}" \
    --must-change-password=false 2>/dev/null \
    && echo "[forgejo-init] Admin user created." \
    || echo "[forgejo-init] Admin user already exists (ok)."

# --- Create API token via basic auth --------------------------------------
echo "[forgejo-init] Creating API token..."
EXISTING_TOKEN=$(wget -qO- \
    --header "Content-Type: application/json" \
    --user "${ADMIN_USER}:${ADMIN_PASS}" \
    "${FORGEJO_API}/users/${ADMIN_USER}/tokens" 2>/dev/null || echo "[]")

# Check if our token already exists
if echo "${EXISTING_TOKEN}" | grep -q "\"${TOKEN_NAME}\""; then
    echo "[forgejo-init] Token '${TOKEN_NAME}' already exists — deleting to regenerate."
    TOKEN_ID=$(echo "${EXISTING_TOKEN}" | sed -n "s/.*\"id\":\([0-9]*\).*\"name\":\"${TOKEN_NAME}\".*/\1/p")
    if [ -n "${TOKEN_ID}" ]; then
        wget -qO- --method=DELETE \
            --user "${ADMIN_USER}:${ADMIN_PASS}" \
            "${FORGEJO_API}/users/${ADMIN_USER}/tokens/${TOKEN_ID}" 2>/dev/null || true
    fi
fi

# Create fresh token with all scopes
TOKEN_RESPONSE=$(wget -qO- \
    --header "Content-Type: application/json" \
    --post-data "{\"name\":\"${TOKEN_NAME}\",\"scopes\":[\"all\"]}" \
    --user "${ADMIN_USER}:${ADMIN_PASS}" \
    "${FORGEJO_API}/users/${ADMIN_USER}/tokens" 2>/dev/null || echo "")

# Extract the token SHA — Forgejo returns sha1 field
TOKEN=$(echo "${TOKEN_RESPONSE}" | sed -n 's/.*"sha1":"\([^"]*\)".*/\1/p')

if [ -z "${TOKEN}" ]; then
    echo "[forgejo-init] ERROR: Failed to create API token."
    echo "[forgejo-init] Response: ${TOKEN_RESPONSE}"
    exit 1
fi
echo "[forgejo-init] API token created."

# --- Create organisation ---------------------------------------------------
echo "[forgejo-init] Creating org '${ORG_NAME}'..."
wget -qO- \
    --header "Content-Type: application/json" \
    --header "Authorization: token ${TOKEN}" \
    --post-data "{\"username\":\"${ORG_NAME}\",\"visibility\":\"private\"}" \
    "${FORGEJO_API}/orgs" 2>/dev/null \
    && echo "[forgejo-init] Org created." \
    || echo "[forgejo-init] Org already exists (ok)."

# --- Write token to shared volume -----------------------------------------
echo "${TOKEN}" > "${TOKEN_FILE}"
chmod 600 "${TOKEN_FILE}"
echo "[forgejo-init] Token written to ${TOKEN_FILE}"
echo "[forgejo-init] Bootstrap complete."
