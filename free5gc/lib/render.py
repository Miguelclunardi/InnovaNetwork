#!/usr/bin/env python3
"""Gera os manifestos do free5GC (JSON = YAML válido) a partir das variáveis de ambiente
que free5gc/install.sh exporta (config.env + free5gc/free5gc.env). Nada fixo aqui.

Uso: render.py manifests > free5gc.json
     render.py ueransim  > ueransim-values.json
"""
import hashlib
import json
import os
import sys

E = os.environ


def env(k, d=None):
    v = E.get(k, d)
    if v is None:
        sys.exit("render.py: falta a variável %s" % k)
    return v


NS = env("F5_NAMESPACE")
TAG = env("F5_VERSION")
REG = env("F5_REGISTRY")
MCC, MNC = env("MCC"), env("MNC")
TAC_HEX = "%06x" % int(env("TAC"), 10)
LOG = env("F5_LOG_LEVEL", "info")
PREFIX = env("RAN_LINK_CIDR").split("/")[1]
AMF_IP, UPF_IP = env("F5_AMF_N2_IP"), env("F5_UPF_N3_IP")
DNS = env("DNS_SERVERS").split()[0]
HASH_ANN = "innovanetwork/config-hash"

# SLICES do config.env: "SST:SD:DNN:CIDR" (o CIDR é do Open5GS; o do free5GC vem de F5_UE_POOLS)
SLICES = []
pools = [p for p in env("F5_UE_POOLS_ENV").split("\n") if p.strip()]
for i, line in enumerate(x for x in env("SLICES_ENV").split("\n") if x.strip()):
    sst, sd, dnn, _ = line.split(":")
    if i >= len(pools):
        sys.exit("render.py: F5_UE_POOLS tem menos itens que SLICES")
    SLICES.append({"sst": int(sst), "sd": sd.lower(), "dnn": dnn, "pool": pools[i]})
# DNNs extras só do free5GC (F5_EXTRA_DNNS: "SST:SD:DNN:CIDR"), ex.: ims, que os celulares pedem
for line in (x for x in env("F5_EXTRA_DNNS_ENV").split("\n") if x.strip()):
    sst, sd, dnn, cidr = line.split(":")
    SLICES.append({"sst": int(sst), "sd": sd.lower(), "dnn": dnn, "pool": cidr})
PLMN = {"mcc": MCC, "mnc": MNC}
SNSSAIS = []
for s in SLICES:
    if {"sst": s["sst"], "sd": s["sd"]} not in SNSSAIS:
        SNSSAIS.append({"sst": s["sst"], "sd": s["sd"]})
BY_SNSSAI = [(n, [s for s in SLICES if s["sst"] == n["sst"] and s["sd"] == n["sd"]]) for n in SNSSAIS]
DNNS = sorted({s["dnn"] for s in SLICES})
NRF = "http://nrf:8000"
MONGO = "mongodb://mongodb:27017"
LOGGER = {"enable": True, "level": LOG, "reportCaller": False}


def sbi(name):
    return {"scheme": "http", "registerIPv4": name, "bindingIPv4": "0.0.0.0", "port": 8000,
            "tls": {"pem": "cert/%s.pem" % name, "key": "cert/%s.key" % name}}


def info(desc, ver):
    return {"version": ver, "description": desc}


CFG = {}
CFG["nrf"] = {"info": info("NRF", "1.0.2"), "configuration": {
    "MongoDBName": "free5gc", "MongoDBUrl": MONGO,
    "sbi": dict(sbi("nrf"), cert={"pem": "cert/nrf.pem", "key": "cert/nrf.key"},
                rootcert={"pem": "cert/root.pem", "key": "cert/root.key"}, oauth=False),
    "DefaultPlmnId": PLMN, "serviceNameList": ["nnrf-nfm", "nnrf-disc"]}, "logger": LOGGER}

