#!/usr/bin/env bash
# =============================================================================
#  helm/postrender/drop-gnb-hpa.sh — post-renderer do Helm para o ueransim-gnb.
#
#  O chart ueransim-gnb (Gradiant 0.2.6) sempre cria um HorizontalPodAutoscaler
#  (min=max=1) apontando para "kind: StatefulSet", mas o gNB é um Deployment.
#  O controlador de HPA então registra em loop no k3s:
#    failed to query scale subresource for StatefulSet/<ns>/<release>
#  O HPA não tem função (1 réplica fixa) e o chart não permite desligá-lo,
#  então ele é removido do manifesto aqui. Lê YAML no stdin, escreve no stdout.
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
