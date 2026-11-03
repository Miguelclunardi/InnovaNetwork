# Tutorial 3 — OCUDU em Kubernetes

**Objetivo:** levar o gNB OCUDU, que já funciona na máquina do RAN, para dentro do cluster como um pod, e
controlá-lo pelo painel.
**Tempo:** ~1 h (a compilação leva ~15 min). **Precisa de:** core instalado; máquina do RAN preparada
([requisitos](../instalacao.md#máquina-do-ran-só-para-a-parte-3)); SSH sem senha da máquina do core para a do RAN.

> Cada passo diz **onde** rodar. 🖥️ = máquina do core (na pasta do repositório). 📡 = máquina do RAN.
> Guarde a saída dos passos longos com `2>&1 | tee arquivo.log`.

## Passo 0 — Conferir o ponto de partida

📡 O gNB nativo funciona e está **parado**; o código do OCUDU está commitado:

```bash
pgrep -ax gnb || echo "nenhum gnb rodando"
git -C ~/ocudu status --short | head          # vazio = tudo commitado
git -C ~/ocudu log --oneline -1               # este commit vira a tag da imagem
ls ~/ocudu/configs/*.yml
```

🖥️ O core está no ar e o nó do RAN responde pela fibra:

```bash
kubectl get nodes
ssh -o BatchMode=yes usuario@10.10.0.1 hostname
```

## Passo 1 — Configurar

🖥️ Revise `ran/ocudu/ocudu.env` (nó, IPs, pasta do OCUDU, CPUs, hugepages). Tabela das variáveis:
[componentes/ocudu.md](../componentes/ocudu.md#3-configuração-ocuduenv).

## Passo 2 — Copiar os scripts para o nó

🖥️
```bash
./ran/ocudu/install.sh copiar
```

Esperado: `~/innovanetwork-ran/` criado no nó com `no-ran.sh` e `ocudu.env`.

## Passo 3 — Compilar a imagem

📡
```bash
sudo ~/innovanetwork-ran/no-ran.sh imagem 2>&1 | tee ~/innovanetwork-ran/build.log
```

Esperado, no fim: `[ok]` com a imagem `innovanetwork/ocudu-gnb:<commit>` e a confirmação de que ela tem `gnb`,
`taskset` e `bash`. Confira com `sudo docker images innovanetwork/ocudu-gnb`.

## Passo 4 — Preparar o servidor

🖥️
```bash
sudo ./ran/ocudu/install.sh preparar
```

Esperado: firewall liberado (se houver UFW) e o token copiado para `~/innovanetwork-ran/join.env` no nó (válido
por 2 h; ele não aparece na tela).

## Passo 5 — O nó entra no cluster

📡
```bash
sudo ~/innovanetwork-ran/no-ran.sh entrar 2>&1 | tee ~/innovanetwork-ran/entrar.log
```

🖥️ Conferir:

```bash
kubectl get nodes -o wide
# NAME           STATUS   ROLES           INTERNAL-IP
# innovaserver   Ready    <none>          10.10.0.1
# torre2         Ready    control-plane   10.254.254.1
kubectl describe node innovaserver | grep -E "Taints|role=ran|hugepages-1Gi"
```

Se a imagem foi compilada depois de entrar: 📡 `sudo ~/innovanetwork-ran/no-ran.sh importar`.

## Passo 6 — Criar o Deployment

🖥️
```bash
./ran/ocudu/install.sh --dry-run
./ran/ocudu/install.sh
kubectl -n ocudu get deploy,cm        # ocudu-gnb 0/0 (parado) + descritor
```

## Passo 7 — Ligar o gNB pela linha de comando

Antes: GNSS válido e O-RU sincronizada ([hardware](../hardware/e810-liteon.md#4-sincronismo-espere-o-gnss)).

🖥️
```bash
./ran/ocudu/gnb.sh configs
./ran/ocudu/gnb.sh iniciar gnb_split_open5gs
./ran/ocudu/gnb.sh log -f
```

Esperado no log:

```
ocudu-gnb: taskset -c 0-17 gnb -c /configs/gnb_split_open5gs.yml -c /configs/metricas.yml
N2: Connection to AMF on 10.10.0.10:38412 completed
==== gNB started ===
```

E no painel → **RU**: `SYNCHRONIZED`, DU `Ready`, ~90 % dos pacotes no tempo.

## Passo 8 — Passar o controle para o painel

🖥️ No `config.env`:

```bash
GNB_CTL_MODE="k8s"
GNB_CTL_SSH="usuario@10.10.0.1"
GNB_CTL_DIR="/home/usuario/ocudu"
```

```bash
sudo ./install.sh --dashboard-only
```

No painel, aba **Controle**, o cartão vira **gNB (Kubernetes)** e mostra o pod rodando com o `.yml` e o PID.
Teste **↻ Reiniciar**: a aba confere o pod, o DU conectado na O-RU e o N2 no AMF.

## Passo 9 — Testar a proteção de boot (opcional)

📡 `sudo reboot`. Quando o nó voltar:

- 🖥️ `kubectl get nodes` → o nó `Ready` de novo, sozinho;
- painel → cartão do gNB: **"parado (nó reiniciou)"** — o gNB não ligou sozinho;
- depois do GNSS (`s2`), `sudo systemctl restart ptp4l-gm phc2sys`, reiniciar a O-RU e **▶ Iniciar** no painel.

## O que você fez

O nó do RAN virou parte do cluster, e o gNB passou a ser um pod com o mesmo binário, comando, configuração e
desempenho do serviço nativo, agora ligado e desligado pelo Kubernetes. Próximo: [Celular na rede](04-celular-na-rede.md).
