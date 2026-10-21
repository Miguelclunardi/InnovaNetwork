#!/usr/bin/env bash
# =============================================================================
#  helm/postrender/amf-ngap-net1.sh — post-renderer do Helm para o release do Open5GS
#  (usado só com RAN_LINK_ENABLED=true).
#
#  O chart open5gs-amf (Gradiant) fixa o N2 em "ngap: server: - dev: eth0" e não
#  tem value para mudar. Com o Multus, o AMF ganha a interface net1 no link com o
#  gNB real; aqui o N2 passa a ouvir em net1. Lê YAML no stdin, escreve no stdout.
# =============================================================================
set -euo pipefail
awk '
  st == 0 && /^ *ngap:[[:space:]]*$/   { st = 1; print; next }
  st == 1 && /^ *server:[[:space:]]*$/ { st = 2; print; next }
  st == 2 && /^ *- dev: eth0[[:space:]]*$/ { sub(/eth0/, "net1"); done = 1; st = 0; print; next }
  { if (st > 0) st = 0; print }
  END { if (!done) { print "amf-ngap-net1.sh: bloco ngap/server/dev eth0 não encontrado" > "/dev/stderr"; exit 1 } }
'
