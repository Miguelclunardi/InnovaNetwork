<p align="center">
  <img src="dashboard/app/logo.svg" alt="InnovaNetwork" width="120">
</p>

<h1 align="center">InnovaNetwork</h1>

<p align="center">
  <b>Rede 5G Standalone completa em Kubernetes</b><br>
  core 5G (Open5GS ou free5GC) · gNB real OCUDU (O-RAN split 7.2) · UERANSIM · painel web de operação e medição
</p>

<p align="center">
  <img alt="versão" src="https://img.shields.io/badge/vers%C3%A3o-3.0-1f6feb">
  <img alt="licença" src="https://img.shields.io/badge/licen%C3%A7a-Apache--2.0-blue">
  <img alt="kubernetes" src="https://img.shields.io/badge/k3s-v1.36-326ce5">
  <img alt="5G SA" src="https://img.shields.io/badge/5G-Standalone-555">
</p>

---

O **InnovaNetwork** monta e opera uma rede 5G SA de laboratório **inteiramente em Kubernetes (k3s)**: o core,
o gNB de rádio real, o gNB/UE simulados e o painel rodam como pods de um único cluster, configurados a partir de
arquivos de texto e instalados por scripts idempotentes.

Foi construído e validado no **Centro Innova** com celulares comerciais, uma O-RU **LiteOn FlexFi** (n78, 4T4R)
e uma placa **Intel E810**, mas foi pensado para ser **replicável**: tudo o que depende do hardware fica isolado
e documentado.

## Destaques

- **Tudo em Kubernetes.** Core, gNB OCUDU, UERANSIM e painel no mesmo cluster k3s, com duas máquinas: uma para o
  core e uma (nó dedicado) para o rádio.
- **Dois cores, um por vez.** **Open5GS** (padrão) e **free5GC** (opcional) instalados lado a lado; a troca é um
  clique no painel.
- **Rádio real.** gNB **OCUDU** (CU+DU, split 7.2, DPDK) como pod, com a mesma performance do serviço nativo
  (~92 % dos pacotes do fronthaul no tempo).
- **Painel de operação.** *Innova Center Dashboard*: métricas de rádio por UE, core, RU, máquinas, logs, controle
  (iniciar/parar/trocar core), edição da configuração, histórico persistente e experimentos comparáveis.
- **Configuração em texto, nada fixo no código.** PLMN, slices, IPs, versões e o setup do rádio vêm de
  `config.env`, `free5gc/free5gc.env` e `ran/ocudu/ocudu.env`.
- **Seguro após reboot.** Depois de um boot nada de rádio liga sozinho (o GPS pode levar minutos): o operador
  liga pelo painel quando o sincronismo estiver pronto.

## Arquitetura

```
                       máquina do CORE (servidor k3s)                       máquina do RAN (nó k3s)
            ┌────────────────────────────────────────────────┐     ┌──────────────────────────────────┐
            │ ns open5gs          ns free5gc (opcional)      │     │ ns ocudu                         │
            │  Open5GS  AMF ─┐     free5GC  AMF ─┐           │     │  pod ocudu-gnb (OCUDU CU+DU)     │
 internet ◄─┤  (N6/NAT) UPF ─┤              UPF ─┤           │     │   rede do host, DPDK, PTP        │
            │  UERANSIM      │     UERANSIM      │           │     │                                  │
            │  painel :30998 │                   │           │     │  E810 ── fronthaul 7.2 ──┐       │
            │        macvlan "ran-link" (N2/N3)  │           │     └──────────┬───────────────┼───────┘
            └────────────────────┬───────────────┴───────────┘                │               │
                                 └────────── fibra N2/N3 + cluster ───────────┘        ┌──────┴──────┐
                                             10.10.0.0/24                              │  O-RU (n78) │ ))) celulares
                                                                                       └─────────────┘
```

Detalhes, IPs, portas e pastas: **[docs/arquitetura.md](docs/arquitetura.md)**.

## Componentes

| Componente | Versão | Onde roda | Documentação |
|---|---|---|---|
| **Open5GS** (core padrão) | 2.7.5 | namespace `open5gs` | [componentes/open5gs.md](docs/componentes/open5gs.md) |
| **free5GC** (core opcional) | v4.3.0 | namespace `free5gc` | [componentes/free5gc.md](docs/componentes/free5gc.md) |
| **UERANSIM** (gNB/UE simulados) | 3.2.6 | um par por core | [componentes/ueransim.md](docs/componentes/ueransim.md) |
| **OCUDU** (gNB real) | commit fixo do usuário | namespace `ocudu`, nó do RAN | [componentes/ocudu.md](docs/componentes/ocudu.md) |
| **Innova Center Dashboard** | 3.0 | namespace `open5gs`, porta 30998 | [componentes/painel.md](docs/componentes/painel.md) |
| **k3s** + Multus | v1.36.5+k3s1 | as duas máquinas | [arquitetura.md](docs/arquitetura.md) |

