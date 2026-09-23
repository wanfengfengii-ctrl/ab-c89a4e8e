#!/usr/bin/env bash
# One-shot verification entrypoint:
#   1. wait for backend/frontend health
#   2. backend code tests (pytest)
#   3. frontend production build check
#   4. live API smoke against the running stack
# Exits non-zero if any stage fails.
set -u

BACKEND_URL="${BACKEND_URL:-http://backend:8000}"
FRONTEND_URL="${FRONTEND_URL:-http://frontend:80}"
PYTEST_ARGS="${PYTEST_ARGS:-q}"
STAGE_FAILURES=0

report() {
    echo
    echo "================ verify summary ================"
    if [ "$STAGE_FAILURES" -eq 0 ]; then
        echo "ALL STAGES PASSED"
        exit 0
    fi
    echo "${STAGE_FAILURES} STAGE(S) FAILED"
    exit 1
}

wait_http() {
    local url="$1" name="$2" tries=60
    echo "--> waiting for ${name} at ${url}"
    for _ in $(seq 1 "$tries"); do
        if node -e "fetch(process.argv[1]).then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))" "$url" 2>/dev/null; then
            echo "    ${name} is up"
            return 0
        fi
        sleep 2
    done
    echo "    TIMEOUT waiting for ${name}"
    return 1
}

echo "############ [1/4] service health ############"
wait_http "${BACKEND_URL}/api/health" backend || STAGE_FAILURES=$((STAGE_FAILURES + 1))
wait_http "${FRONTEND_URL}/healthz" frontend || STAGE_FAILURES=$((STAGE_FAILURES + 1))

echo
echo "############ [2/4] backend code tests (pytest) ############"
(
    cd /workspace/backend
    python3 -m venv /tmp/venv
    # shellcheck disable=SC1091
    . /tmp/venv/bin/activate
    pip install --quiet -r requirements-dev.txt
    python -m pytest $PYTEST_ARGS
) || STAGE_FAILURES=$((STAGE_FAILURES + 1))

echo
echo "############ [3/4] frontend build check ############"
(
    cd /workspace/frontend
    npm ci --no-audit --no-fund
    npm run build
    # The running frontend must actually serve the freshly built image.
    html="$(node -e "fetch(process.argv[1]).then(r=>r.text()).then(t=>console.log(t))" "${FRONTEND_URL}/")"
    echo "$html" | grep -q '<div id="root">' || {
        echo "served index.html missing app mount point"
        exit 1
    }
) || STAGE_FAILURES=$((STAGE_FAILURES + 1))

echo
echo "############ [4/4] live API smoke ############"
python3 /workspace/scripts/api_smoke.py "${BACKEND_URL}" || STAGE_FAILURES=$((STAGE_FAILURES + 1))

report
