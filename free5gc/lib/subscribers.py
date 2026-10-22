#!/usr/bin/env python3
"""Sincroniza os assinantes do config.env no free5GC pela API do WebConsole
(o mesmo formato que a página de cadastro dele envia). Idempotente: apaga e recria.

Modo --from-open5gs: lê da entrada padrão a lista de assinantes exportada do MongoDB do
Open5GS (import-open5gs) e cadastra os mesmos SIMs aqui, nas slices/DNNs que este core tem.

Entradas (ambiente, exportadas por free5gc/install.sh): MCC MNC SLICES UE_COUNT UE_MSIN_START
UE_KEY UE_OPC SUBSCRIBERS_ENV F5_WEBUI_URL [F5_WEBUI_USER F5_WEBUI_PASS]. As chaves não são impressas.
"""
import json
import os
import sys
import urllib.error
import urllib.request

E = os.environ
URL = E["F5_WEBUI_URL"].rstrip("/")
MCC, MNC = E["MCC"], E["MNC"]
PLMN = MCC + MNC
SLICES = []
for line in (x for x in E["SLICES_ENV"].split("\n") if x.strip()):
    sst, sd, dnn, _ = line.split(":")
    SLICES.append((int(sst), sd.lower(), dnn))
EXTRA = []   # DNNs extras do free5GC (F5_EXTRA_DNNS), ex.: (1, "111111", "ims")
for line in (x for x in os.environ.get("F5_EXTRA_DNNS_ENV", "").split("\n") if x.strip()):
    sst, sd, dnn, _ = line.split(":")
    EXTRA.append((int(sst), sd.lower(), dnn))


def call(method, path, body=None, token=None):
    req = urllib.request.Request(URL + path, method=method,
                                 data=None if body is None else json.dumps(body).encode())
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Token", token)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")[:300]


def body(imsi, k, opc, sst, sd, dnn, slices=None, op_type="OPc"):
    """slices = [(sst, sd, [dnn, ...]), ...]; sem ele, uma slice com uma DNN."""
    slices = slices or [(sst, sd, [dnn])]
    key = lambda a, b: "%02d%s" % (a, b)
    smd = [{"singleNssai": {"sst": a, "sd": b}, "dnnConfigurations": {d: dnn_cfg() for d in ds}} for a, b, ds in slices]
    return {
        "userNumber": 1, "ueId": "imsi-" + imsi, "plmnID": PLMN,
        "AuthenticationSubscription": {
            "authenticationMethod": "5G_AKA",
            "permanentKey": {"permanentKeyValue": k, "encryptionKey": 0, "encryptionAlgorithm": 0},
            "sequenceNumber": "000000000023", "authenticationManagementField": "8000",
            "milenage": {"op": {"opValue": opc if op_type == "OP" else "", "encryptionKey": 0, "encryptionAlgorithm": 0}},
            "opc": {"opcValue": opc if op_type == "OPc" else "", "encryptionKey": 0, "encryptionAlgorithm": 0}},
        "AccessAndMobilitySubscriptionData": {
            "gpsis": ["msisdn-"], "subscribedUeAmbr": {"uplink": "1 Gbps", "downlink": "2 Gbps"},
            "nssai": {"defaultSingleNssais": [{"sst": a, "sd": b} for a, b, _ in slices], "singleNssais": []}},
        "SessionManagementSubscriptionData": smd,
        "SmfSelectionSubscriptionData": {"subscribedSnssaiInfos": {
            key(a, b): {"dnnInfos": [{"dnn": d} for d in ds]} for a, b, ds in slices}},
        "AmPolicyData": {"subscCats": ["free5gc"]},
        "SmPolicyData": {"smPolicySnssaiData": {key(a, b): {"snssai": {"sst": a, "sd": b},
                                                            "smPolicyDnnData": {d: {"dnn": d} for d in ds}}
                                                for a, b, ds in slices}},
        "FlowRules": [], "QosFlows": [],
        "ChargingDatas": [{"chargingMethod": "Offline", "quota": "100000", "unitCost": "1",
                           "snssai": key(a, b), "dnn": "", "filter": ""} for a, b, _ in slices],
    }


def dnn_cfg():
    return {"pduSessionTypes": {"defaultSessionType": "IPV4", "allowedSessionTypes": ["IPV4"]},
            "sscModes": {"defaultSscMode": "SSC_MODE_1", "allowedSscModes": ["SSC_MODE_2", "SSC_MODE_3"]},
            "5gQosProfile": {"5qi": 9, "arp": {"priorityLevel": 8, "preemptCap": "", "preemptVuln": ""},
                             "priorityLevel": 8},
            "sessionAmbr": {"uplink": "1000 Mbps", "downlink": "1000 Mbps"},
            "staticIpAddress": []}


