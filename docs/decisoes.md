# Decisões técnicas, estado e próximos passos — open5GK3S

Core 5G **Open5GS** em Kubernetes (**k3s**) num único nó Ubuntu 24.04, validado com **UERANSIM**.
Próxima fase: RAN real com **OCUDU** + O-RU **LiteOn**.
Documentação do projeto: **português**.

> Regra do projeto: **sempre atualizar este arquivo** quando uma decisão nova for tomada
> ou uma existente mudar (seções "Decisões", "Estado atual" e "Histórico").

## Estado atual (2026-10-19, fim do dia)

- **Funcionando** no desktop de dev: `./test.sh` → **7/7 OK** (16 pods, 9 NFs no NRF, NG Setup, UE `001010000000001`
  registrado, PDU `10.45.0.2`, ping ao UPF `10.45.0.1` e a `8.8.8.8` pela `uesimtun0`).
- `kubectl` funciona **sem sudo** para o usuário `lunardi` (`~/.kube/config`, contexto `open5gs-k3s`; backup do config
  vazio antigo em `~/.kube/config.bak-20261019`). Alias `k` + autocomplete no `~/.bashrc` (bloco com marcadores).
- HPA bugado do gNB removido do cluster (post-renderer aplicado no release `ueransim`).
- Projeto reorganizado (ver Estrutura). Repositório **privado** no GitHub: https://github.com/Miguelclunardi/open5GK3S (branch `main`).
- **Atenção**: as últimas correções (NRF servingList, Recreate, post-renderer, firewalld, kubeconfig 0600) foram aplicadas no
  cluster **sem root** (helm do scratchpad, `INSTALL_DIR` temporário). O `/opt/open5gs-k3s` tem o clone de charts
  feito pelo `sudo ./install.sh` do usuário. Rodar `sudo ./install.sh` uma vez deixa tudo consistente pelo caminho oficial
  (sem mudança de config ⇒ nenhum pod reinicia, exceto se o hash mudar).
- Nó do k3s em `k3s0`/10.254.254.1 (decisão 27), validado com troca cabo→Wi‑Fi e com reboot.
- Recuperação automática no boot (decisão 28): `heal.sh` validado (recuperou o 5/7 pós-reboot para 7/7).

## Próximos passos

1. `sudo ./install.sh` (consolidar pelo caminho oficial **e** migrar o nó para `k3s0`; conferir `logs/install.log`) e `./test.sh`.
2. Manter o GitHub em dia: commitar e `git push` a cada mudança (`gh` em `~/.local/bin`, conta `Miguelclunardi`).
3. **Ubuntu Server `torre2`: migrado e validado em 2026-10-20** (`./test.sh` 7/7, ping 8.8.8.8 a ~19 ms; units netif e heal habilitadas):
   - acesso do desktop por SSH com chave: `Host torre2` em `~/.ssh/config` (usuário `torre2`; IP por DHCP,
     hoje 191.4.205.114 — atualizar `HostName` quando mudar);
   - **o servidor é o ambiente principal** (decisão do usuário, 2026-10-20): edita-se direto em `torre2:~/open5GK3S`,
     aplica-se com `sudo ./install.sh`, testa-se com `./test.sh` e **o git vai do servidor para o GitHub**
     (`git commit` + `git push` no servidor). O clone do desktop vira cópia: `git pull` antes de mexer nele;
   - push pelo servidor com **deploy key de leitura e escrita** só deste repositório (`~/.ssh/github-open5gk3s`,
     `Host github-open5gk3s`; título "torre2 (leitura e escrita)" no GitHub), sem login do GitHub no servidor;
     identidade do git configurada só no clone (`git config user.name/user.email`). Risco aceito: quem usar a conta
     `torre2` pode fazer push neste repositório;
   - o servidor tinha um k3s manual (v1.36.5, kubeconfig 644) com uma tentativa antiga do Open5GS quebrada:
     removido com `k3s-uninstall.sh` (autorizado pelo usuário) antes do `sudo ./install.sh`;
   - o assistente de IA fica no desktop e opera o servidor por SSH (`ssh torre2`); comandos com sudo no servidor
     são rodados pelo usuário (`ssh -t torre2 'sudo …'`).
