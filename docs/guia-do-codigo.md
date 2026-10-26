# Guia do código e das demonstrações (v2.1)

Para **entender** o InnovaNetwork por dentro e **mostrar** a outras pessoas: onde cada coisa está no código
(arquivo:linha na tag `v2.1-innovanetwork`) e roteiros de demonstração prontos. Visão geral: [README](../README.md).

> As linhas citadas valem para a tag `v2.1-innovanetwork`; se o código mudar, procure pelo nome da função.

---

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
| `dashboard/agent/` | agentes que rodam no torre2 e falam com o innovaserver/RU por SSH | `gnb-ctl-agent.py`, `gnb-log-agent.py`, `ru-agent.py`, `host-agent.py` |
| innovaserver | OCUDU + LiteOn, fora do git do projeto (cópia no repositório de contexto) | `~/ocudu/configs/*.yml` |

Tamanho: ~7.500 linhas de código próprio (shell, Python, JavaScript).

---

## 2. Do `config.env` ao pod rodando (o caminho de uma configuração)

Exemplo: o IP do AMF na fibra, `AMF_N2_IP="10.10.0.10"`.

1. **Definido** em `config.env:214` (comentário ao lado explica que é o `cu_cp.amf.addr` do gNB).
2. **Validado** em `validate_config` (`scripts/lib/common.sh:174`): confere formato, se está dentro do
   `RAN_LINK_CIDR` e se não colide com outros IPs.
3. **Vira values do Helm** em `_nf_common` (`scripts/lib/common.sh:418`): cada função de rede ganha a anotação do
   Multus (`ran_link_annotation`, linha 414) com o IP fixo na fibra; o AMF em `common.sh:473`.
4. **Hash de configuração**: `common.sh:425` põe `open5gs-k3s/config-hash` nos pods — se a config muda, o hash
   muda e o pod é recriado (os charts não fazem isso sozinhos — decisão 14).
5. **Aplicado** por `step_deploy_core` (`install.sh:387`) com `helm upgrade --install` e o post-renderer
   `helm/postrender/amf-ngap-net1.sh`, que muda o N2 do AMF de `eth0` para `net1` (a interface da fibra).
6. **No pod**: a anotação do Multus mostra as duas interfaces do AMF (troque `open5gs` por `free5gc` para o
   outro core):
   ```bash
   kubectl -n open5gs get pods -o name | grep amf      # nome do pod
   kubectl -n open5gs get pod <nome> -o jsonpath='{.metadata.annotations.k8s\.v1\.cni\.cncf\.io/network-status}'
   # → eth0 10.42.x.x (rede dos pods)  e  net1 10.10.0.10 (fibra)
   ```

As etapas do install, na ordem (`install.sh:864`, `main`): pacotes → módulos (SCTP) → sysctl → perfil
desktop/servidor → interface `k3s0` → k3s → Helm → charts → link da fibra (Multus) → core → assinantes →
UERANSIM → painel → unit de boot → kubeconfig do usuário.

---

## 3. A rede (o que está em cada interface)

```
celular ──rádio n78── LiteOn ──fronthaul 7.2 (E810 porta 1, DPDK)── OCUDU (innovaserver)
                                                                       │ 10.10.0.1  (E810 porta 4)
                                                                fibra 10.10.0.0/24, MTU 9000
                                                                       │ 10.10.0.2  (torre2 enp5s0f1)
                         ┌─────────────── macvlan "ran-link" (Multus) ─┴──────────────┐
                    AMF net1 10.10.0.10 (N2)   UPF net1 10.10.0.11 (N3)   gNB UERANSIM net1 10.10.0.20
                    AMF net1 10.10.0.30        UPF net1 10.10.0.31        gNB UERANSIM net1 10.10.0.32   (free5GC)
                         │ eth0 (rede dos pods, flannel): SBI, PFCP (N4), MongoDB…
                    UPF ──NAT── internet (N6, rota padrão do torre2)
```

