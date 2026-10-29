# Tutorial 7 — Alterar o gNB

**Objetivo:** mudar a configuração (`.yml`) ou o código do OCUDU e colocar a mudança no ar.
**Tempo:** 5 min (`.yml`) · ~30 min (código). **Precisa de:** gNB no Kubernetes ([tutorial 3](03-ocudu-em-kubernetes.md)).

| Mudou… | Recompilar? | O que fazer |
|---|---|---|
| um `.yml` | não | editar → reiniciar o gNB |
| o código C++ do OCUDU | sim | commit → imagem → `install.sh` → reiniciar |

## A. Mudar um `.yml`

O pod lê `~/ocudu/configs/` **direto do host**, sem cópia.

📡 Máquina do RAN:

```bash
cd ~/ocudu/configs
cp gnb_split_open5gs.yml gnb_teste.yml        # trabalhe numa cópia
nano gnb_teste.yml                                   # ex.: ru_ofh → cells → tx_gain / dl_arfcn
```

🖥️ Máquina do core (ou painel → cartão do gNB → arquivo `gnb_teste` → **▶ Iniciar**):

```bash
./ran/ocudu/gnb.sh iniciar gnb_teste
./ran/ocudu/gnb.sh log -f
```

O pod é recriado com o novo arquivo (~15 s até o N2). Para voltar: `./ran/ocudu/gnb.sh iniciar gnb_split_open5gs`.

> Não altere o `metricas.yml`: ele liga as métricas lidas pelo painel.

## B. Mudar o código do OCUDU

A imagem é gerada **do commit**: mudanças sem commit não entram.

📡 Máquina do RAN:

```bash
cd ~/ocudu
git checkout -b minha-mudanca
# … editar o código …
git commit -am "minha mudança"
sudo ~/innovanetwork-ran/no-ran.sh imagem 2>&1 | tee ~/innovanetwork-ran/build.log
```

Resultado: uma imagem nova `innovanetwork/ocudu-gnb:<novo commit>`, importada no k3s.

🖥️ Máquina do core:

```bash
./ran/ocudu/install.sh            # o Deployment passa a usar a tag do commit atual (mantém o .yml)
./ran/ocudu/gnb.sh iniciar        # reinicia com a imagem nova
kubectl -n ocudu get deploy ocudu-gnb -o jsonpath='{.spec.template.spec.containers[0].image}'
```

### Voltar para a versão anterior

📡 `git -C ~/ocudu checkout <commit anterior>` — a imagem dele já existe no nó (a tag é o commit), então basta 🖥️
`./ran/ocudu/install.sh` e `./ran/ocudu/gnb.sh iniciar`.

Imagens antigas ocupam ~140 MB cada; limpe com 📡 `sudo k3s crictl rmi <imagem>` e `sudo docker rmi <imagem>`.

## Dicas

- A compilação usa `OCUDU_BUILD_JOBS` CPUs fora das reservadas ao gNB, mas pesa na máquina: evite durante
  experimentos.
- `OCUDU_IMAGE_MARCH="native"` otimiza para a CPU do nó; a imagem não serve para outra CPU diferente.
- Para comparar antes/depois, grave um experimento com cada versão ([tutorial 8](08-experimentos.md)).