4. **Painel (Innova Center Dashboard) no ar desde 2026-10-21 19:12 UTC** em http://191.4.205.17:30998 (decisão 32;
   `sudo ./install.sh --dashboard-only`, core sem reinício). **v1.0 em 2026-10-21**: chave SSH torre2 → innovaserver
   feita, log do gNB (`GNB_LOG_SSH`), aba Máquinas, aba Configuração, UEs do rádio por nome/IMSI/IP. Pendentes:
   medidor de energia atrás do NAT do Wi‑Fi (docs/dashboard.md, "Energia"); `OPEN5GS_METRICS=true` numa janela
   livre (reinicia o core); `/tmp/gnb.log` do OCUDU com 9 GB (rotacionar).
5. Fase RAN real: **OCUDU** (CU/DU) + **LiteOn** (O-RU) — validar `EXPOSE_RAN` com SCTP real ou migrar N2/N3 para
   Multus/macvlan/SR-IOV; alinhar PLMN/TAC/S-NSSAI; cadastrar SIMs em `SUBSCRIBERS`; preparar host do DU (PTP, fronthaul).

## Estrutura

| Caminho | Função |
|---|---|
| `install.sh` | Idempotente: deps, SCTP, sysctl, firewall, k3s, Helm, charts, Open5GS, assinantes, UERANSIM, kubeconfig do usuário. Log automático em `logs/install.log`. `--deploy-only`. |
| `test.sh` | Pods → NRF → NG Setup → registro → PDU → ping (gateway UPF e internet). Exit 0/1. |
| `uninstall.sh` | Padrão (releases/PVC/ns), `--k3s` (+ k3s + contexto kubeconfig), `--purge` (+ sistema, firewall, `/opt`, bashrc). |
| `config.env` | Única fonte de parâmetros. Nada fixo no código. |
| `scripts/lib/common.sh` | Biblioteca: log, `load_config`, `validate_config`, `detect_env`, render de values, assinantes, kubeconfig/bashrc do usuário. `PROJECT_DIR` = `../..` dela. |
| `scripts/heal.sh` | Recupera o plano de usuário (UEs → UPF/SMF/gNB/UEs). Manual ou `--boot` (unit `open5gs-k3s-heal`, cópia root em `/opt/open5gs-k3s/heal`). |
| `scripts/subscribers.sh` | sync/list/add/remove/reset via `open5gs-dbctl` no pod populate. |
| `helm/postrender/drop-gnb-hpa.sh` | Post-renderer que remove o HPA do chart `ueransim-gnb`. |
| `helm/generated/` | Values gerados (gitignored). |
| `docs/arquitetura.md`, `docs/troubleshooting.md`, `docs/decisoes.md` | Documentação detalhada; este arquivo é o `decisoes.md`. |
| `logs/` | `install.log` (gitignored). |

## Decisões