CFG["amf"] = {"info": info("AMF", "1.0.9"), "configuration": {
    "amfName": "AMF", "ngapIpList": [AMF_IP], "ngapPort": 38412, "sbi": sbi("amf"),
    "serviceNameList": ["namf-comm", "namf-evts", "namf-mt", "namf-loc", "namf-oam", "namf-callback"],
    "servedGuamiList": [{"plmnId": PLMN, "amfId": "cafe00"}],
    "supportTaiList": [{"plmnId": PLMN, "tac": TAC_HEX}],
    "plmnSupportList": [{"plmnId": PLMN, "snssaiList": SNSSAIS}],
    "supportDnnList": DNNS, "nrfUri": NRF, "nrfCertPem": "cert/nrf.pem",
    "security": {"integrityOrder": ["NIA2"], "cipheringOrder": ["NEA0", "NEA2"]},
    "networkName": {"full": env("F5_NETWORK_NAME", "free5GC"), "short": env("F5_NETWORK_NAME", "free5GC")},
    "ngapIE": {"mobilityRestrictionList": {"enable": True}, "maskedIMEISV": {"enable": True},
               "redirectionVoiceFallback": {"enable": False}},
    "nasIE": {"networkFeatureSupport5GS": {"enable": True, "length": 1, "imsVoPS": 1, "emc": 0, "emf": 0,
                                           "iwkN26": 0, "mpsi": 0, "emcN3": 0, "mcsi": 0}},
    "t3502Value": 720, "t3512Value": 3600, "non3gppDeregTimerValue": 3240,
    **{t: {"enable": True, "expireTime": "6s", "maxRetryTimes": 4}
       for t in ("t3513", "t3522", "t3550", "t3555", "t3560", "t3565", "t3570")},
    "locality": "area1",
    "sctp": {"numOstreams": 3, "maxInstreams": 5, "maxAttempts": 2, "maxInitTimeout": 2},
    "defaultUECtxReq": False, "ngapWorkerPoolSize": 0, "ngapTaskBufferSize": 4096}, "logger": LOGGER}

CFG["smf"] = {"info": info("SMF", "1.0.7"), "configuration": {
    "smfName": "SMF", "sbi": sbi("smf"),
    "serviceNameList": ["nsmf-pdusession", "nsmf-event-exposure", "nsmf-oam", "nsmf-callback"],
    "snssaiInfos": [{"sNssai": n, "dnnInfos": [{"dnn": s["dnn"], "dns": {"ipv4": DNS}} for s in ss]}
                    for n, ss in BY_SNSSAI],
    "plmnList": [PLMN], "locality": "area1",
    # POD_IP_ADDR e UPF_IP_ADDR: trocados na partida (wrapper) pelo IP do pod do SMF e do UPF
    "pfcp": {"nodeID": "POD_IP_ADDR", "listenAddr": "POD_IP_ADDR", "externalAddr": "POD_IP_ADDR",
             "assocFailAlertInterval": "10s", "assocFailRetryInterval": "30s", "heartbeatInterval": "10s"},
    "userplaneInformation": {
        "upNodes": {
            "gNB1": {"type": "AN"},
            "UPF": {"type": "UPF", "nodeID": "UPF_IP_ADDR", "addr": "UPF_IP_ADDR",
                    "sNssaiUpfInfos": [{"sNssai": n,
                                        "dnnUpfInfoList": [{"dnn": s["dnn"], "pools": [{"cidr": s["pool"]}]}
                                                           for s in ss]}
                                       for n, ss in BY_SNSSAI],
                    "interfaces": [{"interfaceType": "N3", "endpoints": [UPF_IP], "networkInstances": DNNS}]}},
        "links": [{"A": "gNB1", "B": "UPF"}]},
    "t3591": {"enable": True, "expireTime": "16s", "maxRetryTimes": 3},
    "t3592": {"enable": True, "expireTime": "16s", "maxRetryTimes": 3},
    "nrfUri": NRF, "nrfCertPem": "cert/nrf.pem",
    "urrPeriod": 30, "urrThreshold": 500000, "requestedUnit": 1000}, "logger": LOGGER}
