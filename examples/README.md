# Examples

Every example is **deterministic and offline**: it uses the built-in `echo`
provider, needs no API key and no network, and produces identical artifacts on
every run. That is deliberate — you should be able to verify AstraForge's claims
before trusting it with a real model.

| Example | Demonstrates | Plan |
| --- | --- | --- |
| [`hello_world`](hello_world/) | The smallest complete goal → artifact → report loop | default planner |
| [`software_engineering`](software_engineering/) | Reproduce a real test failure, fix it, prove the fix | [`plan.yaml`](software_engineering/plan.yaml) |
| [`data_analysis`](data_analysis/) | CSV → anomaly detection → chart → report | [`plan.yaml`](data_analysis/plan.yaml) |
| [`research`](research/) | Sources → synthesis → automated citation checking | [`plan.yaml`](research/plan.yaml) |

Run any of them from the repository root:

```bash
astraforge run "<any goal text>" --plan examples/<name>/plan.yaml -y
```

Then inspect what actually happened:

```bash
astraforge inspect latest     # the full proof-of-work report
astraforge logs latest        # every structured event
astraforge artifacts latest   # outputs with SHA-256 hashes
astraforge verify latest      # re-check the hashes
```

All four examples are executed by the test suite
(`tests/end_to_end/test_examples.py`), so a broken example fails the build.
