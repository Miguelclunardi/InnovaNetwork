# Tutorial 7 — Change the gNB

**Goal:** change the OCUDU configuration (`.yml`) or source code and put the change live.
**Time:** 5 min (`.yml`) · ~30 min (source). **Needs:** gNB on Kubernetes ([tutorial 3](03-ocudu-on-kubernetes.md)).

| Changed… | Rebuild? | What to do |
|---|---|---|
| a `.yml` | no | edit → restart the gNB |
| the OCUDU C++ source | yes | commit → image → `install.sh` → restart |

## A. Change a `.yml`

The pod reads `~/ocudu/configs/` **straight from the host**, with no copy.

📡 RAN machine:

```bash
cd ~/ocudu/configs
cp gnb_split_open5gs.yml gnb_test.yml         # work on a copy
nano gnb_test.yml                             # e.g. ru_ofh → cells → tx_gain / dl_arfcn
```

🖥️ Core machine (or dashboard → gNB card → file `gnb_test` → **▶ Start**):

```bash
./ran/ocudu/gnb.sh start gnb_test
./ran/ocudu/gnb.sh log -f
```

The pod is recreated with the new file (~15 s until N2). To go back: `./ran/ocudu/gnb.sh start gnb_split_open5gs`.

> Do not change `metricas.yml`: it turns on the metrics read by the dashboard.

## B. Change the OCUDU source

The image is built **from the commit**: uncommitted changes are not included.

📡 RAN machine:

```bash
cd ~/ocudu
git checkout -b my-change
# … edit the source …
git commit -am "my change"
sudo ~/innovanetwork-ran/no-ran.sh image 2>&1 | tee ~/innovanetwork-ran/build.log
```

Result: a new image `innovanetwork/ocudu-gnb:<new commit>`, imported into k3s.

🖥️ Core machine:

```bash
./ran/ocudu/install.sh            # the Deployment now uses the tag of the current commit (keeps the .yml)
./ran/ocudu/gnb.sh start          # restarts with the new image
kubectl -n ocudu get deploy ocudu-gnb -o jsonpath='{.spec.template.spec.containers[0].image}'
```

### Go back to the previous version

📡 `git -C ~/ocudu checkout <previous commit>` — its image already exists on the node (the tag is the commit), so
🖥️ `./ran/ocudu/install.sh` and `./ran/ocudu/gnb.sh start` are enough.

Old images take ~140 MB each; clean them with 📡 `sudo k3s crictl rmi <image>` and `sudo docker rmi <image>`.

## Tips

- The build uses `OCUDU_BUILD_JOBS` CPUs outside the ones reserved for the gNB, but it loads the machine: avoid it
  during experiments.
- `OCUDU_IMAGE_MARCH="native"` optimizes for the node CPU; the image does not work on a different CPU.
- To compare before/after, record an experiment with each version ([tutorial 8](08-experiments.md)).
