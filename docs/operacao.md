# Operação

O dia a dia da rede. Quase tudo é feito pelo **painel** (`http://<IP da máquina do core>:30998`).

- [1. Login de administrador](#1-login-de-administrador)
- [2. Depois de ligar as máquinas](#2-depois-de-ligar-as-máquinas)
- [3. Ligar e parar](#3-ligar-e-parar)
- [4. Trocar de core](#4-trocar-de-core)
- [5. O gNB OCUDU](#5-o-gnb-ocudu)
- [6. Assinantes (SIMs)](#6-assinantes-sims)
- [7. Mudar a configuração](#7-mudar-a-configuração)
- [8. Testar](#8-testar)
- [9. Comandos úteis](#9-comandos-úteis)

---

## 1. Login de administrador

Ver o estado é livre. Ações (iniciar, parar, trocar core, editar a configuração) pedem a senha de administrador:

- **🔒 Admin**, no topo: um login vale para todas as abas e janelas do mesmo navegador, por 8 h;
- **🔓 Admin · Sair** encerra a sessão;
- a senha está em `sudo cat /opt/open5gs-k3s/state/dashboard-admin-password` (máquina do core).

## 2. Depois de ligar as máquinas

Por segurança, **só o painel sobe sozinho** (`CORE_AUTOSTART=false`). Core e gNB são ligados pelo operador.

| # | Onde | O que fazer | Pronto quando |
|---|---|---|---|
| 1 | painel | **🔒 Admin** → aba **Controle** → confira o **Core ativo** → **▶ Iniciar tudo** | todas as etapas ✓ (AMF escutando N2, SMF associado ao UPF) |
| 2 | máquina do RAN | esperar o GNSS: `journalctl -u ts2phc -f` | linhas com `offset … s2` (até ~30 min após o boot) |
| 3 | máquina do RAN | se o relógio deu salto (o normal após o boot): `sudo systemctl restart ptp4l-gm phc2sys` | `phc2sys` com offset de poucos ns |
| 4 | O-RU | reiniciar a O-RU (ela sincronizou com o relógio antigo) | aba **RU**: `SYNCHRONIZED` |
| 5 | painel | cartão **gNB (Kubernetes)**: escolher o `.yml` do core ativo → **▶ Iniciar** | a aba confere pod rodando, DU conectado e N2 no AMF |
| 6 | painel | **Visão geral** | celulares registrados com IP |

> Se a máquina do RAN reiniciar, o pod do gNB volta **sem ligar o gNB** e mostra "parado (nó reiniciou)". É a
> proteção de boot: ligue de novo pelo painel depois dos passos 2–4. Ver [componentes/ocudu.md](componentes/ocudu.md#proteção-de-boot).

Os IPs da rede local (DHCP) podem mudar após um reboot. Só o endereço para abrir o painel muda; o cluster e a
fibra usam IPs fixos.

## 3. Ligar e parar

Aba **Controle**:

| Ação | O que acontece |
|---|---|
| **▶ Iniciar tudo** | sobe o core ativo em ordem (MongoDB → NRF → … → UPF → SMF → AMF → UERANSIM) conferindo cada etapa nos logs |
| **■ Parar tudo** | escala o core e o UERANSIM para 0 (nada é apagado: configuração e assinantes ficam) |
| botões por função | iniciar / parar / reiniciar uma função; reiniciar UPF também reinicia o SMF, e AMF reinicia o gNB do UERANSIM |
| cartão do gNB | iniciar com um `.yml` / reiniciar / parar o gNB OCUDU |

Antes de desligar as máquinas, pare o gNB e depois o core.

## 4. Trocar de core

Disponível com o free5GC instalado. **Derruba quem estiver conectado** durante a troca.

1. Aba **Controle** → cartão **Core ativo** → clique no outro core.
2. Deixe **religar o gNB OCUDU com** marcado e escolha o `.yml` que aponta para o AMF do novo core (o painel só
   lista esses).
3. **Trocar agora.** O painel para o gNB → para o core atual → marca o novo → sobe o novo conferindo cada etapa →
   religa o gNB.

Tempos típicos: Open5GS → free5GC ~1 min; free5GC → Open5GS ~5 min. Todas as abas passam a seguir o core ativo
(funções, logs, assinantes, sessões, tráfego).

> Use sempre o cartão **Core ativo**. Parar um core e iniciar o outro pelos botões separados não mexe no gNB, que
> fica apontando para o AMF antigo.

Tutorial: [Trocar de core](tutoriais/05-trocar-de-core.md).

## 5. O gNB OCUDU

Pelo painel (cartão **gNB (Kubernetes)**) ou pela linha de comando, na máquina do core:

```bash
./ran/ocudu/gnb.sh configs                 # .yml disponíveis e o AMF de cada um
./ran/ocudu/gnb.sh iniciar <yml>           # liga (sem extensão; padrão: o atual)
./ran/ocudu/gnb.sh parar                   # SIGINT ao gNB, como Ctrl+C
./ran/ocudu/gnb.sh estado                  # réplicas, .yml, pod, nó, reinícios
./ran/ocudu/gnb.sh log -f                  # saída do gNB (log completo: /tmp/gnb.log no nó)
```

| Mudou… | Faça |
|---|---|
| um `.yml` em `~/ocudu/configs/` (nó do RAN) | reinicie o gNB. O pod lê a pasta do host; não precisa recompilar |
| o código do OCUDU | commit → recompilar a imagem → `./ran/ocudu/install.sh` → reiniciar. Ver [tutorial 7](tutoriais/07-alterar-o-gnb.md) |
| o AMF do core reiniciou | reinicie o gNB (ele não refaz o N2 sozinho) |

## 6. Assinantes (SIMs)

| Core | Onde |
|---|---|
| Open5GS | painel → **Core** → **Assinantes** (WebUI `:30999`); ou `SUBSCRIBERS` no `config.env` + `sudo ./install.sh --deploy-only`; ou `./scripts/subscribers.sh` |
| free5GC | painel → **Core** → **Assinantes** (WebConsole `:31000`); ou `./free5gc/install.sh --importar-open5gs` |

As chaves (K/OPc) nunca vão para o git nem aparecem na tela na importação. Tutorial:
[Celular na rede](tutoriais/04-celular-na-rede.md).

## 7. Mudar a configuração

| Onde | Aplicar com | Efeito |
|---|---|---|
| painel → aba **Configuração** (edita o `config.env` com diff e validação) | o comando que o painel indicar | salvar **não aplica** |
| `config.env` — core/UERANSIM | `sudo ./install.sh --deploy-only` | recria as funções que mudaram (derruba usuários) |
| `config.env` — painel | `sudo ./install.sh --dashboard-only` | só o painel reinicia |
| `config.env` — host/k3s | `sudo ./install.sh` | pode reiniciar o k3s |
| `free5gc/free5gc.env` | `./free5gc/install.sh` | recria o free5GC |
| `ran/ocudu/ocudu.env` | `./ran/ocudu/install.sh` | atualiza o Deployment (preserva `.yml` e estado ligado/desligado) |

Cuidados:

- rode `--deploy-only` **com o Open5GS como core ativo**: o Helm volta as réplicas do Open5GS para 1;
- não rode instalador e troca de core ao mesmo tempo;
- depois de recriar o AMF, reinicie o gNB.

Tutorial: [Mudar PLMN, slices e IPs](tutoriais/06-mudar-configuracao.md).

## 8. Testar

| Teste | Comando (máquina do core) | Esperado |
|---|---|---|
| Open5GS + UERANSIM | `./test.sh` (`-v` mostra logs em caso de falha) | `7 verificações OK` |
| free5GC + UERANSIM | `./free5gc/test.sh` | `6 ok, 0 falha(s)` |
| gNB real | painel → **RU** e **Rádio** | `SYNCHRONIZED`, DU `Ready`, ~90 % no tempo; UEs com vazão |
| celular | painel → **Visão geral** | registrado, sessão com IP do pool do core ativo |

Os testes só leem o estado e usam o UE simulado; o core testado precisa estar ligado.

## 9. Comandos úteis

```bash
kubectl get nodes -o wide                         # as duas máquinas Ready?
kubectl get pods -A -o wide                       # tudo, com o nó de cada pod
kubectl -n open5gs logs deploy/open5gs-amf -f     # AMF ao vivo
kubectl -n ocudu logs deploy/ocudu-gnb -f         # gNB
journalctl -u open5gs-k3s-gnb-ctl -f              # agente de controle do gNB (máquina do core)
less logs/install.log                             # histórico do instalador
```

Problemas: [troubleshooting.md](troubleshooting.md).
