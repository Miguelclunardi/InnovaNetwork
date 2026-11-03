#!/usr/bin/env bash
# =============================================================================
#  helm/postrender/amf-ngap-net1.sh — Helm post-renderer for the Open5GS release
#  (used only with RAN_LINK_ENABLED=true).
#
#  The open5gs-amf chart (Gradiant) hard-codes N2 as "ngap: server: - dev: eth0" and
#  has no value to change it. With Multus, the AMF gets the net1 interface on the
#  link to the real gNB; here N2 is moved to net1. Reads YAML on stdin, writes stdout.
# =============================================================================
set -euo pipefail
awk '
  st == 0 && /^ *ngap:[[:space:]]*$/   { st = 1; print; next }
  st == 1 && /^ *server:[[:space:]]*$/ { st = 2; print; next }
  st == 2 && /^ *- dev: eth0[[:space:]]*$/ { sub(/eth0/, "net1"); done = 1; st = 0; print; next }
  { if (st > 0) st = 0; print }
  END { if (!done) { print "amf-ngap-net1.sh: ngap/server/dev eth0 block not found" > "/dev/stderr"; exit 1 } }
'
