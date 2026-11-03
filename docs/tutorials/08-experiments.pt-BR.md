# Tutorial 8 — Gravar e comparar experimentos

**Objetivo:** medir dois setups (ex.: dois `.yml` do gNB) e compará-los lado a lado no painel.
**Tempo:** ~20 min. **Precisa de:** histórico persistente ligado (`DASHBOARD_PERSIST=true`, padrão) e um UE com
tráfego.

## 1. O que é gravado

Com o histórico ligado, o painel grava **sempre**: métricas do rádio por UE e da célula (1 s), core, máquinas,
O-RU e eventos. Um **experimento** é só um marcador de período com nome, notas e um retrato do setup (UEs, versão,
gNB, configuração da O-RU e o `config.env`, com chaves mascaradas).

## 2. Experimento A

1. Coloque o setup A no ar (ex.: gNB com `gnb_split_open5gs`).
2. No topo do painel: **● Gravar experimento** → nome `A — 100 MHz padrão`, notas (posição do celular, o que mudou).
3. Gere tráfego por um tempo fixo, sempre igual nos dois experimentos. Exemplos:
   - celular: teste de velocidade ou download grande;
   - UE simulado: `kubectl -n open5gs exec deploy/ueransim-ues -- iperf3 -c <servidor> -B <IP da uesimtun0> -t 120`.
4. Clique de novo no botão (vermelho, com cronômetro) para **encerrar**.

## 3. Experimento B

Mude **uma coisa só** (ex.: o `.yml` — [tutorial 7](07-alterar-o-gnb.md)), repita o mesmo tráfego e grave como
`B — …`.

## 4. Comparar

Aba **Histórico** → marque A e B → **Comparar**:

- tabela com média, p95 e pico de DL/UL da célula, BLER, MCS, CQI, RI, SNR, latência do escalonador, CPU e
  temperatura de cada máquina, pacotes da O-RU fora da janela — o melhor de cada linha em verde;
- gráficos sobrepostos com eixo "tempo desde o início".

## 5. Exportar

- **Histórico** → período ou experimento → **CSV** (`timestamp, série, IMSI, campo, valor`);
- API: `curl -s "http://<máquina do core>:30998/api/history/csv?from=<epoch>&to=<epoch>" -o dados.csv`.

## Boas práticas

- mesmo celular, mesma posição, mesmo tráfego, mesma duração;
- uma variável por vez;
- notas completas: o retrato do setup ajuda, mas não substitui saber *por que* o experimento foi feito.

Detalhes do armazenamento (formato, retenção, tamanho): [componentes/painel.md](../componentes/painel.md#histórico-persistente-e-experimentos-aba-histórico).