UEROUTING = {"info": info("UE routing", "1.0.7"), "ueRoutingInfo": {}}

CFG["upf"] = {"version": "1.0.3", "description": "UPF",
              "pfcp": {"addr": "POD_IP_ADDR", "nodeID": "POD_IP_ADDR", "retransTimeout": "1s", "maxRetrans": 3},
              "gtpu": {"forwarder": "gtp5g", "ifList": [{"addr": UPF_IP, "type": "N3"}]},
              "dnnList": [{"dnn": s["dnn"], "cidr": s["pool"], "ipForwardEnable": True} for s in SLICES],
              "logger": LOGGER}

CFG["ausf"] = {"info": info("AUSF", "1.0.3"), "configuration": {
    "sbi": sbi("ausf"), "serviceNameList": ["nausf-auth"], "nrfUri": NRF, "nrfCertPem": "cert/nrf.pem",
    "plmnSupportList": [PLMN], "groupId": "ausfGroup001", "eapAkaSupiImsiPrefix": False}, "logger": LOGGER}

CFG["udm"] = {"info": info("UDM", "1.0.3"), "configuration": {
    "serviceNameList": ["nudm-sdm", "nudm-uecm", "nudm-ueau", "nudm-ee", "nudm-pp"],
    "sbi": sbi("udm"), "nrfUri": NRF, "nrfCertPem": "cert/nrf.pem",
    # Perfis SUCI de exemplo do free5GC (chaves públicas de teste; SIMs sem SUCI usam o esquema nulo)
    "SuciProfile": [
        {"ProtectionScheme": 1,
         "PrivateKey": "c53c22208b61860b06c62e5406a7b330c2b577aa5558981510d128247d38bd1d",
         "PublicKey": "5a8d38864820197c3394b92613b20b91633cbd897119273bf8e4a6f4eec0a650"},
        {"ProtectionScheme": 2,
         "PrivateKey": "F1AB1074477EBCC7F554EA1C5FC368B1616730155E0041AC447D6301975FECDA",
         "PublicKey": "0472DA71976234CE833A6907425867B82E074D44EF907DFB4B3E21C1C2256EBCD15A7DED52FCBB097A4ED250E036C7B9C8C7004C4EEDC4F068CD7BF8D3F900E3B4"}]},
    "logger": LOGGER}

CFG["udr"] = {"info": info("UDR", "1.1.0"), "configuration": {
    "sbi": sbi("udr"), "dbConnectorType": "mongodb", "mongodb": {"name": "free5gc", "url": MONGO},
    "nrfUri": NRF, "nrfCertPem": "cert/nrf.pem"}, "logger": LOGGER}

CFG["pcf"] = {"info": info("PCF", "1.0.2"), "configuration": {
    "pcfName": "PCF", "sbi": sbi("pcf"), "timeFormat": "2019-01-02 15:04:05",
    "defaultBdtRefId": "BdtPolicyId-", "nrfUri": NRF, "nrfCertPem": "cert/nrf.pem",
    "serviceList": [{"serviceName": "npcf-am-policy-control"},
                    {"serviceName": "npcf-smpolicycontrol", "suppFeat": "3fff"},
                    {"serviceName": "npcf-bdtpolicycontrol"},
                    {"serviceName": "npcf-policyauthorization", "suppFeat": "3"},
                    {"serviceName": "npcf-eventexposure"}, {"serviceName": "npcf-ue-policy-control"},
                    {"serviceName": "npcf-callback"}],
    "mongodb": {"name": "free5gc", "url": MONGO}, "locality": "area1"}, "logger": LOGGER}

