#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Custom Forgejo entrypoint: bootstraps admin user and org after Forgejo starts.
# Replaces the separate forgejo-init container with an in-process background task.
set -eu

# Background init: runs after Forgejo's API is ready
(
    ADMIN_USER="${FORGEJO_ADMIN_USER:-phiacta-admin}"
    ADMIN_PASS="${FORGEJO_ADMIN_PASSWORD:-phiacta-dev-password}"
    ADMIN_EMAIL="${FORGEJO_ADMIN_EMAIL:-admin@phiacta.local}"
    ORG_NAME="${FORGEJO_ORG:-phiacta}"

    # Wait for Forgejo API to become available
    until curl -sf http://localhost:3000/api/v1/version >/dev/null 2>&1; do
        sleep 2
    done

    # Create admin user via CLI (talks to DB directly, idempotent)
    su-exec git forgejo admin user create \
        --admin \
        --username "${ADMIN_USER}" \
        --password "${ADMIN_PASS}" \
        --email "${ADMIN_EMAIL}" \
        --must-change-password=false 2>/dev/null \
        || true

    # Create organisation via API with basic auth (idempotent)
    curl -sf \
        -u "${ADMIN_USER}:${ADMIN_PASS}" \
        -H "Content-Type: application/json" \
        -d "{\"username\":\"${ORG_NAME}\",\"visibility\":\"private\"}" \
        "http://localhost:3000/api/v1/orgs" >/dev/null 2>&1 \
        || true
) &

# Start Forgejo via its original entrypoint (PID 1 for proper signal handling)
exec /usr/bin/entrypoint
