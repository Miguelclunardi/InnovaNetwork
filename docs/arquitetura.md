# Arquitetura do core Open5GS

Este documento detalha **o que** está implantado e **como** as peças se conectam.
Visão do projeto completo (RAN, fibra, dois cores): [README](../README.md#2-arquitetura). Para operar e modificar o core, veja [open5gs-core.md](open5gs-core.md); para problemas, [troubleshooting.md](troubleshooting.md).

## 1. Visão geral

```
┌──────────────────────────────── Host Ubuntu 24.04 (1 nó) ────────────────────────────────┐
│  k3s (Kubernetes) · containerd · flannel VXLAN · CoreDNS · local-path · ServiceLB          │
│                                                                                           │
│  ┌──────────────────────────── namespace open5gs ──────────────────────────────────────┐  │
│  │                                                                                      │  │
│  │   Plano de controle (SBA, HTTP/2 :7777)                                              │  │
│  │   ┌─────┐   ┌─────┐   ┌──────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌──────┐              │  │
│  │   │ NRF │◄─►│ SCP │◄─►│ AUSF │ │ UDM │ │ UDR │ │ PCF │ │ BSF │ │ NSSF │              │  │
│  │   └─────┘   └──┬──┘   └──────┘ └─────┘ └──┬──┘ └──┬──┘ └─────┘ └──────┘              │  │
│  │                │                          └───┬───┘                                  │  │
│  │             ┌──┴──┐                      ┌────▼────┐   ┌───────┐                     │  │
│  │   N2 SCTP   │ AMF │        N11           │ MongoDB │◄──│ WebUI │ NodePort :30999     │  │
│  │  ┌─────────►│     │◄──────────┐          └─────────┘   └───────┘                     │  │
│  │  │          └─────┘        ┌──┴──┐                                                   │  │
│  │  │                         │ SMF │                                                   │  │
│  │  │                         └──┬──┘                                                   │  │
│  │  │                            │ N4 PFCP :8805                                        │  │
│  │ ┌┴────────┐   N3 GTP-U :2152 ┌▼────┐  ogstun 10.45.0.1/16                           │  │
│  │ │ gNB     │─────────────────►│ UPF │──── NAT (MASQUERADE) ──► eth0 do pod ──┐       │  │
│  │ │UERANSIM │                  └─────┘                                        │       │  │
│  │ └┬────────┘                                                                 │       │  │
│  │  │ RLS UDP :4997 (rádio simulado)                                           │       │  │
│  │ ┌┴────────┐                                                                 │       │  │
│  │ │ UE(s)   │ uesimtun0 = 10.45.0.x                                           │       │  │
│  │ │UERANSIM │                                                                 │       │  │
│  │ └─────────┘                                                                 │       │  │
│  └─────────────────────────────────────────────────────────────────────────────┼───────┘  │
│                                                         NAT do k3s/flannel ────▼          │
│                                                         rota default (Wi-Fi/cabo) ──► N6 / Internet
└───────────────────────────────────────────────────────────────────────────────────────────┘
```

## 2. Funções de rede (NFs)

| NF | Nome | O que faz aqui | Deployment / Service |
|----|------|----------------|----------------------|
| **NRF** | Network Repository Function | Registro e descoberta de NFs; guarda o PLMN servido (`serving`). | `open5gs-nrf` / `open5gs-nrf-sbi` |
| **SCP** | Service Communication Proxy | Roteia as chamadas SBI entre NFs (descoberta delegada). Detecta PLMN estrangeiro e exigiria SEPP. | `open5gs-scp` / `open5gs-scp-sbi` |
| **AMF** | Access & Mobility Mgmt | N2 (NGAP/SCTP) com o gNB, N1 (NAS) com o UE, registro, autenticação, mobilidade, seleção de SMF. GUAMI, TAI e S-NSSAI suportados. | `open5gs-amf` / `open5gs-amf-ngap` (38412/SCTP) |
| **SMF** | Session Mgmt | Sessões PDU, alocação de IP por DNN, controle do UPF via PFCP. | `open5gs-smf` |
| **UPF** | User Plane | GTP-U (N3) ↔ IP (N6); uma TUN por DNN (`ogstun`, `ogstun2`…) com NAT. Pod privilegiado. | `open5gs-upf` / `-gtpu` (2152/UDP), `-pfcp` (8805/UDP) |
| **AUSF** | Authentication Server | 5G-AKA. | `open5gs-ausf` |
| **UDM** | Unified Data Mgmt | Vetores de autenticação, perfil do assinante (SUPI, slices, DNN). | `open5gs-udm` |
| **UDR** | Unified Data Repository | Acesso ao MongoDB para UDM/PCF. | `open5gs-udr` |
| **PCF** | Policy Control | Políticas de sessão (AMBR, QoS). | `open5gs-pcf` |
| **BSF** | Binding Support | Associação sessão↔PCF. | `open5gs-bsf` |
| **NSSF** | Slice Selection | Escolhe a NSI para o S-NSSAI pedido. | `open5gs-nssf` |
| **WebUI** | Interface web | Cadastro/edição de assinantes. | `open5gs-webui` (NodePort 30999) |
| **MongoDB** | Banco | Assinantes, perfis. PVC `local-path` de 2 GiB. | `open5gs-mongodb` |
| *populate* | Utilitário | Pod com `open5gs-dbctl` usado por `scripts/subscribers.sh`. | `open5gs-populate` |
| **gNB** | UERANSIM | gNodeB simulado. | `ueransim` |
| **UE** | UERANSIM | UE(s) simulado(s), uma `uesimtunN` por UE. | `ueransim-ues` |

Desligados (via `values-5g.yaml` dos charts): HSS, MME, PCRF, SGW-C/U (4G) e SEPP (roaming).

## 3. Interfaces 3GPP

| Interface | Entre | Protocolo / porta | Implementação no cluster |
|-----------|-------|-------------------|--------------------------|
| N1 | UE ↔ AMF | NAS (dentro do NGAP) | — |
| N2 | gNB ↔ AMF | NGAP / SCTP 38412 | Service `open5gs-amf-ngap` (ClusterIP; `LoadBalancer` com `EXPOSE_RAN=true`) |
| N3 | gNB ↔ UPF | GTP-U / UDP 2152 | IP do pod do UPF (anunciado via PFCP); `NODE_IP` com `EXPOSE_RAN=true` |
| N4 | SMF ↔ UPF | PFCP / UDP 8805 | Service `open5gs-upf-pfcp` |
| N6 | UPF ↔ DN | IP | TUN `ogstun` + MASQUERADE no pod → NAT do host |
| SBI (N8, N10, N11, N12…) | NFs | HTTP/2 TCP 7777 | Services `open5gs-<nf>-sbi`, via SCP |
| Rádio simulado | UE ↔ gNB | RLS / UDP 4997 | IP do pod do gNB (Service headless `ueransim`) |

## 4. Fluxo de registro e sessão (o que o `test.sh` valida)

1. **NG Setup**: gNB → AMF (SCTP). O AMF confere PLMN, TAC e S-NSSAI.
2. **Seleção de célula**: o UE recebe MIB/SIB1 do gNB (RLS) e escolhe a célula como `SUITABLE` (PLMN igual ao HPLMN).
3. **Registration Request** com SUCI → AMF → (SCP) → AUSF → UDM → UDR/MongoDB → **5G-AKA** com K/OPc.
   O SCP só aceita o SUCI se o PLMN estiver no `serving` do NRF; senão trata como roaming e falha (*No SEPP*).
4. **PDU Session Establishment** (DNN + S-NSSAI) → AMF → SMF → PFCP Session no UPF.
5. SMF aloca IP do pool (ex.: `10.45.0.2`); o UE cria `uesimtun0`.
6. **Plano de usuário**: `ping -I uesimtun0 10.45.0.1` (gateway na TUN do UPF, testa N3) e `ping -I uesimtun0 8.8.8.8` (testa N6/NAT).

## 5. Rede do Kubernetes

- **Nó**: com `NODE_IP_MODE=stable` (padrão) o k3s usa a interface dummy `k3s0` (10.254.254.1/32), criada pela unit `open5gs-k3s-netif` antes do k3s. Assim o cluster não depende do IP físico, que pode vir de DHCP ou trocar entre Wi‑Fi e cabo.
- **CNI**: flannel (VXLAN) amarrado à interface do nó (`k3s0`, ou `NODE_IFACE` no modo `iface`); pods em `K3S_CLUSTER_CIDR` (10.42.0.0/16), services em `K3S_SERVICE_CIDR` (10.43.0.0/16).
- Cada NF tem só `eth0`; N2/N3/N4/SBI compartilham a rede de pods. Não usamos Multus (ver comparação abaixo).
- Tráfego **via Service** (SBI, NGAP) passa por DNAT do kube-proxy; tráfego **direto pod↔pod** (RLS UE↔gNB, N3 gNB↔UPF) é roteado na bridge `cni0` — por isso um firewall do host (firewalld) pode quebrar só o plano de usuário/rádio.
- O UPF faz NAT do pool de UEs para o IP do pod; o pod sai pelo NAT do flannel pela rota default do momento.

## 6. Decisões de projeto (resumo)

| Tema | Escolha | Motivo |
|------|---------|--------|
| Kubernetes | k3s single-node | Leve, containerd embutido, ServiceLB e local-path prontos. Traefik desabilitado. |
| Charts | Gradiant `5g-charts` via **git em commit fixo** | O registry OCI parou na 2.2.6 (2024); o git tem open5gs 2.3.8 / Open5GS 2.7.5. |
| Core | Open5GS 5G SA | — |
| Referência | towards5gs-helm (Orange) | Só arquitetura. Ele usa **free5GC** + Multus; nada de free5GC é instalado aqui. |
| Configuração | `config.env` → values gerados em `helm/generated/` | Nada fixo no código; mesmo arquivo no desktop e no servidor. |
| Reaplicar config | anotação `open5gs-k3s/config-hash` nos pods | Os charts não reiniciam pods quando o ConfigMap muda. |
| Atualização dos NFs | `updateStrategy: Recreate` | Em RollingUpdate, NFs novos guardavam no cache NFs antigos (24 h) ⇒ falhas no SCP. |
| Assinantes | `open5gs-dbctl` via `kubectl exec` (remove+add) | Idempotente; `initCommands` do chart rodaria a cada restart. |
| HPA do gNB | removido por post-renderer | Bug do chart: aponta para `StatefulSet` inexistente. |

Lista completa e histórico: [decisoes.md](decisoes.md).

## 7. Comparação com towards5gs-helm

| | Este projeto | towards5gs-helm |
|---|---|---|
| Core | Open5GS 2.7.5 | free5GC |
| Charts | Gradiant | Orange |
| Rede N2/N3/N6 | rede de pods (flannel) | Multus + macvlan em placa física |
| RAN de teste | UERANSIM | UERANSIM |
| Alvo | laboratório single-node, depois RAN real | multi-interface, mais próximo de produção |

Para ligar um gNB real com desempenho, o caminho natural é adotar a ideia do towards5gs (interfaces N2/N3/N6 dedicadas via Multus/macvlan ou SR-IOV) — ver *Roadmap* no README.
