# Performance History

Registro delle baseline tecniche catturate nel tempo per misurare regressioni o miglioramenti del core dev.

| Kind | Label | Generated | Runtime budget | Search p95 | Read-heavy best stage | Auth burst best stage | Mixed CRUD best stage | Realtime best stage | Compare |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| checkpoint | milestone-local-core6 | 2026-04-05T12:57:59Z | pass (100%) | pass / 187.38 ms | - | - | - | - | pass / 0 regressions |
| scalability-matrix | smoke-local-matrix-budget | 2026-04-05T12:53:51Z | fail (87%) | pass / 356.57 ms | - | - | 1 | - | fail / 11 regressions |
| scalability-matrix | smoke-local-matrix-kind | 2026-04-05T12:52:10Z | fail (87%) | pass / 179.83 ms | 1 | 1 | 1 | 1 | pass / 0 regressions |
| - | smoke-local-matrix-2 | 2026-04-05T12:48:47Z | fail (87%) | pass / 263.5 ms | - | - | - | - | fail / 5 regressions |
| - | smoke-local-matrix | 2026-04-05T12:47:47Z | pass (100%) | pass / 111.47 ms | - | - | - | 5 | pass / 0 regressions |
| - | milestone-local-core4 | 2026-04-05T12:34:59Z | partial (12%) | pass / 132.2 ms | - | - | - | - | fail / 2 regressions |
| - | milestone-local-core3 | 2026-04-05T12:32:11Z | partial (40%) | pass / 105.71 ms | - | - | - | - | fail / 1 regressions |
| - | milestone-local-core2 | 2026-04-05T12:28:13Z | pass (100%) | pass / 119.24 ms | - | - | - | - | pass / 0 regressions |
| - | milestone-local-core | 2026-04-05T12:27:07Z | pass (100%) | pass / 113.9 ms | - | - | - | - | pass / 0 regressions |
| - | milestone-local | 2026-04-05T12:22:20Z | partial (40%) | pass / 122.63 ms | - | - | - | - | pass / 0 regressions |
| - | local-dev-search-runtime | 2026-04-05T12:15:55Z | partial (40%) | pass / 115.28 ms | - | - | - | - | pass / 0 regressions |
| - | runtime-smoke-a | 2026-04-05T12:02:57Z | partial (20%) | - | - | - | - | - | - |
| - | runtime-smoke-b | 2026-04-05T12:02:57Z | partial (20%) | - | - | - | - | - | pass / 0 regressions |

## Usage

1. Cattura un baseline bundle con `scripts/capture_performance_baseline.py`.
2. Registralo nello storico con `scripts/record_performance_history.py`.
3. Confronta milestone importanti con `scripts/compare_performance_baselines.py`.
