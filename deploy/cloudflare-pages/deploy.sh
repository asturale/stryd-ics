#!/bin/sh
# Static mode on Cloudflare Pages: regenerate the feed and deploy it only when it changed.
# Run from cron, e.g. every 6 hours:  17 */6 * * *  /path/to/deploy/cloudflare-pages/deploy.sh
#
# Needs (env or ../../.env next to the repo root):
#   STRYD_EMAIL, STRYD_PASSWORD, ICS_TOKEN  as for the server
#   CLOUDFLARE_API_TOKEN   a token with only "Account > Cloudflare Pages: Edit"
#   CLOUDFLARE_ACCOUNT_ID, PAGES_PROJECT    your account id and Pages project name
# Set FEED_HOST as a Pages environment variable (your custom domain): the middleware
# serves the feed only there, so *.pages.dev and per-deploy preview URLs return 404.
set -eu
cd "$(dirname "$0")"
[ -f ../../.env ] && set -a && . ../../.env && set +a
: "${CLOUDFLARE_API_TOKEN:?}" "${CLOUDFLARE_ACCOUNT_ID:?}" "${PAGES_PROJECT:?}"
WRANGLER_VERSION=4.156.0  # pinned on purpose; bump deliberately

rc=0; python3 ../../server.py --write public || rc=$?
[ "$rc" = 3 ] && exit 0      # unchanged: nothing to deploy
[ "$rc" = 0 ] || exit "$rc"

npx -y "wrangler@$WRANGLER_VERSION" pages deploy public --project-name "$PAGES_PROJECT" --branch main --commit-dirty=true

# Delete all older deployments, so no old copy of the feed lingers on a preview URL.
# The token goes to curl on stdin (-H @-), never in argv where `ps` would show it.
API="https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID/pages/projects/$PAGES_PROJECT/deployments"
auth() { printf 'Authorization: Bearer %s\n' "$CLOUDFLARE_API_TOKEN"; }
auth | curl -sf -H @- "$API?per_page=25" \
  | python3 -c 'import json,sys; r=json.load(sys.stdin)["result"]; [print(d["id"]) for d in r[1:]]' \
  | while read -r id; do
      auth | curl -sf -o /dev/null -X DELETE -H @- "$API/$id?force=true" \
        || echo "WARN: could not delete deployment $id" >&2
    done
