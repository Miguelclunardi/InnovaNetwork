# Documentação do InnovaNetwork

Comece pelo seu objetivo:

| Quero… | Leia |
|---|---|
| entender o que é e como as peças se encaixam | [Arquitetura](arquitetura.md) |
| testar o core em uma máquina, sem rádio | [Tutorial 1 — Primeiro teste com UERANSIM](tutoriais/01-primeiro-teste-ueransim.md) |
| montar a rede completa com rádio real | [Instalação](instalacao.md) |
| operar a rede no dia a dia | [Operação](operacao.md) |
| resolver um problema | [Solução de problemas](troubleshooting.md) |
| mudar ou estender o código | [Desenvolvimento](desenvolvimento.md) |

## Guias

| Documento | Conteúdo |
|---|---|
| [arquitetura.md](arquitetura.md) | máquinas e papéis, componentes, redes (cluster, fibra, fronthaul), IPs, portas, pastas, fluxo de uma chamada |
| [instalacao.md](instalacao.md) | requisitos e ordem de instalação: core e painel → free5GC (opcional) → OCUDU em Kubernetes |
| [operacao.md](operacao.md) | depois do boot, ligar/parar, trocar de core, assinantes, mudar configuração, testes |
| [troubleshooting.md](troubleshooting.md) | problemas conhecidos de cluster, core, rádio e painel, com causa e solução |
| [desenvolvimento.md](desenvolvimento.md) | mapa do código, caminho de uma configuração, como estender cores, gNB e painel |

## Componentes

| Documento | Conteúdo |
|---|---|
| [componentes/open5gs.md](componentes/open5gs.md) | core padrão: funções, instalador, referência do `config.env`, PLMN, slices, assinantes, versões |
| [componentes/free5gc.md](componentes/free5gc.md) | core opcional: instalação, assinantes, celulares, limitações |
| [componentes/ueransim.md](componentes/ueransim.md) | gNB e UE simulados: como são instalados, `nr-cli`, testes |
| [componentes/ocudu.md](componentes/ocudu.md) | gNB real em Kubernetes: imagem, nó do RAN, Deployment, `.yml` por core, proteção de boot |
| [componentes/painel.md](componentes/painel.md) | Innova Center Dashboard: abas, configuração, agentes, histórico, API |
| [hardware/e810-liteon.md](hardware/e810-liteon.md) | perfil de referência: Intel E810, PTP/GNSS, DPDK, XDP, O-RU LiteOn, célula n78 |

## Tutoriais

Passo a passo, do começo ao fim, com o resultado esperado em cada etapa.

| # | Tutorial | Tempo |
|---|---|---|
| 1 | [Primeiro teste com UERANSIM](tutoriais/01-primeiro-teste-ueransim.md) — instalar o core e ver um UE navegando | 20 min |
| 2 | [Conhecer o painel](tutoriais/02-conhecer-o-painel.md) — login, abas e o que cada uma mostra | 15 min |
| 3 | [OCUDU em Kubernetes](tutoriais/03-ocudu-em-kubernetes.md) — imagem, nó do RAN e gNB como pod | 1 h |
| 4 | [Celular na rede](tutoriais/04-celular-na-rede.md) — cadastrar o SIM, ligar o gNB e conectar | 20 min |
| 5 | [Trocar de core](tutoriais/05-trocar-de-core.md) — instalar o free5GC e alternar pelo painel | 30 min |
| 6 | [Mudar PLMN, slices e IPs](tutoriais/06-mudar-configuracao.md) — editar e aplicar a configuração | 15 min |
| 7 | [Alterar o gNB](tutoriais/07-alterar-o-gnb.md) — editar o `.yml` ou recompilar o OCUDU | 30 min |
| 8 | [Gravar e comparar experimentos](tutoriais/08-experimentos.md) — medir dois setups no painel | 20 min |

## Convenções

- **Máquina do core** = servidor do k3s (no setup de referência, `torre2`). **Máquina do RAN** = nó do k3s com o
  rádio (no setup de referência, `innovaserver`). Cada comando diz em qual máquina roda.
- `sudo` só onde indicado. Os demais comandos rodam como usuário comum, dentro da pasta do repositório.
- Valores de exemplo (IPs, nomes de interface, `.yml`) são os do setup de referência; ajuste aos seus.