1. **k3s** single node; Traefik desabilitado; config em `/etc/rancher/k3s/config.yaml` (mudou ⇒ restart); versão fixa `K3S_VERSION` (v1.36.5+k3s1).
2. **Charts Gradiant via git em commit fixo** `3f998fb7c5221589957593cf7b046eabb8aecb55` (OCI parou na 2.2.6; git: open5gs 2.3.8/Open5GS 2.7.5, ueransim-gnb 0.2.6/UERANSIM 3.2.6). `helm dependency build` com repo `bitnami`.
3. **Só 5G SA**: base `values-5g.yaml` (sem 4G, SEPP off, `smf.config.pcrf.enabled=false`).
4. **free5GC/towards5gs só como referência** de arquitetura. Não misturar cores.
5. **Rede = flannel**, uma interface por pod. `EXPOSE_RAN=true` (experimental): AMF NGAP e UPF GTP-U como `LoadBalancer` (ServiceLB) + GTP-U anunciado com `NODE_IP`.
6. **Slices** `SLICES=("SST:SD:DNN:CIDR")`; 1ª é a do UERANSIM; SD obrigatório; uma TUN por DNN no UPF.
7. **TAC em decimal** (o template do gNB injeta cru).
8. **Assinantes** via `open5gs-dbctl` remove+add (idempotente); `populate.initCommands` vazio.
9. **MongoDB** Bitnami `latest` (8.x) ⇒ CPU com AVX; `MONGODB_IMAGE_*` para alternativa.
10. **kubeconfig explícito** nos scripts (`kc`/`hm`): root usa sempre `/etc/rancher/k3s/k3s.yaml` (mesmo antes de existir — numa instalação do zero ele só aparece depois do k3s subir), usuário usa `~/.kube/open5gs-k3s.yaml`.
11. **Desktop × Server** (`ENV_PROFILE=auto`; desktop = NetworkManager ativo ou `display-manager.service` — `graphical.target` sozinho não conta, o torre2 vem assim sem GUI): NM unmanaged, `linux-modules-extra`, UFW, firewalld, aviso Docker, interface pela rota default, Helm amd64/arm64.
12. **PLMN 001-01, TAC 1** (definido pelo usuário).
13. **UERANSIM**: `fullnameOverride=UERANSIM_RELEASE` ⇒ `ueransim` (gNB) e `ueransim-ues`; `amf.hostname=<release>-amf-ngap`.
14. **Reaplicar config**: anotação `open5gs-k3s/config-hash` nos pods (charts sem checksum de ConfigMap); hash do UERANSIM inclui o do core.
15. **Shell**: `set -Eeuo pipefail`; nunca `cond && ação` como último comando de função (usar `if`).
16. **k3s**: `kubelet-arg registry-qps=20/burst=40`; esperar coredns/local-path **existirem** antes do `rollout status`.
17. **firewalld** rejeita pod↔pod direto ⇒ `CLUSTER_CIDR`/`SERVICE_CIDR` na zona `trusted` (`CONFIGURE_FIREWALLD`).
18. **`/etc/rancher/k3s/k3s.yaml` em 0600** (0644 dava admin do cluster a qualquer usuário local).
19. **NRF `servingList` = PLMN do config** (chart vem com 999/70 ⇒ SCP tratava o UE como roaming: "No SEPP", HTTP 400).
20. **`updateStrategy: Recreate` em todos os NFs** (RollingUpdate deixava cache de NFs antigos por 24 h ⇒ "No route to host" no SCP).
21. **Corrida do UERANSIM** (UE preso em LIMITED-SERVICE/célula ACCEPTABLE): install espera NG Setup e reinicia o pod dos UEs uma vez se não registrar em 60 s.
22. **HPA do `ueransim-gnb`** aponta para StatefulSet inexistente (erro em loop no k3s) ⇒ removido por post-renderer `helm/postrender/drop-gnb-hpa.sh`. Exige **Helm 3** (Helm 4 mudou post-renderers para plugins) — o install instala o Helm 3 fixado se o do sistema não for v3.
23. **kubeconfig do usuário real** (`KUBECONFIG_USER` > `$SUDO_USER` > root): `~/.kube/config` criado se ausente/vazio, ou **merge** com nomes `open5gs-k3s` preservando o contexto atual; backup único `config.bak-open5gs-k3s`; testado com `su - user -c 'kubectl get nodes'`. `uninstall --k3s` remove só esse contexto.
24. **`~/.bashrc`**: alias `k` + autocomplete em bloco `# >>> open5gs-k3s >>>` (não duplica; não sobrescreve `alias k` existente); `--purge` remove.
25. **Log automático** do install em `logs/install.log` (o `| tee palavras…` criou arquivos soltos); `logs/` e `helm/generated/` devolvidos ao usuário (chown) no fim.
26. **Estrutura**: `scripts/lib/common.sh` (biblioteca separada dos executáveis), `helm/` (generated + postrender), `docs/`, `logs/`.
27. **Nó do k3s independente da rede física** (`NODE_IP_MODE=stable`, padrão). O `node-ip` ficava preso ao IP do cabo (191.4.204.79/`enp0s31f6`). Ao desligar o cabo e usar o Wi‑Fi, o k3s não subia (`node IP not found`). Agora uma interface dummy `k3s0` com 10.254.254.1/32, criada pela unit `open5gs-k3s-netif.service` e exigida pelo k3s via drop-in, é o node-ip e o flannel-iface. O host continua em DHCP, sem IP fixo; o N6 sai pela rota default do momento; NodePort e ServiceLB respondem em qualquer IP do host. `iface` mantém o comportamento antigo. Com `EXPOSE_RAN`, o IP físico anunciado ainda precisa ser estável. `uninstall --k3s` remove a unit e a interface.
28. **Recuperação do plano de usuário** (`AUTO_HEAL=true`). Depois de um reboot ou restart do k3s, o UPF passou a rejeitar o SMF (`Cannot find PFCP-Node`): o UE registrava e recebia IP, mas não pingava. `ensure_user_plane` (common.sh) escalona: espera, depois reinicia os UEs, depois UPF → SMF → gNB → UEs. É usado pelo install e por `scripts/heal.sh`. A unit `open5gs-k3s-heal` (`Type=exec`, para não atrasar o boot) roda no boot uma **cópia root** em `/opt/open5gs-k3s/heal`: uma unit root não executa arquivos que o usuário pode editar. `uninstall --k3s` remove a unit.
29. **Rede instável no servidor** (torre2: DNS e downloads falharam por alguns segundos durante o install): `retry` em `common.sh` (5 tentativas, 5–20 s) no instalador do k3s, clone/fetch dos charts, `helm repo add` e `helm dependency build`; `curl --retry` nos downloads.
30. **Setor 2 — link direto com o gNB real (`RAN_LINK_ENABLED`)**. Multus (chart `rke2-multus`, pastas do k3s em
    `helm/multus/values.yaml`; o chart não traz o CRD ⇒ `helm/multus/crd.yaml`) + rede `ran-link` (macvlan sobre
    `RAN_LINK_IFACE`, MTU do link, IP fixo por anotação). AMF (N2), UPF (N3) **e o gNB simulado** ganham `net1` no link,
    como na arquitetura de referência (towards5gs-helm): o `test.sh` passa pelo mesmo caminho do gNB real. O chart do
    AMF fixa `ngap: dev eth0` ⇒ post-renderer `helm/postrender/amf-ngap-net1.sh`. Alternativa `EXPOSE_RAN` (NAT pelo
    IP do host) fica para quem não tem link dedicado. Limitação: sem sinal no cabo o macvlan fica sem carrier e o gNB
    simulado também não conecta.