CFG["nssf"] = {"info": info("NSSF", "1.0.2"), "configuration": {
    "nssfName": "NSSF", "sbi": sbi("nssf"),
    "serviceNameList": ["nnssf-nsselection", "nnssf-nssaiavailability"],
    "nrfUri": NRF, "nrfCertPem": "cert/nrf.pem", "supportedPlmnList": [PLMN],
    "supportedNssaiInPlmnList": [{"plmnId": PLMN, "supportedSnssaiList": SNSSAIS}],
    "nsiList": [{"snssai": n,
                 "nsiInformationList": [{"nrfId": NRF + "/nnrf-nfm/v1/nf-instances", "nsiId": 10 + i}]}
                for i, n in enumerate(SNSSAIS)],
    "taList": [{"tai": {"plmnId": PLMN, "tac": TAC_HEX}, "accessType": "3GPP_ACCESS",
                "supportedSnssaiList": SNSSAIS}]}, "logger": LOGGER}

CFG["chf"] = {"info": info("CHF", "1.0.3"), "configuration": {
    "chfName": "CHF", "sbi": sbi("chf"), "nrfUri": NRF, "nrfCertPem": "cert/nrf.pem",
    "serviceNameList": ["nchf-convergedcharging"], "mongodb": {"name": "free5gc", "url": MONGO},
    "quotaValidityTime": 10000, "volumeLimit": 50000, "volumeLimitPDU": 10000, "volumeThresholdRate": 0.8,
    "cgf": {"hostIPv4": "webui", "port": 2121, "listenPort": 2122,
            "passiveTransferPortRange": {"start": 2123, "end": 2130},
            "tls": {"pem": "cert/chf.pem", "key": "cert/chf.key"}, "cdrFilePath": "/tmp"},
    "abmfDiameter": {"protocol": "tcp", "hostIPv4": "0.0.0.0", "port": 3868,
                     "tls": {"pem": "cert/chf.pem", "key": "cert/chf.key"}},
    "rfDiameter": {"protocol": "tcp", "hostIPv4": "0.0.0.0", "port": 3869,
                   "tls": {"pem": "cert/chf.pem", "key": "cert/chf.key"}}}, "logger": LOGGER}

CFG["nef"] = {"info": info("NEF", "1.0.1"), "configuration": {
    "sbi": sbi("nef"), "nrfUri": NRF, "nrfCertPem": "cert/nrf.pem",
    "serviceList": [{"serviceName": "nnef-pfdmanagement"}, {"serviceName": "nnef-oam"},
                    {"serviceName": "3gpp-traffic-influence"}, {"serviceName": "nnef-callback"}]},
    "logger": LOGGER}

CFG["webui"] = {"info": info("WebUI", "1.0.3"), "configuration": {
    "mongodb": {"name": "free5gc", "url": MONGO}, "nrfUri": NRF,
    "webServer": {"scheme": "http", "ipv4Address": "0.0.0.0", "port": 5000},
    # o WebConsole exige billingServer ligado (é o servidor FTP de CDR que o CHF usa)
    "billingServer": {"enable": True, "hostIPv4": "0.0.0.0", "listenPort": 2121,
                      "portRange": {"start": 2123, "end": 2130}, "basePath": "/tmp/webconsole", "port": 2122,
                      "cert": {"pem": "cert/chf.pem", "key": "cert/chf.key"}}},
    "logger": LOGGER}

# Ordem de partida (o painel usa a mesma): banco -> NRF -> demais -> UPF -> SMF -> AMF
ORDER = ["nrf", "udr", "udm", "ausf", "nssf", "pcf", "chf", "nef", "webui", "upf", "smf", "amf"]


def labels(nf):
    return {"app.kubernetes.io/part-of": "free5gc", "app.kubernetes.io/name": nf, "nf": nf}


def cfg_hash(*objs):
    return hashlib.sha256(json.dumps(objs, sort_keys=True).encode()).hexdigest()[:16]


def ran_link(ip):
    return json.dumps([{"name": "ran-link", "ips": ["%s/%s" % (ip, PREFIX)]}])


WAIT_MONGO = {"name": "wait-mongodb", "image": "%s/nrf:%s" % (REG, TAG), "imagePullPolicy": "IfNotPresent",
              "command": ["sh", "-c", "until nc -z mongodb 27017; do echo esperando o MongoDB; sleep 2; done"]}
