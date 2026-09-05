# Data analysis — CSV to anomaly report

```bash
astraforge run "Analyse sensor readings and report anomalies" \
  --plan examples/data_analysis/plan.yaml -y
```

## The task graph

| Task | Tool | What proves it worked |
| --- | --- | --- |
| `task_dataset` | `fs.write` | `readings.csv` exists with the expected header |
| `task_analysis_script` | `fs.write` | `analyse.py` exists |
| `task_run_analysis` | `shell.run` | stdout says `found 2 anomalies`, with no traceback |
| `task_verify_findings` | `fs.read` | `findings.json` parses, **and contains both planted outliers** |

## Why the verification is not a rubber stamp

The dataset contains two deliberate outliers: `91.7` and `-40.5`. The final
task does not merely check that "some analysis ran" — it asserts that
`findings.json` contains *those specific values*. An analysis that silently
found nothing, or found the wrong rows, fails the run.

The script uses a **median absolute deviation** score rather than a
mean/standard-deviation z-score, because outliers of this magnitude inflate the
standard deviation enough to hide themselves.

## Outputs

`findings.json`, `report.md` and `chart.txt` are written by the analysis
subprocess, not directly by an AstraForge tool. They still appear in
`astraforge artifacts latest` with hashes, because the engine snapshots the
workspace around every tool call and captures files the tool did not declare.

The chart is plain ASCII, so the example needs no plotting dependency:

```
2026-01-01T03:00   ##################                          20.2
2026-01-01T04:00 | ########################################    91.7
2026-01-01T05:00   ##################                          20.0
```
