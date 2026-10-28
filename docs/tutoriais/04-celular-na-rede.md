# Tutorial 4 — Celular na rede

**Objetivo:** cadastrar um SIM programável, conectar um celular comercial e navegar.
**Tempo:** ~20 min. **Precisa de:** core e gNB funcionando ([tutorial 3](03-ocudu-em-kubernetes.md)); um SIM
programável com PLMN `001-01` (IMSI, K e OPc conhecidos); um celular 5G SA com a banda n78.

## 1. Cadastrar o SIM

Escolha **um** jeito.

**WebUI (Open5GS)** — painel → aba **Core** → **Assinantes** (ou `http://<máquina do core>:30999`, `admin`):

1. **+** → IMSI (ex.: `001010000000040`), Subscriber Key (K), Operator Key (**OPc**);
2. slice SST `1` / SD `111111`, DNN `internet` (adicione SST `2` / SD `222222`, DNN `internet2` se quiser a 2ª slice);
3. salvar.

**Arquivo de configuração** — fica registrado e é reaplicado a cada instalação:

```bash
# config.env (máquina do core)
SUBSCRIBERS=(
  "001010000000040:<K 32 hex>:<OPc 32 hex>"
)
```
```bash
sudo ./install.sh --deploy-only
```

**Linha de comando:**

```bash
./scripts/subscribers.sh add 001010000000040 <K> <OPc>
./scripts/subscribers.sh list
```

> As chaves ficam só no banco do core e no seu `config.env` local. Nunca as publique no git.

## 2. Preparar o celular

- Rede: **5G** (SA) ou "5G preferencial";
- APN/DNN: `internet` (a maioria dos celulares usa o padrão do SIM);
- se não achar a rede sozinho: seleção manual de operadora → `00101` ou `InnovaOpen5GS`.

## 3. Ligar a rede

No painel, aba **Controle**: core ativo no ar e **gNB (Kubernetes)** rodando com o `.yml` do core ativo. Aba
**RU**: `SYNCHRONIZED`, DU `Ready`.

## 4. Conectar

Tire o celular do modo avião. Acompanhe:

| Onde | O que aparece |
|---|---|
| **Logs** → `open5gs-amf` (filtro `imsi-001010000000040`) | Registration Request → autenticação → `Registration complete` |
| **Logs** → `open5gs-smf` | sessão `DNN[internet] IPv4[10.45.0.x]` |
| **Visão geral** | o SIM registrado, com a sessão e o IP |
| **Rádio** | o UE com nome/IMSI, MCS, SNR e vazão |

O nome **InnovaOpen5GS** aparece no celular depois do registro.

## 5. Medir

Abra um teste de velocidade no celular e acompanhe a vazão DL/UL na aba **Rádio**. Para comparar setups, grave um
experimento ([tutorial 8](08-experimentos.md)).

## Se não conectar

| Sintoma | Veja |
|---|---|
| a rede não aparece | gNB ligado? O-RU sincronizada? banda n78 no celular? |
| aparece mas recusa o registro | IMSI/K/OPc errados (AMF: falha de autenticação) ou PLMN diferente |
| registra e sai logo em seguida | no free5GC: voz IMS ([free5gc.md](../componentes/free5gc.md#5-celulares-comerciais)) |
| PRACH no log do gNB, mas não registra | O-RU sincronizada antes do GNSS ([hardware](../hardware/e810-liteon.md#4-sincronismo-espere-o-gnss)) |

Mais: [troubleshooting.md](../troubleshooting.md#5-rádio-e-gnb-ocudu).