WAIT_NRF = {"name": "wait-nrf", "image": "%s/nrf:%s" % (REG, TAG), "imagePullPolicy": "IfNotPresent",
            "command": ["sh", "-c", "until nc -z nrf 8000; do echo esperando o NRF; sleep 2; done"]}


def deployment(nf, files, cmd, extra_ann=None, privileged=False, ports=None, wait_nrf=True, env_list=None,
               wait_mongo=False):
    cm = "%s-config" % nf
    ann = {HASH_ANN: cfg_hash(files)}
    ann.update(extra_ann or {})
    c = {"name": nf, "image": "%s/%s:%s" % (REG, nf, TAG), "imagePullPolicy": "IfNotPresent",
         "command": cmd, "workingDir": "/free5gc",
         "env": [{"name": "GIN_MODE", "value": "release"}] + (env_list or []),
         "volumeMounts": [{"name": "config", "mountPath": "/free5gc/config"},
                          {"name": "tls", "mountPath": "/free5gc/config/TLS"},
                          {"name": "cert", "mountPath": "/free5gc/cert", "readOnly": True}],
         "ports": ports or [{"name": "sbi", "containerPort": 8000}]}
    if privileged:
        c["securityContext"] = {"privileged": True}
    spec = {"containers": [c],
            "volumes": [{"name": "config", "configMap": {"name": cm, "defaultMode": 0o755}},
                        {"name": "tls", "emptyDir": {}},
                        {"name": "cert", "secret": {"secretName": "free5gc-cert", "defaultMode": 0o400}}]}
    init = ([WAIT_MONGO] if wait_mongo else []) + ([WAIT_NRF] if wait_nrf else [])
    if init:
        spec["initContainers"] = init
    return [
        {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": cm, "namespace": NS, "labels": labels(nf)},
         "data": files},
        {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": nf, "namespace": NS, "labels": labels(nf)},
         "spec": {"replicas": 1, "strategy": {"type": "Recreate"}, "selector": {"matchLabels": {"nf": nf}},
                  "template": {"metadata": {"labels": labels(nf), "annotations": ann}, "spec": spec}}}]


def service(nf, ports, headless=False, node_port=None):
    s = {"apiVersion": "v1", "kind": "Service", "metadata": {"name": nf, "namespace": NS, "labels": labels(nf)},
         "spec": {"selector": {"nf": nf}, "ports": ports}}
    if headless:
        s["spec"]["clusterIP"] = "None"
    if node_port:
        s["spec"]["type"] = "NodePort"
    return s


def dump(o):
    return json.dumps(o, indent=2)


