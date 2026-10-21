# Painel — Innova Center Dashboard (v1.0)

Página web que roda **no próprio cluster do core** (máquina do core) e junta num só lugar:

| Aba | O que mostra | De onde vem |
|---|---|---|
| **Visão geral** | UEs no rádio (vazão, MCS, CQI, RI, BLER, SNR), assinantes vistos pelo core (registro, sessões DNN → IP), pods (estado, reinícios, IP, IP no link RAN), eventos do core (avisos/erros iguais agrupados com contador) | métricas do gNB + API do Kubernetes + logs do AMF/SMF/UPF |
| **Rádio (gNB)** | UEs identificados por **nome, IMSI, IP e tipo** (SIM real / UERANSIM), não só RNTI; RNTIs parados há mais de 2 min ficam escondidos (botão "Mostrar antigos"); vazão e PRBs da célula; vazão DL/UL por UE; do UE escolhido: BLER, MCS, CQI/rank, SNR/RSRP do PUSCH, buffers, TA/PHR; latência do escalonador e falhas (HARQ atrasado, PDCCH, UCI). Janela de 1/5/15 min, pausa, exportação CSV | WebSocket de métricas do gNB (OCUDU `remote_control`) |
| **Logs** | log de qualquer pod/contêiner do namespace (core e UERANSIM) e do **gNB real**; ao vivo, filtro por texto ou `/regex/`, filtro por nível, cores, download | API do Kubernetes; agente do log do gNB |
| **Máquinas** | lista das máquinas (core e gNB) com CPU, memória e temperatura; ao clicar: CPU por núcleo (isolados destacados), carga, hugepages, gráficos de CPU/temperatura/memória/rede, processos que mais usam CPU, temperaturas, discos e interfaces | `/proc` e `/sys` (core: montados no pod; outras: SSH) |
| **Configuração** | edita o `config.env` (senha de administrador): campos por seção com a explicação do próprio arquivo, diff antes de salvar, validação do install, backup e restauração, e o comando para aplicar | `config.env` da máquina do core |
| **Core** | sempre: gNBs, UEs registrados, sessões, tráfego dos UEs no UPF por DNN (N6) e no link com o gNB (N3), CPU/memória/threads de cada NF, erros/avisos por NF, interfaces do UPF. Opcional: métricas Prometheus dos NFs | `/proc` do host (processos `open5gs-*d` e interfaces do UPF) + logs; Prometheus só com `OPEN5GS_METRICS=true` |

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
| `DASHBOARD_LOCAL_ROLE` | `Core 5G (k3s)` | papel desta máquina na aba Máquinas |
| `DASHBOARD_HOSTS` | `innovaserver\|innovaserver@10.10.0.1\|gNB OCUDU + LiteOn` | outras máquinas (lidas por SSH) |
| `DASHBOARD_UE_NAMES` | `001010000000022:Modem Telit FN990` | apelidos dos SIMs; os do UERANSIM são marcados sozinhos |
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

### Quem é cada UE no rádio (RNTI → nome/IMSI/IP)

O gNB só informa o **RNTI** (número temporário do rádio, muda a cada conexão). O painel cruza três fontes:

```
log do gNB   [RRC]  ue=62 c-rnti=0x4c22          (RNTI 19490 -> UE 62 do CU-CP)
log do gNB   [NGAP] ue=62 ran_ue=53 amf_ue=55    (UE 62 -> AMF_UE_NGAP_ID 55)
log do AMF   [suci-0-001-01-…-0000000040] … AMF_UE_NGAP_ID[55]   (-> IMSI 001010000000040)
log do SMF   UE SUPI[imsi-001010000000040] DNN[internet] IPv4[10.45.0.5]
```

- Precisa do **log do gNB** ligado (`GNB_LOG_SSH`). Sem ele os cartões mostram só o RNTI e um aviso.
- Quando o painel sobe, o agente procura os vínculos recentes nos últimos 300 MB do log (`IDENT_BYTES`, com
  `nice`); depois, cada UE é identificado na próxima troca de mensagens com o core (registro, NAS, sessão).
