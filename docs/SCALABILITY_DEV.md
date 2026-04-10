# Scalability Dev Strategy

## Obiettivo

Capire in anticipo dove la piattaforma inizia a degradare quando aumentiamo il numero di utenti contemporanei.

La domanda corretta non e "3000 utenti funzionano?", ma:

- fino a quale soglia la piattaforma resta dentro tempi accettabili
- quale endpoint o dominio cede per primo
- se il collo di bottiglia e frontend proxy, backend, database o realtime

## Strumenti introdotti

- seed dedicato per workspace/progetto realistico:
  - `scripts/seed_loadtest_fixture.py`
- runner async di carico contro le route frontend vere:
  - `scripts/loadtest_frontend_api.py`
- benchmark dedicato del fanout realtime WebSocket:
  - `scripts/loadtest_realtime_ws.py`
- metriche runtime gia esposte:
  - `/api/v1/health`
  - `/api/v1/health/metrics`
  - `/api/v1/health/metrics/summary`
  - `/api/v1/health/metrics/budget`
- laboratorio superuser per check CRUD/contratti:
  - `/dashboard/admin/tests`
- report CLI dei budget runtime:
  - `scripts/report_runtime_performance.py`
- benchmark dedicato search sul percorso frontend reale:
  - `scripts/benchmark_search_global.py`
- bundle baseline catturabile e confrontabile nel tempo:
  - `scripts/capture_performance_baseline.py`
  - `scripts/compare_performance_baselines.py`
- benchmark search integrabile dentro i baseline bundle:
  - `scripts/capture_performance_baseline.py --search-benchmark-report ...`
- matrice tecnica unificata per `read-heavy`, `auth burst`, `mixed CRUD` e `realtime`:
  - `scripts/run_scalability_matrix.py`
- registro storico delle milestone prestazionali:
  - `scripts/record_performance_history.py`
  - `docs/PERFORMANCE_HISTORY.md`
  - `docs/performance-history/index.json`
- checkpoint unico per milestone locali:
  - `scripts/run_performance_checkpoint.py`

## Cosa misura il runner HTTP

Il runner colpisce le route frontend reali:

- `/api/auth/login`
- `/api/auth/session`
- `/api/projects`
- `/api/feed`
- `/api/notifications`
- `/api/search/global`
- `/api/projects/{id}/overview`
- `/api/projects/{id}/tasks`
- `/api/projects/{id}/documents`
- `/api/projects/{id}/gantt`
- `/api/projects/{id}/assistant`

Quindi misura la catena completa:

- consumer -> Next route -> backend v3 -> DB/Redis -> risposta

## Modalita del runner HTTP

### `steady-state`

Serve a capire come si comporta la piattaforma quando gli utenti sono gia dentro e lavorano insieme.

- il login/bootstrap avviene prima della finestra di misura
- il budget di latenza/fail viene applicato solo alle route applicative
- e la modalita giusta per rispondere alla domanda "3000 utenti contemporanei reggono?"

### `fresh-login`

Serve a misurare il burst di accesso/autenticazione.

- il login rientra direttamente nel budget
- e utile per capire se il problema e l'accesso iniziale, non l'uso ordinario

I due profili vanno tenuti separati: 3000 utenti attivi contemporaneamente non significa 3000 login nello stesso secondo.

## Strategia consigliata

### Fase 1 - Read-heavy

Serve a capire se dashboard e dettaglio progetto reggono il traffico base.

Stage consigliati:

- `25`
- `100`
- `250`
- `500`
- `1000`
- `2000`
- `3000`

Soglie iniziali consigliate:

- fail ratio globale `<= 1%`
- p95 globale `<= 800 ms`
- p99 globale `<= 1500 ms`
- bootstrap/login failure `= 0`

### Fase 2 - Mixed CRUD

Da fare subito dopo il read-heavy:

- post/comment create/delete a bassa frequenza
- document upload leggere
- patch task/activity

### Fase 3 - Realtime/WebSocket

Da trattare separatamente:

- molte sessioni aperte contemporaneamente
- fanout eventi progetto/notifiche
- misura del lag sugli aggiornamenti live

Soglie iniziali consigliate:

- delivery ratio `>= 99%`
- p95 lag realtime `<= 1200 ms`
- connect failure `= 0`

### Fase 4 - AI separata

Assistant e drafting vanno misurati in una matrice dedicata, non dentro il benchmark base:

- costo per request diverso
- colli di bottiglia diversi
- soglie UX diverse

## Comandi

### 1. Seed fixture

```powershell
cd "c:\Users\acoti\Desktop\EDILCLOUD\EDILCLOUD 3.0\edilcloud-back-dn"
docker compose exec -T web python /app/scripts/seed_loadtest_fixture.py --users 3000
```

### 2. Smoke rapido read-heavy steady-state

```powershell
cd "c:\Users\acoti\Desktop\EDILCLOUD\EDILCLOUD 3.0\edilcloud-back-dn"
docker compose exec -T web python /app/scripts/loadtest_frontend_api.py `
  --session-mode steady-state `
  --stages 5,10 `
  --duration-seconds 10 `
  --spawn-rate 5 `
  --base-url http://host.docker.internal:3000 `
  --stop-on-fail
