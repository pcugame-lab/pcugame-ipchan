#!/usr/bin/env bash
set -euo pipefail
[[ $(id -un) == gh-deploy ]] || { echo 'Run this as gh-deploy.' >&2; exit 1; }
revision=${1:?Commit SHA required}
[[ $revision =~ ^[0-9a-f]{40}$ ]] || { echo 'Invalid commit SHA.' >&2; exit 1; }
root="$HOME/server/ipchan"
release="$root/releases/$revision"
shared="$root/shared"
unit="$HOME/.config/containers/systemd/pcugame-ipchan.container"
service=pcugame-ipchan.service
image="localhost/pcugame-ipchan:$revision"
container=pcugame-ipchan
[[ -s "$shared/.env" && -d "$shared/data" && -d "$release/app" ]] || {
    echo 'Missing shared/.env, shared/data, or release source.' >&2; exit 1;
}
umask 077
exec 9>"$root/deploy.lock"
flock -w 600 9
latest_revision() {
    git ls-remote https://github.com/pcugame-lab/pcugame-ipchan.git refs/heads/master | cut -f1
}
if [[ $(latest_revision) != "$revision" ]]; then
    echo 'Skipping a superseded commit.'
    exit 0
fi
BUILD_CPU_QUOTA="$(( $(nproc) * 90 ))%"
BUILD_JOBS="$(( $(nproc) * 9 / 10 ))"
(( BUILD_JOBS >= 1 )) || BUILD_JOBS=1
systemd-run --user --scope \
    -p "CPUQuota=$BUILD_CPU_QUOTA" -p CPUWeight=10 -p IOWeight=10 \
    -- podman build --jobs "$BUILD_JOBS" \
    --cpu-period 100000 --cpu-quota "$(( $(nproc) * 90000 ))" \
    --label "org.opencontainers.image.revision=$revision" \
    --label org.opencontainers.image.source=https://github.com/pcugame-lab/pcugame-ipchan \
    -t "$image" "$release"
if [[ $(latest_revision) != "$revision" ]]; then
    echo 'Build finished, but a newer commit is available; skipping activation.'
    exit 0
fi
backup="$root/backups/$(date -u +%Y%m%dT%H%M%S)-$revision"
install -d -m 700 "$backup" "$(dirname "$unit")"
if [[ -f "$unit" ]]; then cp "$unit" "$backup/previous.container"; fi
cp -a "$shared/data" "$backup/data"
cat > "$backup/proposed.container" <<UNIT
[Unit]
Description=PCUGAME IPCHAN Discord bot
Wants=network-online.target
After=network-online.target

[Container]
Image=$image
ContainerName=$container
Pull=never
Network=host
UserNS=keep-id
User=$(id -u):$(id -g)
EnvironmentFile=$shared/.env
Volume=$shared/data:/app/data
Volume=$shared/logs:/app/logs
PodmanArgs=--no-healthcheck --log-driver=journald

[Service]
Restart=always
RestartSec=5
TimeoutStartSec=120
TimeoutStopSec=20

[Install]
WantedBy=default.target
UNIT
rollback() {
    echo 'Deployment failed; restoring the previous service configuration.' >&2
    systemctl --user stop "$service" || true
    if [[ -f "$backup/previous.container" ]]; then
        cp "$backup/previous.container" "$unit"
        systemctl --user daemon-reload
        systemctl --user start "$service"
    else
        rm -f "$unit"
        systemctl --user daemon-reload
    fi
}
started=$(date +%s)
cp "$backup/proposed.container" "$unit"
if ! systemctl --user daemon-reload || ! systemctl --user restart "$service"; then
    rollback
    exit 1
fi
ready=false
for attempt in $(seq 1 60); do
    if systemctl --user is-active --quiet "$service" && \
       podman exec "$container" python -c 'import os, urllib.request; urllib.request.urlopen("http://127.0.0.1:" + os.getenv("WEB_PORT", "8080") + "/health", timeout=2)' >/dev/null 2>&1 && \
       journalctl --user -u "$service" --since "@$started" --no-pager -o cat | grep -F '봇 준비 완료' >/dev/null; then
        ready=true
        break
    fi
    sleep 1
done
if [[ $ready != true ]]; then
    rollback
    exit 1
fi
ln -sfn "$release" "$root/current"
printf '%s\n' "$revision" > "$root/deployed-revision"
rm -f "$root/incoming/$revision.tar.gz"
printf 'Deployed %s successfully.\n' "$revision"
