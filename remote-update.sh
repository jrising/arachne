#!/usr/bin/env bash
set -Eeuo pipefail

# ---- Configuration ----------------------------------------------------------

HOST="existencia"

LOCAL_PATH="$HOME/projects/arachne"

# Use absolute paths on the remote server.
REMOTE_PATH="/home/jrising/projects/arachne.existencia.org"
BACKUP_ROOT="/home/jrising/projects/arachne-backups"

BRANCH="master"
UPDATE_CHECK_URL="https://arachne.existencia.org/checkupdate"

# Files/directories that are deliberately not managed by Git, but should be
# copied from local to remote during deployment.
FILE_PATHS=(
    "logs"
    "database"
    "knowledge/entries.txt"
    "memory/bayesian.txt"
)

SUBMODULE_PATHS=(
    "chatwrap"
)

LOCAL_VENV_PATH="$LOCAL_PATH/venv2026"
REQUIREMENTS_FILE="$LOCAL_PATH/requirements.txt"

# Unique deployment marker, e.g. 20260803T142530Z-12345
DEPLOY_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
BACKUP_PATH="$BACKUP_ROOT/$DEPLOY_ID"
BACKUP_READY=0

CURRENT_STEP="initializing"

fail_report() {
    local status=$1
    local line=$2
    local command=$3

    echo >&2
    echo "Deployment failed." >&2
    echo "  Status:  $status" >&2
    echo "  Step:    $CURRENT_STEP" >&2
    echo "  Line:    $line" >&2
    echo "  Command: $command" >&2
}

# ---- Rollback ---------------------------------------------------------------

rollback() {
    local status=${1:-$?}
    local line=${2:-unknown}
    local command=${3:-unknown}

    trap - ERR

    fail_report "$status" "$line" "$command"

    echo >&2
    echo "Deployment failed (exit status $status)." >&2

    if [[ "$BACKUP_READY" -eq 1 ]]; then
        echo "Restoring remote backup: $BACKUP_PATH" >&2

        ssh "$HOST" bash -s -- "$REMOTE_PATH" "$BACKUP_PATH" <<'REMOTE'
set -Eeuo pipefail

remote_path=$1
backup_path=$2

if [[ ! -d "$backup_path" ]]; then
    echo "Cannot roll back: backup does not exist: $backup_path" >&2
    exit 1
fi

rm -rf -- "$remote_path"
cp -a -- "$backup_path" "$remote_path"

echo "Rollback complete."
REMOTE
    else
        echo "No remote backup was completed, so automatic rollback is unavailable." >&2
    fi

    # Optional: macOS desktop notification. Safe to ignore on non-macOS systems.
    osascript \
        -e 'display notification "Deployment failed; rollback attempted." with title "Arachne Deployment"' \
        2>/dev/null || true

    exit "$status"
}

# Define this before doing deployment work.
trap 'rollback "$?" "$LINENO" "$BASH_COMMAND"' ERR

# ---- Local Git push ---------------------------------------------------------

CURRENT_STEP="committing and pushing local code"
echo $CURRENT_STEP

git -C "$LOCAL_PATH" status --short --branch

echo "Generating requirements.txt from local virtual environment..."

if [[ ! -x "$LOCAL_VENV_PATH/bin/python" ]]; then
    echo "Local virtual environment Python not found: $LOCAL_VENV_PATH/bin/python" >&2
    exit 1
fi

tmp_requirements="$(mktemp)"
"$LOCAL_VENV_PATH/bin/python" -m pip freeze > "$tmp_requirements"

if [[ ! -f "$REQUIREMENTS_FILE" ]] || ! cmp -s "$tmp_requirements" "$REQUIREMENTS_FILE"; then
    mv "$tmp_requirements" "$REQUIREMENTS_FILE"
    echo "Updated requirements.txt from venv2026."
else
    rm "$tmp_requirements"
    echo "requirements.txt already up to date."
fi

echo "Committing and pushing submodules..."

for submodule in "${SUBMODULE_PATHS[@]}"; do
    submodule_path="$LOCAL_PATH/$submodule"

    if [[ ! -d "$submodule_path/.git" && ! -f "$submodule_path/.git" ]]; then
        echo "Expected submodule Git metadata not found: $submodule_path" >&2
        exit 1
    fi

    echo "Updating submodule: $submodule"

    git -C "$submodule_path" add -A

    if ! git -C "$submodule_path" diff --cached --quiet; then
        git -C "$submodule_path" commit -m "Automated deployment: $DEPLOY_ID"
    else
        echo "No committed file changes in submodule: $submodule"
    fi

    submodule_branch="$(git -C "$submodule_path" branch --show-current)"

    if [[ -z "$submodule_branch" ]]; then
        echo "Submodule is in detached HEAD state: $submodule" >&2
        echo "Check it out to a branch before deploying." >&2
        exit 1
    fi

    git -C "$submodule_path" push origin "HEAD:$submodule_branch"