- O nome vem de `DASHBOARD_UE_NAMES`; o tipo (SIM real/UERANSIM) dos IMSIs gerados para o UERANSIM.
- Só funciona com SUCI sem criptografia (esquema nulo, o caso dos SIMs de teste) ou quando o AMF já escreveu o
  `[imsi-…]` logo depois do `AMF_UE_NGAP_ID`.

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

Sem reiniciar nada: o pod do painel já monta o `/proc` do host (só leitura). Ele acha os processos `open5gs-<nf>d`
e o `mongod` (CPU, memória, threads) e lê as interfaces **dentro do namespace de rede do UPF**
(`/proc/<pid-do-upf>/net/dev`): `ogstun*` = N6 por DNN (rx = uplink, tx = downlink), `net1` = N3 (GTP-U com o
gNB), `eth0` = rede do pod. Erros/avisos por NF vêm dos logs do AMF/SMF/UPF.

**Prometheus (opcional):**

`OPEN5GS_METRICS=true` + `sudo ./install.sh --deploy-only` liga `metrics.enabled` nos charts do AMF, SMF,
UPF e PCF (porta 9090, `/metrics`). **Reinicia esses NFs uma vez** — fazer numa janela sem usuários.
Sem isso, a aba Core explica como ligar, e a Visão geral continua mostrando gNBs, UEs e sessões tirados
dos logs.

### Aba Máquinas

- **Máquina do core**: o pod monta `/proc`, `/sys` e `/` do host **só leitura** e lê com `dashboard/app/hoststats.py`.
- **Outras máquinas** (`DASHBOARD_HOSTS`, formato `nome|usuario@host|papel`): a unit `open5gs-k3s-hosts` (máquina do
  core, usuário do install) abre uma sessão SSH por máquina e manda o `hoststats.py` pela entrada padrão
  (`ssh host nice -n 19 python3 - --loop 2`). **Nada é instalado** na máquina remota; o processo lê `/proc` e `/sys`
  a cada 2 s com prioridade mínima e some quando a sessão cai. Usa a mesma chave SSH do log do gNB.
- Sem a chave, a máquina aparece como "sem dados" com o motivo. Estado: `journalctl -u open5gs-k3s-hosts -f`.
- Núcleos isolados (`isolcpus`, ex.: 0–17 do gNB) aparecem com fundo azul; um núcleo do gNB em 100 % é normal
  (laço do DPDK).

### Energia (medidor MiEnergy)

O medidor MiEnergy (monofásico) tem uma página `http://<IP>/Data` com ~70 grandezas (`v_a`, `i_a`, `p_a`, `fp_a`,
`energia_ativa_total`…). O painel lê essa página a cada 2 s, com o mesmo filtro do `collector.py` do projeto
MiEnergy_Lab_Meter, **sem InfluxDB nem Grafana**, e mostra na aba Máquinas, na máquina `ENERGY_METER_HOST`:
potência no cartão; ao clicar, potência, tensão, corrente, fator de potência, energia acumulada, consumo desde que o
painel iniciou, gráficos e a tabela com todas as grandezas.

- `ENERGY_METER_URL="http://IP/Data"` + `sudo ./install.sh --dashboard-only`.
- O pod do painel (na máquina do core) precisa **alcançar o IP do medidor**. Teste na máquina do core:
  `curl -s http://IP/Data | head -c 200`.
