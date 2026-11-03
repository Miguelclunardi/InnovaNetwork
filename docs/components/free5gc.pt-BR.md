# free5GC — core opcional

Core **free5GC v4.3.0** no mesmo cluster, separado do Open5GS: namespace `free5gc`, configuração própria
(`free5gc/free5gc.env`), instalador e desinstalador próprios. Os IPs não colidem com os do Open5GS, então os dois
ficam instalados juntos; **um core por vez** atende o rádio, e a troca é feita no painel.

| | |
|---|---|
| Funções | NRF, AMF, SMF, UPF, AUSF, UDM, UDR, PCF, NSSF, CHF, NEF + MongoDB 7 + WebConsole |
| Configuração | `config.env` (comum) + `free5gc/free5gc.env` (próprio) → manifestos gerados por `free5gc/lib/render.py` |
| N2 / N3 | `10.10.0.30` / `10.10.0.31` na fibra |
| Pools | `internet` 10.60/16 · `internet2` 10.61/16 · `ims` 10.62/16 |
| Nome da rede | `InnovaFree5GC` |
| Assinantes | WebConsole `http://<máquina do core>:31000` (`admin` / `free5gc` — **troque**) |
| Teste | `./free5gc/test.sh` → `6 ok, 0 falha(s)` |

Por que manifestos próprios e não o chart oficial: o chart fixava PLMN e IPs; o gerador recebe tudo da
configuração do projeto e segue a mesma rede do Open5GS.

## 1. Configuração

| Vem do `config.env` (igual nos dois cores) | Vem do `free5gc/free5gc.env` |
|---|---|
| PLMN (MCC/MNC), TAC | versão e imagens (`F5_VERSION`, `F5_REGISTRY`, `F5_MONGO_IMAGE`) |
| slices: SST, SD, DNN (`SLICES`) | pools por slice (`F5_UE_POOLS`) e DNNs extras (`F5_EXTRA_DNNS`, ex.: `ims`) |
| rede da fibra (`RAN_LINK_*`) | IPs na fibra: AMF, UPF, gNB do UERANSIM (`F5_GNB_SIM_IP`) |
| UEs do UERANSIM e `SUBSCRIBERS` | WebConsole (`F5_WEBUI_NODEPORT`), nome da rede (`F5_NETWORK_NAME`), nível de log |

## 2. Rede

Igual ao desenho do Open5GS: tudo pela rede dos pods, **só N2 (AMF) e N3 (UPF) na fibra** (macvlan
`ran-link`). N4 pela rede dos pods: o SMF descobre o IP do UPF na partida (service headless `upf`), por isso **o SMF
é reiniciado depois de um UPF novo** (o painel já faz). N6: NAT dos pools pelo `eth0` do pod do UPF.

O UPF usa o módulo de kernel **gtp5g** (v0.10.2), instalado no host por DKMS.

## 3. Instalar

Máquina do core, com o Open5GS já instalado:

```bash
sudo ./free5gc/setup-gtp5g.sh       # 1x: módulo do kernel (recompila sozinho quando o kernel atualiza)
./free5gc/install.sh --dry-run      # gera e valida, não aplica
./free5gc/install.sh                # instala e sobe em ordem; cadastra os assinantes do config.env
./free5gc/test.sh                   # pods, PFCP, NG Setup, registro, sessão e ping do UE simulado
sudo ./install.sh --dashboard-only  # o painel passa a oferecer a troca de core
```

| Opção | Faz |
|---|---|
| `--parado` | instala e deixa tudo em 0 réplicas |
| `--sem-ueransim` | não sobe o UERANSIM deste core |
| `--assinantes` | cadastra os do `config.env` (UEs do UERANSIM + `SUBSCRIBERS`) |
| `--importar-open5gs` | copia os SIMs cadastrados no Open5GS (que precisa estar no ar) |

Na importação, as chaves passam direto de um banco para o outro, sem aparecer na tela. Slice sem SD vira a de
mesma SST; DNN que o free5GC não tem fica de fora e é listada.

## 4. Usar com o gNB OCUDU

Crie um `.yml` próprio, cópia do usado com o Open5GS trocando só o AMF:

```yaml
cu_cp:
  amf:
    addr: 10.10.0.30        # AMF do free5GC
```

No setup de referência: `~/ocudu/configs/gnb_split_free5gc.yml`. O N3 do gNB continua `10.10.0.1`. A troca de
core no painel oferece só os `.yml` que apontam para o AMF do core escolhido.

## 5. Celulares comerciais

Validado com o OCUDU + LiteOn: registro, sessões `internet` e `ims`, navegação.

- **Voz IMS anunciada** (`imsVoPS: 1`) e DNN **`ims`** são necessárias: sem isso o celular registra e sai da
  célula ~1 s depois (celulares de voz deixam o 5G quando a rede diz que não tem voz). Já configurado.
- **Limitação da slice 2:** quando o celular pede sessão **sem informar a S-NSSAI**, o AMF do free5GC usa sempre a
  primeira slice permitida, sem olhar a DNN. Um celular que pede `internet2` sem slice cai na slice 1 e é
  recusado. O Open5GS escolhe pela DNN e não tem esse problema. Slice 2 funciona com UE que informa a slice
  (UERANSIM, celular com URSP).
- O nome da rede aparece depois do registro; na busca manual aparece o nome do chip.

## 6. Remover

```bash
./free5gc/uninstall.sh              # apaga o namespace free5gc (inclusive os assinantes dele)
sudo ./free5gc/setup-gtp5g.sh --remove
```

## 7. Arquivos

| Arquivo | Para quê |
|---|---|
| `free5gc/free5gc.env` | configuração própria |
| `free5gc/install.sh` · `uninstall.sh` · `test.sh` | instalar, remover, testar |
| `free5gc/setup-gtp5g.sh` | módulo do kernel (sudo, uma vez) |
| `free5gc/lib/render.py` | gera a configuração de cada função, Deployments, Services, permissões do painel e values do UERANSIM |
| `free5gc/lib/subscribers.py` | cadastro pela API do WebConsole e importação do Open5GS |

Certificados: PKI de teste gerada no primeiro install em `~/.config/innovanetwork/free5gc/cert` (fora do git);
o free5GC exige os arquivos mesmo com a SBI em HTTP.
