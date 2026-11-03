#!/usr/bin/env bash
set -euo pipefail
[[ $(id -un) == gh-deploy ]] || { echo 'Run this as gh-deploy.' >&2; exit 1; }
for command in podman systemctl systemd-run flock git curl; do
    command -v "$command" >/dev/null
 done
[[ $(loginctl show-user gh-deploy -p Linger --value) == yes ]] || {
    echo 'An administrator must enable lingering for gh-deploy.' >&2; exit 1;
}
umask 077
install -d -m 700 "$HOME/server/ipchan" "$HOME/server/ipchan/shared" \
    "$HOME/server/ipchan/shared/data" "$HOME/server/ipchan/shared/logs" \
    "$HOME/server/ipchan/releases" "$HOME/server/ipchan/incoming" \
    "$HOME/.config/containers/systemd"
systemctl --user is-system-running >/dev/null || [[ $(systemctl --user is-system-running) == degraded ]]
printf '%s\n' 'Rootless deployment directories are ready. Copy .env and current data into shared/ before deployment.'
