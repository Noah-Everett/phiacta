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

    # Create "Members" team for provisioned users (idempotent).
    # Users need issues + pulls access for Sudo-based edit proposals.
    curl -sf \
        -u "${ADMIN_USER}:${ADMIN_PASS}" \
        -H "Content-Type: application/json" \
        -d '{"name":"Members","permission":"write","units":["repo.code","repo.issues","repo.pulls"],"includes_all_repositories":true}' \
        "http://localhost:3000/api/v1/orgs/${ORG_NAME}/teams" >/dev/null 2>&1 \
        || true

    # Mint an API token for the backend and write it to a shared file.
    # Opt-in via FORGEJO_TOKEN_FILE (the shared-volume setup, e.g. dev). A
    # deployment that injects FORGEJO_ADMIN_TOKEN via env instead leaves this
    # unset, so we don't mint orphan tokens or clobber the env-provided one.
    #
    # Token auth avoids Forgejo's per-request password KDF (BasicAuth costs
    # ~180ms/request). The secret is shown only on creation, so we delete +
    # recreate each boot; the backend re-reads the file and self-heals if the
    # token rotates. If anything here fails, the backend falls back to BasicAuth.
    if [ -n "${FORGEJO_TOKEN_FILE:-}" ]; then
        TOKEN_NAME="phiacta-backend"
        curl -s -u "${ADMIN_USER}:${ADMIN_PASS}" -X DELETE \
            "http://localhost:3000/api/v1/users/${ADMIN_USER}/tokens/${TOKEN_NAME}" \
            >/dev/null 2>&1 || true
        TOKEN_RESP="$(curl -s \
            -u "${ADMIN_USER}:${ADMIN_PASS}" \
            -H "Content-Type: application/json" \
            -d "{\"name\":\"${TOKEN_NAME}\",\"scopes\":[\"write:admin\",\"write:organization\",\"write:repository\",\"write:issue\",\"write:user\",\"write:misc\"]}" \
            "http://localhost:3000/api/v1/users/${ADMIN_USER}/tokens" 2>/dev/null || true)"
        TOKEN="$(printf '%s' "${TOKEN_RESP}" | sed -n 's/.*"sha1":"\([0-9a-f]*\)".*/\1/p')"
        if [ -n "${TOKEN}" ]; then
            printf '%s' "${TOKEN}" > "${FORGEJO_TOKEN_FILE}"
            chmod 644 "${FORGEJO_TOKEN_FILE}"
            echo "phiacta: wrote backend API token to ${FORGEJO_TOKEN_FILE}"
        else
            echo "phiacta: WARNING could not mint backend API token; backend will use BasicAuth" >&2
        fi
    fi
) &

# Start Forgejo via its original entrypoint (PID 1 for proper signal handling)
exec /usr/bin/entrypoint
