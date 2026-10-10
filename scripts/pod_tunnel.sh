#!/usr/bin/env bash
# Laptop: SSH tunnel to the GPU Pod's vLLM. Pod 127.0.0.1:8000 -> laptop 127.0.0.1:8000. Leave it running.
# Needs the `sentinel-pod` Host entry in ~/.ssh/config (HostName/Port/User/IdentityFile/known_hosts; see docs/INFRA.md).
# No secrets here: the key is referenced only by that ssh config entry.
set -euo pipefail
exec ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -L 127.0.0.1:8000:127.0.0.1:8000 sentinel-pod
