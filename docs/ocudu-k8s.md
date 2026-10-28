# OCUDU no Kubernetes (`ran/ocudu/`)

Como o gNB OCUDU passa a rodar como pod no k3s do InnovaNetwork, **passo a passo, como foi feito**, com os
problemas encontrados e as correções. Serve para repetir a instalação e para estudo.

> **Depende do seu setup.** Este componente roda no Kubernetes o gNB que **já funciona** na máquina. A
> preparação da máquina (kernel realtime, CPUs isoladas, hugepages, DPDK/VF, PTP/GNSS, o `.yml` do gNB) não é
> feita aqui. Os valores de `ran/ocudu/ocudu.env` são do setup Innova (Intel E810-C + RU LiteOn, split 7.2).

Decisões: 37 (OCUDU no Kubernetes) e 38 (arquitetura da v3) em [decisoes.md](decisoes.md).

---

## 1. Como fica

```
torre2 (servidor do k3s, 10.254.254.1)                innovaserver (nó do RAN, 10.10.0.1)
  core Open5GS / free5GC, painel                         pod "ocudu-gnb" (namespace ocudu)
        │                                                  rede do host + privileged
        └──────────── fibra 10.10.0.0/24 ─────────────────  taskset -c 0-17 gnb -c <yml> -c metricas.yml
                (k3s: API, flannel; N2/N3 do gNB)          E810 (VF em DPDK) ── LiteOn
```

- **Um cluster só.** O innovaserver entra como **nó** do k3s do torre2, pela fibra. O servidor continua no
  `10.254.254.1` (interface `k3s0` do torre2); o nó chega lá por uma rota `10.254.254.1 via 10.10.0.2`.
  O k3s do torre2 **não é reinstalado nem reiniciado**.
- **Nó reservado ao RAN:** rótulo `innovanetwork/role=ran` e taint `innovanetwork/ran=true:NoSchedule`. Só o
  gNB (que tolera o taint) e os DaemonSets do sistema (Multus) rodam lá.
- **O gNB roda exatamente como no serviço nativo** `ocudu-gnb@`: mesmo binário (compilado do mesmo commit),
  mesmo comando, `.yml` lidos de `~/ocudu/configs` do host, log em `/tmp/gnb.log` do host, rede do host
  (N2/N3 em `10.10.0.1`, métricas `:8001`). O painel não percebe a diferença.
- Por que **manifesto próprio** e não o chart oficial `ocudu/ocudu-gnb`: o chart exige o CPU Manager do
  Kubernetes, reescreve o `eal_args` do DPDK e roda com um só `-c`. Para a v3.0 a regra é mudar uma coisa por
  vez; o chart pode virar opção depois.

## 2. Arquivos

| Arquivo | Onde roda | Para quê |
|---|---|---|
| `ran/ocudu/ocudu.env` | — | parâmetros do setup (nó, IPs, CPUs, pasta dos `.yml`, imagem) |
| `ran/ocudu/install.sh` | torre2 | `copiar` (scripts para o nó) · `preparar` (sudo: UFW + token) · sem argumento: namespace e Deployment |
| `ran/ocudu/no-ran.sh` | **nó** (`~/innovanetwork-ran/`), sudo | `imagem` · `importar` · `entrar` · `sair` · `estado` |
| `ran/ocudu/gnb.sh` | torre2 | `iniciar [yml]` · `parar` · `estado` · `log [-f]` · `configs` |
| `ran/ocudu/lib/render.py` | torre2 | gera Namespace, descritor e Deployment |

## 3. Passo a passo (como foi executado)

Regra: cada comando diz **em qual máquina** roda. Os de `./ran/ocudu/…` rodam no torre2, dentro de
`~/InnovaNetwork-v3`; os de `~/innovanetwork-ran/no-ran.sh …` rodam no innovaserver.

### 3.0 Antes de qualquer teste com rádio (depois de um boot)

No innovaserver: GPS válido (`journalctl -u ts2phc -n1` mostra `s2`). Se o relógio deu salto, com o gNB
parado: `sudo systemctl restart ptp4l-gm phc2sys` (acerta o relógio do sistema e recoloca o XDP) e reiniciar a
RU. Ver [ran-ocudu-liteon.md](ran-ocudu-liteon.md).

### 3.1 Copiar os scripts para o nó — torre2

```bash
./ran/ocudu/install.sh copiar
```
Cria `~/innovanetwork-ran/` no nó (modo 700) com `no-ran.sh` e `ocudu.env`.

### 3.2 Compilar a imagem do gNB — innovaserver (sudo)

```bash
sudo ~/innovanetwork-ran/no-ran.sh imagem 2>&1 | tee ~/innovanetwork-ran/build.log
```
- Exporta o **commit atual** de `~/ocudu` (`git archive`) para `/var/tmp/innovanetwork-ocudu-src` — sem a pasta
  `build/` nativa (~2 GB), que quebraria o cmake dentro da imagem.
- `docker build` com o **Dockerfile oficial** do OCUDU, alvo `runtime-dpdk`, `COMPONENT=gnb`, Ubuntu 24.04,
  `-march=native`, 8 jobs (só nas CPUs não isoladas).
- Resultado: `innovanetwork/ocudu-gnb:<commit curto>` (aqui `6fe9ad0`), ~13 min. O script confere que a imagem
  tem `gnb`, `taskset` e `bash`.
- Precisa de sudo porque o usuário não está no grupo `docker` (o grupo equivale a root; preferimos não dar).
- Pesa na máquina (CPU, memória, cache): evite durante experimentos de outras pessoas no mesmo servidor.

### 3.3 Liberar o torre2 e gerar o token — torre2 (sudo)

