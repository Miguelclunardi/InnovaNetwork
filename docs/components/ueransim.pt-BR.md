# UERANSIM — gNB e UE simulados

O **UERANSIM 3.2.6** simula um gNB e UEs 5G em software. No InnovaNetwork, cada core tem o seu par gNB + UEs,
usado para testar o core **sem rádio**: registro, autenticação, sessão PDU e tráfego.

| | Open5GS | free5GC |
|---|---|---|
| Namespace | `open5gs` | `free5gc` |
| Deployments | `ueransim` (gNB) e `ueransim-ues` | `ueransim` e `ueransim-ues` |
| gNB na fibra | `10.10.0.20` | `10.10.0.32` |
| Instalado por | `install.sh` (chart Gradiant `ueransim-gnb`) | `free5gc/install.sh` |
| Teste automático | `./test.sh` | `./free5gc/test.sh` |

## 1. Como funciona

```
pod ueransim-ues                pod ueransim (gNB)                       core
  UE imsi-…9001  ── RLS/UDP 4997 ──►  gNB  ── N2 SCTP 38412 (net1 10.10.0.20) ──► AMF 10.10.0.10
  uesimtun0 = 10.45.0.x               │
                                      └── N3 GTP-U 2152 ─────────────────────────► UPF 10.10.0.11
```

- O gNB simulado usa a **mesma fibra** que o gNB real (interface `net1`), então testa o mesmo caminho N2/N3.
- Cada UE ganha uma interface `uesimtunN` dentro do pod; tráfego por ela passa pelo core de verdade.
- O gNB simulado anuncia a **1ª slice** de `SLICES`. Para testar outra, coloque-a em primeiro.

## 2. Configuração

No `config.env`:

| Variável | Padrão | Função |
|---|---|---|
| `DEPLOY_UERANSIM` | `true` | `false` remove o gNB e os UEs simulados |
| `GNB_SIM_IP` | `10.10.0.20` | IP do gNB simulado na fibra |
| `UE_COUNT` | `1` | quantidade de UEs simulados |
| `UE_MSIN_START` | `0000009001` | primeiro MSIN (IMSIs consecutivos, longe dos SIMs reais) |
| `UE_KEY`, `UE_OPC` | chaves de teste públicas do UERANSIM | cadastrados automaticamente no core |
| `UERANSIM_IMAGE_TAG` | vazio (3.2.6) | trocar a imagem |

No free5GC: `F5_DEPLOY_UERANSIM`, `F5_GNB_SIM_IP`.

Os UEs simulados são cadastrados sozinhos no core (Open5GS e free5GC) a cada instalação.

## 3. Usar

```bash
kubectl -n open5gs exec -it deploy/ueransim-ues -- bash
```

Dentro do pod:

```bash
nr-cli -d                                         # lista UEs
nr-cli imsi-001010000009001 --exec status         # MM-REGISTERED/NORMAL-SERVICE?
nr-cli imsi-001010000009001 --exec ps-list        # sessões PDU
ip addr show uesimtun0                            # IP do UE
ping -I uesimtun0 8.8.8.8                         # tráfego pelo core (N3 → UPF → N6)
curl --interface uesimtun0 https://example.com
nr-cli imsi-001010000009001 --exec "deregister normal"
```

Estado do gNB:

```bash
kubectl -n open5gs exec deploy/ueransim -- sh -c 'nr-cli $(nr-cli -d) --exec status'
```

## 4. Teste automático

`./test.sh` (Open5GS) confere, em ordem:

```
==> Pods no namespace open5gs              [ok] todos os pods Running/Ready
==> NRF                                    [ok] NRF registrou 9 NF(s)
==> N2: NG Setup                           [ok] gNB fez NG Setup com o AMF
==> UEs: registro e sessão PDU             [ok] registrado (MM-REGISTERED/NORMAL-SERVICE)
                                           [ok] sessão PDU ativa, uesimtun0 = 10.45.0.x
                                           [ok] ping 10.45.0.1 (gateway no UPF)
                                           [ok] ping 8.8.8.8 via uesimtun0
RESULTADO: 7 verificações OK, 0 falhas
```

O ping ao gateway testa o plano de usuário (N3) sem depender da internet; o ping externo testa N6/NAT. `-v`
mostra os logs do AMF, SMF, UPF, gNB e UE em caso de falha. Código de saída 0/1, útil para automação.

## 5. No painel

- **Visão geral**: os UEs simulados aparecem marcados como **UERANSIM**, separados dos SIMs reais.
- **Controle**: iniciar/parar/reiniciar o UERANSIM do core ativo; o **Iniciar tudo** confere o NG Setup do gNB
  simulado.
- **Logs**: `ueransim` e `ueransim-ues`.

## 6. Problemas comuns

| Sintoma | Causa / solução |
|---|---|
| UE em `MM-DEREGISTERED/LIMITED-SERVICE` | corrida do UERANSIM com o SIB1: `kubectl -n open5gs rollout restart deploy/ueransim-ues` |
| `no cells in coverage` | firewall do host bloqueando pod↔pod (firewalld): rode `sudo ./install.sh` |
| registro OK, ping falha após reboot | PFCP SMF↔UPF dessincronizado: `./scripts/heal.sh` ou reiniciar o UPF pelo painel |
| gNB simulado sem NG Setup | AMF parado ou reiniciado depois do gNB: reinicie o UERANSIM |

Mais: [troubleshooting.md](../troubleshooting.md).
