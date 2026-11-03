#!/usr/bin/env bash
# =============================================================================
#  helm/postrender/drop-gnb-hpa.sh — Helm post-renderer for ueransim-gnb.
#
#  The ueransim-gnb chart (Gradiant 0.2.6) always creates a HorizontalPodAutoscaler
#  (min=max=1) pointing to "kind: StatefulSet", but the gNB is a Deployment.
#  The HPA controller then logs in a loop in k3s:
#    failed to query scale subresource for StatefulSet/<ns>/<release>
#  The HPA has no purpose (1 fixed replica) and the chart cannot disable it,
#  so it is removed from the manifest here. Reads YAML on stdin, writes stdout.
# =============================================================================
set -euo pipefail
awk '
  function flush() {
    if (doc != "" && doc !~ /(^|\n)kind: HorizontalPodAutoscaler\n/) printf "%s", doc
    doc = ""
  }
  /^---/ { flush(); doc = $0 "\n"; next }
         { doc = doc $0 "\n" }
  END    { flush() }
'
