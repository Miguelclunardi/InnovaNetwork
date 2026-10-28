# Instalação

Do zero até um celular navegando. A instalação tem três partes independentes; faça na ordem e pare onde quiser.

| Parte | Resultado | Onde | Tempo |
|---|---|---|---|
| [1. Core e painel](#1-core-open5gs-ueransim-e-painel) | Open5GS + UERANSIM + painel, testados | máquina do core | 15–30 min |
| [2. free5GC (opcional)](#2-free5gc-opcional) | segundo core, alternável pelo painel | máquina do core | 15 min |
| [3. Rádio: OCUDU em Kubernetes](#3-rádio-ocudu-em-kubernetes) | gNB real como pod no nó do RAN | as duas máquinas | ~1 h |

Depois: [operação do dia a dia](operacao.md).

---

## 0. Requisitos

### Máquina do core

- Ubuntu 24.04 LTS (desktop ou server), x86_64; CPU com **AVX** (MongoDB 8); 8 GiB de RAM; 20 GiB livres.
- Acesso à internet (apt, k3s, Helm, GitHub, Docker Hub) e `sudo`.
- Para o rádio: uma porta de rede dedicada ligada à máquina do RAN (fibra ou cobre), de preferência MTU 9000.

### Máquina do RAN (só para a parte 3)

A máquina precisa **já rodar o gNB OCUDU nativamente** com o seu rádio. O InnovaNetwork leva esse gNB para o
Kubernetes; ele **não** prepara a máquina. Antes, garanta:

- kernel de baixa latência, CPUs isoladas para o gNB (`isolcpus`) e hugepages de 1 GiB;
- NIC com VF em `vfio-pci` (DPDK) para o fronthaul e PTP funcionando (grandmaster com GNSS ou outro);
- código do OCUDU em uma pasta Git (ex.: `~/ocudu`) e os `.yml` do gNB em `~/ocudu/configs/`;
- Docker instalado (para compilar a imagem);
- acesso SSH **sem senha** da máquina do core para a do RAN (`ssh-copy-id usuario@ip-da-fibra`).

O setup de referência está descrito em [hardware/e810-liteon.md](hardware/e810-liteon.md).

---

## 1. Core Open5GS, UERANSIM e painel

**Máquina do core.**

```bash
git clone https://github.com/Miguelclunardi/InnovaNetwork.git ~/InnovaNetwork
cd ~/InnovaNetwork
nano config.env
```

O `config.env` é comentado linha a linha. O mínimo a revisar:

| Seção | Variáveis | Exemplo |
|---|---|---|
| PLMN | `MCC`, `MNC`, `TAC`, `NETWORK_NAME` | `001`, `01`, `1`, `InnovaOpen5GS` |
| Slices | `SLICES` (`SST:SD:DNN:pool`) | `"1:111111:internet:10.45.0.0/16"` |
| Fibra até o gNB | `RAN_LINK_ENABLED`, `RAN_LINK_IFACE`, `RAN_LINK_CIDR`, `AMF_N2_IP`, `UPF_N3_IP` | `true`, `enp5s0f1`, `10.10.0.0/24`, `10.10.0.10`, `10.10.0.11` |
| gNB no painel | `GNB_METRICS_URL`, `GNB_LOG_SSH`, `GNB_CTL_MODE`, `GNB_CTL_SSH`, `GNB_CTL_DIR` | `ws://10.10.0.1:8001`, … |
| O-RU no painel | `RU_MGMT_IP`, `RU_SSH_USER`, `RU_MGMT_LOCAL_CIDR` | `10.101.131.59` |

Sem rádio, deixe `RAN_LINK_ENABLED=false` e as variáveis de gNB/O-RU vazias.

```bash
sudo ./install.sh        # 5–15 min na 1ª vez; log em logs/install.log
./test.sh                # pods → NRF → NG Setup → registro → sessão → ping
```

Esperado:

```
RESULTADO: 7 verificações OK, 0 falhas
```

O instalador, em etapas que só agem se algo mudou: valida a configuração → pacotes, módulos (SCTP) e sysctl →
interface estável `k3s0` → k3s → Helm e charts → Multus e rede da fibra → Open5GS → assinantes → UERANSIM →
painel e agentes → units de boot → `~/.kube/config` do usuário.

No fim ele mostra o endereço do painel e onde está a **senha de administrador**:

```bash
sudo cat /opt/open5gs-k3s/state/dashboard-admin-password
```

Opções úteis:

| Comando | Faz |
|---|---|
| `sudo ./install.sh --deploy-only` | reaplica só core, UERANSIM, assinantes e painel (não mexe em pacotes nem no k3s) |
| `sudo ./install.sh --dashboard-only` | reinstala só o painel e os agentes (não toca no core nem no gNB) |
| `sudo ./uninstall.sh` | remove o core (níveis `--k3s`, `--purge`) |

Detalhes do core: [componentes/open5gs.md](componentes/open5gs.md). Tutorial guiado:
[Primeiro teste com UERANSIM](tutoriais/01-primeiro-teste-ueransim.md).

### Credenciais da O-RU (opcional)

A aba RU do painel lê a O-RU por SSH. A senha fica fora do git, num arquivo do root:

```bash
printf 'RU_PASS=%s\nRU_ENABLE=%s\n' 'SENHA_SSH' 'SENHA_ENABLE' | \
  sudo install -m 0640 -g "$(id -gn)" /dev/stdin /opt/open5gs-k3s/state/ru-credentials
sudo systemctl restart open5gs-k3s-ru
```

---

## 2. free5GC (opcional)

**Máquina do core**, com a parte 1 instalada.

```bash
sudo ./free5gc/setup-gtp5g.sh             # módulo do kernel do UPF (uma vez; DKMS)
nano free5gc/free5gc.env                  # IPs na fibra, pools, nome da rede
./free5gc/install.sh                      # sem sudo; namespace free5gc
./free5gc/install.sh --importar-open5gs   # copia os SIMs cadastrados no Open5GS
./free5gc/test.sh                         # "6 ok, 0 falha(s)"
sudo ./install.sh --dashboard-only        # o painel passa a oferecer a troca de core
```

O free5GC sobe ligado. Para deixá-lo como reserva, troque de volta para o Open5GS pelo painel (aba Controle →
Core ativo). Detalhes: [componentes/free5gc.md](componentes/free5gc.md).

---

## 3. Rádio: OCUDU em Kubernetes

> **Depende do seu setup.** Os valores de `ran/ocudu/ocudu.env` são do setup de referência (Intel E810 + LiteOn,
> split 7.2). Revise todos antes de começar.

Cada passo indica a máquina. Comandos `./ran/ocudu/…` rodam na **máquina do core**, dentro do repositório;
comandos `~/innovanetwork-ran/no-ran.sh …` rodam na **máquina do RAN**.

### 3.1 Configurar — máquina do core

```bash
nano ran/ocudu/ocudu.env
```

| Variável | Exemplo | Significado |
|---|---|---|
| `OCUDU_NODE`, `OCUDU_NODE_SSH` | `innovaserver`, `innovaserver@10.10.0.1` | nome do nó e acesso SSH pela fibra |
| `OCUDU_NODE_IP`, `OCUDU_NODE_IFACE` | `10.10.0.1`, `ens4f3np3` | IP e interface do nó no cluster (a fibra, **nunca** o fronthaul) |
| `OCUDU_SERVER_VIA` | `10.10.0.2` | IP da máquina do core na fibra (rota até `10.254.254.1`) |
| `OCUDU_SRC_DIR`, `OCUDU_CONFIG_DIR` | `/home/innovaserver/ocudu`, `…/configs` | código e `.yml` do gNB no nó |
| `OCUDU_DEFAULT_CONFIG`, `OCUDU_EXTRA_CONFIG` | `gnb_ru_liteon_SLPIT_CORE`, `metricas.yml` | `.yml` padrão e o 2º `-c` (métricas na porta 8001) |
| `OCUDU_CPUS` | `0-17` | CPUs do gNB (`taskset`) |
| `OCUDU_HUGEPAGES_1G`, `OCUDU_MEMORY_REQUEST` | `2Gi`, `2Gi` | hugepages e memória pedidas pelo pod |
| `OCUDU_IMAGE*`, `OCUDU_BUILD_JOBS` | `innovanetwork/ocudu-gnb`, `8` | imagem (tag = commit do código) e compilação |

### 3.2 Copiar os scripts para o nó — máquina do core

```bash
./ran/ocudu/install.sh copiar
```

Cria `~/innovanetwork-ran/` no nó (modo 700) com `no-ran.sh` e `ocudu.env`.

### 3.3 Compilar a imagem do gNB — máquina do RAN (sudo)

```bash
sudo ~/innovanetwork-ran/no-ran.sh imagem 2>&1 | tee ~/innovanetwork-ran/build.log
```

Exporta o **commit atual** do código (`git archive`, sem a pasta `build/` nativa) e compila com o **Dockerfile
oficial** do OCUDU (alvo `runtime-dpdk`, `-march=native`). Resultado: `innovanetwork/ocudu-gnb:<commit>`
(~140 MB, ~15 min). Pesa na máquina: evite durante experimentos.

### 3.4 Liberar o servidor e gerar o token — máquina do core (sudo)

```bash
sudo ./ran/ocudu/install.sh preparar
```

Libera o nó no firewall (UFW, se ativo) e cria um token de entrada **válido por 2 h**, copiado ao nó em
`~/innovanetwork-ran/join.env` (modo 600). O token nunca aparece na tela.

### 3.5 Entrar no cluster — máquina do RAN (sudo)

```bash
sudo ~/innovanetwork-ran/no-ran.sh entrar 2>&1 | tee ~/innovanetwork-ran/entrar.log
```

Verifica conflitos (outro Kubernetes nas portas do kubelet), cria a rota até o servidor, grava a configuração do
agente (IP, interface, rótulo, taint), instala o k3s agente na mesma versão do servidor, apaga o token e importa a
imagem. Conferir na máquina do core:

```bash
kubectl get nodes -o wide     # o nó do RAN "Ready", INTERNAL-IP 10.10.0.1
```

Se a imagem foi compilada depois: `sudo ~/innovanetwork-ran/no-ran.sh importar`.

### 3.6 Criar o Deployment — máquina do core

```bash
./ran/ocudu/install.sh --dry-run   # gera e valida, sem aplicar
./ran/ocudu/install.sh             # namespace ocudu + Deployment com 0 réplicas (gNB parado)
```

### 3.7 Ligar o gNB — máquina do core

Antes: core ligado, PTP/GNSS válidos, O-RU pronta e **nenhum gNB nativo rodando** no nó.

```bash
./ran/ocudu/gnb.sh configs                            # .yml disponíveis e o AMF de cada um
./ran/ocudu/gnb.sh iniciar gnb_ru_liteon_SLPIT_CORE
./ran/ocudu/gnb.sh log -f                             # esperar "N2: Connection to AMF … completed"
```

### 3.8 Controlar pelo painel

No `config.env`: `GNB_CTL_MODE="k8s"` (e `GNB_CTL_SSH`, `GNB_CTL_DIR` do nó). Depois:

```bash
sudo ./install.sh --dashboard-only
```

A aba **Controle** passa a mostrar o cartão **gNB (Kubernetes)**, com iniciar/parar/reiniciar e a escolha do
`.yml`. Tutorial completo com resultados esperados: [OCUDU em Kubernetes](tutoriais/03-ocudu-em-kubernetes.md).

---

## Verificação final

| O quê | Como | Esperado |
|---|---|---|
| Cluster | `kubectl get nodes` | dois nós `Ready` |
| Core | `./test.sh` | `7 verificações OK` |
| gNB | `./ran/ocudu/gnb.sh log` | `N2: Connection to AMF … completed`, `gNB started` |
| O-RU | painel → aba RU | `SYNCHRONIZED`, DU `Ready`, ~90 % dos pacotes no tempo |
| Celular | painel → Visão geral | registrado, sessão com IP do pool |

## Desinstalar

| O quê | Comando |
|---|---|
| gNB (Deployment e namespace) | `./ran/ocudu/install.sh --remover` |
| nó do RAN | no nó: `sudo ~/innovanetwork-ran/no-ran.sh sair`; no core: `kubectl delete node <nó>` |
| free5GC | `./free5gc/uninstall.sh`; módulo: `sudo ./free5gc/setup-gtp5g.sh --remove` |
| core e painel | `sudo ./uninstall.sh` (`--k3s` remove o k3s; `--purge` tudo o que o install criou) |
