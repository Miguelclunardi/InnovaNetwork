# Tutorial 8 — Record and compare experiments

**Goal:** measure two setups (e.g. two gNB `.yml` files) and compare them side by side in the dashboard.
**Time:** ~20 min. **Needs:** persistent history on (`DASHBOARD_PERSIST=true`, the default) and a UE with
traffic.

## 1. What is recorded

With the history on, the dashboard **always** records: radio metrics per UE and of the cell (1 s), core, machines,
O-RU and events. An **experiment** is just a period marker with a name, notes and a snapshot of the setup (UEs,
version, gNB, O-RU configuration and `config.env`, with masked keys).

## 2. Experiment A

1. Put setup A live (e.g. gNB with `gnb_split_open5gs`).
2. At the top of the dashboard: **● Record experiment** → name `A — default 100 MHz`, notes (phone position, what
   changed).
3. Generate traffic for a fixed time, always the same in both experiments. Examples:
   - phone: a speed test or a large download;
   - simulated UE: `kubectl -n open5gs exec deploy/ueransim-ues -- iperf3 -c <server> -B <uesimtun0 IP> -t 120`.
4. Click the button again (red, with a timer) to **stop**.

## 3. Experiment B

Change **one thing only** (e.g. the `.yml` — [tutorial 7](07-change-the-gnb.md)), repeat the same traffic and
record it as `B — …`.

## 4. Compare

**History** tab → tick A and B → **Compare**:

- table with the mean, p95 and peak of cell DL/UL, BLER, MCS, CQI, RI, SNR, scheduler latency, CPU and
  temperature of each machine, O-RU packets outside the window — the best of each row in green;
- overlaid charts with a "time since start" axis.

## 5. Export

- **History** → period or experiment → **CSV** (`timestamp, series, IMSI, field, value`);
- API: `curl -s "http://<core machine>:30998/api/history/csv?from=<epoch>&to=<epoch>" -o data.csv`.

## Good practice

- same phone, same position, same traffic, same duration;
- one variable at a time;
- complete notes: the setup snapshot helps, but it does not replace knowing *why* the experiment was done.

Storage details (format, retention, size): [components/dashboard.md](../components/dashboard.md#persistent-history-and-experiments-history-tab).