def manifests():
    # rótulo innovanetwork/core: no boot (CORE_AUTOSTART=false) o heal.sh para todo namespace com ele
    out = [{"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": NS, "labels": {
        "app.kubernetes.io/part-of": "free5gc", "innovanetwork/core": "free5gc"}}},
           {"apiVersion": "k8s.cni.cncf.io/v1", "kind": "NetworkAttachmentDefinition",
            "metadata": {"name": "ran-link", "namespace": NS},
            "spec": {"config": json.dumps({"cniVersion": "0.3.1", "type": "macvlan", "master": env("RAN_LINK_IFACE"),
                                           "mode": "bridge", "mtu": int(env("RAN_LINK_MTU")),
                                           "ipam": {"type": "static"}, "capabilities": {"ips": True}})}}]
    # MongoDB (volume local do k3s: os assinantes sobrevivem a reinícios)
    out += [
        {"apiVersion": "v1", "kind": "PersistentVolumeClaim", "metadata": {"name": "mongodb", "namespace": NS},
         "spec": {"accessModes": ["ReadWriteOnce"], "resources": {"requests": {"storage": env("F5_MONGO_SIZE")}}}},
        {"apiVersion": "apps/v1", "kind": "Deployment",
         "metadata": {"name": "mongodb", "namespace": NS, "labels": labels("mongodb")},
         "spec": {"replicas": 1, "strategy": {"type": "Recreate"}, "selector": {"matchLabels": {"nf": "mongodb"}},
                  "template": {"metadata": {"labels": labels("mongodb")}, "spec": {
                      "containers": [{"name": "mongodb", "image": env("F5_MONGO_IMAGE"), "imagePullPolicy": "IfNotPresent",
                                      "args": ["--bind_ip_all"], "ports": [{"containerPort": 27017}],
                                      "readinessProbe": {"tcpSocket": {"port": 27017}, "periodSeconds": 5},
                                      "volumeMounts": [{"name": "data", "mountPath": "/data/db"}]}],
                      "volumes": [{"name": "data", "persistentVolumeClaim": {"claimName": "mongodb"}}]}}}},
        service("mongodb", [{"name": "mongo", "port": 27017}])]

    sbi_port = [{"name": "sbi", "port": 8000}]
    for nf in ORDER:
        name = "%scfg.yaml" % nf
        if nf == "smf":
            wrapper = "\n".join([
                "set -e",
                "POD_IP=$(hostname -i | awk '{print $1}')",
                "for i in $(seq 1 60); do UPF_IP=$(getent hosts upf | awk '{print $1}' | head -1); [ -n \"$UPF_IP\" ] && break; echo esperando o UPF; sleep 2; done",
                "[ -n \"$UPF_IP\" ] || { echo 'UPF não resolvido'; exit 1; }",
                "sed -e \"s/POD_IP_ADDR/$POD_IP/g\" -e \"s/UPF_IP_ADDR/$UPF_IP/g\" config/smfcfg.yaml > /tmp/smfcfg.yaml",
                "echo \"SMF pfcp=$POD_IP  UPF=$UPF_IP\"",
                "exec ./smf -c /tmp/smfcfg.yaml -u config/uerouting.yaml"])
            files = {name: dump(CFG[nf]), "uerouting.yaml": dump(UEROUTING), "wrapper.sh": wrapper}
            out += deployment(nf, files, ["/sbin/tini", "--", "sh", "config/wrapper.sh"],
                              ports=[{"name": "sbi", "containerPort": 8000},
                                     {"name": "pfcp", "containerPort": 8805, "protocol": "UDP"}])
            out.append(service(nf, sbi_port))
        elif nf == "upf":
            nat = "\n".join("iptables -t nat -C POSTROUTING -s %s -o eth0 -j MASQUERADE 2>/dev/null || "
                            "iptables -t nat -A POSTROUTING -s %s -o eth0 -j MASQUERADE" % (s["pool"], s["pool"])
                            for s in SLICES)
            wrapper = "\n".join([
                "set -e",
                "POD_IP=$(hostname -i | awk '{print $1}')",
                "sed \"s/POD_IP_ADDR/$POD_IP/g\" config/upfcfg.yaml > /tmp/upfcfg.yaml",
                "echo 1 > /proc/sys/net/ipv4/ip_forward",   # a imagem não tem sysctl
                "iptables -C FORWARD -j ACCEPT 2>/dev/null || iptables -A FORWARD -j ACCEPT",
                nat,
                "echo \"UPF pfcp=$POD_IP  N3=%s (net1)\"" % UPF_IP,
                "exec ./upf -c /tmp/upfcfg.yaml"])
            files = {name: dump(CFG[nf]), "wrapper.sh": wrapper}
            out += deployment(nf, files, ["/sbin/tini", "--", "sh", "config/wrapper.sh"], privileged=True,
                              wait_nrf=False, extra_ann={"k8s.v1.cni.cncf.io/networks": ran_link(UPF_IP)},
                              ports=[{"name": "pfcp", "containerPort": 8805, "protocol": "UDP"}])
            # headless: o nome "upf" resolve direto para o IP do pod (o SMF usa como nodeID)
            out.append(service(nf, [{"name": "pfcp", "port": 8805, "protocol": "UDP"}], headless=True))
        elif nf == "amf":
            files = {name: dump(CFG[nf])}
            out += deployment(nf, files, ["/sbin/tini", "--", "./amf", "-c", "config/" + name],
                              extra_ann={"k8s.v1.cni.cncf.io/networks": ran_link(AMF_IP)},
                              ports=[{"name": "sbi", "containerPort": 8000},
                                     {"name": "ngap", "containerPort": 38412, "protocol": "SCTP"}])
            out.append(service(nf, sbi_port))
        elif nf == "webui":
            files = {"webuicfg.yaml": dump(CFG[nf])}
            out += deployment(nf, files, ["/sbin/tini", "--", "./webui", "-c", "config/webuicfg.yaml"],
                              wait_nrf=False, wait_mongo=True,
                              ports=[{"name": "http", "containerPort": 5000},
                                     {"name": "cgf", "containerPort": 2121}])
            svc = service(nf, [{"name": "http", "port": 5000, "targetPort": 5000,
                                "nodePort": int(env("F5_WEBUI_NODEPORT"))},
                               {"name": "cgf", "port": 2121, "targetPort": 2121}], node_port=True)
            out.append(svc)
        else:
            files = {name: dump(CFG[nf])}
            out += deployment(nf, files, ["/sbin/tini", "--", "./" + nf, "-c", "config/" + name],
                              wait_nrf=(nf != "nrf"), wait_mongo=(nf == "nrf"))
            out.append(service(nf, sbi_port))
    out += dashboard_rbac()
    return {"apiVersion": "v1", "kind": "List", "items": out}


