# free5GC — segundo core (InnovaNetwork)

> **Opcional.** O padrão do InnovaNetwork é OCUDU + Open5GS (o `install.sh` da raiz). O free5GC só existe se
> você rodar `free5gc/install.sh`; sem ele nada muda.

Core **free5GC v4.3.0** no mesmo k3s do torre2, separado do Open5GS: namespace `free5gc`, configuração
própria (`free5gc/free5gc.env`), instalador e desinstalador próprios. **Um core por vez** em operação
(o gNB OCUDU aponta para um AMF de cada vez), mas os IPs não colidem, então os dois podem coexistir instalados.

## O que é comum e o que é próprio

| Vem do `config.env` (igual nos dois cores) | Vem do `free5gc/free5gc.env` |
|---|---|
| PLMN (MCC/MNC), TAC, `NETWORK_NAME` | versão e imagens (`F5_VERSION`) |
| slices: SST, SD, DNN (`SLICES`) | pool de IPs dos UEs por slice (`F5_UE_POOLS`: 10.60/16, 10.61/16) |
| link da fibra (`RAN_LINK_*`) | IPs na fibra: AMF `10.10.0.30`, UPF `10.10.0.31`, gNB simulado `10.10.0.32` |
| UEs do UERANSIM e `SUBSCRIBERS` | WebConsole NodePort `31000` |

## Rede

Igual ao desenho do Open5GS: tudo pela rede dos pods, **só N2 (AMF) e N3 (UPF) na fibra** (macvlan `ran-link`
em `RAN_LINK_IFACE`). N4 (PFCP) pela rede dos pods: o SMF descobre o IP do UPF na partida (serviço headless
`upf`), por isso **o SMF precisa ser reiniciado depois de um UPF novo** (o painel já faz isso). N6: o UPF faz NAT
dos pools para a internet pelo `eth0` do pod.

## Instalar

1. Uma vez, com sudo, o módulo do kernel do UPF (DKMS; recompila sozinho quando o kernel atualizar; não afeta o Open5GS):
   ```bash
   sudo ./free5gc/setup-gtp5g.sh
   ```
2. Como usuário comum (não precisa de sudo):
   ```bash
   ./free5gc/install.sh --dry-run    # gera e valida, não aplica
   ./free5gc/install.sh              # instala e sobe em ordem; cadastra os assinantes do config.env
   ./free5gc/test.sh                 # pods, PFCP, NG Setup, registro, sessão e ping do UE simulado
   ```
   `--parado` instala e deixa tudo em 0 réplicas; `--sem-ueransim` não sobe o UERANSIM deste core.

## Assinantes

- `./free5gc/install.sh --assinantes`: cadastra os do `config.env` (UEs do UERANSIM + `SUBSCRIBERS`).
- `./free5gc/install.sh --importar-open5gs`: copia os SIMs cadastrados na WebUI do Open5GS (o Open5GS precisa
  estar no ar). As chaves passam direto de um banco para o outro, sem aparecer na tela. Slice sem SD vira a slice
  de mesma SST; DNN que o free5GC não tem (ex.: `ims`) fica de fora e é listada.
- WebConsole: `http://<IP do torre2>:31000`, usuário `admin`, senha padrão `free5gc` — **troque**.

## gNB OCUDU

Um `.yml` próprio, cópia do que usa o Open5GS com o AMF trocado (`cu_cp.amf.addr: 10.10.0.30`), por exemplo
`configs/gnb_ru_liteon_FREE5GC.yml`. O N3 do gNB continua `10.10.0.1`. Iniciar pela aba Controle.

## Remover

`./free5gc/uninstall.sh` apaga só o namespace `free5gc` (inclusive os assinantes dele). O módulo:
`sudo ./free5gc/setup-gtp5g.sh --remove`.

## Arquivos

| Arquivo | Para quê |
|---|---|
| `free5gc.env` | configuração própria do free5GC |
| `install.sh` / `uninstall.sh` / `test.sh` | instalar, remover, conferir |
| `setup-gtp5g.sh` | módulo do kernel (sudo, uma vez) |
| `lib/render.py` | gera os manifestos e a configuração de cada função a partir dos dois arquivos de config |
| `lib/subscribers.py` | cadastro pela API do WebConsole (e importação do Open5GS) |

Certificados: PKI de teste gerada no primeiro install em `~/.config/innovanetwork/free5gc/cert` (fora do git).
O free5GC exige os arquivos mesmo com a SBI em http.