```bash
sudo ./ran/ocudu/install.sh preparar
```
- UFW do torre2 (se ativo): libera `10.10.0.1` e as redes do k3s (`10.42.0.0/16`, `10.43.0.0/16`).
- `k3s token create --ttl 2h`: token de entrada **temporário**, copiado ao nó em `~/innovanetwork-ran/join.env`
  (modo 600). Nunca aparece na tela.

### 3.4 Entrar no cluster — innovaserver (sudo)

```bash
sudo ~/innovanetwork-ran/no-ran.sh entrar 2>&1 | tee ~/innovanetwork-ran/entrar.log
```
1. Verificações: nenhum outro Kubernetes nas portas do kubelet; limpa restos de tentativa anterior.
2. Unit `innovanetwork-k3s-route.service`: rota `10.254.254.1/32 via 10.10.0.2 dev ens4f3np3` (persistente,
   sem `netplan`).
3. UFW do nó (se ativo): libera o torre2 e as redes do k3s.
4. `/etc/rancher/k3s/config.yaml`: `node-ip 10.10.0.1`, `flannel-iface ens4f3np3` (**nunca** a porta do
   fronthaul), rótulo e taint.
5. Instalador oficial do k3s, mesma versão do servidor (`v1.36.5+k3s1`), modo agente.
6. Apaga o token e importa a imagem (se já compilada).

Conferir no torre2: `kubectl get nodes -o wide` → `innovaserver Ready … 10.10.0.1`.

### 3.5 Importar a imagem no k3s — innovaserver (sudo)

```bash
sudo ~/innovanetwork-ran/no-ran.sh importar 2>&1 | tee ~/innovanetwork-ran/importar.log
```
`docker save | k3s ctr -n k8s.io images import -`. *(Em andamento — ver seção 5.)*

### 3.6 Namespace e Deployment — torre2

```bash
./ran/ocudu/install.sh --dry-run   # gera e valida, sem aplicar
./ran/ocudu/install.sh             # aplica: namespace "ocudu", Deployment com 0 réplicas (parado)
```
*(Pendente.)*

### 3.7 Ligar o gNB pelo Kubernetes — torre2

```bash
./ran/ocudu/gnb.sh configs                          # .yml disponíveis e o AMF de cada um
./ran/ocudu/gnb.sh iniciar gnb_ru_liteon_SLPIT_CORE # o serviço nativo ocudu-gnb@ precisa estar parado
./ran/ocudu/gnb.sh log -f
./ran/ocudu/gnb.sh parar                            # SIGINT ao gNB, como Ctrl+C
```
*(Pendente.)*

## 4. Verificações feitas

| O quê | Como | Resultado (2026-10-28) |
|---|---|---|
| k3s fora das CPUs do gNB | `taskset -pc <pid do k3s>` no nó | `18-31` (as 0–17 seguem reservadas) |
| Rede de pods entre os nós | `ping 10.42.0.1` a partir do nó | 0,4 ms |
| Core e painel intactos | `kubectl get pods -A` | sem reinício |
| Rótulo e taint | `kubectl describe node innovaserver` | `innovanetwork/role=ran`, `innovanetwork/ran=true:NoSchedule` |

## 5. Problemas encontrados (e a correção)

| # | Sintoma | Causa | Correção |
|---|---|---|---|
| 1 | build falha em `build_rohc.sh` com `curl: (35) Connection reset by peer` | `rohc-lib.org` derruba conexões da rede da universidade | imagem **sem ROHC**, igual ao gNB nativo (que foi compilado sem). `OCUDU_IMAGE_ROHC=false` troca o script só na cópia temporária |
| 2 | `entrar` rodado no torre2: `command not found` | comando do nó executado na máquina errada | nenhuma mudança; a regra de "em qual máquina" está em cada passo |
| 3 | k3s instala mas não sobe: `listen tcp 0.0.0.0:10250: bind: address already in use` | **MicroK8s** instalado no nó (snap, desde 2026-08-04, com namespaces do RIC O-RAN) ocupando as portas | `sudo microk8s stop` (desliga e não volta no boot; **não apaga nada**). O `entrar` agora detecta isso antes de instalar |
| 4 | depois de liberar as portas, o agente fica em ciclo: `Node authorization rejected` + `ContentLength=… with Body length 0` | certificados da tentativa que falhou (o nó nunca se registrou) + defeito conhecido do k3s na nova tentativa | `sudo systemctl stop k3s-agent; sudo rm -rf /var/lib/rancher/k3s/agent; sudo systemctl start k3s-agent`. O `entrar` agora limpa isso sozinho |
| 5 | `importar` não colocou a imagem no k3s | em análise | — |

Observação: a rede de pods ficou com MTU diferente nos dois nós (8950 no innovaserver, fibra 9000; 1450 no
torre2, `k3s0`). Não afeta o gNB (rede do host). A revisar.

## 6. MicroK8s e o nosso k3s na mesma máquina

Os dois **não rodam ao mesmo tempo** (mesmas portas). Trocar, no innovaserver:

```bash
# usar o MicroK8s (ex.: RIC):          # voltar ao InnovaNetwork:
sudo systemctl disable --now k3s-agent  sudo microk8s stop
sudo microk8s start                     sudo systemctl enable --now k3s-agent
```

## 7. Voltar atrás

| Desfazer | Comando |
|---|---|
| gNB pelo Kubernetes → nativo | `./ran/ocudu/gnb.sh parar`; depois o painel (serviço `ocudu-gnb@`) como antes |
| Tirar o Deployment | `./ran/ocudu/install.sh --remover` (apaga o namespace `ocudu`) |
| Tirar o nó do cluster | no nó: `sudo ~/innovanetwork-ran/no-ran.sh sair`; no torre2: `kubectl delete node innovaserver` |
| MicroK8s de volta | seção 6 |
