# Tutorial 6 — Mudar PLMN, slices e IPs

**Objetivo:** alterar a configuração da rede e aplicar sem quebrar nada.
**Tempo:** ~15 min. **Precisa de:** core instalado; login de administrador no painel.

## Como uma configuração chega ao core

```
config.env ──► validate_config ──► values do Helm (helm/generated/) ──► helm upgrade ──► ConfigMap ──► pod
                                     + hash da configuração no pod: mudou → o pod é recriado
```

Você nunca edita `amf.yaml` ou `smf.yaml` à mão: eles são gerados. Para ver o resultado:

```bash
kubectl -n open5gs get configmap open5gs-amf -o jsonpath='{.data.amf\.yaml}' | less
```

## 1. Editar

**Pelo painel:** aba **Configuração** → a seção desejada → altere → confira o diff → salve. O painel valida
com as mesmas regras do instalador e guarda um backup.

**Pelo terminal:** `nano config.env` na máquina do core.

## 2. Exemplos

**Nome da rede no celular:**

```bash
NETWORK_NAME="MinhaRede5G"
```

**Uma terceira slice:**

```bash
SLICES=(
  "1:111111:internet:10.45.0.0/16"
  "2:222222:internet2:10.46.0.0/16"
  "3:333333:iot:10.47.0.0/16"          # SST:SD:DNN:pool
)
```

Cada slice gera S-NSSAI no AMF, NSI no NSSF, sessão no SMF e uma TUN com NAT no UPF. No gNB, a nova slice também
precisa estar no `.yml` (`cu_cp` / `du` → `slicing`). No free5GC, informe o pool em `F5_UE_POOLS`.

**PLMN:**

```bash
MCC="001"; MNC="01"; TAC="1"
```

O PLMN muda AMF, NRF, gNB do UERANSIM e IMSIs dos UEs simulados. O `.yml` do gNB real (`cu_cp` → `plmn`, `tac`) e os
SIMs precisam acompanhar.

## 3. Aplicar

| O que mudou | Comando (máquina do core) | Impacto |
|---|---|---|
| core / UERANSIM (PLMN, slices, nome, assinantes) | `sudo ./install.sh --deploy-only` | recria as funções afetadas; usuários caem ~1 min |
| só o painel | `sudo ./install.sh --dashboard-only` | só o painel reinicia |
| free5GC | `./free5gc/install.sh` | recria o free5GC |

Depois de recriar o AMF, **reinicie o gNB** (painel → cartão do gNB → **↻ Reiniciar**): ele não refaz o N2 sozinho.

## 4. Conferir

```bash
./test.sh
kubectl -n open5gs get configmap open5gs-amf -o jsonpath='{.data.amf\.yaml}' | grep -A2 network_name
```

## Cuidados

- Rode `--deploy-only` com o **Open5GS como core ativo**.
- Pools de IP sem sobreposição entre si e com `10.42/16`, `10.43/16` e a fibra (a validação recusa).
- Use PLMN de teste e respeite a regulamentação de espectro.
