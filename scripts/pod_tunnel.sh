#!/usr/bin/env bash
# Laptop: SSH tunnel to the GPU Pod's vLLM servers. Leave it running.
#   Apertus: Pod 127.0.0.1:8000 -> laptop 127.0.0.1:8000 (provider builder_pod)
#   Qwen:    Pod 127.0.0.1:8010 -> laptop 127.0.0.1:8002 (provider builder_pod_qwen; laptop 8001 is the API)
# Needs the `sentinel-pod` Host entry in ~/.ssh/config (HostName/Port/User/IdentityFile/known_hosts; see docs/INFRA.md).
# No secrets here: the key is referenced only by that ssh config entry.
set -euo pipefail
exec ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -L 127.0.0.1:8000:127.0.0.1:8000 -L 127.0.0.1:8002:127.0.0.1:8010 sentinel-pod
