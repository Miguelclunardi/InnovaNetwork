# Documentação do InnovaNetwork

> 🇬🇧 [English version](README.md)

Comece pelo seu objetivo:

| Quero… | Leia |
|---|---|
| entender o que é e como as peças se encaixam | [Arquitetura](architecture.pt-BR.md) |
| testar o core em uma máquina, sem rádio | [Tutorial 1 — Primeiro teste com UERANSIM](tutorials/01-first-test-ueransim.pt-BR.md) |
| montar a rede completa com rádio real | [Instalação](installation.pt-BR.md) |
| operar a rede no dia a dia | [Operação](operation.pt-BR.md) |
| resolver um problema | [Solução de problemas](troubleshooting.pt-BR.md) |
| mudar ou estender o código | [Desenvolvimento](development.pt-BR.md) |

## Guias

| Documento | Conteúdo |
|---|---|
| [arquitetura.md](architecture.pt-BR.md) | máquinas e papéis, componentes, redes (cluster, fibra, fronthaul), IPs, portas, pastas, fluxo de uma chamada |
| [instalacao.md](installation.pt-BR.md) | requisitos e ordem de instalação: core e painel → free5GC (opcional) → OCUDU em Kubernetes |
| [operacao.md](operation.pt-BR.md) | depois do boot, ligar/parar, trocar de core, assinantes, mudar configuração, testes |
| [troubleshooting.md](troubleshooting.pt-BR.md) | problemas conhecidos de cluster, core, rádio e painel, com causa e solução |
| [desenvolvimento.md](development.pt-BR.md) | mapa do código, caminho de uma configuração, como estender cores, gNB e painel |

## Componentes

| Documento | Conteúdo |
|---|---|
| [componentes/open5gs.md](components/open5gs.pt-BR.md) | core padrão: funções, instalador, referência do `config.env`, PLMN, slices, assinantes, versões |
| [componentes/free5gc.md](components/free5gc.pt-BR.md) | core opcional: instalação, assinantes, celulares, limitações |
| [componentes/ueransim.md](components/ueransim.pt-BR.md) | gNB e UE simulados: como são instalados, `nr-cli`, testes |
| [componentes/ocudu.md](components/ocudu.pt-BR.md) | gNB real em Kubernetes: imagem, nó do RAN, Deployment, `.yml` por core, proteção de boot |
| [componentes/painel.md](components/dashboard.pt-BR.md) | Innova Center Dashboard: abas, configuração, agentes, histórico, API |
| [hardware/e810-liteon.md](hardware/e810-liteon.pt-BR.md) | perfil de referência: Intel E810, PTP/GNSS, DPDK, XDP, O-RU LiteOn, célula n78 |

## Tutoriais

Passo a passo, do começo ao fim, com o resultado esperado em cada etapa.

| # | Tutorial | Tempo |
|---|---|---|
| 1 | [Primeiro teste com UERANSIM](tutorials/01-first-test-ueransim.pt-BR.md) — instalar o core e ver um UE navegando | 20 min |
| 2 | [Conhecer o painel](tutorials/02-dashboard-tour.pt-BR.md) — login, abas e o que cada uma mostra | 15 min |
| 3 | [OCUDU em Kubernetes](tutorials/03-ocudu-on-kubernetes.pt-BR.md) — imagem, nó do RAN e gNB como pod | 1 h |
| 4 | [Celular na rede](tutorials/04-phone-on-the-network.pt-BR.md) — cadastrar o SIM, ligar o gNB e conectar | 20 min |
| 5 | [Trocar de core](tutorials/05-switch-core.pt-BR.md) — instalar o free5GC e alternar pelo painel | 30 min |
| 6 | [Mudar PLMN, slices e IPs](tutorials/06-change-configuration.pt-BR.md) — editar e aplicar a configuração | 15 min |
| 7 | [Alterar o gNB](tutorials/07-change-the-gnb.pt-BR.md) — editar o `.yml` ou recompilar o OCUDU | 30 min |
| 8 | [Gravar e comparar experimentos](tutorials/08-experiments.pt-BR.md) — medir dois setups no painel | 20 min |

## Convenções

- **Máquina do core** = servidor do k3s (no setup de referência, `torre2`). **Máquina do RAN** = nó do k3s com o
  rádio (no setup de referência, `innovaserver`). Cada comando diz em qual máquina roda.
- `sudo` só onde indicado. Os demais comandos rodam como usuário comum, dentro da pasta do repositório.
- Valores de exemplo (IPs, nomes de interface, `.yml`) são os do setup de referência; ajuste aos seus.
