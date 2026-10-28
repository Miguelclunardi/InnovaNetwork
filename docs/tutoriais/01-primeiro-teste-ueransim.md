# Tutorial 1 — Primeiro teste com UERANSIM

**Objetivo:** instalar o core Open5GS em uma máquina e ver um UE simulado registrar, abrir sessão e navegar.
**Tempo:** ~20 min. **Precisa de:** Ubuntu 24.04 com `sudo` e internet. Nenhum rádio.

## 1. Baixar o projeto

```bash
git clone https://github.com/Miguelclunardi/InnovaNetwork.git ~/InnovaNetwork
cd ~/InnovaNetwork
```

## 2. Ajustar a configuração para uma máquina só

Abra o `config.env` e desligue o que depende de rádio:

```bash
RAN_LINK_ENABLED=false      # sem a fibra até um gNB real
GNB_METRICS_URL=""          # sem gNB real no painel
GNB_LOG_SSH=""
GNB_CTL_SSH=""
RU_MGMT_IP=""               # sem O-RU
DASHBOARD_HOSTS=()          # sem outras máquinas
```

O resto pode ficar como está: PLMN `001-01`, TAC `1`, slices `internet` e `internet2`.

## 3. Instalar

```bash
sudo ./install.sh
```

Acompanhe as etapas (`==> …`). Na primeira vez leva 5–15 min, quase tudo é download de imagens. No fim:

```
[ok] painel no ar: http://<IP>:30998
```

Se algo falhar, a mensagem `[erro]` diz a etapa; o log completo fica em `logs/install.log`.

## 4. Testar

```bash
./test.sh
```

Esperado:

```
RESULTADO: 7 verificações OK, 0 falhas
```

## 5. Ver por dentro

```bash
kubectl -n open5gs get pods -o wide                 # ~17 pods Running
kubectl -n open5gs logs deploy/open5gs-amf | grep -iE "NG Setup|Registration complete"
kubectl -n open5gs exec -it deploy/ueransim-ues -- bash
```

Dentro do pod do UE:

```bash
nr-cli -d                                           # imsi-001010000009001
nr-cli imsi-001010000009001 --exec status           # MM-REGISTERED / NORMAL-SERVICE
ip -br addr show uesimtun0                          # 10.45.0.x: IP entregue pelo SMF
ping -I uesimtun0 -c 3 8.8.8.8                      # o tráfego passa pelo UPF
curl --interface uesimtun0 -s https://example.com | head -5
exit
```

## 6. Ver no painel

Abra `http://<IP da máquina>:30998`:

- **Visão geral:** o UE simulado aparece como *UERANSIM*, registrado, com a sessão `internet → 10.45.0.x`;
- **Logs:** escolha `open5gs-amf` e acompanhe ao vivo;
- **Core:** o tráfego do UE no UPF.

## O que você fez

Instalou um k3s, o core Open5GS (13 funções + MongoDB), um gNB e um UE simulados, e o painel — tudo como pods,
gerado a partir do `config.env`. Próximo: [Conhecer o painel](02-conhecer-o-painel.md).
