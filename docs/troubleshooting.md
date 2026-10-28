# Solução de problemas

Sintoma → causa → solução. Organizado por área.

- [1. Diagnóstico rápido](#1-diagnóstico-rápido)
- [2. Acesso ao cluster](#2-acesso-ao-cluster-kubectl)
- [3. Core: problemas já corrigidos no código](#3-core-problemas-já-corrigidos-no-código)
- [4. Core: outros problemas possíveis](#4-core-outros-problemas-possíveis)
- [5. Rádio e gNB OCUDU](#5-rádio-e-gnb-ocudu)
- [6. Nó do RAN e instalação do OCUDU em Kubernetes](#6-nó-do-ran-e-instalação-do-ocudu-em-kubernetes)
- [7. Operação: troca de core e instaladores](#7-operação-troca-de-core-e-instaladores)
- [8. Painel](#8-painel)
- [9. Logs úteis](#9-logs-úteis)

---

## 1. Diagnóstico rápido

```bash
kubectl get nodes -o wide                    # as duas máquinas Ready?
kubectl get pods -A | grep -v Running        # algo fora do normal?
./test.sh -v                                 # core Open5GS de ponta a ponta (com logs se falhar)
./ran/ocudu/gnb.sh estado; ./ran/ocudu/gnb.sh log | tail -20
journalctl -u open5gs-k3s-heal -b            # o que a unit de boot fez
```

| Sintoma | Primeiro passo |
|---|---|
| nada responde depois do boot | normal: só o painel sobe. Aba Controle → **Iniciar tudo** |
| painel não abre | `kubectl -n open5gs get pods -l app=dashboard`; `sudo ./install.sh --dashboard-only` |
| celular não vê a rede | gNB ligado? O-RU `SYNCHRONIZED` e DU `Ready`? (seção 5) |
| celular vê a rede mas não registra | SIM cadastrado no core ativo? PLMN igual? log do AMF |
| registra mas não navega | reinicie o UPF pelo painel (reinicia o SMF junto) |

## 2. Acesso ao cluster (`kubectl`)

### 2.1 `The connection to the server localhost:8080 was refused`

**Causa**: o `kubectl` do seu usuário não tem kubeconfig. Sem `~/.kube/config` (ou com ele vazio)
e sem `KUBECONFIG`, o kubectl tenta o padrão `localhost:8080`, onde nada escuta. O k3s está
funcionando — ele expõe a API em `https://127.0.0.1:6443` e grava as credenciais em
`/etc/rancher/k3s/k3s.yaml`, legível **só pelo root** (modo 0600, de propósito: esse arquivo dá
controle total do cluster).

**Solução**: o `install.sh` já faz isso ao final para o usuário que chamou o `sudo`. Se precisar refazer:

```bash
sudo ./install.sh --deploy-only        # refaz values/deploy e o kubeconfig do usuário
# ou manualmente:
mkdir -p ~/.kube
sudo cat /etc/rancher/k3s/k3s.yaml > ~/.kube/config
chmod 600 ~/.kube/config
kubectl get nodes
```

> Se você já tinha um `~/.kube/config` com outros clusters, o `install.sh` faz **merge** (contexto
> `open5gs-k3s`) e mantém o seu contexto atual; troque com `kubectl config use-context open5gs-k3s`.
> O config anterior é salvo uma vez em `~/.kube/config.bak-open5gs-k3s`.

### 2.2 Formas de acessar

| Como | Quando usar |
|------|-------------|
| `kubectl …` (ou `k …`) | Uso normal, sem sudo. Usa `~/.kube/config` (contexto `open5gs-k3s`). |
| `KUBECONFIG=~/.kube/open5gs-k3s.yaml kubectl …` | Cópia avulsa só deste cluster (útil se o `~/.kube/config` aponta para outro). |
| `sudo k3s kubectl …` | Sempre funciona (root lê `/etc/rancher/k3s/k3s.yaml`). Bom para emergências. |
| `sudo kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml …` | Equivalente, com um kubectl próprio. |

Os scripts do projeto escolhem sozinhos: `/etc/rancher/k3s/k3s.yaml` se rodarem como root, senão
`~/.kube/open5gs-k3s.yaml`.

### 2.3 Comandos básicos de verificação

```bash
kubectl get nodes -o wide                          # nó Ready?
kubectl -n open5gs get pods -o wide                # todos 1/1 Running?
kubectl -n open5gs get svc                         # services (amf-ngap, upf-gtpu, webui…)
kubectl -n open5gs describe pod <pod>              # eventos: pull de imagem, crash, probes
kubectl -n open5gs logs deploy/open5gs-amf -f      # logs ao vivo de um NF
kubectl -n open5gs logs deploy/open5gs-amf --previous   # logs da execução anterior (após crash)
kubectl -n open5gs get events --sort-by=.lastTimestamp | tail -20
kubectl -n open5gs exec -it deploy/ueransim-ues -- bash  # shell no UE
sudo systemctl status k3s ; sudo journalctl -u k3s -f   # serviço do k3s
./test.sh -v                                       # validação ponta a ponta com logs
```

## 3. Core: problemas já corrigidos no código

| # | Sintoma | Causa | Correção (já no projeto) |
|---|---------|-------|--------------------------|
| 1 | `deployments.apps "coredns" not found` logo após instalar o k3s | O k3s cria os manifests do sistema de forma assíncrona; o script checava antes de existirem. | `install.sh` espera os deployments existirem antes do `rollout status`. |
| 2 | Pods em `ErrImagePull: pull QPS exceeded` na 1ª subida | Limite do kubelet (5 pulls/s) com ~15 imagens ao mesmo tempo. Passageiro. | `kubelet-arg: registry-qps=20, registry-burst=40` no config do k3s. |
| 3 | UDR/PCF/WebUI em `CrashLoopBackOff` nos primeiros minutos | MongoDB ainda baixando/iniciando. | Nenhuma — se resolve sozinho quando o Mongo sobe. |
| 4 | UE: `no cells in coverage`; `ping` entre pods → *Packet filtered* | **firewalld** rejeitando tráfego direto pod↔pod (via Service passava, então o core parecia OK). | `CONFIGURE_FIREWALLD=true`: `K3S_CLUSTER_CIDR` e `K3S_SERVICE_CIDR` na zona `trusted`. |
| 5 | UE preso em `MM-DEREGISTERED/LIMITED-SERVICE`, célula `ACCEPTABLE` | Corrida do UERANSIM: selecionou a célula antes do SIB1 e não reavalia. | `install.sh` espera NG Setup e, se o UE não registrar em 60 s, reinicia o pod dos UEs uma vez. Manual: `kubectl -n open5gs rollout restart deploy/ueransim-ues`. |
| 6 | Registro rejeitado; AMF `HTTP response error [400]`; SCP `No SEPP` | Chart do NRF com `servingList` fixo em 999/70; com PLMN 001/01 o UE parecia de outra rede (roaming). | `nrf.config.servingList` gerado a partir de `MCC`/`MNC`. |
| 7 | Registro rejeitado (`UE_IDENTITY_CANNOT_BE_DERIVED…`); SCP `No route to host` para IP antigo | RollingUpdate: NFs novos descobriram NFs antigos e guardaram no cache (validade 24 h). | `updateStrategy: Recreate` em todos os NFs. Manual: reiniciar os NFs juntos. |
| 8 | `failed to query scale subresource for StatefulSet/open5gs/ueransim` repetindo no `journalctl -u k3s` | Bug do chart `ueransim-gnb`: HPA (min=max=1) aponta para `StatefulSet`, mas o gNB é `Deployment`. | Post-renderer `helm/postrender/drop-gnb-hpa.sh` remove o HPA. |
| 9 | `localhost:8080 was refused` no terminal do usuário | Sem kubeconfig do usuário (ver §2.1). | `install.sh` configura `~/.kube/config` do `$SUDO_USER` (merge idempotente). |
| 10 | Arquivos com palavras soltas na pasta do projeto | `cmd \| tee install.log palavra palavra…` — o `tee` cria um arquivo por argumento. | `install.sh` grava o próprio log em `logs/install.log`; não use `\| tee`. |
| 11 | k3s parado em `activating`; `kubectl`: `apiserver not ready`/`connection refused` depois de desligar o cabo | `node-ip` preso ao IP físico; no Wi‑Fi o IP era outro. | `NODE_IP_MODE=stable`: interface dummy `k3s0` com IP fixo e privado, criada pela unit `open5gs-k3s-netif` antes do k3s. |
| 12 | Após reboot ou restart do k3s: UE registrado e com IP, mas `ping` falha; o UPF loga `Cannot find PFCP-Node … from [IP do SMF]` | Os pods voltam em ordem qualquer; a associação PFCP (N4) entre SMF e UPF e as sessões dos UEs ficam dessincronizadas. | `scripts/heal.sh` (UEs e depois UPF → SMF → gNB → UEs), rodado no boot pela unit `open5gs-k3s-heal` (`AUTO_HEAL=true`) e pelo `install.sh`. |

### Ruído conhecido (não é erro)

- `journalctl -u k3s`: `Error on socket receive … 127.0.0.1:10250 … use of closed network connection`
  — conexões locais do kubelet sendo fechadas ao fim de `kubectl logs/exec`. Inofensivo.
- Logs do AMF/SMF com `Failed to connect to open5gs-scp-sbi … Connection refused` nos primeiros
  segundos após um restart — os NFs sobem antes do SCP e tentam de novo.

## 4. Core: outros problemas possíveis

| Sintoma | Causa provável / solução |
|---------|--------------------------|
| `open5gs-mongodb` em `CrashLoopBackOff` com *Illegal instruction* | CPU/VM sem **AVX** (MongoDB 8). Em VM use CPU `host-passthrough`, ou defina `MONGODB_IMAGE_*` com uma imagem 4.4. |
| `ImagePullBackOff` persistente | Sem acesso ao Docker Hub ou rate limit: `kubectl -n open5gs describe pod …`. |
| gNB sem NG Setup | `lsmod \| grep sctp`; PLMN/TAC/S-NSSAI do gNB diferentes do AMF. |
| UE `Registration reject` / falha de autenticação | IMSI/K/OPc não cadastrados ou diferentes: `./scripts/subscribers.sh list`. |
| UE registra mas sem sessão PDU | DNN/slice do UE inexistente no SMF ou no assinante. Ver logs do SMF/UPF. |
| Ping ao gateway (10.45.0.1) OK, à internet não | N6: host sem saída, DNS, ou firewall (Docker/UFW/firewalld) bloqueando forward. `sudo iptables -L FORWARD -n -v`. |
| Pods sem rede após instalar Docker | Docker põe `FORWARD` em `DROP`. O k3s cria regras para `10.42.0.0/16`; se preciso: `sudo iptables -I FORWARD -s 10.42.0.0/16 -j ACCEPT; sudo iptables -I FORWARD -d 10.42.0.0/16 -j ACCEPT`. |
| Desktop perde rede / pods instáveis | NetworkManager gerenciando `cni0`/`flannel.1`: confira `/etc/NetworkManager/conf.d/90-open5gs-k3s-unmanaged.conf`. |
| k3s não sobe depois que o IP do host mudou (DHCP, cabo desligado, troca para Wi‑Fi) e o `journalctl -u k3s` mostra `node IP … not found in the host's network interfaces` | Instalação antiga com `node-ip` na placa física. Com `NODE_IP_MODE=stable` (padrão) rode `sudo ./install.sh` uma vez: o nó passa para `k3s0`/10.254.254.1 e isso não se repete. Verifique com `ip -br a show k3s0` e `systemctl status open5gs-k3s-netif`. |
| `helm` timeout na 1ª instalação | Download lento: aumente `HELM_TIMEOUT` e rode de novo. |

## 5. Rádio e gNB OCUDU

| Sintoma | Causa | Solução |
|---|---|---|
| gNB sobe mas não aparece no AMF | `.yml` aponta para o outro core, ou o AMF reiniciou depois do gNB | escolha o `.yml` do core ativo; reinicie o gNB |
| gNB perde o AMF ("Handling N2 disconnection") | core parado ou trocado com o gNB ligado | use a troca de core do painel, que religa o gNB |
| celulares fazem PRACH mas não conectam; RU com muitos pacotes adiantados/atrasados | O-RU sincronizou antes do GNSS ficar válido | `restart ptp4l-gm phc2sys`, reiniciar a O-RU, reiniciar o gNB ([hardware](hardware/e810-liteon.md#4-sincronismo-espere-o-gnss)) |
| O-RU sem "DU conectado" | PTP parado ou VF fora do `vfio-pci` | `systemctl status ptp4l-gm ts2phc`; `dpdk-devbind.py --status` |
| painel: "parado (nó reiniciou)" | proteção de boot: o nó reiniciou depois do último pedido | espere o GNSS, ajuste PTP/O-RU e clique **Iniciar** |
| pod recusa iniciar: "há um gnb rodando no host" | serviço nativo `ocudu-gnb@` ou gNB aberto no terminal | pare o outro gNB (os dois usam a mesma O-RU e VF) |
| `gnb.sh iniciar` recusa: "serviço nativo ligado" | idem | `systemctl stop 'ocudu-gnb@*'` no nó |
| celular registra e sai ~1 s depois (free5GC) | falta voz IMS anunciada / DNN `ims` | já configurado no `free5gc.env`; confira `F5_EXTRA_DNNS` |
| "bad message" contínuo no `ptp4l` | XDP fora da porta do fronthaul | `sudo systemctl restart ptp4l-gm phc2sys` com o gNB parado |

## 6. Nó do RAN e instalação do OCUDU em Kubernetes

Problemas encontrados na primeira instalação, já tratados nos scripts:

| Sintoma | Causa | Solução |
|---|---|---|
| build falha em `build_rohc.sh` com `curl: (35) Connection reset by peer` | o site da biblioteca ROHC bloqueia a rede | `OCUDU_IMAGE_ROHC=false` (padrão): imagem sem ROHC, como o build nativo típico |
| k3s agente não sobe: `listen tcp 0.0.0.0:10250: bind: address already in use` | outro Kubernetes no nó (ex.: MicroK8s) | `entrar` detecta e aborta; pare o outro (ex.: `sudo microk8s stop`) |
| agente em ciclo: `Node authorization rejected` | certificados de uma tentativa anterior que falhou | `entrar` limpa sozinho; manual: parar o agente, `rm -rf /var/lib/rancher/k3s/agent`, iniciar |
| pod: `EAL: … /dev/hugepages/rtemap_0 failed: Permission denied`, `cannot open /proc/self/pagemap` | a imagem oficial roda como usuário 1001; o DPDK neste modo precisa de root | o pod roda com `runAsUser: 0` e `privileged` |
| pod: `Unable to create log file "/tmp/gnb.log": Permission denied` | log antigo de outro dono; `fs.protected_regular=2` impede reabrir | o pod remove o log se o dono não for root |
| pod: `EAL: Cannot init memory` com hugepages livres | o Kubernetes limita o hugetlb ao que o pod pede | `OCUDU_HUGEPAGES_1G` (o pod pede `hugepages-1Gi`) |
| `entrar` rodado na máquina errada: `command not found` | comando do nó executado na máquina do core | cada passo da instalação indica a máquina |
| imagem não aparece no nó depois do `importar` | importação incompleta | rode `importar` de novo, guardando a saída: `2>&1 \| tee importar.log` |

Conferir o nó: `kubectl describe node <nó>` (rótulo, taint, `hugepages-1Gi` alocável) e
`kubectl get node <nó> -o json | grep -o 'innovanetwork/ocudu-gnb:[0-9a-f]*'` (imagem presente).

## 7. Operação: troca de core e instaladores

| Sintoma | Causa | Solução |
|---|---|---|
| os dois cores ligados ao mesmo tempo | `install.sh --deploy-only` rodado com o free5GC ativo (o Helm volta as réplicas do Open5GS para 1) | rode o `--deploy-only` com o Open5GS ativo, ou troque de core em seguida |
| `--deploy-only` falha em "Assinantes" (`timed out waiting for the condition`) | rodado junto com uma troca de core, que parava o pod `populate` | não rode instalador e troca juntos; rode o install de novo |
| célula some depois de trocar de core pelos botões separados | o gNB ficou apontando para o AMF antigo | use o cartão **Core ativo** |
| UE registra mas não navega depois de reboot | PFCP SMF↔UPF dessincronizado | reinicie o UPF pelo painel (reinicia o SMF), ou `./scripts/heal.sh` |

## 8. Painel

| Sintoma | Causa / solução |
|---|---|
| cartão do gNB: "agente sem contato" | `journalctl -u open5gs-k3s-gnb-ctl` na máquina do core (kubeconfig, SSH ao nó) |
| "gNB sem dados" na aba Rádio | gNB parado ou sem `remote_control`: `nc -vz 10.10.0.1 8001` |
| UEs só com "RNTI …" | log do gNB desligado (`GNB_LOG_SSH`) ou o UE ainda não trocou mensagens com o core |
| aba RU sem dados | credenciais da O-RU ausentes (`/opt/open5gs-k3s/state/ru-credentials`) ou IP de gestão; `journalctl -u open5gs-k3s-ru` |
| Configuração recusa salvar | o arquivo mudou no servidor; recarregue a página |
| página não abre de outro PC | firewall: o install abre a porta do painel; `sudo ufw status` |

Mais: [componentes/painel.md](componentes/painel.md#problemas-comuns).

## 9. Logs úteis

```bash
kubectl -n open5gs logs deploy/open5gs-amf | grep -iE 'gNB|Registration|reject'
kubectl -n open5gs logs deploy/open5gs-smf | grep -iE 'UE|session|PFCP'
kubectl -n open5gs logs deploy/open5gs-scp | grep -iE 'error|warn'
kubectl -n open5gs logs deploy/open5gs-upf
kubectl -n open5gs logs deploy/ueransim          # gNB
kubectl -n open5gs logs deploy/ueransim-ues      # UEs
kubectl -n open5gs exec deploy/ueransim-ues -- nr-cli imsi-001010000000001 --exec status
less logs/install.log                            # histórico das execuções do install.sh
kubectl -n ocudu logs deploy/ocudu-gnb           # gNB OCUDU
journalctl -u open5gs-k3s-gnb-ctl -f             # agente de controle do gNB
```
