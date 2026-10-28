# Tutorial 5 — Trocar de core

**Objetivo:** instalar o free5GC ao lado do Open5GS e alternar entre os dois pelo painel, com o celular
voltando sozinho na rede nova.
**Tempo:** ~30 min. **Precisa de:** core Open5GS e painel instalados; para o rádio, o gNB no Kubernetes.

## 1. Instalar o free5GC

🖥️ Máquina do core:

```bash
sudo ./free5gc/setup-gtp5g.sh               # módulo do kernel do UPF (uma vez)
./free5gc/install.sh                        # sobe o free5GC
./free5gc/install.sh --importar-open5gs     # copia os SIMs do Open5GS
./free5gc/test.sh                           # "6 ok, 0 falha(s)"
sudo ./install.sh --dashboard-only          # o painel ganha o cartão "Core ativo"
```

## 2. Criar o `.yml` do gNB para o free5GC

📡 Máquina do RAN, uma cópia do `.yml` atual com outro AMF:

```bash
cd ~/ocudu/configs
cp gnb_ru_liteon_SLPIT_CORE.yml gnb_ru_liteon_FREE5GC.yml
sed -i 's/addr: 10.10.0.10/addr: 10.10.0.30/' gnb_ru_liteon_FREE5GC.yml
grep -n -A2 "amf:" gnb_ru_liteon_FREE5GC.yml          # addr: 10.10.0.30
```

## 3. Trocar

Painel → **🔒 Admin** → aba **Controle** → cartão **Core ativo**:

1. clique em **free5GC**;
2. deixe **religar o gNB OCUDU com** marcado e escolha `gnb_ru_liteon_FREE5GC` (só aparecem os `.yml` deste AMF);
3. **Trocar agora**.

O andamento aparece linha a linha (exemplo resumido):

```
parando o gNB OCUDU
parando o core Open5GS e o UERANSIM dele
core ativo: free5GC
iniciando … NRF ✓ … UPF ✓ … SMF ✓ (PFCP associado) … AMF ✓ (escutando 10.10.0.30)
UERANSIM: NG Setup ✓
gNB OCUDU iniciado com gnb_ru_liteon_FREE5GC.yml · RU: DU conectado · AMF: gNB conectado (N2)
```

Leva ~1 min. Os celulares caem e voltam com a rede **InnovaFree5GC** e IPs `10.60.x.x` (`internet`) e
`10.62.x.x` (`ims`).

## 4. Conferir

| Onde | Esperado |
|---|---|
| topo do painel | pílula **free5GC** |
| Visão geral | celulares registrados com IPs `10.60/16` |
| Core → Assinantes | WebConsole do free5GC (`:31000`) |
| `kubectl -n open5gs get deploy` | funções do Open5GS com 0 réplicas (o painel continua no ar) |

## 5. Voltar ao Open5GS

Mesmo caminho: cartão **Core ativo** → **Open5GS** → `.yml` `gnb_ru_liteon_SLPIT_CORE` → **Trocar agora**
(~5 min: o Open5GS tem mais funções e espera o NRF/SCP).

## Regras

- Sempre pelo cartão **Core ativo**: ele segue a ordem certa e religa o gNB no AMF certo.
- Não rode instaladores durante a troca.
- `sudo ./install.sh --deploy-only` só com o Open5GS ativo.
