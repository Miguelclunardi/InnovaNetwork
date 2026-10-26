# Rádio — OCUDU + LiteOn (innovaserver)

Como o gNB real do InnovaNetwork está montado e como ele se liga ao core do torre2.
Visão geral do projeto: [README](../README.md). Operação: [operacao.md](operacao.md).

> O OCUDU roda **direto no host** (CPU dedicada, DPDK, PTP) e **nunca em container ou no k3s**. O projeto só
> instala no innovaserver o serviço `ocudu-gnb@` (para o painel iniciar e parar o gNB); a preparação da máquina é
> dela própria (serviços de boot listados abaixo).

## 1. Peças

| Peça | Detalhe |
|---|---|
| **innovaserver** | Máquina do gNB. Rede da universidade em `eno1np0` (DHCP, ex.: 191.4.205.80) |
| **Intel E810-C (4 portas SFP)** | Porta 1 `ens4f0np0`: fronthaul até a RU (VF `0000:ac:01.0` em DPDK) e PTP grandmaster. Porta 4 `ens4f3np3`: fibra até o torre2, `10.10.0.1/24`, MTU 9000 |
| **OCUDU** | `~/ocudu` (binário `build/apps/gnb/gnb`, arquivos em `configs/`). CU + DU no mesmo processo, split 7.2 |
| **LiteOn FlexFi FR1** | O-RU n78, 4T4R. Gestão (SSH/CLI) em `10.101.131.59`, no switch da rede de gestão |
| **GNSS** | Referência de tempo da E810 (`ts2phc` lê NMEA) |

## 2. Célula

Igual nos dois cores (só o AMF muda entre os arquivos `.yml`):

| Parâmetro | Valor |
|---|---|
| Banda / ARFCN | n78 / `649980` |
| Largura / SCS | 100 MHz / 30 kHz, TDD |
| Antenas | 4 DL × 4 UL (portas 0–3 no fronthaul) |
| PLMN / TAC / PCI | `00101` / `1` / `1` |
| Slices | SST 1 SD `0x111111` (50–70 % dos PRBs) · SST 2 SD `0x222222` (30–50 %) |
| Fronthaul | VLAN 564 (C e U-plane), compressão BFP 9 bits, RU MAC `e8:c7:4f:25:83:dd` |

## 3. Um `.yml` por core

Os arquivos ficam em `~/ocudu/configs/`. Para cada core existe uma cópia em que só muda `cu_cp.amf.addr`:

| Arquivo | AMF (`cu_cp.amf.addr`) | Core |
|---|---|---|
| `gnb_ru_liteon_SLPIT_CORE.yml` | `10.10.0.10` | Open5GS no torre2 (padrão) |
| `gnb_ru_liteon_FREE5GC.yml` | `10.10.0.30` | free5GC no torre2 |
| `gnb_ru_liteon_tdd_n78_100mhz.yml`, `gnb_ru_liteon_SLICE.yml` | `127.0.0.5` | Open5GS local do innovaserver (antigo, fora do projeto) |

Nos dois arquivos do torre2: `bind_addr: 10.10.0.1` (N2) e `cu_up.ngu.socket.bind_addr: 10.10.0.1` (N3). O
endereço N3 do UPF não aparece no `.yml`: o SMF o informa na sessão.

O painel lê de cada `.yml` o AMF configurado e, na troca de core, **oferece só os arquivos que apontam para o
AMF do core escolhido**. Para criar o arquivo de um core novo: copie um existente e troque só o `addr`.

O serviço passa `configs/metricas.yml` como segundo `-c` (se existir). É ele que liga o `remote_control` na porta
**8001** (métricas JSON que o painel lê). **Não altere o `metricas.yml`.**

## 4. Preparação da máquina (serviços de boot do innovaserver)

Estes serviços são da máquina, não do projeto; sobem sozinhos no boot:

