# Hardware de referência: Intel E810 + O-RU LiteOn FlexFi

O setup em que o InnovaNetwork foi validado. Use como referência para montar o seu: o que muda de um setup para
outro fica em `ran/ocudu/ocudu.env` e nos `.yml` do gNB.

> Contribua com o seu perfil de hardware: veja [CONTRIBUTING.md](../../CONTRIBUTING.md).

## 1. Peças

| Peça | Detalhe |
|---|---|
| **Máquina do RAN** | x86_64, Ubuntu 24.04, kernel de baixa latência; CPUs 0–17 isoladas para o gNB; hugepages de 1 GiB |
| **Intel E810-C, 4 portas SFP** | porta 1 (`ens4f0np0`): fronthaul até a O-RU (VF `vfio-pci` em DPDK) e PTP grandmaster · porta 4 (`ens4f3np3`): fibra até a máquina do core, `10.10.0.1/24`, MTU 9000 |
| **GNSS** | referência de tempo da E810 (`ts2phc` lê o PPS/NMEA) |
| **O-RU LiteOn FlexFi FR1** | n78, TDD, 4T4R, O-RAN split 7.2; gestão por SSH em `10.101.131.59` (porta RJ45) |
| **Máquina do core** | porta `enp5s0f1` na fibra (`10.10.0.2/24`); IP extra `10.101.131.10/24` na rede de gestão da O-RU |

## 2. Célula

Igual nos dois cores (só o AMF muda entre os `.yml`):

| Parâmetro | Valor |
|---|---|
| Banda / ARFCN | n78 / `649980` |
| Largura / SCS | 100 MHz / 30 kHz, TDD |
| Antenas | 4 DL × 4 UL |
| PLMN / TAC / PCI | `00101` / `1` / `1` |
| Slices | SST 1 SD `0x111111` · SST 2 SD `0x222222` (divisão de PRBs por slice) |
| Fronthaul | VLAN 564 (C e U-plane), compressão BFP 9 bits |

## 3. Preparação da máquina do RAN

Serviços do host (não do InnovaNetwork), que sobem no boot:

| Serviço | O que faz |
|---|---|
| `ocudu-setup` | porta do fronthaul com MTU 1500 (só PTP), offloads de VLAN desligados, 1 VF SR-IOV em `vfio-pci` com `trust on` / `spoofchk off`, programa XDP de ajuste do PTP, `ip_forward` |
| `dpdk` | ambiente do DPDK (hugepages) |
| `ts2phc` | relógio da E810 a partir do GNSS |
| `ptp4l-gm` | PTP grandmaster na porta do fronthaul (a O-RU sincroniza por aqui) |
| `phc2sys` | relógio do sistema a partir da E810 |

Conferir: `systemctl status ocudu-setup ptp4l-gm ts2phc phc2sys` e `dpdk-devbind.py --status`.

## 4. Sincronismo: espere o GNSS

Depois de um boot o GNSS pode levar **até ~30 min** para dar hora válida (`ts2phc` mostra `source ts not valid`).
Até lá o relógio da E810, que é o mestre PTP da O-RU, pode estar **dezenas de segundos errado**. Quando o GNSS
volta, o `ts2phc` corrige com um salto (observado: entre −31 e −37 s). Consequências:

- uma O-RU que sincronizou no tempo errado **não se acerta sozinha**: mostra `SYNCHRONIZED`, mas só ~5 % dos
  pacotes do fronthaul chegam no tempo (normal: ~90 %) e o uplink some (os celulares fazem PRACH, mas a Msg3 não
  chega);
- o relógio do sistema leva minutos para alcançar.

**Sequência depois de um boot:**

```bash
journalctl -u ts2phc -f                          # 1. esperar "offset … s2"
sudo systemctl restart ptp4l-gm phc2sys          # 2. acerta o relógio do sistema e recoloca o XDP (gNB parado)
# 3. reiniciar a O-RU
# 4. ligar o gNB (painel ou ./ran/ocudu/gnb.sh iniciar)
```

O InnovaNetwork já impede o gNB de ligar sozinho depois do boot ([proteção de boot](../componentes/ocudu.md#proteção-de-boot)).

## 5. XDP de ajuste do PTP

A O-RU LiteOn envia Delay_Req com enchimento que o `ptp4l` rejeita ("bad message", dezenas por segundo). Um
programa XDP na porta do fronthaul corta esse enchimento.

- **Os celulares funcionam sem ele** (a O-RU segue o PTP pelos Sync), mas sem medir o atraso.
- O XDP sai da porta quando o link da O-RU cai (O-RU reiniciando) e quando o `ptp4l` reinicia a porta depois de
  uma falha "timed out while polling for tx timestamp". Carregá-lo com o `ptp4l` rodando também causa essa falha.
- Ajustes: `tx_timestamp_timeout 50` em `/etc/linuxptp/ptp4l.cfg` e um `ExecStartPre` no `ptp4l-gm` que carrega o
  XDP antes do `ptp4l`. Para recolocar: `sudo systemctl restart ptp4l-gm phc2sys` com o gNB parado.

## 6. Valores do `ocudu.env` para este hardware

```bash
OCUDU_NODE_IP="10.10.0.1"; OCUDU_NODE_IFACE="ens4f3np3"   # porta 4 (fibra), nunca a porta do fronthaul
OCUDU_CPUS="0-17"                                         # = CPUs isoladas
OCUDU_HUGEPAGES_1G="2Gi"                                  # = --socket-mem 2048 do eal_args
OCUDU_IMAGE_MARCH="native"                                # imagem otimizada para esta CPU
```

## 7. Indicadores de saúde

| Onde | Normal |
|---|---|
| painel → RU | `SYNCHRONIZED`, DU `Ready`, ~90–92 % dos pacotes no tempo, 0 atrasados |
| painel → Máquinas | CPUs do DPDK do gNB em 100 % (laço de polling) — esperado |
| `journalctl -u phc2sys` | offset de poucos ns, estado `s2` |

## 8. Problemas comuns

| Sintoma | Causa provável / o que fazer |
|---|---|
| celulares fazem PRACH mas não conectam; muitos pacotes adiantados/atrasados | O-RU sincronizou antes do GNSS: seção 4 |
| O-RU sem "DU conectado" | PTP parado (`ptp4l-gm`, `ts2phc`) ou VF fora do `vfio-pci` |
| "bad message" no `ptp4l` | XDP fora da porta: seção 5 |
| `/tmp/gnb.log` enorme | nível `info`: rotacione ou apague com o gNB parado |