- **Situação em 2026-10-21: desligado (`ENERGY_METER_URL=""`).** O medidor está no Wi‑Fi do laboratório
  (roteador TP‑Link, rede 192.168.68.0/22), que faz **NAT**: os computadores do switch (rede 191.4.204.0/23)
  não alcançam 192.168.68.105 (ping sem resposta; a porta 80 "conecta" com qualquer IP por causa do proxy
  transparente do campus, mas o HTTP não responde). Caminhos, do mais simples ao mais trabalhoso:
  1. **Redirecionamento de porta** no roteador Wi‑Fi (NAT Forwarding): porta externa (ex.: 8080) →
     192.168.68.105:80, com IP fixo (reserva DHCP) para o medidor. Depois: `ENERGY_METER_URL="http://<IP WAN do
     roteador>:8080/Data"`.
  2. **Roteador em modo Access Point (bridge)**: o medidor passa a pegar IP da rede do switch.
  3. Cabo de uma porta LAN do roteador numa porta livre do torre2 (`enp5s0f0`), com DHCP **sem rota padrão**
     (`dhcp4-overrides: {use-routes: false}` no netplan) — senão a internet do core passaria pelo Wi‑Fi.

## Aba Configuração (editar o `config.env`)

Liga com `DASHBOARD_CONFIG_EDIT=true` (padrão no config deste repositório) + `sudo ./install.sh --dashboard-only`.

- **Senha própria de administrador**, gerada uma vez pelo install e guardada só para root:
  `sudo cat /opt/open5gs-k3s/state/dashboard-admin-password`. Sessão de 8 h no navegador (aba fechada = sai).
  O resto do painel continua sem senha (ou com `DASHBOARD_PASSWORD`).
- **Só altera o valor** de variáveis que já existem no arquivo (não cria linhas). Recusa quebra de linha, `$`,
  `` ` ``, `\` e `"` nos valores — o `config.env` é lido com `source` pelo install como root.
- Antes de salvar mostra o **diff** e roda a **mesma validação do install** (`validate_config`); com erro, não grava.
- Cada gravação guarda o arquivo anterior em `/opt/open5gs-k3s/state/config-backups/` (últimos 50); a lista de
  backups mostra o diff e permite restaurar.
- Segredos (`UE_KEY`, `UE_OPC`, `SUBSCRIBERS`, `DASHBOARD_PASSWORD`) aparecem mascarados até clicar em
  "Mostrar segredos".
- Se alguém mudou o arquivo no servidor depois que a página abriu, a gravação é recusada (recarregue).
- **Salvar não aplica.** O painel diz o comando necessário:
  `--dashboard-only` (só variáveis do painel), `--deploy-only` (core/UERANSIM: reinicia NFs) ou install completo
  (k3s/host). Rodar continua sendo com você, na máquina do core — o painel não tem acesso de root.
- Como funciona: o pod monta o projeto **só leitura** e apenas o `config.env` com escrita, pelo grupo do dono
  do arquivo (`supplementalGroups`); o install garante `g+w` no `config.env`.
- Depois de salvar pela interface, o arquivo fica modificado no git do servidor: faça o commit como de costume.
- Se o arquivo for **substituído** no servidor (ex.: `git checkout`, editor que recria o arquivo), o painel
  passa a recusar a gravação até um novo `sudo ./install.sh --dashboard-only`.

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
| `GET /api/hosts` · `GET /api/hosts/<nome>?window=` | máquinas: resumo · detalhes e séries |
| `POST /api/ingest/host` | entrada do agente das máquinas (`X-Ingest-Token`) |
| `POST /api/ingest/gnb-log` | entrada do agente (cabeçalho `X-Ingest-Token`) |

Exemplo: `curl -s http://IP:30998/api/ran.csv?window=900 -o ran.csv`.

## Problemas comuns

| Sintoma | Causa / solução |
|---|---|
| "gNB sem dados" | gNB parado ou sem `remote_control`; teste `nc -vz 10.10.0.1 8001` na máquina do core |
| Aba Rádio vazia com gNB no ar | nenhum UE conectado (UEs ociosos são liberados pelo AMF e somem da célula) |
| Cartões do Rádio só com "RNTI …" / "não identificado" | log do gNB desligado (`GNB_LOG_SSH`) ou o UE ainda não trocou mensagens com o core desde que o painel subiu; aguarde ou force um registro (modo avião) |
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