- **Rede da fibra no Kubernetes**: `render_ran_link_nad` (`common.sh:573`) cria o NetworkAttachmentDefinition
  `ran-link` (macvlan em `RAN_LINK_IFACE`). O Multus foi instalado por `step_ran_link` (`install.sh:366`).
- **PFCP sem NAT**: Service headless (decisão 31) — o SMF fala direto com o IP do pod do UPF.
- **Nó do k3s em `k3s0`** (10.254.254.1, `step_stable_netif`, `install.sh:169`): o cluster não depende do IP da
  universidade (DHCP).

---

## 4. Os dois cores

| | Open5GS | free5GC |
|---|---|---|
| Como é instalado | charts Gradiant + values gerados (`common.sh`) | manifestos gerados do zero por `free5gc/lib/render.py` (o chart oficial fixava PLMN/IPs) |
| Configuração própria | `config.env` | `free5gc/free5gc.env` (+ o comum do `config.env`) |
| Ordem de subida | `CoreOps.ORDERS["open5gs"]` (`dashboard/app/control.py:65`) | `CoreOps.ORDERS["free5gc"]` (`control.py:68`); no render, `ORDER` (`render.py:196`) |
| Particularidades | NRF com `servingList` do PLMN (`common.sh:466`), `Recreate` (`common.sh:420`) | voz IMS anunciada (`imsVoPS: 1`, `render.py:85`), DNN `ims` extra (`render.py:42`), nome da rede (`render.py:82`) |

`render.py` em 4 partes: lê o ambiente (linhas 13–55) → monta a config oficial de cada função (`CFG`, linha 67
em diante) → cria Deployments/Services (`deployment` linha 217, `service` 246, `manifests` 260) → Role do painel
(`dashboard_rbac`, 346) e values do UERANSIM (`ueransim`, 361).

---

## 5. O painel por dentro

```
navegador ──HTTP :30998──► pod "dashboard" (namespace open5gs)
                             server.py ── API do Kubernetes (pods, logs, escalar)
                                       ── WebSocket do gNB (métricas, ws://10.10.0.1:8001)
                                       ◄─ agentes no torre2 (POST /api/ingest/*): log do gNB, controle do gNB, RU, máquinas
                             control.py ── iniciar/parar/trocar core, em ordem e conferindo
```

| Para mostrar… | Abra |
|---|---|
| como o painel sabe que um celular registrou | expressões regulares dos logs: Open5GS `server.py:485` (`RE_REG_OK`), free5GC `server.py:500` (`RE5_REG_OK`); quem as aplica: `CoreState.line` (`server.py:641`) e `_line_f5` (701) |
| de onde vem a lista de pods/NFs | `CoreCollector` (`server.py:812`) |
| qual é o core ativo | `CoreSet.active` (`server.py:1417`): o único com AMF rodando; senão, o último escolhido |
| a troca de core | `Controller._switch` (`control.py:461`): para o gNB → para o core atual → grava o ativo → sobe o novo em ordem → religa o gNB |
| a conferência de cada etapa | `CoreOps._verify` (`control.py:312`): espera o pod e procura no log, ex.: AMF "Listen on 10.10.0.30" |
| como o gNB é ligado | `GnbCtl` (`control.py:491`) → agente `dashboard/agent/gnb-ctl-agent.py` → `systemctl start ocudu-gnb@<yml>` no innovaserver |
| o login único | `Admin` no fim de `dashboard/app/settings.js`; no servidor `class Admin` (`server.py:1461`) |
| a aba Documentação | `dashboard/app/docs.js` (leitor de Markdown) e `docs_list`/`doc_read` em `server.py` |

O painel não tem dependências: só a biblioteca padrão do Python e o uPlot (gráficos) guardado no repositório.
É instalado como ConfigMap + Deployment por `render_dashboard` (`common.sh:600`).

---

## 6. Roteiros de demonstração

