# Desenvolvimento

Para entender o InnovaNetwork por dentro, mostrar o projeto e estendê-lo: onde cada coisa está no código, como uma
configuração vira um pod, e como mudar cores, gNB e painel. As referências usam nomes de função (procure com
`grep -n`).

## 1. O mapa em uma frase por peça

| Peça | Em uma frase | Onde |
|---|---|---|
| `config.env` | **a única fonte de parâmetros**: PLMN, slices, IPs da fibra, gNB, RU, painel | `config.env` |
| `install.sh` | lê o `config.env`, prepara a máquina, instala o k3s e aplica tudo com Helm, em etapas idempotentes | `install.sh` |
| `scripts/lib/common.sh` | a "biblioteca" do instalador: valida a config e **gera os values do Helm** | `scripts/lib/common.sh` |
| Charts Gradiant | os charts prontos do Open5GS e do UERANSIM (não editados; ajustados por values e post-renderers) | baixados em `/opt/open5gs-k3s` |
| `helm/postrender/` | pequenas correções nos charts na hora de aplicar | `amf-ngap-net1.sh`, `drop-gnb-hpa.sh` |
| `free5gc/` | o segundo core: gera os manifestos sozinho (sem chart) a partir do `config.env` + `free5gc.env` | `free5gc/lib/render.py` |
| `dashboard/app/` | o painel: um servidor Python sem dependências + páginas HTML/JS | `server.py`, `control.py`, `*.js` |
| `dashboard/agent/` | agentes que rodam na máquina do core e falam com o nó do RAN e a O-RU | `gnb-ctl-agent.py`, `gnb-log-agent.py`, `ru-agent.py`, `host-agent.py` |
| `ran/ocudu/` | o gNB OCUDU em Kubernetes: imagem, entrada do nó, Deployment, `gnb.sh` | `install.sh`, `no-ran.sh`, `gnb.sh`, `lib/render.py` |

Tamanho: ~8.000 linhas de código próprio (shell, Python, JavaScript), sem dependências além da biblioteca padrão
do Python, do Helm e dos charts.

---

## 2. Do `config.env` ao pod rodando (o caminho de uma configuração)

Exemplo: o IP do AMF na fibra, `AMF_N2_IP="10.10.0.10"`.

1. **Definido** em `config.env` (comentário ao lado explica que é o `cu_cp.amf.addr` do gNB).
2. **Validado** em `validate_config` (`scripts/lib/common.sh`): confere formato, se está dentro do
   `RAN_LINK_CIDR` e se não colide com outros IPs.
3. **Vira values do Helm** em `_nf_common` (`scripts/lib/common.sh`): cada função de rede ganha a anotação do
   Multus (`ran_link_annotation`) com o IP fixo na fibra; o AMF em `common.sh`.
4. **Hash de configuração**: `common.sh` põe `open5gs-k3s/config-hash` nos pods — se a config muda, o hash
   muda e o pod é recriado (os charts não fazem isso sozinhos).
5. **Aplicado** por `step_deploy_core` (`install.sh`) com `helm upgrade --install` e o post-renderer
   `helm/postrender/amf-ngap-net1.sh`, que muda o N2 do AMF de `eth0` para `net1` (a interface da fibra).
6. **No pod**: a anotação do Multus mostra as duas interfaces do AMF (troque `open5gs` por `free5gc` para o
   outro core):
   ```bash
   kubectl -n open5gs get pods -o name | grep amf      # nome do pod
   kubectl -n open5gs get pod <nome> -o jsonpath='{.metadata.annotations.k8s\.v1\.cni\.cncf\.io/network-status}'
   # → eth0 10.42.x.x (rede dos pods)  e  net1 10.10.0.10 (fibra)
   ```

As etapas do install, na ordem (`install.sh`, `main`): pacotes → módulos (SCTP) → sysctl → perfil
desktop/servidor → interface `k3s0` → k3s → Helm → charts → link da fibra (Multus) → core → assinantes →
UERANSIM → painel → unit de boot → kubeconfig do usuário.

---

## 3. A rede (o que está em cada interface)

```
celular ──rádio n78── LiteOn ──fronthaul 7.2 (E810 porta 1, DPDK)── OCUDU (nó do RAN)
                                                                       │ 10.10.0.1  (E810 porta)
                                                                fibra 10.10.0.0/24, MTU 9000
                                                                       │ 10.10.0.2  (máquina do core, enp5s0f1)
                         ┌─────────────── macvlan "ran-link" (Multus) ─┴──────────────┐
                    AMF net1 10.10.0.10 (N2)   UPF net1 10.10.0.11 (N3)   gNB UERANSIM net1 10.10.0.20
                    AMF net1 10.10.0.30        UPF net1 10.10.0.31        gNB UERANSIM net1 10.10.0.32   (free5GC)
                         │ eth0 (rede dos pods, flannel): SBI, PFCP (N4), MongoDB…
                    UPF ──NAT── internet (N6, rota padrão da máquina do core)
```

- **Rede da fibra no Kubernetes**: `render_ran_link_nad` (`common.sh`) cria o NetworkAttachmentDefinition
  `ran-link` (macvlan em `RAN_LINK_IFACE`). O Multus foi instalado por `step_ran_link` (`install.sh`).
