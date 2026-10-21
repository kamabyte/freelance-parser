#!/usr/bin/env bash
# Deploy to Dokploy from the Mac, via its API: wait for the commit's image in
# GitHub Actions, then on every install point the application at the
# sha-<commit> image, Deploy, wait for the result and for the bot to start.
# GitHub never reaches the servers, and Actions holds no secrets.
#
#     deploy/dokploy/deploy.sh                       — origin/main to every install
#     deploy/dokploy/deploy.sh <commit>              — pin / roll back to <commit>
#     deploy/dokploy/deploy.sh -t home [<commit>]    — one install only
#
# Installs go one at a time; the first error stops the run.
# Always a sha tag, never latest: the application's General tab shows what is
# deployed, and a rollback is the same call with an earlier commit.
#
# An install is deploy/dokploy/targets/<name>.env (gitignored):
#     DOKPLOY_URL=http://dokploy.example.lan      # Dokploy directly, or
#     DOKPLOY_SSH=root@203.0.113.10               # via an ssh tunnel to its localhost:3000
#     DOKPLOY_PORT=3000                           # Dokploy's port on the server (for the tunnel)
#     PROJECT=<project> APP=<application>         # the application in Dokploy (required)
#     KEYCHAIN=dokploy-api-<name>                 # API key's Keychain entry (default)
#     IMAGE=ghcr.io/<owner>/freelance-parser      # no tag; defaults to the application's image
#
# API key: Dokploy → Settings → Profile → API/CLI → Generate, then once
#     security add-generic-password -U -a "$USER" -s dokploy-api-<name> -w
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "${HERE}/../.." && pwd)"
WORKFLOW=image.yml
# python-telegram-bot logs this once getMe succeeded (Telegram accepted the token)
# and polling started.
READY='Application started'

log() { printf '==> %s\n' "$*"; }
ok()  { printf '  ✓ %s\n' "$*"; }
die() { printf '  ✗ %s\n' "$*" >&2; exit 1; }

only=""
while getopts 't:' opt; do
  case "${opt}" in
    t) only="${OPTARG}" ;;
    *) die "usage: deploy/dokploy/deploy.sh [-t <install>] [<commit>]" ;;
  esac
done
shift $((OPTIND - 1))

if [[ -n "${only}" ]]; then
  [[ -f "${HERE}/targets/${only}.env" ]] || die "no install ${only}: deploy/dokploy/targets/${only}.env"
  TARGETS=("${only}")
