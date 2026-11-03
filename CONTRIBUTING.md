# Contributing

Thank you for your interest! InnovaNetwork aims to be a replicable base for lab 5G networks on Kubernetes.
Contributions are welcome:

- **hardware profiles** (other NICs, O-RUs, SDRs) in `docs/hardware/`;
- fixes and improvements to the installers, the dashboard and the configuration generators;
- documentation and tutorials;
- bug reports with steps to reproduce.

## Before you start

- Read the [architecture](docs/architecture.md) and the [development guide](docs/development.md).
- For large changes, open an *issue* describing the idea before writing code.

## Project rules

| Rule | Why |
|---|---|
| **Nothing hard-coded:** every parameter comes from `config.env`, `free5gc/free5gc.env` or `ran/ocudu/ocudu.env`, with a default and validation | the same code serves different setups |
| **Idempotency:** running an installer again only applies what changed | installing and updating are the same operation |
| **What depends on the hardware stays isolated** (`ran/`, `docs/hardware/`) and is stated explicitly | whoever replicates it knows what to adapt |
| **Secrets never go into git:** SIM keys, passwords, tokens | the repository is public |
| **English** for documentation, code, comments, commands and output; every document keeps a Portuguese translation (`*.pt-BR.md`) updated in the same commit | the dashboard shows the docs of the version in use, in both languages |
| **Dashboard texts** are written in English; add the Portuguese to `dashboard/i18n/pt.json` and run `dashboard/i18n/build.py` | the PT mode translates on the page |
| **No new dependencies** in the dashboard (Python standard library only) | simple, offline installation |

## Workflow

1. *Fork* and create a branch from `main`.
2. Make the change and run the checks:
   ```bash
   bash -n install.sh uninstall.sh test.sh scripts/*.sh scripts/lib/*.sh free5gc/*.sh ran/ocudu/*.sh
   python3 -m py_compile dashboard/app/*.py dashboard/agent/*.py free5gc/lib/*.py ran/ocudu/lib/*.py
   ./free5gc/install.sh --dry-run && ./ran/ocudu/install.sh --dry-run
   ./test.sh
   ```
3. Describe in the *pull request*: what changes, why, and how you tested it (setup and result).

## Hardware profile

Copy `docs/hardware/e810-liteon.md` and describe: parts, cell, host preparation (services, DPDK, PTP), the
`ocudu.env` values and the expected health indicators.

## License

By contributing, you agree that your contribution is licensed under the [Apache License 2.0](LICENSE).