31. **PFCP (N4) sem NAT: Service `upf-pfcp` headless** (`clusterIP: None`). Com ClusterIP, o SMF falava com o UPF via
    DNAT e o UPF respondia direto ao pod do SMF; os dois fluxos UDP 8805↔8805 colidiam no conntrack, a porta de origem
    do SMF era reescrita (ex.: 16098, 1155) e o UPF rejeitava tudo com `Cannot find PFCP-Node` (heartbeats e
    modificações de sessão). É a causa provável da "dessincronia PFCP" da decisão 28. Apareceu de forma constante com o
    gNB real (2026-10-21). Limitação: o SMF resolve o nome só ao iniciar; se o UPF reiniciar sozinho (IP novo), é preciso
    reiniciar o SMF depois (o `heal.sh` já faz UPF → SMF). O install apaga o Service antigo (clusterIP é imutável).

32. **Painel de logs e métricas: Innova Center Dashboard** (`dashboard/`, `docs/dashboard.md`). Pedido do usuário:
    analisar logs e métricas (gNB, core, tráfego, BLER) num site local, parte do core. Escolhas:
    - **roda na máquina do core**, como pod no namespace do core (o OCUDU precisa da CPU; nada é instalado no host do gNB):
      as métricas do gNB são *puxadas* do WebSocket `remote_control` (`GNB_METRICS_URL`) e o log do gNB é lido por SSH
      (`tail -F`, só leitura) por uma unit na máquina do core (`open5gs-k3s-gnb-log`, usuário do install), que descarta
      `[PHY] [I]` por padrão (`GNB_LOG_DROP`; ~100 kB/s de log com o gNB parado);
    - **sem dependências**: backend só com a biblioteca padrão do Python (imagem `python:3.12-slim`, arquivos num
      ConfigMap), gráficos com uPlot 1.6.31 guardado no repositório (funciona offline);
    - **só leitura**: ServiceAccount com `get/list/watch` em `pods` e `pods/log`; usuário 65534, raiz só leitura; senha
      opcional (`DASHBOARD_PASSWORD`); o agente usa token gerado pelo install (só root lê);
    - estado do core (gNBs N2, registros, sessões DNN→IP, erros) **tirado dos logs** do AMF/SMF/UPF; métricas Prometheus
      (`OPEN5GS_METRICS`) são opcionais porque ligá-las reinicia o core;
    - histórico só em memória (15 min); BLER nos cartões em janela de 10 s; MCS/SNR sem transmissão viram lacuna;
    - `install.sh --dashboard-only` sobe só o painel; com `OPEN5GS_METRICS=false` os values do core ficam idênticos
      (verificado), então o install completo também não reinicia o core por causa do painel;
    - visual: branco/azul/cinza (pedido do usuário) com o verde do Centro Innova (#91cf50) só como detalhe;
    - aba **Máquinas**: a do core lida pelo pod (`/proc`, `/sys` e `/` do host montados só leitura); as outras
      (`DASHBOARD_HOSTS`) por SSH a partir da máquina do core, enviando o coletor pela entrada padrão — nada instalado
      no host do gNB; unit `open5gs-k3s-hosts`. Pods com nome curto (AMF…) e assinantes "SIM real" × "UERANSIM";
    - **aba Configuração**: edita o `config.env` pela web com senha de administrador própria, diff, validação do
      install, backup/restauração. Salvar não aplica: o painel mostra o `sudo ./install.sh ...` necessário (o
      pod não ganha root). Pod com o projeto só leitura e só o `config.env` gravável (grupo do dono);
    - **histórico persistente** (`DASHBOARD_PERSIST`): SQLite no host (`/var/lib/open5gs-k3s/dashboard`), todas as
      séries em blocos de 60 s comprimidos, eventos do core, **experimentos** (marcadores com nome/notas/setup) e
      comparação lado a lado. Escolhido SQLite da biblioteca padrão em vez de InfluxDB/Prometheus: nada novo para
      instalar, um arquivo só, fácil de copiar;
    - **aba RU** (v1.2): a O-RU LiteOn é lida pela porta de gestão RJ45 (10.101.131.59, mesmo switch do core) por
      SSH com senha, só comandos `show`, numa unit da máquina do core (`open5gs-k3s-ru`). Senhas num arquivo do root
      (`state/ru-credentials`), nunca no `config.env`/git. IP extra `/24` na interface do core (nunca `/8`: cobriria a
      fibra e o k3s). Escolhido CLI em vez de NETCONF (porta 830 aberta) porque a CLI já dá estado, PM e
      configuração, sem biblioteca nova;
    - **aba Controle** (v1.3): iniciar/parar/reiniciar por função, "Iniciar tudo" em ordem com conferência e
      recriação de pod sem `net1`; no boot só o painel (`CORE_AUTOSTART=false`, `heal.sh --boot-off`). gNB OCUDU
      por serviço `ocudu-gnb@<yml>` + regra polkit só para essas units (o usuário não quer sudo sem senha);
      escolha do usuário: o serviço roda binário e `.yml` direto da home (sem cópia do root) e não prepara a
      máquina (interface/DPDK/XDP/PTP continuam manuais);
    - **energia** do innovaserver pelo medidor MiEnergy: o painel lê `http://IP/Data` direto (sem InfluxDB/Grafana do
      projeto original). Pendente: o medidor ficar alcançável a partir do torre2 (`ENERGY_METER_URL`).

## Ruído conhecido

- `journalctl -u k3s`: `127.0.0.1:10250 … use of closed network connection` = conexões locais do kubelet fechando ao fim de `kubectl logs/exec`. Inofensivo.

## Ambiente de desenvolvimento

Ubuntu 24.04.5 desktop (`lunardint1`), kernel 7.0.0-38-generic, 8 vCPU/32 GiB, AVX, rede física `enp0s31f6` (cabo) ou `wlp0s20f3` (Wi‑Fi) em DHCP,
Docker ativo, **firewalld ativo**, NetworkManager, tailscale e zerotier, `kubectl` v1.36.1 próprio em `/usr/local/bin`.

## Histórico

- 2026-10-19: estrutura inicial, decisões 1–15, PLMN 001-01/TAC 1.
- 2026-10-19: 1ª execução real. Corrigidos em sequência: corrida do coredns (16), pull QPS (16), firewalld (17),
  kubeconfig 0600 (18), NRF servingList (19), Recreate (20), corrida do UE (21). Teste 7/7 OK.
- 2026-10-19: kubectl sem sudo para o usuário (23, 24), HPA do gNB (22), limpeza de 14 arquivos criados por `tee`,
  reorganização (25, 26), docs/ e README reescritos, Helm arm64, repositório git.
- 2026-10-19: publicado em https://github.com/Miguelclunardi/open5GK3S (privado).
- 2026-10-19: cabo desligado ⇒ k3s não subia (node-ip preso ao IP físico). Criado `NODE_IP_MODE=stable` com interface
  dummy `k3s0` (27); o host continua em DHCP. Reboot revelou dessincronia PFCP ⇒ `heal.sh` + unit de boot (28).
- 2026-10-21: Setor 2 no torre2: Multus + link direto com o OCUDU (30), PFCP headless (31), rede InnovaSplit, UEs reais
  conectados. Painel Innova Center Dashboard (32) escrito e testado fora do cluster (só leitura); instalação adiada
  porque havia pessoas testando a rede.
- 2026-10-21 (noite): painel **v1.0** — aba Configuração (edita o `config.env` com senha de administrador, diff,
  validação e backup; aplicar continua sendo `sudo ./install.sh`), UEs do rádio identificados (RNTI → IMSI/IP pelos
  logs do gNB, AMF e SMF), log do gNB ligado. Medidor MiEnergy integrado mas desligado: está atrás do NAT do Wi‑Fi.
- 2026-10-21 (fim do dia): painel com aba Core sem Prometheus (CPU/memória dos NFs e tráfego do UPF pelo /proc do
  host), WebUI do Open5GS embutida na aba Core (Assinantes), install do painel com server-side apply. Pendentes:
  pool para a DNN `ims` (SMF/UPF reiniciam: janela sem usuários), medidor de energia atrás do NAT do Wi-Fi,
  temperatura do innovaserver (ver IPMI), rotação do `/tmp/gnb.log` (9 GB).
- 2026-10-22: reboot com troca de IP (torre2 .17 → .117, innovaserver .77 → .122). Os agentes do painel (log do gNB e
  aba Máquinas) enviavam para o IP físico gravado no install ⇒ passaram a usar o IP fixo do nó (`k3s0`
  10.254.254.1). Depois do boot, AMF/UPF/UERANSIM subiram sem `net1` (Multus ainda não estava pronto) e o `heal.sh`
  reiniciou gNB e UEs ao mesmo tempo (o UE pegou o IP do gNB antigo). Decidido: o core **não** sobe sozinho no boot;
  só o painel. O painel ganha iniciar/parar/reiniciar por função e "iniciar core inteiro" em ordem (em andamento).
- 2026-10-22: RU LiteOn ligada no switch (gestão 10.101.131.59). Painel **v1.2** com a aba RU (estado, potência,
  temperatura, fronthaul, configuração; só leitura) e a RU no histórico/experimentos.
- 2026-10-22: painel **v1.3** com a aba Controle (core, UERANSIM e gNB OCUDU). Testado o "Iniciar tudo" com tudo
  rodando (só confere, nada reiniciado). Validado em uso pelo usuário: Parar tudo → Iniciar core (~4 min, UPF/SMF/AMF
  conferidos) → gNB OCUDU pelo serviço (RU "DU conectado" e N2 em ~14 s) → UERANSIM. O serviço passa
  `configs/metricas.yml` como 2º `-c` (como o usuário rodava à mão; liga as métricas na porta 8001 do painel; o
  arquivo não é alterado). Abas: Visão geral, Controle, Rádio, Core, RU, Logs, Máquinas, Histórico, Configuração.
  Tags `v1.2-dashboard` (8b8c9ed, aba RU) e `v1.3-dashboard` (aba Controle).
- 2026-10-22 (noite): painel **v1.4** — logotipo oficial da Innova, abas na ordem Visão geral, Controle, Rádio, Core,
  RU, Logs, Máquinas, Histórico, Configuração; título maior sem o nome da rede. Tag `v1.4-dashboard` = estado
  estável de referência (Open5GS + OCUDU + RU + painel).
- **Próxima fase (decidida em 2026-10-22):**
  - o projeto completo passa a se chamar **InnovaNetwork** (repositório novo); **Open5GK3S** fica sendo só o
    core Open5GS + UERANSIM (setor 1, `v1.0-ueransim`);
  - segundo core: **free5GC** (versão mais nova) no mesmo k3s do torre2, namespace próprio, pasta e config
    próprios; **um core por vez**, trocado pela aba Controle; também com o OCUDU (`.yml` próprio, AMF na fibra);
  - painel com o conceito de **core ativo** (adaptador por core; as abas mostram só o core ativo; Rádio, RU,
    Máquinas e Histórico não mudam; cada experimento registra o core). Protótipo aprovado pelo usuário;
  - nomes técnicos instalados (`open5gs-k3s-*`, `/opt/open5gs-k3s`) só migram numa janela combinada.
