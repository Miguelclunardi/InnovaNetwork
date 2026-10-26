# InnovaNetwork — rede 5G SA do Centro Innova

Rede **5G Standalone** completa de laboratório: rádio real **OCUDU** (CU/DU) com a O-RU **LiteOn**, core 5G em
**Kubernetes (k3s)** e o painel **Innova Center Dashboard** para operar e medir tudo pelo navegador.

- **Padrão:** OCUDU + **Open5GS** (instalado pelo `install.sh` da raiz).
- **Opcional:** um segundo core, **free5GC**, no mesmo cluster ([free5gc/README.md](free5gc/README.md)).
  **Um core por vez** atende o rádio; a troca é feita na aba **Controle** do painel.
- Tudo configurável em **`config.env`** (e `free5gc/free5gc.env` para o free5GC): nada fixo no código.

> **Estado (2026-10-26):** validado ponta a ponta com os dois cores — celulares comerciais pelo OCUDU + LiteOn,
> UERANSIM (`./test.sh` 7/7 no Open5GS, `./free5gc/test.sh` 6/6 no free5GC) e troca de core pelo painel nos
> dois sentidos (free5GC → Open5GS em ~5 min, Open5GS → free5GC em ~1 min).

---

## Sumário

1. [Componentes](#1-componentes)
2. [Arquitetura](#2-arquitetura)
3. [Endereços e portas](#3-endereços-e-portas)
4. [Instalação](#4-instalação)
5. [Uso no dia a dia](#5-uso-no-dia-a-dia)
6. [Documentação](#6-documentação)
7. [Estrutura do repositório](#7-estrutura-do-repositório)
8. [Versões](#8-versões)
9. [Limitações conhecidas](#9-limitações-conhecidas)
10. [Regras do projeto](#10-regras-do-projeto)

---

## 1. Componentes

| Peça | O que é | Onde roda |
|---|---|---|
| **Open5GS 2.7.5** | Core 5G SA padrão (AMF, SMF, UPF, NRF, SCP, AUSF, UDM, UDR, PCF, BSF, NSSF, WebUI, MongoDB) | k3s no **torre2**, namespace `open5gs` |
| **free5GC v4.3.0** (opcional) | Segundo core 5G SA (AMF, SMF, UPF, NRF, AUSF, UDM, UDR, PCF, NSSF, CHF, NEF, WebConsole, MongoDB) | k3s no **torre2**, namespace `free5gc` |
| **UERANSIM 3.2.6** | gNB e UE simulados, um par por core, para testar sem rádio | k3s no **torre2** |
| **Innova Center Dashboard** | Painel web: estado, métricas, logs, controle, histórico, configuração e documentação | k3s no **torre2** (porta 30998) |
| **OCUDU** | gNB real (CU + DU, split 7.2) | **innovaserver**, serviço `ocudu-gnb@<yml>` — **nunca em container** |
| **LiteOn FlexFi FR1** | O-RU, banda n78, TDD, 4T4R | ligada ao innovaserver pela fibra de fronthaul |

O **torre2** é a máquina do core (Ubuntu 24.04, k3s de um nó). O **innovaserver** é a máquina do gNB (Intel E810,
DPDK, PTP). As duas se falam por uma **fibra dedicada** (N2/N3) — veja a arquitetura.

## 2. Arquitetura

```
                 rede da universidade (DHCP)                 switch da RU (gestão)
       ─────────────┬──────────────────────────────────┬──────────────┬─────────────
                    │ 191.4.205.x                      │ 191.4.205.x  │ 10.101.131.0/24
┌───────────────────┴───────────────────────┐   ┌──────┴──────────────┴──────────────┐
│ torre2 — core 5G (k3s, nó em k3s0)        │   │ innovaserver — gNB                 │
│                                           │   │                                    │
│  ns open5gs (padrão)    ns free5gc (opc.) │   │  OCUDU (CU/DU)  ocudu-gnb@<yml>    │
│  AMF 10.10.0.10 ◄─┐     AMF 10.10.0.30 ◄┐ │   │   cu_cp.amf.addr = AMF do core     │
│  UPF 10.10.0.11 ◄─┤     UPF 10.10.0.31 ◄┤ │   │   métricas ws :8001, log /tmp/gnb.log│
│  UERANSIM .20     │     UERANSIM .32    │ │   │                                    │
│                   │ macvlan "ran-link"  │ │   │  E810 porta 4 ── 10.10.0.1/24      │
│  painel :30998    └──────┬──────────────┘ │   │  E810 porta 1 ── DPDK + PTP ──┐    │
│                   enp5s0f1 10.10.0.2/24   │   └──────────┬────────────────────┼────┘
└──────────────────────────┼────────────────┘              │                    │ fronthaul
                           └──────── fibra N2/N3 ──────────┘                    │ O-RAN 7.2
                                      10.10.0.0/24, MTU 9000           ┌────────┴────────┐
                                                                       │ LiteOn FlexFi   │
                                                                       │ gestão          │
                                                                       │ 10.101.131.59   │
                                                                       └────────┬────────┘
                                                                                │ n78
                                                                          celulares / modems
```

- **Só N2 (AMF) e N3 (UPF) saem do cluster**, cada um com IP fixo na fibra (Multus + macvlan sobre
  `enp5s0f1`). O resto (SBI, N4/PFCP) fica na rede dos pods.
- **N6 (internet):** o UPF faz NAT dos IPs dos UEs e sai pela rota padrão do torre2.
- **Os dois cores podem ficar instalados juntos** (IPs e pools diferentes), mas **só um fica ligado**: o gNB
  OCUDU aponta para um AMF de cada vez (um `.yml` por core).
- O painel lê o gNB à distância: métricas pelo WebSocket do OCUDU e log por SSH (só leitura). Nada do painel é
  instalado no innovaserver além do serviço `ocudu-gnb@`.

Detalhes do core: [docs/arquitetura.md](docs/arquitetura.md). Rádio: [docs/ran-ocudu-liteon.md](docs/ran-ocudu-liteon.md).

## 3. Endereços e portas

| O quê | Open5GS (padrão) | free5GC (opcional) |
|---|---|---|
| AMF (N2, SCTP 38412) | `10.10.0.10` | `10.10.0.30` |
| UPF (N3, GTP-U 2152) | `10.10.0.11` | `10.10.0.31` |
| gNB UERANSIM na fibra | `10.10.0.20` | `10.10.0.32` |
| Pools dos UEs | `internet` 10.45/16 · `internet2` 10.46/16 | `internet` 10.60/16 · `internet2` 10.61/16 · `ims` 10.62/16 |
| Nome da rede no celular | `InnovaOpen5GS` | `InnovaFree5GC` |
| Cadastro de assinantes | WebUI `:30999` | WebConsole `:31000` |
| `.yml` do gNB OCUDU | `gnb_ru_liteon_SLPIT_CORE.yml` | `gnb_ru_liteon_FREE5GC.yml` |

| Comum | Valor |
|---|---|
| PLMN / TAC | `001-01` / `1` |
| Slices | SST 1 / SD 111111 (`internet`) · SST 2 / SD 222222 (`internet2`) |
| Fibra N2/N3 | `10.10.0.0/24`, MTU 9000 — torre2 `10.10.0.2` (`enp5s0f1`), innovaserver `10.10.0.1` |
| Painel | `http://<IP do torre2>:30998` |
| Gestão da RU | `10.101.131.59` (o torre2 ganha `10.101.131.10/24` na mesma rede) |
| Nó do k3s | `10.254.254.1` na interface `k3s0` (não depende do IP da universidade) |

> Os IPs da rede da universidade vêm por **DHCP** e mudam após um reboot (ex.: torre2 `191.4.205.77`,
> innovaserver `191.4.205.80` em 2026-10-26). Nada no projeto depende deles: o cluster usa `k3s0` e a fibra
> tem IPs fixos. Só os atalhos de SSH de quem acessa de fora precisam ser atualizados.

## 4. Instalação

Ordem para montar do zero. Comandos com `sudo` mexem no sistema; os outros rodam como usuário comum.

### 4.1 torre2 — core Open5GS, UERANSIM e painel (padrão)

```bash
cd ~/InnovaNetwork
nano config.env          # PLMN, slices, fibra, gNB, painel… (comentado linha a linha)
sudo ./install.sh        # idempotente: k3s, Multus, Open5GS, UERANSIM, assinantes, painel, units de boot
./test.sh                # pods, NRF, NG Setup, registro, sessão PDU e ping (7 verificações)
```

- `sudo ./install.sh --deploy-only` reaplica só o core/UERANSIM (sem mexer em pacotes nem no k3s).
- `sudo ./install.sh --dashboard-only` reinstala só o painel (não toca no core nem no gNB).
- A senha de administrador do painel aparece no fim do install (também em
  `sudo cat /opt/open5gs-k3s/state/dashboard-admin-password`).
- Tudo sobre o core Open5GS e o `config.env`: [docs/open5gs-core.md](docs/open5gs-core.md).

### 4.2 torre2 — free5GC (opcional)

```bash
sudo ./free5gc/setup-gtp5g.sh           # módulo do kernel do UPF (uma vez; v0.10.2)
./free5gc/install.sh                    # sem sudo; instala no namespace free5gc
./free5gc/install.sh --importar-open5gs # copia os SIMs cadastrados no Open5GS
./free5gc/test.sh                       # 6 verificações
sudo ./install.sh --dashboard-only      # o painel passa a mostrar a troca de core
```

Detalhes: [free5gc/README.md](free5gc/README.md).

### 4.3 innovaserver — gNB OCUDU

O OCUDU roda direto no host (CPU dedicada, DPDK, PTP). A preparação da máquina (DPDK, XDP, PTP) é feita por
serviços de boot da própria máquina, descritos em [docs/ran-ocudu-liteon.md](docs/ran-ocudu-liteon.md). Para o painel poder iniciar e parar o gNB, uma vez:

```bash
scp scripts/ocudu/setup-gnb-service.sh innovaserver@10.10.0.1:/tmp/
ssh -t innovaserver@10.10.0.1 sudo bash /tmp/setup-gnb-service.sh
```

## 5. Uso no dia a dia

Depois de um boot **só o painel sobe** (`CORE_AUTOSTART=false`); o resto começa pelo painel:

1. Abra `http://<IP do torre2>:30998` e clique em **🔒 Admin** (topo) — um login vale para todas as abas.
2. Aba **Controle** → confira o **Core ativo** → **▶ Iniciar tudo** (sobe o core em ordem e confere cada etapa).
3. No cartão **gNB OCUDU**, escolha o `.yml` do core ativo e inicie (o innovaserver já se prepara sozinho no boot).
4. Confira: aba **RU** "DU conectado", aba **Core** com o gNB no AMF, celulares na **Visão geral**.

Trocar de core, parar tudo, testar, cadastrar SIMs e resolver problemas: [docs/operacao.md](docs/operacao.md).

## 6. Documentação

Toda a documentação também aparece no painel, na aba **Documentação** (lida da pasta do projeto).

| Documento | Conteúdo |
|---|---|
| [docs/operacao.md](docs/operacao.md) | **Comece aqui para operar:** boot, iniciar, trocar de core, gNB, testes, SIMs, problemas comuns |
| [docs/guia-do-codigo.md](docs/guia-do-codigo.md) | **Para entender e mostrar:** onde cada coisa está no código e roteiros de demonstração |
| [docs/ran-ocudu-liteon.md](docs/ran-ocudu-liteon.md) | Rádio: innovaserver, OCUDU, LiteOn, fibra, `.yml` por core |
| [docs/open5gs-core.md](docs/open5gs-core.md) | Core Open5GS: install, `config.env`, operação, modificação, testes, desinstalação |
| [free5gc/README.md](free5gc/README.md) | Core free5GC: instalação, assinantes, celulares, limitações |
| [docs/dashboard.md](docs/dashboard.md) | Painel: abas, instalação, configuração, API |
| [docs/arquitetura.md](docs/arquitetura.md) | Funções de rede, interfaces 3GPP, fluxo de registro, rede do Kubernetes |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Problemas encontrados e como foram resolvidos |
| [docs/decisoes.md](docs/decisoes.md) | Decisões técnicas, estado atual e histórico |

## 7. Estrutura do repositório

| Caminho | Função |
|---|---|
| `config.env` | Configuração única do projeto (core Open5GS, fibra, gNB, RU, painel) |
| `install.sh` / `uninstall.sh` / `test.sh` | Instalar (idempotente), remover em níveis, testar o Open5GS |
| `free5gc/` | Segundo core (opcional): `free5gc.env`, instalador, teste, gerador de manifestos |
| `dashboard/app/` | Painel (Python só com biblioteca padrão + HTML/JS sem dependências externas) |
| `dashboard/agent/` | Agentes da máquina do core: log do gNB, controle do gNB, RU, outras máquinas |
| `scripts/lib/common.sh` | Biblioteca do instalador (validação, geração dos values Helm, painel) |
| `scripts/heal.sh` | Boot: deixa os cores parados (`--boot-off`) ou recupera o plano de usuário |
| `scripts/subscribers.sh` | Assinantes do Open5GS (sync/list/add/remove) |
| `scripts/ocudu/setup-gnb-service.sh` | Serviço `ocudu-gnb@` + permissão (polkit) no host do gNB |
| `helm/` | Multus, post-renderers dos charts e values gerados (`helm/generated/`, fora do git) |
| `docs/` | Documentação |

## 8. Versões

| Tag / branch | O que é |
|---|---|
| `v1.0-ueransim` (branch `main`) | **Open5GK3S**: só o core Open5GS em k3s com UERANSIM (setor 1, congelado) |
| `v1.0-dashboard` … `v1.4-dashboard` | Evolução do painel com OCUDU + Open5GS; `v1.4` é a referência estável de um core |
| `v2.0-innovanetwork` (branch `innovanetwork`) | **InnovaNetwork**: dois cores (Open5GS padrão, free5GC opcional), troca pelo painel, login único, aba Documentação |

## 9. Limitações conhecidas

- **free5GC, slice 2:** celular que pede sessão sem informar a slice cai sempre na 1ª slice permitida
  (comportamento do AMF do free5GC). Slice 2 só com UE que informa a S-NSSAI. No Open5GS funciona.
- **gNB não reconecta sozinho** se o AMF reiniciar: reinicie o gNB pela aba Controle (a troca de core já faz isso).
- **Um core por vez** no rádio; trocar derruba quem estiver conectado (~1 a 5 min).
- A preparação do innovaserver (DPDK, XDP `ptp-trim.o`, PTP) é dos serviços da máquina; o painel só
  inicia/para o gNB e mostra se o PTP e a VF estão ok.
- Os nomes técnicos instalados (`open5gs-k3s-*`, `/opt/open5gs-k3s`) ainda são os do projeto original; migram
  numa janela combinada.

## 10. Regras do projeto

- Documentação e comunicação em **português**.
- Toda decisão nova ou alterada vai para [docs/decisoes.md](docs/decisoes.md).
- O **torre2 é o ambiente principal**: edita-se lá e o git vai do servidor para o GitHub.
- Senhas e chaves (SIMs, RU, painel) **nunca** no git.
- O OCUDU **não** roda em container nem no k3s.
