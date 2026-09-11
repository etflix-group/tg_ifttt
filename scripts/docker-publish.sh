#!/usr/bin/env bash
#
# Build multi-architecture Docker images for tg-ifttt and push them to Docker Hub.
#
# Usage:
#   ./scripts/docker-publish.sh                          # default: linux/amd64,linux/arm64
#   ./scripts/docker-publish.sh --platforms linux/amd64   # single platform
#   ./scripts/docker-publish.sh --tag v0.2.0             # custom tag
#   ./scripts/docker-publish.sh --dry-run                # build only, don't push
#   ./scripts/docker-publish.sh --services api ui        # build only specific services
#
# Environment variables:
#   DOCKER_USER   Docker Hub username (default: derived from `docker info` or $USER)
#   IMAGE_NAME     Repository name (default: tg-ifttt)
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
PLATFORMS="linux/amd64,linux/arm64"
TAG=""
DRY_RUN=0
SERVICES="api ui nodered"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m ✓\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31m ✗\033[0m %s\n' "$*" >&2; }
die()  { err "$*"; exit 1; }

# ---------------------------------------------------------------------------
# Service definitions (bash 3.2 compatible — no associative arrays)
# ---------------------------------------------------------------------------
service_context() {
  case "$1" in
    api)    echo "$PROJECT_DIR" ;;
    ui)     echo "$PROJECT_DIR/frontend" ;;
    nodered) echo "$PROJECT_DIR/nodered" ;;
    *)      return 1 ;;
  esac
}

service_dockerfile() {
  case "$1" in
    api)    echo "$PROJECT_DIR/Dockerfile" ;;
    ui)     echo "$PROJECT_DIR/frontend/Dockerfile" ;;
    nodered) echo "$PROJECT_DIR/nodered/Dockerfile" ;;
    *)      return 1 ;;
  esac
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --platforms)  PLATFORMS="$2"; shift 2 ;;
    --tag)       TAG="$2"; shift 2 ;;
    --dry-run)   DRY_RUN=1; shift ;;
    --services)  shift; SERVICES=""
                 while [[ $# -gt 0 && "$1" != --* ]]; do
                   SERVICES="$SERVICES $1"; shift
                 done
                 SERVICES="${SERVICES# }" ;;
    -h|--help)
      sed -n '3,14p' "$0" | sed 's/^# \?//'
      exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

# ---------------------------------------------------------------------------
# Resolve image tag
# ---------------------------------------------------------------------------
if [[ -z "$TAG" ]]; then
  if [[ -f "$PROJECT_DIR/pyproject.toml" ]]; then
    TAG=$(grep -m1 '^version' "$PROJECT_DIR/pyproject.toml" | sed -E 's/.*"(.*)".*/\1/')
  fi
  [[ -z "$TAG" ]] && TAG="latest"
fi

# ---------------------------------------------------------------------------
# Resolve Docker Hub user
# ---------------------------------------------------------------------------
if [[ -z "${DOCKER_USER:-}" ]]; then
  DOCKER_USER=$(docker info 2>/dev/null | awk '/Username:/{print $2}' | head -1)
  if [[ -z "$DOCKER_USER" ]]; then
    die "Could not detect Docker Hub username. Set DOCKER_USER or run 'docker login'."
  fi
fi

IMAGE_NAME="${IMAGE_NAME:-tg-ifttt}"
FULL_PREFIX="${DOCKER_USER}/${IMAGE_NAME}"

log "Configuration"
echo "  Platforms : $PLATFORMS"
echo "  Tag       : $TAG"
echo "  Registry  : $FULL_PREFIX"
echo "  Services  : $SERVICES"
[[ $DRY_RUN -eq 1 ]] && echo "  Mode      : dry-run (no push)"

# ---------------------------------------------------------------------------
# Ensure buildx builder exists
# ---------------------------------------------------------------------------
BUILDER_NAME="tg-ifttt-multiarch"

ensure_builder() {
  if ! docker buildx inspect "$BUILDER_NAME" >/dev/null 2>&1; then
    log "Creating buildx builder: $BUILDER_NAME"
    docker buildx create --name "$BUILDER_NAME" --driver docker-container --use
    ok "Builder created"
  else
    docker buildx use "$BUILDER_NAME"
  fi
}

# ---------------------------------------------------------------------------
# Login check
# ---------------------------------------------------------------------------
check_login() {
  if [[ $DRY_RUN -eq 1 ]]; then
    return 0
  fi
  if ! docker info 2>/dev/null | grep -q "Username:"; then
    log "Docker Hub login required"
    docker login
  fi
  ok "Docker Hub authenticated as $DOCKER_USER"
}

# ---------------------------------------------------------------------------
# Build & push a single service
# ---------------------------------------------------------------------------
build_service() {
  local service="$1"
  local context dockerfile image
  context=$(service_context "$service") || die "Unknown service: $service"
  dockerfile=$(service_dockerfile "$service")
  image="${FULL_PREFIX}-${service}"

  [[ ! -f "$dockerfile" ]] && die "Dockerfile not found: $dockerfile"

  local push_flag=""
  [[ $DRY_RUN -eq 0 ]] && push_flag="--push"

  log "Building $service -> ${image}:${TAG} ($PLATFORMS)"
  echo "  context    : $context"
  echo "  dockerfile : $dockerfile"

  docker buildx build \
    --platform "$PLATFORMS" \
    --file "$dockerfile" \
    --tag "${image}:${TAG}" \
    --tag "${image}:latest" \
    $push_flag \
    "$context"

  if [[ $DRY_RUN -eq 0 ]]; then
    ok "Pushed ${image}:${TAG} and ${image}:latest"
  else
    ok "Built (dry-run) ${image}:${TAG}"
  fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
  check_login
  ensure_builder

  for service in $SERVICES; do
    build_service "$service"
  done

  log "Done"
  echo ""
  echo "  Pull with:"
  for service in $SERVICES; do
    echo "    docker pull ${FULL_PREFIX}-${service}:${TAG}"
  done
  echo ""
  echo "  Or use docker-compose with pre-built images:"
  echo "    export TG_IFTTT_API_IMAGE=${FULL_PREFIX}-api"
  echo "    export TG_IFTTT_UI_IMAGE=${FULL_PREFIX}-ui"
  echo "    export TG_IFTTT_NODERED_IMAGE=${FULL_PREFIX}-nodered"
  echo "    export TG_IFTTT_IMAGE_TAG=$TAG"
  echo "    docker compose up -d"
}

main