| Serviço | O que faz |
|---|---|
| `ocudu-setup` | `/usr/local/sbin/setup-ocudu.sh`: porta do fronthaul com MTU 1500 (só PTP), offloads de VLAN desligados, 1 VF SR-IOV em `vfio-pci` (DPDK) com `trust on`/`spoofchk off`, programa XDP `/usr/local/lib/ocudu/ptp-trim.o` na porta (ajuste do PTP para a RU), `ip_forward` |
| `dpdk` | ambiente do DPDK (hugepages) |
| `ts2phc` | relógio da E810 a partir do GNSS |
| `ptp4l-gm` | PTP grandmaster em `ens4f0np0` (a RU sincroniza por aqui) |
| `phc2sys` | relógio do sistema a partir da E810 |

Se algum falhar, o gNB não sobe ou a RU não sincroniza. Conferir: `systemctl status ocudu-setup ptp4l-gm ts2phc phc2sys`.

> Regras: a porta 1 da E810 (fronthaul/PTP) e o PTP **não** são mexidos pelo projeto. Nada de `netplan apply`
> no innovaserver sem combinar.

## 5. Serviço `ocudu-gnb@<arquivo>`

Criado uma vez com `scripts/ocudu/setup-gnb-service.sh` (sudo no innovaserver). Ele roda, a partir da pasta do
OCUDU do usuário:

```
taskset -c 0-17 ~/ocudu/build/apps/gnb/gnb -c configs/<arquivo>.yml [-c configs/metricas.yml]
```

- Parar = SIGINT (igual a Ctrl+C). Um gNB por vez: se houver um `gnb` aberto no terminal, o serviço recusa.
- Uma regra do **polkit** deixa só o usuário `innovaserver` iniciar/parar essas units, sem sudo.
- No torre2, a unit `open5gs-k3s-gnb-ctl` lê o estado a cada 3 s (serviço, `.yml` com o AMF de cada um, PTP,
  driver da VF) e executa os pedidos do painel com `systemctl`.

À mão, no innovaserver:

```bash
systemctl start ocudu-gnb@gnb_ru_liteon_SLPIT_CORE    # Open5GS
systemctl start ocudu-gnb@gnb_ru_liteon_FREE5GC       # free5GC
systemctl stop  'ocudu-gnb@*'
journalctl -u 'ocudu-gnb@*' -f                         # saída do processo; log completo em /tmp/gnb.log
```

## 6. Como o gNB fala com o core

| Interface | Do innovaserver | Para o torre2 | Por onde |
|---|---|---|---|
| N2 (NGAP/SCTP 38412) | `10.10.0.1` | AMF `10.10.0.10` (Open5GS) ou `10.10.0.30` (free5GC) | fibra |
| N3 (GTP-U 2152) | `10.10.0.1` | UPF `10.10.0.11` ou `10.10.0.31` | fibra |
| Métricas | `:8001` (WebSocket) | painel (`GNB_METRICS_URL`) | fibra |
| Log | `/tmp/gnb.log` | unit `open5gs-k3s-gnb-log` (SSH, `tail -F`, só leitura) | fibra |

A RU é lida pelo torre2 na rede de gestão (`10.101.131.59`, SSH só com comandos `show`; senha num arquivo do
root, fora do git) — aba **RU** do painel.

## 7. Problemas comuns

| Sintoma | Causa provável / o que fazer |
|---|---|
| gNB sobe mas não aparece no AMF | `.yml` aponta para o outro core, ou o AMF reiniciou depois do gNB: reinicie o gNB |
| RU sem "DU conectado" | PTP fora (`ptp4l-gm`, `ts2phc`) ou VF não está em `vfio-pci` (`dpdk-devbind.py --status`) |
| Serviço recusa iniciar | já existe um `gnb` rodando fora do serviço (Ctrl+C nele) ou outro `ocudu-gnb@` ativo |
| Celular registra e sai ~1 s depois (free5GC) | falta voz IMS anunciada / DNN `ims` — já configurado no `free5gc.env` |
| `/tmp/gnb.log` enorme | o log fica em nível `info`; rotacionar ou apagar com o gNB parado |