Cada roteiro: **o que dizer → o que mostrar → onde está no código**. Todos os comandos rodam no torre2
(`ssh torre2`, pasta `~/InnovaNetwork`).

### 6.1 "É tudo Kubernetes" (2 min)

```bash
kubectl get nodes -o wide                 # um nó k3s
kubectl get pods -n open5gs -o wide       # Open5GS + UERANSIM + painel
kubectl get pods -n free5gc               # o segundo core (0 pods quando desligado)
kubectl get net-attach-def -A             # a rede "ran-link" na fibra (Multus)
```
Código: `install.sh` (`main`, linha 864) e `docs/arquitetura.md`.

### 6.2 "Uma configuração só" (3 min)

Abra `config.env` na seção de slices (linha 95): duas slices, cada uma com SST, SD, DNN e pool. Mostre que o
mesmo arquivo alimenta o Open5GS (`common.sh`), o free5GC (`render.py:35`), o UERANSIM e o painel. No painel:
aba **Configuração** (edita o arquivo com diff e validação).

### 6.3 "Um celular entrando na rede" (5 min)

1. Painel → **Logs** → AMF (ao vivo; no campo de filtro, `imsi-`).
2. Ligue o modo avião do celular e desligue.
3. Mostre na ordem: NG Setup (já feito) → Registration Request → autenticação → Registration Complete → sessão
   PDU com IP (SMF).
4. **Visão geral**: o celular aparece com IMSI, DNN e IP; **Rádio**: vazão, MCS, SNR dele.
Código: as expressões da seção 5 (`server.py:485–506`).

### 6.4 "Trocar de core em um clique" (3–6 min)

Painel → **🔒 Admin** → **Controle** → cartão **Core ativo** → clicar no outro core → "Trocar agora" com
"religar o gNB" marcado. Mostre o andamento linha a linha (cada etapa conferida no log) e o celular voltando com
o nome da outra rede (InnovaOpen5GS / InnovaFree5GC).
Código: `control.py:461` (`_switch`).

### 6.5 "Teste automático ponta a ponta" (1 min)

```bash
./test.sh            # Open5GS: pods → NRF → NG Setup → registro → sessão → ping 8.8.8.8 (7 verificações)
./free5gc/test.sh    # free5GC: 6 verificações
```

### 6.6 "O rádio por dentro"

Painel → **RU**: sincronismo PTP, potência, temperatura, pacotes do fronthaul **no tempo / adiantados /
atrasados** (o indicador de saúde do fronthaul: ~91 % no tempo é o normal). **Máquinas** → innovaserver: os núcleos
reservados ao gNB (0–17) aparecem com fundo azul.

### 6.7 "Experimentos reproduzíveis"

Botão **● Gravar experimento** (topo) → nome e notas → depois, aba **Histórico**: KPIs do período e comparação
lado a lado de dois experimentos. Cada experimento guarda o core em uso.

---

## 7. Perguntas que costumam aparecer

| Pergunta | Resposta curta | Onde ver |
|---|---|---|
| Por que k3s e não Kubernetes "completo"? | é Kubernetes certificado, num binário só, ideal para um nó | `docs/decisoes.md`, decisão 1 |
| Por que só N2 e N3 na fibra? | são as únicas interfaces que falam com o gNB; o resto fica na rede interna | decisão 30 |
| Por que o nó do k3s tem IP próprio (`k3s0`)? | o IP da universidade muda (DHCP) e o cluster não pode depender dele | decisão 27 |
| Por que dois cores? | pesquisadores precisam do free5GC; um por vez, sem misturar | decisão 33 |
| O que acontece num reboot? | só o painel sobe; o core e o gNB começam pelo painel; esperar o GPS | `docs/operacao.md`, seção 2 |
| Onde estão as senhas? | nunca no git: Secret do Kubernetes e arquivos do root | `docs/dashboard.md` |
| O OCUDU roda no Kubernetes? | ainda não (serviço do host); é o próximo passo (decisão 37) | `docs/ran-ocudu-liteon.md` |