- **PFCP sem NAT**: Service headless: o SMF fala direto com o IP do pod do UPF.
- **Nó do k3s em `k3s0`** (10.254.254.1, `step_stable_netif`, `install.sh`): o cluster não depende do IP da
  universidade (DHCP).

---

## 4. Os dois cores

| | Open5GS | free5GC |
|---|---|---|
| Como é instalado | charts Gradiant + values gerados (`common.sh`) | manifestos gerados do zero por `free5gc/lib/render.py` (o chart oficial fixava PLMN/IPs) |
| Configuração própria | `config.env` | `free5gc/free5gc.env` (+ o comum do `config.env`) |
| Ordem de subida | `CoreOps.ORDERS["open5gs"]` (`dashboard/app/control.py`) | `CoreOps.ORDERS["free5gc"]` (`control.py`); no render, `ORDER` (`render.py`) |
| Particularidades | NRF com `servingList` do PLMN (`common.sh`), `Recreate` (`common.sh`) | voz IMS anunciada (`imsVoPS: 1`, `render.py`), DNN `ims` extra (`render.py`), nome da rede (`render.py`) |

`render.py` em 4 partes: lê o ambiente  → monta a config oficial de cada função (`CFG`
em diante) → cria Deployments/Services (`deployment`, `service` 246, `manifests`) → Role do painel
(`dashboard_rbac`,) e values do UERANSIM (`ueransim`,).

---

## 5. O painel por dentro

```
navegador ──HTTP :30998──► pod "dashboard" (namespace open5gs)
                             server.py ── API do Kubernetes (pods, logs, escalar)
                                       ── WebSocket do gNB (métricas, ws://10.10.0.1:8001)
                                       ◄─ agentes na máquina do core (POST /api/ingest/*): log do gNB, controle do gNB, RU, máquinas
                             control.py ── iniciar/parar/trocar core, em ordem e conferindo
```

| Para mostrar… | Abra |
|---|---|
| como o painel sabe que um celular registrou | expressões regulares dos logs: Open5GS `server.py` (`RE_REG_OK`), free5GC `server.py` (`RE5_REG_OK`); quem as aplica: `CoreState.line` (`server.py`) e `_line_f5` (701) |
| de onde vem a lista de pods/NFs | `CoreCollector` (`server.py`) |
| qual é o core ativo | `CoreSet.active` (`server.py`): o único com AMF rodando; senão, o último escolhido |
| a troca de core | `Controller._switch` (`control.py`): para o gNB → para o core atual → grava o ativo → sobe o novo em ordem → religa o gNB |
| a conferência de cada etapa | `CoreOps._verify` (`control.py`): espera o pod e procura no log, ex.: AMF "Listen on 10.10.0.30" |
| como o gNB é ligado | `GnbCtl` (`control.py`) → agente `dashboard/agent/gnb-ctl-agent.py` → `ran/ocudu/gnb.sh` → réplicas do Deployment `ocudu-gnb` (modo `k8s`) |
| o login único | `Admin` no fim de `dashboard/app/settings.js`; no servidor `class Admin` (`server.py`) |
| a aba Documentação | `dashboard/app/docs.js` (leitor de Markdown) e `docs_list`/`doc_read` em `server.py` |

O painel não tem dependências: só a biblioteca padrão do Python e o uPlot (gráficos) guardado no repositório.
É instalado como ConfigMap + Deployment por `render_dashboard` (`common.sh`).

---

## 6. Roteiros de demonstração

Cada roteiro: **o que dizer → o que mostrar → onde está no código**. Todos os comandos rodam na máquina do core,
na pasta do repositório.

### 6.1 "É tudo Kubernetes" (2 min)

```bash
kubectl get nodes -o wide                 # um nó k3s
kubectl get pods -n open5gs -o wide       # Open5GS + UERANSIM + painel
kubectl get pods -n free5gc               # o segundo core (0 pods quando desligado)
kubectl get net-attach-def -A             # a rede "ran-link" na fibra (Multus)
```
Código: `install.sh` (`main`) e `docs/arquitetura.md`.

### 6.2 "Uma configuração só" (3 min)

Abra `config.env` na seção de slices (): duas slices, cada uma com SST, SD, DNN e pool. Mostre que o
mesmo arquivo alimenta o Open5GS (`common.sh`), o free5GC (`render.py`), o UERANSIM e o painel. No painel:
aba **Configuração** (edita o arquivo com diff e validação).

### 6.3 "Um celular entrando na rede" (5 min)

1. Painel → **Logs** → AMF (ao vivo; no campo de filtro, `imsi-`).
2. Ligue o modo avião do celular e desligue.
3. Mostre na ordem: NG Setup (já feito) → Registration Request → autenticação → Registration Complete → sessão
   PDU com IP (SMF).
4. **Visão geral**: o celular aparece com IMSI, DNN e IP; **Rádio**: vazão, MCS, SNR dele.
Código: as expressões da seção 5 (`server.py`).

### 6.4 "Trocar de core em um clique" (3–6 min)

