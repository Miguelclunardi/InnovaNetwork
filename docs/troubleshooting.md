# Troubleshooting

Problemas reais encontrados na primeira instalação (Ubuntu 24.04 desktop) e como foram resolvidos,
mais o guia de acesso ao cluster e os comandos de verificação.

## 1. Acesso ao cluster (`kubectl`)

### 1.1 `The connection to the server localhost:8080 was refused`

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

### 1.2 Formas de acessar

| Como | Quando usar |
|------|-------------|
| `kubectl …` (ou `k …`) | Uso normal, sem sudo. Usa `~/.kube/config` (contexto `open5gs-k3s`). |
| `KUBECONFIG=~/.kube/open5gs-k3s.yaml kubectl …` | Cópia avulsa só deste cluster (útil se o `~/.kube/config` aponta para outro). |
| `sudo k3s kubectl …` | Sempre funciona (root lê `/etc/rancher/k3s/k3s.yaml`). Bom para emergências. |
| `sudo kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml …` | Equivalente, com um kubectl próprio. |

Os scripts do projeto escolhem sozinhos: `/etc/rancher/k3s/k3s.yaml` se rodarem como root, senão
`~/.kube/open5gs-k3s.yaml`.

### 1.3 Comandos básicos de verificação

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

## 2. Problemas encontrados e corrigidos

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
| 9 | `localhost:8080 was refused` no terminal do usuário | Sem kubeconfig do usuário (ver §1.1). | `install.sh` configura `~/.kube/config` do `$SUDO_USER` (merge idempotente). |
| 10 | Arquivos com palavras soltas na pasta do projeto | `cmd \| tee install.log palavra palavra…` — o `tee` cria um arquivo por argumento. | `install.sh` grava o próprio log em `logs/install.log`; não use `\| tee`. |

### Ruído conhecido (não é erro)

- `journalctl -u k3s`: `Error on socket receive … 127.0.0.1:10250 … use of closed network connection`
  — conexões locais do kubelet sendo fechadas ao fim de `kubectl logs/exec`. Inofensivo.
- Logs do AMF/SMF com `Failed to connect to open5gs-scp-sbi … Connection refused` nos primeiros
  segundos após um restart — os NFs sobem antes do SCP e tentam de novo.

## 3. Outros problemas possíveis

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
| k3s quebra após o IP do nó mudar (DHCP) | `node-ip` fica fixo no `/etc/rancher/k3s/config.yaml`: rode `sudo ./install.sh` de novo (ou fixe o IP). |
| `helm` timeout na 1ª instalação | Download lento: aumente `HELM_TIMEOUT` e rode de novo. |

## 4. Logs úteis

```bash
kubectl -n open5gs logs deploy/open5gs-amf | grep -iE 'gNB|Registration|reject'
kubectl -n open5gs logs deploy/open5gs-smf | grep -iE 'UE|session|PFCP'
kubectl -n open5gs logs deploy/open5gs-scp | grep -iE 'error|warn'
kubectl -n open5gs logs deploy/open5gs-upf
kubectl -n open5gs logs deploy/ueransim          # gNB
kubectl -n open5gs logs deploy/ueransim-ues      # UEs
kubectl -n open5gs exec deploy/ueransim-ues -- nr-cli imsi-001010000000001 --exec status
less logs/install.log                            # histórico das execuções do install.sh
```
