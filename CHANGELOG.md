# Histórico de versões

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/). Cada versão tem uma tag no Git.

## [3.0] — 2026-10-28 · tag `v3.0-innovanetwork`

### Adicionado
- **gNB OCUDU em Kubernetes** (`ran/ocudu/`): imagem compilada do commit do OCUDU com o Dockerfile oficial;
  máquina do RAN entra no cluster como nó dedicado (rótulo e taint); Deployment com rede do host, DPDK e
  hugepages; `gnb.sh` para iniciar/parar/ver logs.
- **Proteção de boot do gNB:** depois de um reboot do nó, o gNB não liga sozinho (espera o operador, depois do GNSS).
- **Painel controla o gNB pelo Kubernetes** (`GNB_CTL_MODE=k8s`): cartão "gNB (Kubernetes)", troca de core religa o
  pod no AMF certo.
- Documentação nova: arquitetura, instalação, operação, componentes, hardware de referência, 8 tutoriais,
  solução de problemas e guia de desenvolvimento. Licença Apache-2.0, `CONTRIBUTING.md`.

### Alterado
- O gNB OCUDU deixa de rodar como serviço systemd do host (modo `systemd` continua disponível como legado).

### Validado
- Open5GS e free5GC com celulares comerciais pelo gNB no Kubernetes; fronthaul ~92 % no tempo (igual ao nativo);
  reboot do nó do RAN com retorno automático ao cluster.

## [2.1] — 2026-10-26 · `v2.1-innovanetwork`
- Estado de referência com dois cores e o gNB nativo; lições do rádio (GNSS/PTP, XDP).

## [2.0] — 2026-10-26 · `v2.0-innovanetwork`
- **Dois cores:** free5GC v4.3.0 opcional ao lado do Open5GS; troca do core ativo pelo painel, religando o gNB.
- Login único de administrador; aba Documentação.

## [1.0 – 1.4] — 2026-10-21 a 22 · `v1.0-ueransim`, `v1.0-dashboard` … `v1.4-dashboard`
- Core Open5GS em k3s com UERANSIM, instalador idempotente, `config.env`, teste ponta a ponta.
- Painel *Innova Center Dashboard*: rádio, core, logs, RU, máquinas, controle, configuração, histórico e
  experimentos.
- Ligação com o gNB OCUDU real pela fibra (Multus/macvlan para N2/N3).