Painel → **🔒 Admin** → **Controle** → cartão **Core ativo** → clicar no outro core → "Trocar agora" com
"religar o gNB" marcado. Mostre o andamento linha a linha (cada etapa conferida no log) e o celular voltando com
o nome da outra rede (InnovaOpen5GS / InnovaFree5GC).
Código: `control.py` (`_switch`).

### 6.5 "Teste automático ponta a ponta" (1 min)

```bash
./test.sh            # Open5GS: pods → NRF → NG Setup → registro → sessão → ping 8.8.8.8 (7 verificações)
./free5gc/test.sh    # free5GC: 6 verificações
```

### 6.6 "O rádio por dentro"

Painel → **RU**: sincronismo PTP, potência, temperatura, pacotes do fronthaul **no tempo / adiantados /
atrasados** (o indicador de saúde do fronthaul: ~91 % no tempo é o normal). **Máquinas** → nó do RAN: os núcleos
reservados ao gNB (0–17) aparecem com fundo azul.

### 6.7 "Experimentos reproduzíveis"

Botão **● Gravar experimento** (topo) → nome e notas → depois, aba **Histórico**: KPIs do período e comparação
lado a lado de dois experimentos. Cada experimento guarda o core em uso.

---

## 7. Perguntas que costumam aparecer

| Pergunta | Resposta curta |
|---|---|
| Por que k3s e não um Kubernetes "completo"? | é Kubernetes certificado num binário só: leve, com containerd, ServiceLB e local-path prontos |
| Por que só N2 e N3 na fibra? | são as únicas interfaces que falam com o gNB; o resto fica na rede interna do cluster |
| Por que o servidor do k3s tem IP próprio (`k3s0`)? | o IP da rede local muda (DHCP) e o cluster não pode depender dele |
| Por que dois cores? | pesquisas diferentes pedem cores diferentes; um por vez, sem misturar |
| Por que o gNB usa a rede do host e privilégios? | DPDK, VF da NIC e PTP exigem acesso direto ao hardware, como no serviço nativo |
| Por que manifesto próprio para o gNB, e não o chart oficial? | o chart muda o comando e os argumentos do DPDK; o manifesto reproduz o comando validado |
| O que acontece num reboot? | só o painel sobe; core e gNB são ligados pelo operador, depois do GNSS ([operação](operacao.md#2-depois-de-ligar-as-máquinas)) |
| Onde estão as senhas? | nunca no git: Secret do Kubernetes e arquivos do root em `/opt/open5gs-k3s/state/` |

---

## 8. Estender o projeto

| Quero… | Onde mexer |
|---|---|
| expor um parâmetro novo do Open5GS | declarar no `config.env` → padrão em `load_config` e validação em `validate_config` (`scripts/lib/common.sh`) → usar em `render_open5gs_values` |
| mudar a configuração de uma função do free5GC | `CFG` em `free5gc/lib/render.py` |
| outro gNB/hardware no nó do RAN | `ran/ocudu/ocudu.env` e os `.yml`; o Deployment em `ran/ocudu/lib/render.py` |
| um core novo | seguir o modelo do `free5gc/`: instalador próprio, namespace com rótulo `innovanetwork/core`, ordem de subida em `CoreOps.ORDERS` (`dashboard/app/control.py`) |
| uma aba ou métrica no painel | backend em `dashboard/app/server.py`, página em `index.html` + `*.js` |
| um agente novo | `dashboard/agent/`, unit criada em `install.sh` (modelo: `setup_gnb_ctl_agent`), dados via `POST /api/ingest/*` com o token |

### Modificar o código do Open5GS

O Open5GS vem das imagens dos charts (`OPEN5GS_IMAGE_TAG`). Para usar um código modificado:

1. clonar `https://github.com/open5gs/open5gs` na versão em uso (`v2.7.5`) e fazer as mudanças;
2. gerar uma imagem compatível com a dos charts (mesmos binários em `/opt/open5gs/bin`);
3. importar no k3s: `docker save <imagem> | sudo k3s ctr -n k8s.io images import -`;
4. apontar `OPEN5GS_IMAGE_TAG` (e o repositório, se mudou) e rodar `sudo ./install.sh --deploy-only`.

### Modificar o código do OCUDU

Commit no repositório do OCUDU → `sudo ~/innovanetwork-ran/no-ran.sh imagem` → `./ran/ocudu/install.sh` → reiniciar o
gNB. Passo a passo: [tutorial 7](tutoriais/07-alterar-o-gnb.md).

### Verificações antes de propor uma mudança

```bash
bash -n install.sh uninstall.sh test.sh scripts/*.sh scripts/lib/*.sh free5gc/*.sh ran/ocudu/*.sh
shellcheck install.sh scripts/lib/common.sh            # se disponível
python3 -m py_compile dashboard/app/*.py dashboard/agent/*.py free5gc/lib/*.py ran/ocudu/lib/*.py
./free5gc/install.sh --dry-run; ./ran/ocudu/install.sh --dry-run
./test.sh
```

Rodar o painel fora do cluster: [componentes/painel.md](componentes/painel.md#desenvolvimento).
