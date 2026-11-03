# Open5GS — core padrão

Core **5G Standalone Open5GS 2.7.5** no namespace `open5gs`, instalado pelo `install.sh` da raiz com os Helm
charts da [Gradiant](https://github.com/Gradiant/5g-charts) (commit fixo) e values gerados a partir do
`config.env`. Validado com UERANSIM e com celulares comerciais pelo gNB OCUDU.

| | |
|---|---|
| Funções | NRF, SCP, AMF, SMF, UPF, AUSF, UDM, UDR, PCF, BSF, NSSF + MongoDB + WebUI (4G e SEPP desligados) |
| Configuração | `config.env` → `helm/generated/open5gs-values.yaml` |
| N2 / N3 | `10.10.0.10` / `10.10.0.11` na fibra (Multus) |
| Pools | `internet` 10.45.0.0/16 · `internet2` 10.46.0.0/16 |
| Assinantes | WebUI `http://<máquina do core>:30999` (`admin` / `1423` — troque) ou `scripts/subscribers.sh` |
| Teste | `./test.sh` → `7 verificações OK` |

Arquitetura geral: [../arquitetura.md](../arquitetura.md). Instalação: [../instalacao.md](../instalacao.md).

## Sumário

1. [O que o install.sh faz](#1-o-que-o-installsh-faz)
2. [Operação](#2-operação-dia-a-dia)
3. [Modificação](#3-modificação): referência do `config.env`, PLMN, slices, IPs, assinantes, versões, fibra
4. [Desktop × Server](#4-desktop--server)
5. [Testes](#5-testes)
6. [Desinstalação](#6-desinstalação)
7. [Problemas comuns](#7-problemas-comuns)
8. [Limitações](#8-limitações-conhecidas)
9. [Referências](#9-referências)

---

## 1. O que o install.sh faz

Cada passo só age se algo mudou — rodar de novo é seguro.

1. **Valida** o `config.env` (MCC/MNC/TAC/SD, sobreposição de CIDRs, tamanho do IMSI, chaves…).
2. **Detecta o ambiente**: desktop/server, interface e IP (rota default), AVX, RAM, NetworkManager, UFW, firewalld, Docker.
3. **Pacotes** que faltarem (`curl git iptables lksctp-tools bash-completion …`).
4. **Módulos** `sctp tun br_netfilter overlay` (carregados e persistidos).
5. **sysctl**: `ip_forward`, `bridge-nf-call-iptables`, inotify, buffers.
6. **Perfil do host**: NetworkManager ignora `cni0/flannel*/veth*/k3s0`; regras UFW; **firewalld** com as redes do cluster na zona `trusted`; avisos (Docker, AVX, RAM).
7. **Interface estável** `k3s0` (unit `open5gs-k3s-netif`), para o cluster não depender do IP do host.
8. **k3s** `K3S_VERSION` via `/etc/rancher/k3s/config.yaml` (node-ip, interface do flannel, CIDRs, sem Traefik, kubelet com mais QPS de pull, kubeconfig 0600). Mudou o config ⇒ restart do k3s.
9. **Helm** `HELM_VERSION` (SHA-256 verificado) se não houver um Helm 3 no sistema.
10. **Charts Gradiant** no commit `GRADIANT_CHARTS_REF` + `helm dependency build`.
11. **Open5GS**: gera `helm/generated/open5gs-values.yaml` e faz `helm upgrade --install --wait`.
12. **Assinantes**: sincroniza UEs simulados + `SUBSCRIBERS` no MongoDB.
13. **UERANSIM**: gera `helm/generated/ueransim-values.yaml`, instala com o post-renderer, espera o NG Setup e garante UEs registrados **e pingando o UPF** (se preciso reinicia os UEs e, depois, UPF → SMF → gNB → UEs).
14. **Recuperação no boot** (`AUTO_HEAL`): instala a unit `open5gs-k3s-heal`.
15. **kubeconfig do usuário real** (`$SUDO_USER`): cria/mescla `~/.kube/config` (0600), alias `k` + autocomplete, e testa `kubectl get nodes` como esse usuário.

Depois do UERANSIM vêm o **painel e os agentes** ([painel.md](painel.md)) e as units de boot.

Opções: `--deploy-only` (pula 3–9: só values, deploy, assinantes, painel e kubeconfig), `--dashboard-only` (só o painel e os agentes), `-h`.

---

## 2. Operação (dia a dia)

Todos os comandos abaixo rodam **sem sudo**, exceto onde indicado.

### 2.1 Ver o estado

```bash
kubectl get nodes                                  # nó Ready
kubectl -n open5gs get pods -o wide                # 16 pods 1/1 Running
kubectl -n open5gs get svc                         # services (amf-ngap 38412/SCTP, webui 30999…)
./test.sh                                          # verificação completa (exit 0 = OK)
```

`k` é um alias para `kubectl` (com autocomplete) em terminais novos.

### 2.2 Logs

```bash
kubectl -n open5gs logs deploy/open5gs-amf -f      # AMF ao vivo (registros, gNBs)
kubectl -n open5gs logs deploy/open5gs-smf -f      # sessões PDU, IPs alocados
kubectl -n open5gs logs deploy/open5gs-upf         # PFCP, TUN
kubectl -n open5gs logs deploy/ueransim            # gNB
kubectl -n open5gs logs deploy/ueransim-ues        # UEs
kubectl -n open5gs logs deploy/open5gs-amf --previous   # execução anterior (após crash)
sudo journalctl -u k3s -f                          # k3s (sudo)
less logs/install.log                              # histórico do instalador
```

### 2.3 Usar o UE simulado

```bash
kubectl -n open5gs exec -it deploy/ueransim-ues -- bash
# dentro do pod:
nr-cli -d                                          # lista UEs (imsi-001010000000001…)
nr-cli imsi-001010000000001 --exec status          # RM-REGISTERED? MM-REGISTERED/NORMAL-SERVICE?
nr-cli imsi-001010000000001 --exec ps-list         # sessões PDU
ip addr show uesimtun0                             # IP do UE
ping -I uesimtun0 8.8.8.8                          # tráfego pelo core
curl --interface uesimtun0 https://example.com
traceroute -i uesimtun0 8.8.8.8
nr-cli imsi-001010000000001 --exec "deregister normal"   # desregistrar
```

gNB: `kubectl -n open5gs exec deploy/ueransim -- sh -c 'nr-cli $(nr-cli -d) --exec status'`.

### 2.4 WebUI

`http://<NODE_IP>:30999` (`admin` / `1423`; troque a senha no primeiro acesso). Permite criar/editar
assinantes, AMBR, QoS (5QI/ARP), IP fixo e múltiplas slices por assinante.

### 2.5 Assinantes

```bash
./scripts/subscribers.sh list                                   # IMSI, K, OPc, DNN, IP
./scripts/subscribers.sh add 001010000000200 <K> <OPc>          # 1ª slice/DNN
./scripts/subscribers.sh add 001010000000201 <K> <OPc> 1 111111 internet
./scripts/subscribers.sh remove 001010000000200
./scripts/subscribers.sh sync                                   # reaplica o que está no config.env
./scripts/subscribers.sh reset                                  # APAGA todos (pede confirmação)
```

`add`/`remove` não ficam no `config.env`; para persistir, use `SUBSCRIBERS` (ver §3.5).

### 2.6 Reiniciar componentes

```bash
kubectl -n open5gs rollout restart deploy/open5gs-amf          # um NF
kubectl -n open5gs rollout restart deploy/ueransim-ues          # UEs (ex.: UE preso em LIMITED-SERVICE)
kubectl -n open5gs rollout restart deploy                       # tudo (core + RAN)
```

> Reinicie **todos os NFs juntos** em vez de um a um quando houver erros de SBI com IPs antigos
> (cache de descoberta — ver [troubleshooting](../troubleshooting.md)).

### 2.7 Parar, iniciar e reboot

O jeito normal é a aba **Controle** do painel (**▶ Iniciar tudo** / **■ Parar tudo**), que segue a ordem certa e
confere cada etapa. Ver [../operacao.md](../operacao.md).

**No boot**, o comportamento depende de `CORE_AUTOSTART`:

| `CORE_AUTOSTART` | Depois de ligar a máquina |
|---|---|
| `false` (padrão) | a unit `open5gs-k3s-heal` roda `heal.sh --boot-off`: **só o painel fica no ar**; o core (e o free5GC) começam parados e são ligados pelo painel |
| `true` | tudo sobe, e a mesma unit confere se o UE simulado pinga o UPF; se não, reinicia UEs e depois UPF → SMF → gNB → UEs (depois de um reboot os pods voltam em ordem qualquer e o UPF pode não reconhecer o SMF: `Cannot find PFCP-Node`) |

```bash
journalctl -u open5gs-k3s-heal -b      # o que a unit fez neste boot
./scripts/heal.sh                      # recuperação manual do plano de usuário
```

Parar o k3s inteiro (libera CPU/RAM; o nó do RAN perde o servidor enquanto isso):

```bash
sudo systemctl stop k3s && sudo /usr/local/bin/k3s-killall.sh
sudo systemctl start k3s
```

### 2.8 Backup e restauração dos assinantes

```bash
# backup
kubectl -n open5gs exec deploy/open5gs-mongodb -- mongodump --db open5gs --archive > backup-open5gs-$(date +%F).archive
# restauração (substitui as coleções)
kubectl -n open5gs exec -i deploy/open5gs-mongodb -- mongorestore --drop --archive < backup-open5gs-AAAA-MM-DD.archive
```

O volume do MongoDB (PVC `local-path`) fica em `/var/lib/rancher/k3s/storage/` e sobrevive a reboots
e a `helm upgrade`; é apagado por `./uninstall.sh`.

### 2.9 Aplicar uma mudança de configuração

```bash
vim config.env
sudo ./install.sh --deploy-only     # rápido: só regenera values e faz deploy
./test.sh
```

Use o `sudo ./install.sh` completo quando mudar algo do host/k3s (interface, IP do nó, versões, firewall).

---

## 3. Modificação

**Regra geral**: edite `config.env` → `sudo ./install.sh --deploy-only` (ou o completo) → `./test.sh`.

Como as mudanças são aplicadas: os values em `helm/generated/` são regenerados; um **hash** da
configuração vai como anotação em cada pod (`open5gs-k3s/config-hash`). Se mudou, os NFs são
recriados (estratégia `Recreate`, todos juntos) e o gNB/UEs também; os assinantes são re-sincronizados.

### 3.1 Referência do config.env

| Variável | Padrão | Função |
|----------|--------|--------|
| `ENV_PROFILE` | `auto` | `auto`/`desktop`/`server` (ver §4) |
| `NODE_IP_MODE` | `stable` | `stable`: o k3s usa a interface virtual `STABLE_IFACE` com `STABLE_IP` (padrão `k3s0` / `10.254.254.1`), recriada a cada boot. Assim o cluster não depende do IP do host (DHCP, troca entre Wi‑Fi e cabo, outra rede). `iface`: usa a placa física, e se o IP mudar é preciso rodar o install de novo |
| `STABLE_IFACE`, `STABLE_IP` | `k3s0`, `10.254.254.1` | interface e IP virtuais do nó (o IP deve ser privado e fora da LAN e de `K3S_*_CIDR`) |
| `NODE_IFACE`, `NODE_IP` | vazio (rota default) | interface e IP físicos do host. No modo `stable` servem só para a URL da WebUI e para o anúncio do N3 externo (`EXPOSE_RAN`); no modo `iface` também são o nó do k3s |
| `KUBECONFIG_USER` | vazio (`$SUDO_USER`) | usuário que recebe `~/.kube/config` |
| `SHELL_EXTRAS` | `true` | alias `k` + autocomplete no `~/.bashrc` |
| `INSTALL_DIR` | `/opt/open5gs-k3s` | charts clonados, helm, estado |
| `AUTO_INSTALL_MODULES_EXTRA` | `true` | instala `linux-modules-extra` se faltar SCTP |
| `CONFIGURE_UFW`, `CONFIGURE_FIREWALLD` | `true` | libera o cluster no firewall ativo |
| `K3S_VERSION`, `HELM_VERSION` | `v1.36.5+k3s1`, `v3.22.1` | versões fixadas |
| `GRADIANT_CHARTS_REPO`, `GRADIANT_CHARTS_REF` | GitHub, commit `3f998fb` | origem e versão dos charts |
| `OPEN5GS_IMAGE_TAG`, `UERANSIM_IMAGE_TAG` | vazio (2.7.5 / 3.2.6) | trocar imagens |
| `K8S_NAMESPACE`, `OPEN5GS_RELEASE`, `UERANSIM_RELEASE` | `open5gs`, `open5gs`, `ueransim` | nomes no k8s |
| `K3S_CLUSTER_CIDR`, `K3S_SERVICE_CIDR` | `10.42.0.0/16`, `10.43.0.0/16` | redes do cluster |
| `K3S_EXTRA_ARGS` | `()` | flags extras do `k3s server` |
| `HELM_TIMEOUT` | `20m` | timeout do `helm --wait` |
| `MCC`, `MNC` | `001`, `01` | PLMN |
| `TAC` | `1` | Tracking Area Code (decimal) |
| `AMF_REGION_ID`, `AMF_SET_ID` | `2`, `1` | GUAMI |
| `NETWORK_NAME` | `InnovaOpen5GS` | nome da rede exibido no UE |
| `SLICES` | `internet` 10.45/16 e `internet2` 10.46/16 | slices/DNN/pools (ver §3.3) |
| `DNS_SERVERS`, `UE_MTU` | `8.8.8.8 8.8.4.4`, `1400` | entregues ao UE |
| `WEBUI_ENABLED`, `WEBUI_NODEPORT` | `true`, `30999` | WebUI |
| `DASHBOARD_*`, `GNB_METRICS_URL`, `GNB_LOG_*`, `OPEN5GS_METRICS` | ver [painel.md](painel.md) | painel de logs e métricas |
| `MONGODB_PERSISTENCE`, `MONGODB_PERSISTENCE_SIZE` | `true`, `2Gi` | volume do banco |
| `MONGODB_IMAGE_REGISTRY/REPOSITORY/TAG` | vazio (Bitnami latest) | imagem alternativa (ex.: CPU sem AVX) |
| `DEPLOY_UERANSIM` | `true` | `false` remove gNB/UEs simulados (para RAN real) |
| `AUTO_HEAL` | `true` | unit `open5gs-k3s-heal`: no boot, confere o plano de usuário e reinicia UEs/UPF/SMF/gNB se preciso |
| `EXPOSE_RAN` | `false` | expõe N2/N3 no `NODE_IP` para gNB externo (ver §3.7) |
| `UE_COUNT`, `UE_MSIN_START`, `UE_KEY`, `UE_OPC` | `1`, `0000000001`, chaves de teste | UEs simulados (cadastrados automaticamente) |
| `SUBSCRIBERS` | `()` | assinantes extras (SIMs reais) |
| `TEST_*` | ping 4×, 8.8.8.8, 180 s | parâmetros do `test.sh` |

### 3.2 PLMN e TAC

```bash
MCC="001"; MNC="01"          # MNC de 2 ou 3 dígitos: "01" ≠ "001"
TAC="1"                      # decimal (TAC hex 0x000064 = 100)
UE_MSIN_START="0000000001"   # 15 − len(MCC) − len(MNC) dígitos (10 com MNC de 2, 9 com MNC de 3)
```

O PLMN é aplicado em: AMF (GUAMI, TAI, PLMN suportado), **NRF (PLMN servido)**, gNB e UEs/IMSIs.
Assinantes do PLMN anterior ficam no banco — remova com `./scripts/subscribers.sh remove <IMSI>`.

> Use PLMNs de teste (`001-01`, `999-70`). Com rádio real, nunca irradie com PLMN de operadora e
> respeite a regulamentação de espectro.

### 3.3 Slices, DNN e pools de IP

```bash
SLICES=(
  "1:111111:internet:10.45.0.0/16"     # SST:SD:DNN:POOL
  "2:222222:ims:10.46.0.0/16"
)
```

Cada item gera: S-NSSAI no AMF, NSI no NSSF, sessão (pool, gateway `.1`, DNN) no SMF e uma TUN com
NAT no UPF (`ogstun`, `ogstun2`, …). Regras: **SD obrigatório** (6 hex, sem `0x`), um DNN por slice,
pools sem sobreposição entre si nem com as redes do cluster (validado). A **1ª slice** é a do gNB/UEs
do UERANSIM — para testar outra, coloque-a em primeiro.

### 3.4 IPs e rede

| O que mudar | Como |
|-------------|------|
| Pool de IP dos UEs | 4º campo de cada item de `SLICES` |
| DNS / MTU do UE | `DNS_SERVERS`, `UE_MTU` |
| Endereço do nó do k3s | `NODE_IP_MODE`, `STABLE_IFACE`, `STABLE_IP`, `NODE_IFACE`, `NODE_IP` → `sudo ./install.sh` (regrava o config do k3s e reinicia) |
| Redes do cluster | `K3S_CLUSTER_CIDR`, `K3S_SERVICE_CIDR` → **exige** `sudo ./uninstall.sh --k3s` antes |
| Porta da WebUI | `WEBUI_NODEPORT` (30000–32767) |

### 3.5 Assinantes persistentes

```bash
UE_COUNT="3"                     # UEs simulados 001010000000001..003, cadastrados sozinhos
SUBSCRIBERS=(
  "001010000000101:<K 32 hex>:<OPc 32 hex>"                 # 1ª slice/DNN
  "001010000000102:<K>:<OPc>:2:222222:ims"                  # slice/DNN específicos
)
```

O sync faz *remove + add* de cada IMSI listado (mudanças feitas na WebUI nesses IMSIs são
sobrescritas); IMSIs fora do `config.env` não são tocados.

### 3.6 Versões

Mude `K3S_VERSION`, `HELM_VERSION`, `GRADIANT_CHARTS_REF` (commit/tag), `OPEN5GS_IMAGE_TAG`,
`UERANSIM_IMAGE_TAG` e rode `sudo ./install.sh`. Ao subir o `GRADIANT_CHARTS_REF`, confira se o bug do HPA (`helm/postrender/`) e o `servingList` do NRF
continuam iguais (`helm template` ajuda — ver §3.8).

### 3.7 Ligação com o gNB real (fibra N2/N3)

```bash
RAN_LINK_ENABLED=true
RAN_LINK_IFACE="enp5s0f1"      # porta da máquina do core ligada ao gNB
RAN_LINK_CIDR="10.10.0.0/24"   # a máquina do core usa .2, o gNB .1
RAN_LINK_MTU="9000"
AMF_N2_IP="10.10.0.10"         # = cu_cp.amf.addr no .yml do gNB
UPF_N3_IP="10.10.0.11"         # endereço N3 anunciado pelo UPF
GNB_SIM_IP="10.10.0.20"        # gNB do UERANSIM na mesma rede
```

O instalador cria o NetworkAttachmentDefinition `ran-link` (macvlan) e dá ao AMF, ao UPF e ao gNB do UERANSIM
uma 2ª interface (`net1`) com esses IPs. O post-renderer `helm/postrender/amf-ngap-net1.sh` faz o AMF escutar o
N2 em `net1`. Alternativa sem porta dedicada (experimental): `EXPOSE_RAN=true` expõe N2/N3 no IP do nó.

### 3.8 Modificar além do config.env

| Quero… | Onde |
|--------|------|
| Mudar um parâmetro de NF que o `config.env` não expõe | `render_open5gs_values()` em `scripts/lib/common.sh` (gera o YAML de values). Valores possíveis: `values.yaml` de cada subchart em `/opt/open5gs-k3s/5g-charts/charts/open5gs-<nf>/`. |
| Sobrescrever o arquivo de config inteiro de um NF | `<nf>.customOpen5gsConfig` nos values (suportado pelos charts). |
| Adicionar uma variável nova ao `config.env` | declarar no `config.env`, dar padrão em `load_config()`, validar em `validate_config()`, usar no render. |
| Mexer no gNB/UE simulados | `render_ueransim_values()` em `scripts/lib/common.sh`. |
| Filtrar/alterar manifestos renderizados | post-renderers em `helm/postrender/`. |
| Ver o que será aplicado sem aplicar | `helm template open5gs /opt/open5gs-k3s/5g-charts/charts/open5gs -f /opt/open5gs-k3s/5g-charts/charts/open5gs/values-5g.yaml -f helm/generated/open5gs-values.yaml` |
| Ver o que está aplicado | `helm -n open5gs get values open5gs`, `kubectl -n open5gs get cm open5gs-amf -o yaml` |

Depois de editar scripts: `bash -n *.sh scripts/*.sh scripts/lib/*.sh helm/postrender/*.sh` e, se
possível, `shellcheck`.

---

## 4. Desktop × Server

O mesmo `config.env` serve aos dois; as diferenças de host são detectadas (`ENV_PROFILE=auto`).

| Aspecto | Desktop | Server | Tratamento |
|---------|---------|--------|------------|
| Perfil | NetworkManager ativo ou gerenciador de login (gdm etc.) | sem os dois (netplan + networkd), mesmo com `graphical.target` | `auto` ou force `desktop`/`server` |
| NetworkManager | ativo — tentaria gerenciar `cni0`/`flannel.1`/`veth*` | normalmente ausente | arquivo de `unmanaged-devices` se o NM estiver ativo |
| Interface | `enp*`, `wlp*` (Wi-Fi) | `ens*`, `eno*`, bonds, VLANs | rota default ou `NODE_IFACE`/`NODE_IP` |
| IP | DHCP pode mudar, Wi‑Fi ou cabo | normalmente fixo | `NODE_IP_MODE=stable`: o nó do k3s fica em `k3s0` (10.254.254.1) e a troca de IP não afeta o cluster |
| SCTP | kernel `generic` já tem | kernels `-virtual`/cloud podem não ter | instala `linux-modules-extra-$(uname -r)` |
| Firewall | firewalld/UFW podem estar ativos | idem | redes do cluster liberadas automaticamente |
| Docker | comum | raro | aviso (política FORWARD DROP) |
| kubectl | pode já existir em `/usr/local/bin` | normalmente vem do k3s | `~/.kube/config` do `$SUDO_USER`; scripts usam kubeconfig explícito |
| Arquitetura | x86_64 | x86_64 ou arm64 | Helm baixado para a arquitetura certa |

A saída para a internet (N6) segue sempre a rota default do momento. Com mais de uma placa, fixe
`NODE_IFACE` e `NODE_IP` para escolher o IP anunciado a um gNB externo (`EXPOSE_RAN`).

---

## 5. Testes

`./test.sh` (ou `./test.sh -v` para logs do AMF/SMF/UPF/gNB/UE em caso de falha). Saída da validação:

```
==> Pods no namespace open5gs
    [ok] todos os pods Running/Ready (16)
==> NRF
    [ok] NRF registrou 9 NF(s)
==> N2: NG Setup
    [ok] gNB fez NG Setup com o AMF (open5gs-amf-ngap:38412/SCTP)
==> UEs: registro (5GMM) e sessão PDU (DNN internet, S-NSSAI 1/111111)
    [ok] imsi-001010000000001: registrado (MM-REGISTERED/NORMAL-SERVICE)
    [ok] imsi-001010000000001: sessão PDU ativa, uesimtun0 = 10.45.0.2 (pool 10.45.0.0/16)
    [ok] imsi-001010000000001: ping 10.45.0.1 (gateway no UPF) via uesimtun0
    [ok] imsi-001010000000001: ping 8.8.8.8 via uesimtun0 (0% packet loss; rtt 15.670 ms)
RESULTADO: 7 verificações OK, 0 falhas
```

O ping ao gateway testa o plano de usuário (N3/GTP-U → UPF) sem depender de internet; o ping externo
testa N6/NAT. Código de saída 0/1 (serve para automação).

---

## 6. Desinstalação

```bash
sudo ./uninstall.sh            # releases + PVC do MongoDB + namespace (k3s continua)
sudo ./uninstall.sh --k3s      # + k3s inteiro + contexto open5gs-k3s do ~/.kube/config
sudo ./uninstall.sh --purge    # + sysctl, módulos, NetworkManager, UFW/firewalld, /opt/open5gs-k3s,
                               #   helm/generated/ e o bloco do ~/.bashrc
sudo ./uninstall.sh --purge -y # sem confirmação
```

Outros contextos do seu `~/.kube/config` são preservados. Pacotes apt não são removidos.

---

## 7. Problemas comuns

Guia completo: **[troubleshooting.md](../troubleshooting.md)**. Os mais comuns:

| Sintoma | Solução rápida |
|---------|----------------|
| `connection to the server localhost:8080 was refused` | Falta kubeconfig do usuário: `sudo ./install.sh --deploy-only` (ou `sudo k3s kubectl …`). |
| UE `no cells in coverage` | Firewall do host bloqueando pod↔pod (firewalld): rode `sudo ./install.sh`. |
| UE em `LIMITED-SERVICE` | `kubectl -n open5gs rollout restart deploy/ueransim-ues`. |
| Registro rejeitado, SCP `No SEPP` | PLMN fora do `serving` do NRF — já tratado; confira `MCC`/`MNC` e rode o install. |
| Pods `CrashLoopBackOff` nos primeiros minutos | Normal enquanto o MongoDB sobe. |
| MongoDB *Illegal instruction* | CPU sem AVX → `MONGODB_IMAGE_*`. |

---

## 8. Limitações conhecidas

- Single node, sem alta disponibilidade; MongoDB standalone.
- N4, SBI e N6 pela rede dos pods; só N2 e N3 na fibra (Multus/macvlan).
- UERANSIM testa só a 1ª slice por instalação.
- Somente IPv4 nos pools de UE; SBI em HTTP (sem TLS), como nos charts padrão.

---

## 9. Referências

- Open5GS — https://open5gs.org · https://github.com/open5gs/open5gs
- Gradiant 5g-charts — https://github.com/Gradiant/5g-charts
- UERANSIM — https://github.com/aligungr/UERANSIM
- k3s — https://docs.k3s.io
- towards5gs-helm (referência de arquitetura) — https://github.com/Orange-OpenSource/towards5gs-helm
- 3GPP TS 23.501 (arquitetura 5GS), TS 23.502 (procedimentos), TS 38.413 (NGAP), TS 29.281 (GTP-U)
