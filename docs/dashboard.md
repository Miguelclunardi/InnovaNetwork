# Painel — Innova Center Dashboard

Página web que roda **no próprio cluster do core** (máquina do core) e junta num só lugar:

| Aba | O que mostra | De onde vem |
|---|---|---|
| **Visão geral** | UEs no rádio (vazão, MCS, CQI, RI, BLER, SNR), assinantes vistos pelo core (registro, sessões DNN → IP), pods (estado, reinícios, IP, IP no link RAN), eventos do core (avisos/erros iguais agrupados com contador) | métricas do gNB + API do Kubernetes + logs do AMF/SMF/UPF |
| **Rádio (gNB)** | vazão e PRBs da célula; vazão DL/UL por UE; do UE escolhido: BLER, MCS, CQI/rank, SNR/RSRP do PUSCH, buffers, TA/PHR; latência do escalonador e falhas (HARQ atrasado, PDCCH, UCI). Janela de 1/5/15 min, pausa, exportação CSV | WebSocket de métricas do gNB (OCUDU `remote_control`) |
| **Logs** | log de qualquer pod/contêiner do namespace (core e UERANSIM) e do **gNB real**; ao vivo, filtro por texto ou `/regex/`, filtro por nível, cores, download | API do Kubernetes; agente do log do gNB |
| **Core** | métricas Prometheus do AMF/SMF/UPF/PCF: gNBs, UEs, sessões, tráfego N3 do UPF, tabela com todas as métricas | `:9090/metrics` dos NFs (precisa `OPEN5GS_METRICS=true`) |

Endereço: `http://<IP-do-core>:30998` (`DASHBOARD_NODEPORT`). Sem senha por padrão; com
`DASHBOARD_PASSWORD`, o navegador pede usuário `admin` e a senha.

**Nada roda na máquina do gNB.** O painel *puxa* as métricas do gNB pelo WebSocket, e o agente do log
(também na máquina do core) lê o arquivo do gNB por SSH (`tail -F`, só leitura).

## Arquitetura

```
 máquina do core (torre2)                                         máquina do gNB (innovaserver)
┌──────────────────────────────────────────────────────────┐     ┌─────────────────────────────┐
│ k3s, namespace open5gs                                   │     │ OCUDU gNB                   │
│  ┌──────────────────────┐  API k8s (só leitura)          │     │  remote_control :8001 (WS) ◄──── métricas (1/s)
│  │ pod dashboard        │◄──── pods, logs dos NFs        │     │  log: /tmp/gnb.log ◄─────────┐
│  │ python:3.12-slim     │◄──── :9090/metrics (opcional)  │     └─────────────────────────────┘│
│  │ server.py (stdlib)   │──────────────────────────────────────────────── ws://10.10.0.1:8001 │
│  └──────────▲───────────┘                                │                                    │
│      NodePort 30998  ▲ POST /api/ingest/gnb-log (token)  │                                    │
│                      │                                   │                                    │
│  unit open5gs-k3s-gnb-log (usuário do install) ──── ssh innovaserver@10.10.0.1 tail -F ───────┘
└──────────────────────────────────────────────────────────┘
```

- **Backend** (`dashboard/app/server.py`): só biblioteca padrão do Python; nenhum `pip install`. Guarda
  em memória os últimos `DASHBOARD_HISTORY_SECONDS` (padrão 15 min). Reiniciar o pod zera o histórico.
- **Página** (`index.html`, `app.js`, `style.css`) + **uPlot 1.6.31** (gráficos, licença MIT, guardado no
  repositório — funciona sem internet).
- **Kubernetes**: ConfigMap `dashboard-app` (os arquivos), Secret `dashboard` (senha e token),
  ServiceAccount com Role só `get/list/watch` em `pods` e `pods/log`, Deployment (usuário 65534,
  sistema de arquivos só leitura, sem capabilities), Service NodePort. Tudo gerado em
  `helm/generated/dashboard.yaml`.
- **Agente do log do gNB** (`dashboard/agent/gnb-log-agent.py`): unit `open5gs-k3s-gnb-log`, roda como o
  usuário do install (usa a chave SSH dele), reconecta sozinho, descarta linhas por regex
  (`GNB_LOG_DROP`) **antes** de enviar e guarda até 50 000 linhas se o painel estiver fora.

## Instalar / atualizar

O painel faz parte do `install.sh` (passo depois do UERANSIM). Para subir **só o painel**, sem tocar no
core, no UERANSIM nem no gNB — seguro com usuários na rede:

```bash
sudo ./install.sh --dashboard-only
```

A instalação completa (`sudo ./install.sh` ou `--deploy-only`) também sobe o painel. Com
`OPEN5GS_METRICS=false` os values do core não mudam, então o core **não** reinicia por causa do painel.

Mudou a página ou o `config.env`? Rode de novo `--dashboard-only`: o hash dos arquivos vai na anotação do
pod, que reinicia sozinho.

## Configuração (`config.env`)

| Variável | Padrão | Para quê |
|---|---|---|
| `DASHBOARD_ENABLED` | `true` | liga/desliga (desligar remove os objetos e a unit do agente) |
| `DASHBOARD_NODEPORT` | `30998` | porta (30000–32767); aberta na UFW/firewalld como a WebUI |
| `DASHBOARD_IMAGE` | `python:3.12-slim` | imagem base |
| `DASHBOARD_PASSWORD` | vazio | senha (usuário `admin`); vazio = aberto |
| `DASHBOARD_HISTORY_SECONDS` | `900` | histórico dos gráficos (60–21600 s) |
| `GNB_METRICS_URL` | `ws://10.10.0.1:8001` | WebSocket de métricas do gNB; vazio = sem aba Rádio |
| `GNB_NAME` | `OCUDU + LiteOn` | nome mostrado |
| `GNB_LOG_SSH` | vazio | `usuario@host` do gNB para o agente do log; vazio = sem log do gNB |
| `GNB_LOG_FILE` | `/tmp/gnb.log` | arquivo `log: filename:` da config do gNB |
| `GNB_LOG_DROP` | `\[PHY *\] \[I\]` | regex de linhas descartadas; vazio = envia tudo |
| `OPEN5GS_METRICS` | `false` | Prometheus nos NFs (aba Core). **Mudar reinicia o core** no próximo install |