def from_open5gs(docs):
    """Converte assinantes do Open5GS para as slices/DNNs que este core tem (SLICES do config.env).
    Slice sem SD vira a slice configurada de mesma SST; DNN que este core não tem (ex.: ims) fica de fora."""
    for d in docs:
        sec = d.get("security") or {}
        k = (sec.get("k") or "").replace(" ", "").upper()
        opc = (sec.get("opc") or "").replace(" ", "").upper()
        op = (sec.get("op") or "").replace(" ", "").upper()
        out, skipped = [], []
        for sl in d.get("slice") or []:
            sst, sd = int(sl.get("sst", 0)), (sl.get("sd") or "").lower()
            conf = [c for c in SLICES if c[0] == sst and (c[1] == sd or not sd)]
            if not conf:
                skipped.append("slice %d/%s" % (sst, sd or "-"))
                continue
            csst, csd, _ = conf[0]
            have = [c[2] for c in SLICES + EXTRA if c[0] == csst and c[1] == csd]
            names = [x.get("name") for x in sl.get("session") or []]
            ok = [n for n in names if n in have]
            if ok:
                out.append((csst, csd, ok))
            skipped += ["DNN %s" % n for n in names if n not in have]
        yield d.get("imsi", ""), k, (opc or op), ("OPc" if opc else "OP"), out, skipped


def subscribers():
    sst, sd, dnn = SLICES[0]
    msin_len = 15 - len(MCC) - len(MNC)
    start = int(E["UE_MSIN_START"], 10)
    for i in range(int(E.get("UE_COUNT", "0"))):
        yield (MCC + MNC + str(start + i).zfill(msin_len), E["UE_KEY"].upper(), E["UE_OPC"].upper(), sst, sd, dnn)
    for line in (x for x in E.get("SUBSCRIBERS_ENV", "").split("\n") if x.strip()):
        f = line.split(":")
        if len(f) == 6:   # IMSI:K:OPC:SST:SD:DNN
            yield (f[0], f[1].upper(), f[2].upper(), int(f[3]), f[4].lower(), f[5])
        else:             # IMSI:K:OPC (slice padrão)
            yield (f[0], f[1].upper(), f[2].upper(), sst, sd, dnn)


def main_import(tok):
    docs = json.load(sys.stdin)
    n = 0
    for imsi, k, opc, op_type, slices, skipped in from_open5gs(docs):
        if not (imsi and k and opc):
            print("    - %s: sem chave/OPc no Open5GS, ignorado" % (imsi or "?"))
            continue
        if not slices:
            print("    - %s: nenhuma slice/DNN em comum com este core, ignorado" % imsi)
            continue
        path = "/api/subscriber/imsi-%s/%s" % (imsi, PLMN)
        call("DELETE", path, token=tok)
        st, r = call("POST", path, body(imsi, k, opc, 0, "", "", slices=slices, op_type=op_type), token=tok)
        if st not in (200, 201, 204):
            sys.exit("    [erro] assinante %s: HTTP %s %s" % (imsi, st, r))
        print("    + %s  %s%s" % (imsi, ", ".join("%d/%s %s" % (a, b, "+".join(ds)) for a, b, ds in slices),
                                  ("  (fora: %s)" % ", ".join(sorted(set(skipped)))) if skipped else ""))
        n += 1
    print("    [ok] %d assinante(s) do Open5GS cadastrado(s) no free5GC" % n)


def main():
    st, r = call("POST", "/api/login", {"username": E.get("F5_WEBUI_USER", "admin"),
                                        "password": E.get("F5_WEBUI_PASS", "free5gc")})
    if st != 200 or not isinstance(r, dict) or not r.get("access_token"):
        sys.exit("    [erro] login no WebConsole falhou (%s): %s" % (st, r))
    tok = r["access_token"]
    if "--from-open5gs" in sys.argv:
        return main_import(tok)
    n = 0
    for imsi, k, opc, sst, sd, dnn in subscribers():
        path = "/api/subscriber/imsi-%s/%s" % (imsi, PLMN)
        call("DELETE", path, token=tok)
        st, r = call("POST", path, body(imsi, k, opc, sst, sd, dnn), token=tok)
        if st not in (200, 201, 204):
            sys.exit("    [erro] assinante %s: HTTP %s %s" % (imsi, st, r))
        print("    + %s  DNN=%s  S-NSSAI=%d/%s" % (imsi, dnn, sst, sd))
        n += 1
    print("    [ok] %d assinante(s) sincronizado(s) no free5GC" % n)


if __name__ == "__main__":
    main()
