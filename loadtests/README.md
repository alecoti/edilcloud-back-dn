# EdilCloud Test Center load tests

Questa cartella contiene le suite Locust usate dal Test Center per generare
artefatti normalizzati leggibili dalla dashboard admin.

## Profili disponibili

- `read-heavy`: sessione utente con login, elenco progetti, feed, notifiche,
  ricerca globale, overview progetto, task, documenti, gantt e stato assistant.
- `mixed-crud`: include il profilo read-heavy e aggiunge creazione/rimozione
  controllata di post e commenti su task.
- `auth-burst`: raffica di login per misurare il comportamento dello strato auth.

## Shape disponibili

- `step`: crescita progressiva fino al carico massimo e breve hold finale.
- `spike`: warmup, picco aggressivo e cooldown.
- `soak`: carico stabile prolungato.

## Esecuzione locale

```powershell
..\venv\Scripts\python.exe scripts\run_locust_suite.py `
  --host http://localhost:3000 `
  --profile read-heavy `
  --users 10 `
  --spawn-rate 5 `
  --run-time 2m
```

## Esecuzione staging o produzione controllata

Usare sempre utenti e dati dedicati ai load test. La password passa tramite
variabile ambiente o argomento locale, ma non viene salvata nel report.

```powershell
$env:EDILCLOUD_LOADTEST_PASSWORD="***"
..\venv\Scripts\python.exe scripts\run_locust_suite.py `
  --host https://test.edilcloud.eu `
  --profile mixed-crud `
  --shape spike `
  --users 20 `
  --spawn-rate 10 `
  --run-time 5m `
  --project-id 42 `
  --fail-on-threshold
```

## Artefatti prodotti

Il runner scrive una directory sotto `.tmp/test-center/loadtests/` con:

- `locust-report.json`: report normalizzato letto dal Test Center.
- `locust-report.html`: report HTML generato da Locust.
- `locust_stats.csv`, `locust_failures.csv`, `locust_exceptions.csv`: dati grezzi.

La dashboard admin legge automaticamente gli artefatti dalle directory:

- `.tmp/test-center/loadtests/**/*.json`
- `docs/performance-history/loadtests/**/*.json`

Per conservare uno storico versionabile, promuovere il JSON normalizzato dentro
`docs/performance-history/loadtests/<yyyy-mm-dd>/<run-id>/locust-report.json`.

## Soglie

Le soglie principali del wrapper sono:

- `--max-failure-ratio`, default `0.01`
- `--max-p95-ms`, default `1200`

Con `--fail-on-threshold`, il processo torna con exit code `1` quando il report
non passa le soglie. Questo lo rende adatto a job schedulati e pipeline CI.