done

git -C "$LOCAL_PATH" add -A

if ! git -C "$LOCAL_PATH" diff --cached --quiet; then
    git -C "$LOCAL_PATH" commit -m "Automated deployment: $DEPLOY_ID"
else
    echo "No Git changes to commit."
fi

echo "Pushing current HEAD to origin/$BRANCH..."
git -C "$LOCAL_PATH" push origin "HEAD:$BRANCH"

# ---- Remote backup ----------------------------------------------------------

CURRENT_STEP="Creating remote backup..."
echo $CURRENT_STEP

ssh "$HOST" bash -s -- "$REMOTE_PATH" "$BACKUP_ROOT" "$BACKUP_PATH" <<'REMOTE'
set -Eeuo pipefail

remote_path=$1
backup_root=$2
backup_path=$3

if [[ ! -d "$remote_path" ]]; then
    echo "Remote project directory does not exist: $remote_path" >&2
    exit 1
fi

mkdir -p -- "$backup_root"

# The backup path must not already exist; this avoids mixing deployments.
if [[ -e "$backup_path" ]]; then
    echo "Backup path unexpectedly already exists: $backup_path" >&2
    exit 1
fi

cp -a -- "$remote_path" "$backup_path"

echo "Backup created at: $backup_path"
REMOTE

BACKUP_READY=1

# ---- Sync non-Git state -----------------------------------------------------

CURRENT_STEP="Syncing non-Git files and directories..."
echo $CURRENT_STEP

for path in "${FILE_PATHS[@]}"; do
    local_item="$LOCAL_PATH/$path"
    remote_item="$REMOTE_PATH/$path"

    if [[ ! -e "$local_item" ]]; then
        echo "Warning: skipping missing local item: $local_item" >&2
        continue
    fi

    # Ensure the remote parent directory exists, especially for individual files.
    remote_parent="$(dirname "$remote_item")"
    ssh "$HOST" "mkdir -p -- $(printf '%q' "$remote_parent")"

    if [[ -d "$local_item" ]]; then
        # A trailing slash means “copy the directory's contents,” rather than
        # potentially creating logs/logs or database/database.
        rsync -az --delete \
            "$local_item/" \
            "$HOST:$remote_item/"
    else
        rsync -az \
            "$local_item" \
            "$HOST:$remote_item"
    fi
done

# ---- Deploy on remote -------------------------------------------------------

CURRENT_STEP="Updating code and dependencies on DreamHost..."
echo $CURRENT_STEP

ssh "$HOST" bash -s -- \
    "$REMOTE_PATH" \
    "$BRANCH" \
    "$DEPLOY_ID" <<'REMOTE'
set -Eeuo pipefail

remote_path=$1
branch=$2
deploy_id=$3

cd -- "$remote_path"

# `git pull --ff-only` refuses unexpected merge commits. This is desirable:
# the server should not contain hand-edited Git-tracked code.
git fetch origin "$branch"
git checkout "$branch"
git pull --ff-only origin "$branch"

git submodule sync --recursive
git submodule update --init --recursive

# Do not `source venv/bin/activate` in deployment scripts.
# Calling the virtual environment's Python directly is clearer and safer.
if [[ ! -x "venv/bin/python" ]]; then
    echo "Remote virtual environment missing; creating it."
    python3 -m venv venv
fi

venv/bin/python -m pip install --upgrade pip

# This is conditional until you adopt a dependency file.
if [[ -f "requirements.txt" ]]; then
    venv/bin/python -m pip install -r requirements.txt
else
    echo "No requirements.txt found; leaving remote virtual environment unchanged."
fi

# This is the value that /checkupdate should return.
printf '%s\n' "$deploy_id" > last_updated.txt

# If this is a DreamHost Passenger application, uncomment the appropriate
# restart mechanism if needed:
#
# touch tmp/restart.txt
#
# Or, depending on your setup:
# touch passenger_wsgi.py
REMOTE

# ---- Verify that the deployed application is live --------------------------

CURRENT_STEP="Checking deployment status..."
echo $CURRENT_STEP

# `-f`: treat HTTP 4xx/5xx as an error
# `-sS`: silent except for meaningful errors
#
# grep -F: fixed-string matching
# grep -x: require the entire response line to equal DEPLOY_ID
if curl --fail --silent --show-error "$UPDATE_CHECK_URL" |
    tr -d '\r' |
    grep -Fqx "$DEPLOY_ID"; then

    echo "Deployment successful: $DEPLOY_ID"
    trap - ERR

    osascript \
        -e 'display notification "Deployment succeeded." with title "Arachne Deployment"' \
        2>/dev/null || true
else
    echo "Update check did not return expected deployment ID: $DEPLOY_ID" >&2
    exit 1
fi
