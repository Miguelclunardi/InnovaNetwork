# Operação do InnovaNetwork

O dia a dia da rede: ligar, trocar de core, testar, cadastrar SIMs e resolver problemas. Quase tudo é feito pelo
**painel** (`http://<IP do torre2>:30998`). Visão geral: [README](../README.md).

## 1. Login de administrador

Ver o estado é livre. Ações (iniciar, parar, trocar core, editar o `config.env`) pedem a senha de administrador:

- clique em **🔒 Admin** no topo do painel; **um login vale para todas as abas** (Controle, Configuração) e para
  as outras abas/janelas do mesmo navegador, por 8 h;
- **🔓 Admin · Sair** encerra a sessão em todas elas;
- a senha aparece no fim do `sudo ./install.sh` e fica em `sudo cat /opt/open5gs-k3s/state/dashboard-admin-password`.

## 2. Depois de ligar as máquinas

Com `CORE_AUTOSTART=false` (padrão) **só o painel sobe** no boot; os cores ficam parados (Open5GS e free5GC).
O innovaserver sobe sozinho a preparação (DPDK, XDP, PTP), mas **não** o gNB.

1. Painel → **🔒 Admin**.
2. Aba **Controle** → cartão **Core ativo**: confira qual core vai usar (o último escolhido fica marcado).
3. **▶ Iniciar tudo** — sobe o core ativo em ordem (MongoDB → NRF → … → UPF → SMF → AMF → UERANSIM) e confere
   cada etapa nos logs (UPF no IP da fibra, SMF associado ao UPF, AMF escutando N2, NG Setup do gNB simulado).
   Pod que sobe sem a interface da fibra é recriado sozinho.
4. Cartão **gNB OCUDU**: escolha o `.yml` do core ativo (os outros aparecem marcados) e **Iniciar**. A aba confere
   o serviço, a RU com "DU conectado" e o N2 no AMF.
5. **Visão geral**: celulares registrados, sessões e tráfego.

> Os IPs da universidade (DHCP) podem mudar depois de um reboot. O painel continua em
> `http://<novo IP do torre2>:30998`; nada dentro do projeto depende desses IPs.

## 3. Trocar de core (Open5GS ⇄ free5GC)

Só aparece quando o free5GC está instalado. **Derruba quem estiver conectado** durante a troca.

1. Aba **Controle** → cartão **Core ativo** → clique no outro core.
2. Na caixa que abre:
   - **religar o gNB OCUDU com** — marcado se o gNB estiver rodando; escolha o `.yml` que aponta para o AMF do
     core novo (o painel só lista esses);
   - **Trocar agora**.
3. O painel, em ordem: para o gNB OCUDU → para o core atual e o UERANSIM dele → marca o novo core como ativo →
   sobe o novo core inteiro conferindo cada etapa → religa o gNB com o `.yml` escolhido.
4. O andamento aparece no topo da aba Controle e vai para os eventos e o histórico.

Tempos medidos (2026-10-26, sem gNB): free5GC → Open5GS ~5 min (o Open5GS tem mais funções e espera o NRF/SCP);
Open5GS → free5GC ~1 min. Com o gNB, some ~15 s para o N2.

Depois da troca, **todas as abas seguem o core ativo**: nomes das funções, logs, assinantes (WebUI do Open5GS ou
WebConsole do free5GC), sessões e tráfego. Rádio, RU, Máquinas e Histórico não mudam; cada experimento gravado
registra o core em uso.

Prefira sempre o painel para trocar: ele segue a ordem certa e confere cada etapa. Escalar Deployments à mão
no namespace `open5gs` também para o painel, que mora lá.

## 4. Parar tudo

Aba **Controle** → **■ Parar tudo** (escala para 0; nada é apagado: configuração e assinantes ficam).
O gNB OCUDU tem botão próprio. Antes de desligar as máquinas, pare o gNB primeiro.

## 5. Testar

| Teste | Comando (no torre2, `~/InnovaNetwork`) | Esperado |
|---|---|---|
| Open5GS + UERANSIM | `./test.sh` | `7 verificações OK` |
| free5GC + UERANSIM | `./free5gc/test.sh` | `6 ok, 0 falha(s)` |
| Celular real | Visão geral do painel | registrado, sessão com IP do pool do core ativo, tráfego |

Os testes só leem o estado (e usam o UE simulado); não reiniciam nada. O core testado precisa estar ligado.

## 6. Assinantes (SIMs)

| Core | Onde cadastrar |
|---|---|
| Open5GS | painel → aba **Core** → **Assinantes** (WebUI, `:30999`), ou `SUBSCRIBERS` no `config.env` + `sudo ./install.sh --deploy-only` |
| free5GC | painel → aba **Core** → **Assinantes** (WebConsole, `:31000`, usuário `admin`), ou `./free5gc/install.sh --importar-open5gs` para copiar os do Open5GS |

As chaves (K/OPc) passam direto de um banco para o outro na importação; não aparecem na tela nem vão para o git.

## 7. Mudar a configuração

- Pelo painel: aba **Configuração** (edita o `config.env`, mostra o diff e valida). Salvar **não aplica**: o
  painel mostra o comando `sudo ./install.sh …` necessário.
- Core Open5GS: `sudo ./install.sh --deploy-only`. Painel: `sudo ./install.sh --dashboard-only`.
- free5GC: editar `free5gc/free5gc.env` e rodar `./free5gc/install.sh`.
- Mudou o AMF de um core? Reinicie o gNB depois (ele não reconecta sozinho).

## 8. Documentação no painel

A aba **Documentação** mostra estes arquivos `.md` direto da pasta do projeto no torre2 (o mesmo conteúdo do
git), com a branch e o commit em uso e um link para abrir o arquivo no GitHub.

## 9. Problemas comuns

| Sintoma | O que fazer |
|---|---|
| Painel não abre | `kubectl -n open5gs get pods -l app=dashboard`; `sudo ./install.sh --dashboard-only` |
| "Iniciar tudo" para numa etapa | leia a linha de erro no topo da aba Controle e o log da função na aba Logs |
| UE registra mas não navega (Open5GS) | reinicie UPF e depois SMF (o painel faz em ordem: botão Reiniciar do UPF) |
| gNB não aparece no AMF | `.yml` do outro core, ou AMF reiniciou: reinicie o gNB |
| Celular na slice 2 recusado (free5GC) | limitação do free5GC — ver [free5gc/README.md](../free5gc/README.md) |
| Depois do boot nada responde | normal: só o painel sobe; use **▶ Iniciar tudo** |

Mais casos: [troubleshooting.md](troubleshooting.md) (core) e [ran-ocudu-liteon.md](ran-ocudu-liteon.md#7-problemas-comuns) (rádio).
