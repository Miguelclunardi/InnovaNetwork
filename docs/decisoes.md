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
   - repositório clonado em `~/open5GK3S` com **deploy key só leitura** (`~/.ssh/github-open5gk3s`,
     `Host github-open5gk3s`; título "torre2 (leitura)" no GitHub), sem login do GitHub no servidor;
   - o servidor tinha um k3s manual (v1.36.5, kubeconfig 644) com uma tentativa antiga do Open5GS quebrada:
     removido com `k3s-uninstall.sh` (autorizado pelo usuário) antes do `sudo ./install.sh`;
   - desenvolvimento: ferramentas de IA **ficam no desktop** e operam o servidor por SSH; fluxo editar local →
     `git push` → `ssh torre2 'cd ~/open5GK3S && git pull --ff-only && ./test.sh'`;
     comandos com sudo no servidor são rodados pelo usuário (`ssh -t torre2 'sudo …'`).
4. Dashboard de acompanhamento (pedido do usuário, adiado): pods/NFs, UEs registrados, sessões, tráfego.
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
