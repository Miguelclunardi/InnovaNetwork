# Histórico de versões

> 🇬🇧 [English version](CHANGELOG.md)

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/). Cada versão tem uma tag no Git.

## [Não lançado]

### Alterado
- **Tudo em inglês:** documentação, comandos, saída dos scripts e comentários do código. Cada documento mantém
  uma tradução em português (`*.pt-BR.md`). Documentos renomeados para caminhos em inglês (`docs/architecture.md`,
  `docs/components/`, `docs/tutorials/`…).
- **Painel em inglês ou português:** botão EN/PT no topo (ou `?lang=pt` / `?lang=en`); traduções em
  `dashboard/i18n/pt.json`. A aba Documentação abre a versão `*.pt-BR.md` no modo português.
- `ran/ocudu/gnb.sh`: comandos `start`/`stop`/`status` (`iniciar`/`parar`/`estado` continuam funcionando).
- Os códigos de estado da API do painel estão em inglês (`running`/`stopped`/`starting`/`stopping`; GPS
  `locked`/`searching`/`adjusting`/`unlocked`/`stalled`; UE `registered`/`deregistered`).
- Nomes de opções em inglês, com os nomes em português mantidos como apelidos: `free5gc/install.sh --subscribers`,
  `--import-open5gs`, `--stopped`, `--no-ueransim`; `ran/ocudu/install.sh copy|prepare|--remove`;
  `ran/ocudu/no-ran.sh image|import|join|leave|status`. Os prefixos dos scripts passam a ser `[warn]` e `[error]`.
- Os hashes dos values do Open5GS e do UERANSIM ignoram comentários: editar um comentário não recria mais os pods.
  **Uma vez**, no primeiro `--deploy-only` depois desta mudança, o core e os UEs são recriados (fórmula nova do
  hash) — rode numa janela sem usuários.
- O `install.sh` não reinicia mais o k3s quando só mudam comentários do arquivo de configuração dele.
- O texto do script do pod do gNB mudou (mensagem de boot em inglês): o próximo `./ran/ocudu/install.sh` recria o
  pod do gNB.

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