## Início rápido

**Só o core com UE simulado** (uma máquina Ubuntu 24.04, sem rádio), em ~15 minutos:

```bash
git clone https://github.com/Miguelclunardi/InnovaNetwork.git
cd InnovaNetwork
sudo ./install.sh        # k3s, Open5GS, UERANSIM e painel (idempotente)
./test.sh                # registro, sessão PDU e ping pelo core: "7 verificações OK"
```

Abra o painel em `http://<IP da máquina>:30998`.

Rede completa com rádio real: siga a **[instalação](docs/instalacao.md)**.

## Documentação

| | |
|---|---|
| 🧭 **[Visão geral da documentação](docs/README.md)** | por onde começar, conforme o seu objetivo |
| 🏗️ **[Arquitetura](docs/arquitetura.md)** | máquinas, componentes, redes, IPs, portas e pastas |
| ⚙️ **[Instalação](docs/instalacao.md)** | do zero até o celular navegando |
| 🕹️ **[Operação](docs/operacao.md)** | o dia a dia: ligar, trocar de core, reboot, testes |
| 🎓 **[Tutoriais](docs/README.md#tutoriais)** | passo a passo: primeiro teste, celular na rede, troca de core, OCUDU em k8s, experimentos… |
| 🧩 **Componentes** | [Open5GS](docs/componentes/open5gs.md) · [free5GC](docs/componentes/free5gc.md) · [UERANSIM](docs/componentes/ueransim.md) · [OCUDU](docs/componentes/ocudu.md) · [Painel](docs/componentes/painel.md) |
| 🔧 **[Hardware de referência](docs/hardware/e810-liteon.md)** | Intel E810 + LiteOn FlexFi: PTP/GNSS, DPDK, XDP, célula n78 |
| 🩺 **[Solução de problemas](docs/troubleshooting.md)** | sintomas → causa → solução |
| 🛠️ **[Desenvolvimento](docs/desenvolvimento.md)** | mapa do código e como estender |

A mesma documentação aparece no painel, na aba **Documentação**.

## Estrutura do repositório

```
InnovaNetwork/
├── install.sh · uninstall.sh · test.sh   # core Open5GS + UERANSIM + painel (máquina do core)
├── config.env                            # configuração principal
├── free5gc/                              # core free5GC opcional (instalador próprio)
├── ran/ocudu/                            # gNB OCUDU em Kubernetes (instalador próprio, depende do setup)
├── dashboard/                            # painel (app/) e agentes da máquina do core (agent/)
├── scripts/                              # biblioteca do instalador, recuperação no boot, assinantes
├── helm/                                 # Multus e post-renderers dos charts
└── docs/                                 # documentação
```

## Requisitos

| | Máquina do core | Máquina do RAN (opcional) |
|---|---|---|
| SO | Ubuntu 24.04 LTS | Ubuntu 24.04 LTS, kernel de baixa latência |
| CPU / RAM | 4+ vCPU com AVX · 8 GiB | CPUs isoladas para o gNB · hugepages de 1 GiB |
| Rede | internet; porta dedicada para a fibra N2/N3 | NIC com SR-IOV/DPDK e PTP (ex.: Intel E810) + GNSS |
| Rádio | — | O-RU O-RAN 7.2 (ex.: LiteOn FlexFi) |

## Versões

| Versão | Conteúdo |
|---|---|
| **v3.0** | OCUDU em Kubernetes (nó dedicado), painel controlando o gNB pelo Kubernetes, documentação nova |
| v2.x | dois cores (Open5GS + free5GC), troca pelo painel |
| v1.x | core Open5GS em k3s com UERANSIM; painel |

Histórico completo: [CHANGELOG.md](CHANGELOG.md).

## Contribuir

Contribuições são bem-vindas: novos perfis de hardware, correções e documentação. Veja
[CONTRIBUTING.md](CONTRIBUTING.md).

## Licença

[Apache License 2.0](LICENSE). Os projetos usados (Open5GS, free5GC, UERANSIM, OCUDU, k3s, charts da Gradiant,
uPlot) mantêm as suas próprias licenças.

> **Uso responsável:** use PLMN de teste (`001-01`) e respeite a regulamentação de espectro da sua região ao
> transmitir com rádio real.