def dashboard_rbac():
    """O painel (ServiceAccount "dashboard" no namespace do Open5GS) lê e controla este core."""
    dns = env("K8S_NAMESPACE", "open5gs")
    rules = [{"apiGroups": [""], "resources": ["pods", "pods/log"], "verbs": ["get", "list", "watch"]},
             {"apiGroups": [""], "resources": ["pods"], "verbs": ["delete"]},
             {"apiGroups": ["apps"], "resources": ["deployments"], "verbs": ["get", "list", "watch"]},
             {"apiGroups": ["apps"], "resources": ["deployments/scale"], "verbs": ["get", "patch", "update"]}]
    return [{"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "Role",
             "metadata": {"name": "innovanetwork-dashboard", "namespace": NS}, "rules": rules},
            {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "RoleBinding",
             "metadata": {"name": "innovanetwork-dashboard", "namespace": NS},
             "subjects": [{"kind": "ServiceAccount", "name": "dashboard", "namespace": dns}],
             "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": "innovanetwork-dashboard"}}]


def ueransim():
    s = SLICES[0]
    sd = "0x" + s["sd"]
    return {
        "fullnameOverride": env("F5_UERANSIM_RELEASE"),
        "image": {"pullPolicy": "IfNotPresent"},
        "podAnnotations": {"k8s.v1.cni.cncf.io/networks": ran_link(env("F5_GNB_SIM_IP")),
                           HASH_ANN: cfg_hash(AMF_IP, env("F5_GNB_SIM_IP"), MCC, MNC, TAC_HEX, s)},
        "amf": {"ip": AMF_IP},
        "interfaces": {"n2": {"dev": "net1"}, "n3": {"dev": "net1"}, "radio": {"dev": "eth0"}},
        "mcc": MCC, "mnc": MNC, "tac": str(int(env("TAC"), 10)), "sst": s["sst"], "sd": sd,
        "ues": {"enabled": True, "count": int(env("UE_COUNT")), "initialMSISDN": env("UE_MSIN_START"),
                "key": env("UE_KEY").upper(), "op": env("UE_OPC").upper(), "opType": "OPC",
                "podAnnotations": {HASH_ANN: cfg_hash(env("UE_COUNT"), env("UE_MSIN_START"), AMF_IP)},
                "apnList": [{"type": "IPv4", "apn": s["dnn"], "slice": {"sst": s["sst"], "sd": sd},
                             "emergency": False}]}}


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "manifests"
    print(json.dumps(manifests() if what == "manifests" else ueransim(), indent=1))
