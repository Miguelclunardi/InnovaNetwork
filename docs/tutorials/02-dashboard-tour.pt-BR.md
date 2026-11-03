# Tutorial 2 — Conhecer o painel

**Objetivo:** entrar como administrador e saber o que cada aba do *Innova Center Dashboard* mostra e faz.
**Tempo:** ~15 min. **Precisa de:** o core instalado ([tutorial 1](01-primeiro-teste-ueransim.md) ou a [instalação](../instalacao.md)).

## 1. Abrir e entrar

1. Abra `http://<IP da máquina do core>:30998`.
2. Pegue a senha de administrador na máquina do core:
   ```bash
   sudo cat /opt/open5gs-k3s/state/dashboard-admin-password
   ```
3. Clique em **🔒 Admin** (topo) e entre. O login vale para todas as abas por 8 h.

Sem login dá para ver tudo; ações (iniciar, parar, editar) pedem o login.

## 2. As abas

| Aba | Para que serve | Experimente |
|---|---|---|
| **Visão geral** | resumo: UEs no rádio, assinantes registrados, sessões, pods, eventos | veja o seu UE com IMSI, DNN e IP |
| **Rádio** | métricas do gNB real por UE: vazão, MCS, CQI, BLER, SNR, PRBs | com um celular conectado, abra um vídeo e veja a vazão DL subir |
| **Core** | gNBs no AMF, UEs, sessões, tráfego do UPF por DNN, CPU de cada função; **Assinantes** (WebUI) | cadastre um assinante pela WebUI embutida |
| **Logs** | log de qualquer pod e do gNB real, ao vivo, com filtro | filtre o AMF por `Registration` |
| **RU** | O-RU: sincronismo PTP, potência, temperatura, pacotes do fronthaul no tempo | confira `SYNCHRONIZED` e ~90 % no tempo |
| **Controle** | iniciar/parar/reiniciar o core, o UERANSIM e o gNB; trocar de core | reinicie o UERANSIM e acompanhe as etapas |
| **Máquinas** | CPU por núcleo, memória, temperatura, rede das máquinas | veja os núcleos isolados do gNB em azul |
| **Histórico** | métricas gravadas de qualquer período; experimentos e comparação | abra as últimas 24 h |
| **Configuração** | editar o `config.env` com diff e validação | abra uma seção e leia as explicações |
| **Documentação** | estes documentos, dentro do painel | — |

## 3. Uma ação completa

1. Aba **Controle** → linha do **UERANSIM** → **↻ Reiniciar**.
2. Acompanhe no topo da aba: cada etapa aparece com hora e resultado.
3. Na **Visão geral**, o UE some e volta registrado em segundos.

## 4. O topo da página

- **pílula do core ativo** (Open5GS ou free5GC): todas as abas seguem esse core;
- **● Gravar experimento**: marca um período para comparar depois ([tutorial 8](08-experimentos.md));
- tema claro/escuro.

## Próximo

Com rádio: [OCUDU em Kubernetes](03-ocudu-em-kubernetes.md). Referência completa: [componentes/painel.md](../componentes/painel.md).