### Métricas do gNB (OCUDU)

O gNB precisa do `remote_control` ligado (já está no `metricas.yml` usado no innovaserver):

```yaml
metrics:
  autostart_stdout_metrics: true
  enable_json: true
remote_control:
  enabled: true
  bind_addr: 0.0.0.0
  port: 8001
```

O painel envia `{"cmd":"metrics_subscribe"}` e recebe uma mensagem por segundo com `cells[].cell_metrics`,
`cells[].ue_list[]` e `du.du_high.mac.dl[]`. Se o gNB cair, o painel reconecta sozinho (espera crescente
até 30 s).

**BLER**: o gNB informa blocos OK/NOK por período; o painel calcula `NOK / (OK + NOK)`. Nos gráficos é por
segundo; nos cartões e tabelas é dos **últimos 10 s** (com poucos blocos o valor de 1 s oscila demais —
passe o mouse para ver quantos blocos entraram na conta). Sem transmissão no período, MCS/SNR viram lacuna
em vez de 0.

### Log do gNB real

1. Chave SSH do usuário do install (na máquina do core) para o gNB, **sem senha**:
   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ''          # se ainda não tiver
   ssh-copy-id innovaserver@10.10.0.1                         # pede a senha uma vez
   ssh -o BatchMode=yes innovaserver@10.10.0.1 test -r /tmp/gnb.log && echo ok
   ```
2. `GNB_LOG_SSH="innovaserver@10.10.0.1"` no `config.env` e `sudo ./install.sh --dashboard-only`.
3. Aba **Logs → gNB (real)**. Estado do agente: `journalctl -u open5gs-k3s-gnb-log -f`.

Volume: com `all_level: info` o OCUDU escreve ~100 kB/s **parado** (≈600 linhas/s, quase tudo
`[PHY] [I]`), e muito mais com tráfego. O filtro padrão deixa passar MAC, RRC, NGAP, avisos e erros. O
painel guarda as últimas 20 000 linhas do gNB.

> O arquivo `/tmp/gnb.log` do OCUDU cresce sem limite (1,7 GB em 2026-10-21). Isso é do gNB, não do
> painel — vale rotacionar ou reduzir `all_level`.

### Métricas do core (aba Core)

`OPEN5GS_METRICS=true` + `sudo ./install.sh --deploy-only` liga `metrics.enabled` nos charts do AMF, SMF,
UPF e PCF (porta 9090, `/metrics`). **Reinicia esses NFs uma vez** — fazer numa janela sem usuários.
Sem isso, a aba Core explica como ligar, e a Visão geral continua mostrando gNBs, UEs e sessões tirados
dos logs.

## API (para scripts)

| Rota | Retorna |
|---|---|
| `GET /api/health` | `{"ok":true}` (sem senha; usado pelas probes) |
| `GET /api/overview` | resumo usado pela Visão geral |
| `GET /api/ran?window=300` | séries por UE, célula e DU |
| `GET /api/ran.csv?window=900` | CSV por UE (UTC) |
| `GET /api/core` | pods, gNBs N2, UEs, sessões, eventos, contadores |
| `GET /api/core/metrics?window=300` | métricas Prometheus dos NFs |
| `GET /api/logs?pod=&container=&tail=` | log de um pod |
| `GET /api/logs/stream?pod=&container=` | log ao vivo (Server-Sent Events) |
| `GET /api/gnb-log?tail=` · `/api/gnb-log/stream` | log do gNB |
| `POST /api/ingest/gnb-log` | entrada do agente (cabeçalho `X-Ingest-Token`) |

Exemplo: `curl -s http://IP:30998/api/ran.csv?window=900 -o ran.csv`.

## Problemas comuns

| Sintoma | Causa / solução |
|---|---|
| "gNB sem dados" | gNB parado ou sem `remote_control`; teste `nc -vz 10.10.0.1 8001` na máquina do core |
| Aba Rádio vazia com gNB no ar | nenhum UE conectado (UEs ociosos são liberados pelo AMF e somem da célula) |
| "gNB (real)" sem linhas | `journalctl -u open5gs-k3s-gnb-log`: chave SSH, `GNB_LOG_FILE` errado, ou o filtro descartou tudo |
| Página não abre de outro PC | UFW/firewalld: o install abre `DASHBOARD_NODEPORT`; confira `sudo ufw status` |
| Pod `ImagePullBackOff` | sem acesso ao Docker Hub; troque `DASHBOARD_IMAGE` por uma imagem Python acessível |

## Desenvolvimento

Rodar fora do cluster, na máquina do core, sem instalar nada:

```bash
kubectl proxy --port=18001 &
K8S_API=http://127.0.0.1:18001 NAMESPACE=open5gs GNB_METRICS_URL=ws://10.10.0.1:8001 \
  PORT=18080 BIND=127.0.0.1 python3 dashboard/app/server.py
# no seu PC: ssh -L 18080:127.0.0.1:18080 torre2  e abra http://127.0.0.1:18080
```
