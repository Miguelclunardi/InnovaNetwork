# OCUDU — gNB real em Kubernetes

O gNB **OCUDU** (CU + DU no mesmo processo, O-RAN split 7.2, DPDK) roda como o pod `ocudu-gnb` no **nó do RAN**,
uma máquina que entra no cluster k3s como agente, dedicada ao rádio.

> **Depende do seu setup.** O InnovaNetwork leva para o Kubernetes um gNB que **já funciona** na máquina. A
> preparação do host (kernel, CPUs isoladas, hugepages, VF/DPDK, PTP/GNSS) e os `.yml` do gNB são do seu setup.
> Referência: [hardware/e810-liteon.md](../hardware/e810-liteon.md).

- [1. Como funciona](#1-como-funciona)
- [2. Arquivos](#2-arquivos)
- [3. Configuração (`ocudu.env`)](#3-configuração-ocuduenv)
- [4. A imagem](#4-a-imagem)
- [5. O nó do RAN](#5-o-nó-do-ran)
- [6. O pod](#6-o-pod)
- [7. Um `.yml` por core](#7-um-yml-por-core)
- [8. Proteção de boot](#proteção-de-boot)
- [9. Controle pelo painel](#9-controle-pelo-painel)
- [10. Comandos](#10-comandos)
- [11. Modo nativo (legado)](#11-modo-nativo-legado)
- [12. Remover e voltar atrás](#12-remover-e-voltar-atrás)

---

## 1. Como funciona

```
máquina do core (servidor k3s, 10.254.254.1)          máquina do RAN (agente k3s, 10.10.0.1)
  painel ── gnb.sh ── API do Kubernetes                 kubelet ── pod ocudu-gnb (namespace ocudu)
  AMF 10.10.0.10 / UPF 10.10.0.11 (net1)                 rede do host · privileged · hugepages
        ▲                                                 taskset -c 0-17 gnb -c <yml> -c metricas.yml
        └────────── fibra 10.10.0.0/24 ────────────────── N2/N3 em 10.10.0.1 · métricas :8001
                    (API do k3s, flannel, N2/N3)          E810: VF em DPDK ── fronthaul 7.2 ── O-RU
```

- **Um cluster só.** O nó do RAN entra no k3s da máquina do core pela fibra. Rótulo `innovanetwork/role=ran`,
  taint `innovanetwork/ran=true:NoSchedule`: só o gNB roda lá.
- **O gNB roda exatamente como no host:** mesmo binário (compilado do mesmo commit), mesmo comando e CPUs, `.yml`
  lidos de `~/ocudu/configs` do host, log em `/tmp/gnb.log` do host, rede do host (N2/N3 em `10.10.0.1`,
  métricas em `:8001`). Resultado medido: ~92 % dos pacotes do fronthaul no tempo, igual ao nativo.
- **Ligado/desligado = réplicas.** `gnb.sh iniciar` põe 1 réplica; `parar`, 0.

**Por que manifesto próprio e não o chart oficial `ocudu-gnb`:** o chart exige o CPU Manager estático do
Kubernetes, reescreve os argumentos do DPDK (`eal_args`), passa um único `-c` e roda como usuário sem privilégio.
O manifesto próprio reproduz o comando nativo validado, sem mudar o comportamento do gNB. O chart pode virar uma
opção futura.

## 2. Arquivos

| Arquivo | Roda em | Para quê |
|---|---|---|
| `ran/ocudu/ocudu.env` | — | parâmetros do setup |
| `ran/ocudu/install.sh` | máquina do core | `copiar` · `preparar` (sudo) · sem argumento: namespace e Deployment · `--dry-run` · `--remover` |
| `ran/ocudu/no-ran.sh` | **nó do RAN** (`~/innovanetwork-ran/`), sudo | `imagem` · `importar` · `entrar` · `sair` · `estado` |
| `ran/ocudu/gnb.sh` | máquina do core | `iniciar [yml]` · `parar` · `estado` · `log [-f]` · `configs` |
| `ran/ocudu/lib/render.py` | máquina do core | gera Namespace, ConfigMap descritor e Deployment |

## 3. Configuração (`ocudu.env`)

| Variável | Referência | Significado |
|---|---|---|
| `OCUDU_NODE` | `innovaserver` | nome do nó no Kubernetes (hostname) |
| `OCUDU_NODE_SSH` | `innovaserver@10.10.0.1` | SSH da máquina do core para o nó (sem senha) |
| `OCUDU_NODE_IP` / `OCUDU_NODE_IFACE` | `10.10.0.1` / `ens4f3np3` | IP e interface do nó no cluster (a fibra) |
| `OCUDU_SERVER_VIA` | `10.10.0.2` | próximo salto até o servidor (`10.254.254.1`) |
| `OCUDU_NAMESPACE` | `ocudu` | namespace |
| `OCUDU_SRC_DIR` | `/home/innovaserver/ocudu` | repositório Git do OCUDU (fonte da imagem) |
| `OCUDU_CONFIG_DIR` | `…/ocudu/configs` | pasta dos `.yml`, montada só leitura no pod |
| `OCUDU_DEFAULT_CONFIG` | `gnb_split_open5gs` | `.yml` inicial |
| `OCUDU_EXTRA_CONFIG` | `metricas.yml` | 2º `-c` (liga o `remote_control` na porta 8001, usado pelo painel) |
| `OCUDU_CPUS` | `0-17` | CPUs do gNB (`taskset`) |
| `OCUDU_HUGEPAGES_1G` / `OCUDU_MEMORY_REQUEST` | `2Gi` / `2Gi` | recursos pedidos pelo pod |
| `OCUDU_LOG_DIR` | `/tmp` | pasta do log no host |
| `OCUDU_IMAGE` / `OCUDU_IMAGE_TAG` | `innovanetwork/ocudu-gnb` / vazio | imagem; tag vazia = commit curto do código |
| `OCUDU_IMAGE_OS*`, `OCUDU_IMAGE_MARCH`, `OCUDU_BUILD_JOBS` | `ubuntu 24.04`, `native`, `8` | compilação |
| `OCUDU_IMAGE_ROHC` | `false` | compilar com ROHC (precisa baixar a biblioteca) |

## 4. A imagem

`sudo ~/innovanetwork-ran/no-ran.sh imagem` (no nó):

1. exporta o **commit atual** de `OCUDU_SRC_DIR` com `git archive` para `/var/tmp/innovanetwork-ocudu-src` (sem a
   pasta `build/` nativa, que quebraria o CMake). **Mudanças sem commit não entram**;
2. `docker build` com o **Dockerfile oficial** do OCUDU: alvo `runtime-dpdk`, `COMPONENT=gnb`, Ubuntu 24.04,
   `-march=native` (a imagem só roda nesta CPU ou compatível);
3. confere que a imagem tem `gnb`, `taskset` e `bash`;
4. importa no containerd do k3s (`docker save | k3s ctr -n k8s.io images import -`), se o nó já estiver no cluster.

Resultado: `innovanetwork/ocudu-gnb:<commit>` (~140 MB). O Deployment usa `imagePullPolicy: Never`: a imagem
existe só no nó, sem registry.

## 5. O nó do RAN

`sudo ~/innovanetwork-ran/no-ran.sh entrar` (depois de `sudo ./ran/ocudu/install.sh preparar` na máquina do core):

| Etapa | Detalhe |
|---|---|
| Verificações | aborta se outro Kubernetes ocupa as portas do kubelet (10250/10248) e indica como pará-lo; limpa restos de tentativa anterior |
| Rota | unit `innovanetwork-k3s-route`: `10.254.254.1/32 via 10.10.0.2` (persistente, sem netplan) |
| Firewall | UFW (se ativo) libera o servidor e as redes do k3s |
| `/etc/rancher/k3s/config.yaml` | `node-ip`, `flannel-iface` (a fibra), rótulo e taint |
| k3s | instalador oficial, **mesma versão do servidor**, modo agente; o token temporário é apagado em seguida |
| Imagem | importada, se já compilada |

`sair` desinstala o agente k3s e a rota (as regras do UFW ficam). `estado` mostra o agente, a rota, o token
pendente, o commit do OCUDU e se há um gNB nativo ligado.

## 6. O pod

| Item | Valor | Por quê |
|---|---|---|
| `nodeSelector` + toleration | nó do RAN | só lá existem a NIC e a O-RU |
| `hostNetwork`, `hostPID` | sim | N2/N3/métricas nos IPs do host; o pod vê processos `gnb` do host |
| `privileged`, `runAsUser: 0` | sim | DPDK (VF `vfio-pci`, `/proc/self/pagemap`, hugepages), como no serviço nativo |
| hugepages | `hugepages-1Gi: 2Gi` pedido e limite | o Kubernetes limita o hugetlb do pod ao que ele pede |
| montagens | `.yml` (só leitura), `/dev/hugepages`, `/tmp` | mesma configuração e mesmo log do host |
| estratégia | `Recreate`, 0 ou 1 réplica | nunca dois gNBs na mesma RU |

O script de entrada do pod:

1. aplica a [proteção de boot](#proteção-de-boot);
2. **recusa iniciar** se já houver um processo `gnb` no host (serviço nativo ou terminal);
3. remove o log antigo se o dono não for root (o kernel não deixa reabrir arquivo de outro dono no `/tmp`);
4. roda `taskset -c $GNB_CPUS gnb -c /configs/$GNB_CONFIG.yml -c /configs/metricas.yml`;
5. repassa o `SIGTERM` do Kubernetes como `SIGINT` (o gNB encerra limpo, como no Ctrl+C).

## 7. Um `.yml` por core

Os `.yml` ficam em `~/ocudu/configs/` no nó e são lidos direto do host. Para cada core há uma cópia em que só muda
`cu_cp.amf.addr`:

| Arquivo (exemplo) | AMF | Core |
|---|---|---|
| `gnb_split_open5gs.yml` | `10.10.0.10` | Open5GS |
| `gnb_split_free5gc.yml` | `10.10.0.30` | free5GC |

Nos dois: N2 e N3 do gNB em `10.10.0.1` (`cu_cp.amf.bind_addr`, `cu_up.ngu.socket.bind_addr`). O endereço N3 do
UPF não está no `.yml`: o SMF informa na sessão. **Não altere o `metricas.yml`**: é ele que liga as métricas
lidas pelo painel.

| Mudou… | Precisa |
|---|---|
| um `.yml` | reiniciar o gNB (o pod lê a pasta do host) |
| o código do OCUDU | commit → `no-ran.sh imagem` → `./ran/ocudu/install.sh` → reiniciar ([tutorial](../tutoriais/07-alterar-o-gnb.md)) |

<a id="proteção-de-boot"></a>
## 8. Proteção de boot

Depois de um boot o GNSS pode levar até ~30 min para dar hora válida, e o relógio da NIC dá um salto quando isso
acontece. Um gNB ligado antes disso deixa a O-RU sincronizada no tempo errado. Por isso **o gNB nunca liga
sozinho depois de um reboot do nó**:

- cada `gnb.sh iniciar` grava a hora do pedido (`GNB_START_REQUEST`) no Deployment;
- ao iniciar, o pod compara com a hora de boot do host (`btime` de `/proc/stat`);
- pedido **anterior** ao boot → o pod fica de pé **sem ligar o gNB** e mostra:
  `o gNB NÃO liga sozinho. Confira o GPS (ts2phc 's2') e a RU e rode: ./ran/ocudu/gnb.sh iniciar`.

O painel mostra **"parado (nó reiniciou)"**. Depois do GNSS válido, do PTP ajustado e da O-RU reiniciada, ligue de
novo (painel ou `gnb.sh iniciar`). `install.sh` preserva o pedido em vigor e não derruba um gNB ligado.

## 9. Controle pelo painel

Com `GNB_CTL_MODE="k8s"` no `config.env`, o agente `open5gs-k3s-gnb-ctl` (máquina do core):

- lê a cada 3 s o Deployment e o pod (réplicas, `.yml`, fase, reinícios, últimas 25 linhas do log), o processo `gnb`
  no nó, os `.yml` disponíveis com o AMF de cada um, os serviços PTP e o driver da VF;
- executa os pedidos do painel com `ran/ocudu/gnb.sh` (iniciar com o `.yml` escolhido, reiniciar, parar).

Depois de iniciar, o painel confere: pod rodando (e ainda rodando 5 s depois), **DU conectado** na O-RU e **N2 no
AMF** do core ativo. A troca de core também religa o gNB pelo Kubernetes.

## 10. Comandos

```bash
# máquina do core
./ran/ocudu/gnb.sh configs                  # .yml e AMF de cada um
./ran/ocudu/gnb.sh iniciar <yml>            # liga
./ran/ocudu/gnb.sh parar                    # desliga
./ran/ocudu/gnb.sh estado                   # réplicas, .yml, pod, nó, reinícios
./ran/ocudu/gnb.sh log -f                   # saída do gNB
kubectl -n ocudu describe pod -l app.kubernetes.io/name=ocudu-gnb
kubectl describe node <nó do RAN>           # rótulo, taint, hugepages alocáveis

# nó do RAN
sudo ~/innovanetwork-ran/no-ran.sh estado
tail -f /tmp/gnb.log                        # log completo do gNB
```

## 11. Modo nativo (legado)

Antes da v3 o gNB rodava como o serviço systemd `ocudu-gnb@<yml>` no host, criado por
`scripts/ocudu/setup-gnb-service.sh` (com uma regra do polkit para o painel controlá-lo sem sudo). O modo continua
disponível com `GNB_CTL_MODE="systemd"`. Os dois modos não rodam ao mesmo tempo: o pod recusa iniciar com um `gnb`
no host, e `gnb.sh iniciar` recusa com o serviço nativo ativo.

## 12. Remover e voltar atrás

| Desfazer | Comando |
|---|---|
| gNB pelo Kubernetes → nativo | `./ran/ocudu/gnb.sh parar`; `GNB_CTL_MODE="systemd"` + `sudo ./install.sh --dashboard-only` |
| Deployment e namespace | `./ran/ocudu/install.sh --remover` |
| nó do cluster | no nó: `sudo ~/innovanetwork-ran/no-ran.sh sair`; no core: `kubectl delete node <nó>` |

Outro Kubernetes no nó (ex.: MicroK8s) não pode rodar junto com o agente k3s: usam as mesmas portas. Pare um antes
de ligar o outro.