```

### 3. Burst auth separato

```powershell
cd "c:\Users\acoti\Desktop\EDILCLOUD\EDILCLOUD 3.0\edilcloud-back-dn"
docker compose exec -T web python /app/scripts/loadtest_frontend_api.py `
  --session-mode fresh-login `
  --profile read-heavy `
  --stages 25,100,250 `
  --duration-seconds 15 `
  --spawn-rate 50 `
  --base-url http://host.docker.internal:3000 `
  --stop-on-fail
```

### 4. Matrice progressiva seria read-heavy

```powershell
cd "c:\Users\acoti\Desktop\EDILCLOUD\EDILCLOUD 3.0\edilcloud-back-dn"
docker compose exec -T web python /app/scripts/loadtest_frontend_api.py `
  --session-mode steady-state `
  --profile read-heavy `
  --stages 25,100,250,500,1000,2000,3000 `
  --duration-seconds 60 `
  --spawn-rate 50 `
  --max-failure-ratio 0.01 `
  --max-p95-ms 800 `
  --base-url http://host.docker.internal:3000 `
  --stop-on-fail `
  --output /tmp/loadtest-read-heavy.json
```

### 5. Mixed CRUD

```powershell
cd "c:\Users\acoti\Desktop\EDILCLOUD\EDILCLOUD 3.0\edilcloud-back-dn"
docker compose exec -T web python /app/scripts/loadtest_frontend_api.py `
  --session-mode steady-state `
  --profile mixed-crud `
  --stages 10,25,50 `
  --duration-seconds 30 `
  --spawn-rate 15 `
  --max-failure-ratio 0.02 `
  --max-p95-ms 2500 `
  --base-url http://host.docker.internal:3000 `
  --stop-on-fail `
  --output /tmp/loadtest-mixed-crud.json
```

### 6. Realtime WebSocket

```powershell
cd "c:\Users\acoti\Desktop\EDILCLOUD\EDILCLOUD 3.0\edilcloud-back-dn"
docker compose exec -T web python /app/scripts/loadtest_realtime_ws.py `
  --stages 25,100,250,500 `
  --rounds 3 `
  --event-timeout 10 `
  --max-delivery-loss 0.01 `
  --max-p95-lag-ms 1200 `
  --base-url http://host.docker.internal:3000 `
  --stop-on-fail `
  --output /tmp/loadtest-realtime.json
```

### 7. Report budget runtime

```powershell
cd "c:\Users\acoti\Desktop\EDILCLOUD\EDILCLOUD 3.0\edilcloud-back-dn"
..\venv\Scripts\python.exe scripts\report_runtime_performance.py `
  --base-url http://localhost:8001 `
  --format markdown
```

### 8. Benchmark search dedicato

```powershell
cd "c:\Users\acoti\Desktop\EDILCLOUD\EDILCLOUD 3.0\edilcloud-back-dn"
..\venv\Scripts\python.exe scripts\benchmark_search_global.py `
  --base-url http://localhost:3000 `
  --format markdown
```

### 9. Cattura baseline bundle

```powershell
cd "c:\Users\acoti\Desktop\EDILCLOUD\EDILCLOUD 3.0\edilcloud-back-dn"
..\venv\Scripts\python.exe scripts\capture_performance_baseline.py `
  --base-url http://localhost:8001 `
  --label local-dev `
  --output .tmp\baseline-local-dev.json
```

### 10. Cattura baseline bundle con benchmark search reale

```powershell
cd "c:\Users\acoti\Desktop\EDILCLOUD\EDILCLOUD 3.0\edilcloud-back-dn"
..\venv\Scripts\python.exe scripts\benchmark_search_global.py `
  --base-url http://localhost:3000 `
  --format json `
  --output .tmp\search-benchmark.json

..\venv\Scripts\python.exe scripts\capture_performance_baseline.py `
  --base-url http://localhost:8001 `
  --label local-dev-search `
  --search-benchmark-report .tmp\search-benchmark.json `
  --output .tmp\baseline-local-dev-search.json
```

### 11. Confronto baseline bundle

```powershell
cd "c:\Users\acoti\Desktop\EDILCLOUD\EDILCLOUD 3.0\edilcloud-back-dn"
..\venv\Scripts\python.exe scripts\compare_performance_baselines.py `
  --baseline ".tmp\baseline-local-dev.json" `
  --current ".tmp\baseline-local-dev.json" `
  --format markdown
```

Il confronto considera anche la sezione `search_benchmark` quando presente, con guardrail su `p95`, `failure ratio`, `empty ratio` e downgrade `pass -> fail`.

### 12. Registrazione nello storico repo

```powershell
cd "c:\Users\acoti\Desktop\EDILCLOUD\EDILCLOUD 3.0\edilcloud-back-dn"
..\venv\Scripts\python.exe scripts\record_performance_history.py `
  --bundle ".tmp\baseline-local-dev.json" `
  --compare-to-latest
```

### 13. Checkpoint tecnico unico

Questo comando orchestra in un solo giro:

- route exercise dei path core (`auth.session`, `projects.list`, `overview`, `tasks`, `gantt`, `health`)
- runtime budget
- runtime summary con hot paths
- benchmark search reale
- capture baseline bundle
- registrazione nello storico repo
- report finale con focus tecnici

```powershell
cd "c:\Users\acoti\Desktop\EDILCLOUD\EDILCLOUD 3.0\edilcloud-back-dn"
..\venv\Scripts\python.exe scripts\run_performance_checkpoint.py `
  --label milestone-local `
  --compare-to-latest `
  --format markdown
```

Nel checkpoint il budget runtime viene valutato sulla stessa snapshot di `runtime summary`, cosi evitiamo discrepanze temporali tra due fetch separate.

### 14. Matrice tecnica completa con baseline e history

```powershell
cd "c:\Users\acoti\Desktop\EDILCLOUD\EDILCLOUD 3.0\edilcloud-back-dn"
..\venv\Scripts\python.exe scripts\run_scalability_matrix.py `
  --label local-dev-matrix `
  --compare-to-latest `
  --format markdown
```

La matrice esegue in sequenza:

- `read-heavy / steady-state`
- `auth burst / fresh-login`
- `mixed CRUD / steady-state`
- `realtime`
- benchmark `search`
- capture baseline bundle
- registrazione nello storico del repo

Lo storico risultante distingue anche il tipo di run:

- `checkpoint`
- `scalability-matrix`

Se vuoi usarlo come guardrail operativo locale:

```powershell
cd "c:\Users\acoti\Desktop\EDILCLOUD\EDILCLOUD 3.0\edilcloud-back-dn"
..\venv\Scripts\python.exe scripts\run_performance_checkpoint.py `
  --label milestone-local `
  --compare-to-latest `
  --fail-on-attention
```

## Come leggere il risultato

Il runner restituisce:

- richieste totali
- fail ratio
- p50, p95, p99, max
- breakdown per endpoint
- `breaking_stage`

Il summary runtime espone inoltre:

- `totals`
- `endpoints`
- `top_slowest`
- `top_errors`
- `hot_paths`

Il budget runtime espone inoltre:

- `score_percent`
- `passing_rules`
- `failing_rules`
- `no_data_rules`
- `rules`

`breaking_stage` e il primo livello di concorrenza che non rispetta le soglie.

Per il realtime hai in piu:

- `delivery_ratio`
- `delivery_loss_ratio`
- `lag_p50/p95/p99`
- `connect_failures`

Per il budget runtime hai in piu:

- regole `pass/fail/no_data`
- score sintetico del perimetro osservato
- elenco dei path core ancora non misurati

Per il benchmark search hai in piu:

- p95 dedicato sul percorso reale `frontend -> Next route -> backend v3`
- empty ratio per query/categoria
- visibilita sulle sezioni realmente colpite dalla query

Per il baseline bundle hai in piu:

- uno snapshot riusabile di `runtime_budget`, `runtime_summary` e report di carico
- un confronto automatico tra baseline e run successiva
- un primo meccanismo per capire se stiamo migliorando o regredendo nel tempo

Per lo storico repo hai in piu:

- un registro versionato delle milestone tecniche
- una dashboard markdown leggibile senza aprire i JSON raw
- un punto unico per vedere score runtime e best stage disponibili nel tempo

## Snapshot Dev del 2026-04-05

Primi numeri gia verificati sullo stack locale attuale:

- `read-heavy / steady-state / 10 utenti`: fail ratio `0`, ma `p95 ~ 3.2s`
- `read-heavy / fresh-login / 10 utenti`: login ok, ma `p95 ~ 4.3s`
- `realtime ws / 10 listener / 2 round`: delivery ratio `1.0`, `lag p95 ~ 776 ms`

Traduzione pratica:

- il realtime locale, oggi, e gia piu sano del percorso HTTP read-heavy
- il collo di bottiglia principale attuale e il profilo applicativo `overview/tasks/search/gantt`, non il socket
- dire oggi "3000 utenti contemporanei reggono" sarebbe infondato: sul dev stack siamo gia oltre soglia a carichi molto piu bassi

## Nota importante

Un laptop locale puo validare il trend e far emergere i colli di bottiglia, ma non equivale a dire "3000 utenti in produzione sono garantiti".

Per dire davvero "3000 utenti contemporanei reggono" bisogna eseguire la stessa matrice:

- su hardware coerente con il target
- con DB/Redis coerenti
- con configurazione Gunicorn/Uvicorn coerente
- con realtime misurato in un benchmark dedicato

## Prossimi passi naturali

- estendere il mixed CRUD con upload documento leggero e patch task/activity
- aggiungere benchmark notifiche realtime separato dal solo canale progetto
- collegare il report budget a un cruscotto dedicato
- collegare anche il benchmark search al ciclo di baseline storiche
- isolare benchmark AI con soglie proprie
- eseguire la matrice completa su hardware target-like per trasformare questi smoke in capacity planning credibile
- salvare baseline bundle ad ogni milestone tecnica importante invece di lasciare solo output temporanei
- automatizzare la registrazione dello storico invece di farla solo manualmente