else
  TARGETS=()
  for f in "${HERE}"/targets/*.env; do
    [[ -f "${f}" ]] && TARGETS+=("$(basename "${f}" .env)")
  done
  (( ${#TARGETS[@]} )) || die "no installs: create deploy/dokploy/targets/<name>.env"
fi

# --- Commit and image -----------------------------------------------------------
cd "${ROOT}"
SHA="$(git rev-parse "${1:-HEAD}")"
TAG="sha-${SHA:0:7}"
git fetch -q origin
git branch -r --contains "${SHA}" | grep -q . || die "${SHA:0:7} is not pushed"
[[ -n "${1:-}" || "${SHA}" == "$(git rev-parse origin/main)" ]] \
  || die "HEAD (${SHA:0:7}) is not origin/main. Push to main or name a commit"

log "Image ${SHA:0:7} (${TAG})"
# A commit can have several builds; concurrency cancels all but the last, so
# cancelled ones are skipped. Right after a push the build takes a moment to appear.
built=""
for _ in $(seq 1 12); do
  RUN="$(gh run list --workflow "${WORKFLOW}" --commit "${SHA}" --limit 10 --json databaseId,conclusion \
    -q '[.[] | select(.conclusion != "cancelled")][0].databaseId // empty')"
  if [[ -n "${RUN}" ]]; then
    gh run watch "${RUN}" --exit-status --interval 10 >/dev/null && { built=1; break; }
    [[ "$(gh run view "${RUN}" --json conclusion -q .conclusion)" == cancelled ]] \
      || die "image build failed: gh run view ${RUN} --log-failed"
  fi
  sleep 5
done
[[ -n "${built}" ]] || die "no image build for ${SHA:0:7} in Actions"
ok "built"

# --- One install (in a subshell: its own variables, tunnel, exit) ---------------
deploy_target() {
  local name=$1
  DOKPLOY_URL="" DOKPLOY_SSH="" DOKPLOY_PORT=3000 PROJECT="" APP=""
  KEYCHAIN="dokploy-api-${name}" IMAGE=""
  # shellcheck source=/dev/null
  source "${HERE}/targets/${name}.env"
  [[ -n "${PROJECT}" && -n "${APP}" ]] || die "targets/${name}.env needs PROJECT and APP — the Dokploy project and application"

  log "Install ${name}: application ${PROJECT}/${APP}"
  KEY="$(security find-generic-password -s "${KEYCHAIN}" -w 2>/dev/null || true)"
  [[ -n "${KEY}" ]] || die "no API key: security add-generic-password -U -a \"\$USER\" -s ${KEYCHAIN} -w"

  # Never talk to a non-TLS Dokploy over the internet: the key goes through an ssh tunnel
  if [[ -n "${DOKPLOY_SSH}" ]]; then
    local port=$(( 20000 + RANDOM % 20000 ))
    ssh -N -o BatchMode=yes -o ExitOnForwardFailure=yes \
      -L "${port}:127.0.0.1:${DOKPLOY_PORT}" "${DOKPLOY_SSH}" &
    local tunnel=$!
    trap 'kill '"${tunnel}"' 2>/dev/null || true' EXIT
    DOKPLOY_URL="http://127.0.0.1:${port}"
    local up=""
    for _ in $(seq 1 30); do
      kill -0 "${tunnel}" 2>/dev/null || die "ssh tunnel to ${DOKPLOY_SSH} did not come up"
      curl -s -o /dev/null --max-time 2 "${DOKPLOY_URL}/" && { up=1; break; }
      sleep 0.5
    done
    [[ -n "${up}" ]] || die "Dokploy is not answering through the tunnel to ${DOKPLOY_SSH}"
  fi
  [[ -n "${DOKPLOY_URL}" ]] || die "targets/${name}.env needs DOKPLOY_URL or DOKPLOY_SSH"

  api() {  # api GET|POST <procedure> [json]
    local method=$1 proc=$2 body=${3:-}
    local args=(-sS --max-time 30 -H "x-api-key: ${KEY}" -H 'Content-Type: application/json'
                -w '\n%{http_code}' -X "${method}")
    [[ -n "${body}" ]] && args+=(-d "${body}")
    local out code
    out="$(curl "${args[@]}" "${DOKPLOY_URL}/api/${proc}")" || die "Dokploy unreachable (${DOKPLOY_URL})"
    code="${out##*$'\n'}"; out="${out%$'\n'*}"
    [[ "${code}" == 2* ]] || die "${proc}: HTTP ${code}: ${out:0:300}"
    printf '%s' "${out}"
  }

  APP_ID="$(api GET project.all | jq -r --arg p "${PROJECT}" --arg n "${APP}" \
    '[.[] | select(.name == $p) | .. | objects | select(has("applicationId") and .name == $n) | .applicationId] | first // empty')"
  [[ -n "${APP_ID}" ]] || die "application ${PROJECT}/${APP} not found"

  # The application's Docker provider: change only the image tag and send the
  # registry credentials back as they are (saveDockerProvider overwrites every field)
  DOCKER="$(api GET "application.one?applicationId=${APP_ID}" | jq -c '{dockerImage, username, password, registryUrl}')"
  PREVIOUS="$(jq -r '.dockerImage // ""' <<<"${DOCKER}")"
  [[ -n "${IMAGE}" ]] || IMAGE="$(sed -E 's/:[^:/]+$//' <<<"${PREVIOUS}")"
  [[ -n "${IMAGE}" ]] || die "the application has no image: set IMAGE= in targets/${name}.env"
  api POST application.saveDockerProvider "$(jq -c --arg id "${APP_ID}" --arg image "${IMAGE}:${TAG}" \
    '{applicationId: $id, dockerImage: $image, username, password, registryUrl}' <<<"${DOCKER}")" >/dev/null
  ok "image ${IMAGE}:${TAG} (was ${PREVIOUS:-unset})"

  # Deploy is queued by Dokploy — wait for the new deployment record and its result
  latest() { api GET "deployment.all?applicationId=${APP_ID}" \
    | jq -r 'sort_by(.createdAt) | last // {} | "\(.deploymentId // "") \(.status // "")"'; }
  local before id="" status="" started
  before="$(latest | cut -d' ' -f1)"
  started="$(date +%s)"
  api POST application.deploy "$(jq -n --arg id "${APP_ID}" --arg title "deploy.sh: ${TAG}" \
    '{applicationId: $id, title: $title}')" >/dev/null
  for _ in $(seq 1 120); do
    sleep 5
    read -r id status <<<"$(latest)"
    [[ "${id}" != "${before}" && ( "${status}" == "done" || "${status}" == error ) ]] && break
  done
  [[ "${id}" != "${before}" && "${status}" == "done" ]] \
    || die "deploy: ${status:-no answer} — log in Dokploy → ${PROJECT} → ${APP} → Deployments"
  ok "application updated"

  # The bot has no port. Sign of life: the ready line in the logs since the
  # deploy started. Until the container is up, Dokploy answers with an error —
  # that's no reason to stop.
  local line=""
  for _ in $(seq 1 24); do
    line="$(curl -sS --max-time 30 -H "x-api-key: ${KEY}" \
      "${DOKPLOY_URL}/api/application.readLogs?applicationId=${APP_ID}&tail=500&since=$(( $(date +%s) - started + 5 ))s" \
      2>/dev/null | jq -r 'strings' 2>/dev/null | grep -m1 "${READY}" || true)"
    [[ -n "${line}" ]] && break
    sleep 5
  done
  [[ -n "${line}" ]] || die "the bot did not start within 2 minutes — logs: Dokploy → ${PROJECT} → ${APP} → Logs"
  ok "bot is running (${TAG})"
  [[ "${PREVIOUS##*:}" == sha-* && "${PREVIOUS##*:}" != "${TAG}" ]] \
    && ok "rollback: deploy/dokploy/deploy.sh -t ${name} ${PREVIOUS##*:sha-}"
  return 0
}

done_targets=()
for name in "${TARGETS[@]}"; do
  # set -e inside: calling it within if/|| would disable it
  set +e
  ( set -e; deploy_target "${name}" )
  rc=$?
  set -e
  (( rc == 0 )) || die "${name} not deployed; already deployed: ${done_targets[*]:-none}"
  done_targets+=("${name}")
done
ok "deployed ${TAG}: ${done_targets[*]}"
