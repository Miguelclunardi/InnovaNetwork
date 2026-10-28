# Como contribuir

Obrigado pelo interesse! O InnovaNetwork quer ser uma base replicável para redes 5G de laboratório em Kubernetes.
Contribuições bem-vindas:

- **perfis de hardware** (outras NICs, O-RUs, SDRs) em `docs/hardware/`;
- correções e melhorias nos instaladores, no painel e nos geradores de configuração;
- documentação e tutoriais;
- relatos de problemas com passos para reproduzir.

## Antes de começar

- Leia a [arquitetura](docs/arquitetura.md) e o [guia de desenvolvimento](docs/desenvolvimento.md).
- Para mudanças grandes, abra uma *issue* descrevendo a ideia antes do código.

## Regras do projeto

| Regra | Por quê |
|---|---|
| **Nada fixo no código:** todo parâmetro vem de `config.env`, `free5gc/free5gc.env` ou `ran/ocudu/ocudu.env`, com padrão e validação | o mesmo código serve a setups diferentes |
| **Idempotência:** rodar um instalador de novo só aplica o que mudou | instalar e atualizar são a mesma operação |
| **O que depende do hardware fica isolado** (`ran/`, `docs/hardware/`) e é dito explicitamente | quem replica sabe o que adaptar |
| **Segredos nunca no git:** chaves de SIM, senhas, tokens | o repositório é público |
| **Documentação em português**, atualizada no mesmo commit da mudança | o painel mostra os docs da versão em uso |
| **Sem dependências novas** no painel (só biblioteca padrão do Python) | instalação offline e simples |

## Fluxo

1. *Fork* e uma branch a partir de `main`.
2. Faça a mudança e rode as verificações:
   ```bash
   bash -n install.sh uninstall.sh test.sh scripts/*.sh scripts/lib/*.sh free5gc/*.sh ran/ocudu/*.sh
   python3 -m py_compile dashboard/app/*.py dashboard/agent/*.py free5gc/lib/*.py ran/ocudu/lib/*.py
   ./free5gc/install.sh --dry-run && ./ran/ocudu/install.sh --dry-run
   ./test.sh
   ```
3. Descreva no *pull request*: o que muda, por quê, como testou (setup e resultado).

## Perfil de hardware

Copie `docs/hardware/e810-liteon.md` e descreva: peças, célula, preparação do host (serviços, DPDK, PTP), os valores
de `ocudu.env` e os indicadores de saúde esperados.

## Licença

Ao contribuir, você concorda que a sua contribuição seja licenciada sob a [Apache License 2.0](LICENSE).
