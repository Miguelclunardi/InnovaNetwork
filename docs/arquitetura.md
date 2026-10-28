# Arquitetura

Como o InnovaNetwork está montado: máquinas, cluster, componentes, redes, IPs, portas e pastas.

- [1. Visão geral](#1-visão-geral)
- [2. Máquinas e papéis](#2-máquinas-e-papéis)
- [3. O cluster Kubernetes](#3-o-cluster-kubernetes)
- [4. Componentes por namespace](#4-componentes-por-namespace)
- [5. Redes](#5-redes)
- [6. Endereços e portas](#6-endereços-e-portas)
- [7. Funções de rede e interfaces 3GPP](#7-funções-de-rede-e-interfaces-3gpp)
- [8. Do celular à internet](#8-do-celular-à-internet)
- [9. Como o painel enxerga tudo](#9-como-o-painel-enxerga-tudo)
- [10. Pastas e serviços instalados](#10-pastas-e-serviços-instalados)
- [11. Princípios de projeto](#11-princípios-de-projeto)

---

## 1. Visão geral

```
                              ┌──────────────────── cluster k3s ─────────────────────┐
                              │                                                       │
  rede local (DHCP) ──────────┤ MÁQUINA DO CORE (servidor)        MÁQUINA DO RAN (nó) │
                              │  ns open5gs: core + UERANSIM       ns ocudu:           │
                              │              + painel               pod ocudu-gnb      │
                              │  ns free5gc: core + UERANSIM        (rede do host)     │
                              │                                                       │
                              │  enp5s0f1 10.10.0.2 ═══ fibra ═══ 10.10.0.1 E810 p4   │
                              └───────────────────────────────────────────┬──────────┘
                                                                          │ E810 p1: fronthaul 7.2 + PTP
                                                                     ┌────┴────┐
                                                                     │  O-RU   │ ))) UEs
                                                                     └─────────┘
```

Três camadas, cada uma com o próprio instalador:

| Camada | O que é | Instalador | Configuração |
|---|---|---|---|
| **Plataforma + core padrão + painel** | k3s, Multus, Open5GS, UERANSIM, painel | `install.sh` | `config.env` |
| **Core opcional** | free5GC + UERANSIM próprio | `free5gc/install.sh` | `free5gc/free5gc.env` |
| **Rádio** | nó do RAN + gNB OCUDU | `ran/ocudu/install.sh` + `no-ran.sh` | `ran/ocudu/ocudu.env` |

## 2. Máquinas e papéis

| | Máquina do core | Máquina do RAN |
|---|---|---|
| Nome no setup de referência | `torre2` | `innovaserver` |
| Papel no k3s | **servidor** (plano de controle + workloads) | **agente** (nó dedicado ao rádio) |
| Roda | Open5GS, free5GC, UERANSIM, painel, agentes do painel | gNB OCUDU (pod) |
| Rede local | DHCP (o IP pode mudar a cada boot; nada depende dele) | DHCP |
| Fibra N2/N3 | `enp5s0f1` `10.10.0.2/24`, MTU 9000 | E810 porta 4 `ens4f3np3` `10.10.0.1/24`, MTU 9000 |
| Outros | `10.101.131.10/24` na rede de gestão da O-RU | E810 porta 1 `ens4f0np0`: fronthaul (VF em DPDK) e PTP grandmaster; GNSS |

## 3. O cluster Kubernetes

- **k3s v1.36.5+k3s1**, flannel VXLAN, CoreDNS, local-path; Traefik desligado.
- **Servidor com IP estável.** O servidor anuncia `10.254.254.1` na interface virtual `k3s0` (criada no boot pela
  unit `open5gs-k3s-netif`). O cluster não depende do IP da rede local, que muda com o DHCP.
- **Nó do RAN pela fibra.** O agente usa `node-ip 10.10.0.1` e `flannel-iface ens4f3np3` (nunca a porta do
  fronthaul). Alcança o servidor pela rota `10.254.254.1/32 via 10.10.0.2` (unit `innovanetwork-k3s-route`).
- **Nó reservado.** Rótulo `innovanetwork/role=ran` e taint `innovanetwork/ran=true:NoSchedule`: só o gNB (que
  tolera o taint) e DaemonSets do sistema rodam lá.
- **Redes do cluster:** pods `10.42.0.0/16` (servidor `10.42.0.x`, nó do RAN `10.42.1.x`), services `10.43.0.0/16`.
- **Multus** (DaemonSet) adiciona uma 2ª interface (`net1`, macvlan sobre a porta da fibra) aos pods que falam com
  o gNB: AMF, UPF e gNB do UERANSIM.
- **CPUs.** No nó do RAN, os processos do k3s ficam nas CPUs fora das reservadas ao gNB (ex.: 18–31).

## 4. Componentes por namespace

| Namespace | Componentes | Instalado por |
|---|---|---|
| `open5gs` | Open5GS (NRF, SCP, AMF, SMF, UPF, AUSF, UDM, UDR, PCF, BSF, NSSF, WebUI, MongoDB, populate), UERANSIM (gNB + UEs), **painel** | `install.sh` (charts Gradiant + values gerados) |
| `free5gc` | free5GC (NRF, AMF, SMF, UPF, AUSF, UDM, UDR, PCF, NSSF, CHF, NEF, WebConsole, MongoDB), UERANSIM | `free5gc/install.sh` (manifestos gerados) |
| `ocudu` | Deployment `ocudu-gnb` (0 ou 1 réplica) | `ran/ocudu/install.sh` |
| `kube-system` | CoreDNS, local-path, metrics-server, Multus | k3s / `install.sh` |

**Um core ativo por vez.** Os dois cores podem ficar instalados (IPs e pools diferentes), mas só um fica ligado;
o gNB aponta para o AMF de um deles (um `.yml` por core). O painel faz a troca.

Cada namespace de componente tem um ConfigMap descritor com o rótulo `innovanetwork/component`, para ferramentas
(como o painel) descobrirem o que está instalado.

## 5. Redes

| Rede | Faixa | Para quê |
|---|---|---|
| Rede local | DHCP | acesso SSH/painel; saída para a internet (N6) |
| **Fibra N2/N3** | `10.10.0.0/24`, MTU 9000 | NGAP (N2) e GTP-U (N3) entre gNB e core; tráfego do cluster com o nó do RAN |
| Gestão da O-RU | `10.101.131.0/24` | CLI da O-RU (só leitura pelo painel). **Nunca use /8**: cobriria a fibra e o cluster |
| Pods / services | `10.42.0.0/16` / `10.43.0.0/16` | SBI, PFCP (N4), MongoDB, painel |
| Nó estável | `10.254.254.1/32` (`k3s0`) | API do k3s (6443) |
| Fronthaul O-RAN 7.2 | VLAN 564, porta 1 da E810 | C/U-plane entre DU e O-RU; PTP |
| Pools dos UEs | ver abaixo | IPs entregues aos celulares e UEs simulados |

**Só N2 e N3 saem do cluster**, com IP fixo na fibra (macvlan `ran-link`). O resto (SBI, N4) fica na rede dos
pods. **N6:** o UPF faz NAT dos pools e sai pela rota padrão da máquina do core.

## 6. Endereços e portas

### Por core

| | Open5GS (padrão) | free5GC (opcional) |
|---|---|---|
| AMF — N2, SCTP 38412 | `10.10.0.10` | `10.10.0.30` |
| UPF — N3, GTP-U 2152 | `10.10.0.11` | `10.10.0.31` |
| gNB UERANSIM na fibra | `10.10.0.20` | `10.10.0.32` |
| Pools dos UEs | `internet` 10.45/16 · `internet2` 10.46/16 | `internet` 10.60/16 · `internet2` 10.61/16 · `ims` 10.62/16 |
| Nome da rede no celular | `InnovaOpen5GS` | `InnovaFree5GC` |
| Assinantes (web) | WebUI `:30999` | WebConsole `:31000` |
| `.yml` do gNB OCUDU (exemplo) | `gnb_ru_liteon_SLPIT_CORE.yml` | `gnb_ru_liteon_FREE5GC.yml` |

### Comum

| | Valor |
|---|---|
| PLMN / TAC | `001-01` / `1` |
| Slices | SST 1 / SD `111111` (`internet`) · SST 2 / SD `222222` (`internet2`) |
| gNB OCUDU | N2 e N3 em `10.10.0.1`; métricas WebSocket `:8001`; log `/tmp/gnb.log` |
| O-RU | gestão `10.101.131.59` |

### Portas

| Porta | Serviço | Onde |
|---|---|---|
| 30998/tcp | painel | máquina do core (NodePort) |
| 30999/tcp | WebUI do Open5GS | máquina do core (NodePort) |
| 31000/tcp | WebConsole do free5GC | máquina do core (NodePort) |
| 38412/sctp | N2 (NGAP) | IP do AMF na fibra |
| 2152/udp | N3 (GTP-U) | IP do UPF na fibra / gNB |
| 8805/udp | N4 (PFCP) | rede dos pods |
| 7777/tcp · 8000/tcp | SBI Open5GS · SBI free5GC | rede dos pods |
| 27017/tcp | MongoDB | rede dos pods |
| 9090/tcp | métricas Prometheus dos NFs (opcional) | rede dos pods |
| 8001/tcp | métricas do gNB (WebSocket) | `10.10.0.1` |
| 6443/tcp · 10250/tcp · 8472/udp | API do k3s · kubelet · VXLAN do flannel | entre as máquinas |

## 7. Funções de rede e interfaces 3GPP

| NF | Papel |
|---|---|
| **NRF** | registro e descoberta de NFs; guarda o PLMN servido |
| **SCP** | roteia as chamadas SBI (Open5GS) |
| **AMF** | N2 com o gNB, N1 (NAS) com o UE: registro, autenticação, mobilidade |
| **SMF** | sessões PDU, alocação de IP por DNN, controla o UPF via PFCP |
| **UPF** | GTP-U (N3) ↔ IP (N6), uma TUN por DNN, NAT |
| **AUSF / UDM / UDR** | 5G-AKA, perfil do assinante, acesso ao banco |
| **PCF / BSF / NSSF** | políticas, vínculo sessão↔PCF, seleção de slice |
| **CHF / NEF** | tarifação e exposição (só free5GC) |
| **WebUI / WebConsole** | cadastro de assinantes |

| Interface | Entre | Protocolo | No cluster |
|---|---|---|---|
| N1 | UE ↔ AMF | NAS (dentro do NGAP) | — |
| N2 | gNB ↔ AMF | NGAP / SCTP 38412 | `net1` do AMF na fibra |
| N3 | gNB ↔ UPF | GTP-U / UDP 2152 | `net1` do UPF na fibra |
| N4 | SMF ↔ UPF | PFCP / UDP 8805 | rede dos pods (service headless, sem NAT) |
| N6 | UPF ↔ internet | IP | TUN + NAT no pod do UPF → rota padrão da máquina |
| SBI | NFs | HTTP/2 | rede dos pods |

## 8. Do celular à internet

1. **Rádio:** o celular encontra a célula n78 da O-RU; a O-RU troca IQ com o DU do OCUDU pelo fronthaul 7.2
   (sincronizados pelo PTP vindo da E810, que segue o GNSS).
2. **N2:** o gNB já fez o *NG Setup* com o AMF (`10.10.0.1` → `10.10.0.10`).
3. **Registro:** Registration Request (SUCI) → AMF → AUSF/UDM/UDR → 5G-AKA com K/OPc do banco.
4. **Sessão:** PDU Session (DNN + S-NSSAI) → SMF → PFCP no UPF → IP do pool (ex.: `10.45.0.2`).
5. **Dados:** GTP-U do gNB (`10.10.0.1`) ao UPF (`10.10.0.11`) → TUN → NAT → internet.

## 9. Como o painel enxerga tudo

```
navegador ── :30998 ──► pod do painel (ns open5gs)
                          ├─ API do Kubernetes ........ pods, logs, escalar Deployments (core, UERANSIM, gNB)
                          ├─ WebSocket :8001 do gNB ... métricas do rádio, 1/s
                          ├─ /proc e /sys do host ..... CPU, memória, tráfego do UPF
                          └─◄ agentes (máquina do core, POST com token)
                               ├─ gnb-log ...... log do gNB por SSH (tail -F, só leitura)
                               ├─ gnb-ctl ...... estado do gNB e iniciar/parar (via ran/ocudu/gnb.sh)
                               ├─ hosts ........ CPU/temperatura das outras máquinas por SSH
                               └─ ru ........... CLI da O-RU, só comandos "show"
```

Nada do painel é instalado na máquina do RAN além do que o Kubernetes já roda.

## 10. Pastas e serviços instalados

### Máquina do core

| Caminho | Conteúdo |
|---|---|
| `~/InnovaNetwork` | este repositório (configuração e scripts) |
| `/opt/open5gs-k3s/` | charts Gradiant, Helm, estado (senhas do painel, credenciais da O-RU, backups do `config.env`) |
| `/var/lib/open5gs-k3s/dashboard/` | histórico persistente do painel (SQLite) |
| `/etc/rancher/k3s/` | configuração e kubeconfig do k3s |
| `helm/generated/` | values e manifestos gerados (fora do git) |
| `logs/install.log` | log do instalador |

| Unit systemd | Função |
|---|---|
| `k3s` | servidor Kubernetes |
| `open5gs-k3s-netif` | cria `k3s0` antes do k3s |
| `open5gs-k3s-heal` | no boot: deixa os cores parados (`CORE_AUTOSTART=false`) ou recupera o plano de usuário |
| `open5gs-k3s-gnb-log` · `-gnb-ctl` · `-hosts` · `-ru` | agentes do painel |

### Máquina do RAN

| Caminho | Conteúdo |
|---|---|
| `~/ocudu` | código do OCUDU (a imagem é gerada de um commit dele) |
| `~/ocudu/configs/*.yml` | configurações do gNB, lidas pelo pod direto do host |
| `~/innovanetwork-ran/` | `no-ran.sh`, `ocudu.env` e logs dos passos |
| `/tmp/gnb.log` | log do gNB |
| `/etc/rancher/k3s/config.yaml` | configuração do agente k3s |

| Unit systemd | Função |
|---|---|
| `k3s-agent` | nó Kubernetes |
| `innovanetwork-k3s-route` | rota até o servidor pela fibra |
| `ocudu-setup`, `dpdk`, `ts2phc`, `ptp4l-gm`, `phc2sys` | preparação da máquina (do setup, não do projeto) — ver [hardware](hardware/e810-liteon.md) |

## 11. Princípios de projeto

| Princípio | Como aparece |
|---|---|
| Nada fixo no código | todo parâmetro vem de `config.env`, `free5gc.env` ou `ocudu.env`, validado antes de aplicar |
| Idempotência | rodar um instalador de novo só aplica o que mudou |
| Hardware isolado | o que depende do setup fica em `ran/ocudu/` e no perfil de hardware |
| Um core por vez | os dois convivem instalados; a troca é feita em ordem e conferida |
| Seguro no boot | só o painel sobe; core e rádio são ligados pelo operador (o GPS pode demorar) |
| Configuração aplicada de verdade | hash da configuração nos pods: mudou, o pod é recriado |
| Segredos fora do git | chaves de SIM, senhas do painel e da O-RU ficam em Secrets e arquivos do root |
