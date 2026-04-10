# Roadmap V3

## North Star

Costruire `edilcloud-back-dn` come backend v3 ufficiale di EdilCloud, con un percorso che porti a:

- un backend locale avviabile con Docker in un solo comando
- un frontend locale che punti solo alla v3 su `http://localhost:8001`
- feature core migrate dal sistema attuale senza dipendenze runtime residue dal backend legacy
- una piattaforma professionale, misurabile, testata e pronta a evolvere verso produzione

## Regola di Chiusura di un Dominio

Un bounded context si considera davvero chiuso lato dev quando:

- esistono endpoint v3 stabili e documentati
- esistono test backend per happy path, error path e permessi principali
- il frontend `edilcloud-next` usa la v3 senza fallback necessario al legacy
- il flusso critico funziona in locale con `docker compose up -d`
- esistono smoke test o verifiche ripetibili sul flusso principale
- non ci sono riferimenti runtime a `localhost:8000` per quel dominio

## Come Leggere Questa Roadmap

- `Progresso dev` e una percentuale di maturita del dominio nel perimetro locale/dev, non una misura di produzione
- `[x]` significa chiuso o verificato nel perimetro dev attuale
- `[ ]` significa aperto o ancora da consolidare lato dev
- le voci `Prod fuori scope adesso` non entrano nella percentuale dev: restano separate per non mescolare hardening/prod con lavoro core
- una percentuale puo restare sotto `100%` anche se il dominio e gia usabile, perche la roadmap deve continuare a guidare miglioramenti tecnici, osservabilita e performance

## Baseline Reale al 2026-04-05

### Piattaforma gia consolidata in dev

- [x] Stack Docker-first funzionante con `db`, `redis` e `web`
- [x] Backend pubblico allineato a `http://localhost:8001`
- [x] Frontend locale puntato alla v3 su `localhost:8001`
- [x] Supporto ASGI/WebSocket attivo nel backend v3
- [x] Zero riferimenti runtime residui a `/api/frontend/...` dentro `edilcloud-next/src`
- [x] [FRONTEND_COMPATIBILITY_MATRIX.md](c:/Users/acoti/Desktop/EDILCLOUD/EDILCLOUD%203.0/edilcloud-back-dn/docs/FRONTEND_COMPATIBILITY_MATRIX.md) rigenerata e coerente con il codice reale
- [x] Laboratorio superuser `/dashboard/admin/tests` attivo per verifiche CRUD e contratti frontend/API

### Resa tecnica e professionale gia introdotta

- [x] `X-Request-ID` e request lifecycle logging
- [x] logging strutturato `console/json`
- [x] healthcheck runtime su `/api/v1/health`
- [x] metriche base su `/api/v1/health/metrics`
- [x] summary operativo endpoint-level su `/api/v1/health/metrics/summary`
- [x] valutazione automatica dei budget runtime su `/api/v1/health/metrics/budget`
- [x] CI dev backend con `makemigrations --check`, `manage.py check`, `pytest`
- [x] smoke CI delle CLI operative per load test/realtime
- [x] report CLI dei budget runtime per rendere leggibile lo stato prestazionale del core
- [x] baseline bundle catturabile e confrontabile nel tempo per `runtime budget + runtime summary + loadtest`
- [x] registro storico baseline in `docs/performance-history` e dashboard leggibile in `docs/PERFORMANCE_HISTORY.md`
- [x] benchmark search collegato ai baseline bundle e visibile nello storico prestazionale del repo
- [x] checkpoint tecnico unico che orchestra budget runtime, summary, benchmark search, baseline bundle e history
- [x] checkpoint tecnico che esercita i path core prima dei guardrail, evitando `no_data` sui percorsi principali
- [x] matrice tecnica unica `read-heavy + auth burst + mixed CRUD + realtime` con report, baseline bundle e history
- [x] storico baseline che distingue chiaramente `checkpoint` e `scalability-matrix`
- [x] guardrail runtime estesi anche a `feed`, `documents` e `assistant state`
- [x] seed load-test dedicato e runner staged per HTTP e realtime

### Misure reali gia raccolte

- [x] `read-heavy / steady-state / 10 utenti` verificato: `fail ratio 0`, ma `p95 ~ 3.2s`
- [x] `read-heavy / fresh-login / 10 utenti` verificato: login ok, ma `p95 ~ 4.3s`
- [x] `realtime ws / 10 listener / 2 round` verificato: `delivery ratio 1.0`, `lag p95 ~ 776 ms`
- [x] Primo verdetto tecnico: oggi il collo di bottiglia e il percorso HTTP `overview/tasks/gantt/search`, non il websocket
- [x] checkpoint `milestone-local-core2` verificato: budget runtime `100%` su `health/overview/tasks/gantt/search`
- [x] checkpoint `milestone-local-core6` verificato: budget runtime `100%` anche su `auth.login`, `projects.list`, `feed`, `documents`, `notifications` e `assistant state`
- [x] smoke matrice `smoke-local-matrix-2` verificato end-to-end: search passa, realtime regge `5` listener, ma `read-heavy/auth burst/mixed CRUD` rompono ancora presto e confermano che serve tuning prima della scala reale
- [ ] Baseline seria `25 -> 3000` ancora da eseguire su hardware coerente con il target

### Verifiche gia presenti nel repo

- [x] `test_health.py`
- [x] `test_identity_api.py`
- [x] `test_workspaces_api.py`
- [x] `test_projects_api.py`
- [x] `test_projects_demo_seed.py`
- [x] `test_notifications_api.py`
- [x] `test_realtime_api.py`
- [x] `test_search_api.py`
- [x] `test_assistant_api.py`
- [x] `test_assistant_eval.py`

## Stato Sintetico per Dominio

- `Platform e Runtime`: `99%`
- `Identity`: `95%`
- `Workspaces e Profili`: `94%`
- `Projects Core`: `95%`
- `Feed, Post, Commenti e Files`: `96%`
- `Notifications e Realtime`: `94%`
- `Search`: `92%`
- `Assistant e AI Drafting`: `82%`
- `Billing`: `0%`

## Stato per Dominio

### Platform e Runtime

Progresso dev: `99%`

Completato in dev:

- [x] Docker Compose locale stabile
- [x] Postgres e Redis interni alla rete Docker
- [x] backend esposto su `8001`
- [x] env locale allineato alla v3
- [x] collectstatic, migrate e healthcheck automatici nel container
- [x] ASGI e WebSocket attivi
- [x] middleware `X-Request-ID` su tutte le response
- [x] logging dev configurabile `console/json`
- [x] request lifecycle log con `status_code`, `duration_ms`, `client_ip`, `user_agent`
- [x] metadata runtime esposti da `/api/v1/health`
- [x] metriche base su `/api/v1/health/metrics`
- [x] summary endpoint-level su `/api/v1/health/metrics/summary`
- [x] endpoint `/api/v1/health/metrics/budget` con valutazione automatica dei budget dev sui path core
- [x] budget iniziali espliciti per `health`, `auth.login`, `projects.list`, `feed`, `overview`, `tasks`, `gantt`, `documents`, `notifications`, `assistant`, `search`
- [x] report CLI `scripts/report_runtime_performance.py` in markdown/json
- [x] script `scripts/capture_performance_baseline.py` per catturare un baseline bundle riusabile
- [x] script `scripts/compare_performance_baselines.py` per confrontare baseline e run successive
- [x] script `scripts/record_performance_history.py` per registrare milestone tecniche nel repo
- [x] storico baseline persistente in `docs/performance-history`
- [x] dashboard tecnica generata in `docs/PERFORMANCE_HISTORY.md`
- [x] baseline bundle estendibile con benchmark search reale
- [x] baseline bundle estendibile anche con `auth burst`
- [x] storico baseline che mostra anche `Search p95` e stato del benchmark search
- [x] storico baseline che distingue `checkpoint` e `scalability-matrix`
- [x] script `scripts/run_performance_checkpoint.py` per eseguire un checkpoint tecnico unico di milestone
- [x] report checkpoint con focus automatici su budget breach, hot paths e regressioni baseline
- [x] checkpoint che esercita `auth.session`, `projects.list`, `feed`, `notifications`, `overview`, `tasks`, `documents`, `gantt`, `assistant` e `health` prima della valutazione budget
- [x] budget del checkpoint calcolato dalla stessa snapshot di `runtime summary`, senza race tra letture separate
- [x] script `scripts/run_scalability_matrix.py` per eseguire una matrice tecnica completa `read-heavy + auth burst + mixed CRUD + realtime`
- [x] matrice tecnica che cattura automaticamente baseline bundle e aggiorna lo storico prestazionale del repo
- [x] CI dev backend con check migrazioni, system check, `pytest` e smoke CLI operative
- [x] deriva migrazioni chiusa e verificata con `makemigrations --dry-run --check`
- [x] seed load-test dedicato
- [x] runner async staged contro le route frontend reali
- [x] modalita distinte `steady-state` e `fresh-login`
- [x] benchmark dedicato del fanout realtime WebSocket su progetto
- [x] strategia di capacity planning documentata in [SCALABILITY_DEV.md](c:/Users/acoti/Desktop/EDILCLOUD/EDILCLOUD%203.0/edilcloud-back-dn/docs/SCALABILITY_DEV.md)

Aperto in dev:

- [ ] eseguire e consolidare una baseline numerica reale `25 -> 3000`
- [ ] promuovere la matrice da smoke locale a baseline seria su hardware coerente con il target
- [ ] agganciare checkpoint e matrice a branch/milestone automatiche, non solo manualmente

Prod fuori scope adesso:

- [ ] gestione secrets e env di produzione
- [ ] immagini Docker separate dev/prod
- [ ] backup e restore strategy per Postgres/media
- [ ] tracing/export metrics esterni di livello produzione

### Identity

Progresso dev: `95%`

Completato in dev:

- [x] login email/password
- [x] register
- [x] access code request/confirm
- [x] Google auth
- [x] token verify
- [x] token refresh con profilo reale
- [x] refresh token separato con rotation
- [x] logout con revoca sessione reale
- [x] invalidazione immediata del vecchio access token dopo refresh/logout/password reset
- [x] `me`
- [x] onboarding profile
- [x] onboarding session
- [x] onboarding complete
- [x] onboarding invites e accept
- [x] password reset request/confirm con email transazionale dedicata
- [x] rate limit sugli endpoint auth sensibili
- [x] messaggi errore auth piu uniformi e meno rivelatori
- [x] bootstrap dev auth

Aperto in dev:

- [ ] schermata frontend dedicata per password reset, solo se confermata come flow utente finale

Prod fuori scope adesso:

- [ ] hardening CSP/headers e session policy specifiche di produzione

### Workspaces e Profili

Progresso dev: `94%`

Completato in dev:

- [x] lista workspace
- [x] profili attivi
- [x] profilo corrente `GET/PATCH` su `/api/v1/workspaces/current/profile`
- [x] current members
- [x] create workspace
- [x] invites create/list/accept
- [x] invites refuse
- [x] CRUD team member del frontend su `current/members`
- [x] enable/disable/resend/delete inviti dal Team panel
- [x] ricerca aziende
- [x] contatti azienda
- [x] guardrail backend sui ruoli interni tra workspace e progetto
- [x] self-healing automatico dei membership legacy disallineati
- [x] smoke browser Playwright verificato sul Team panel con ruoli `owner/delegate/manager/worker`
- [x] smoke browser Playwright verificato sui flussi `invite`, `refused -> resend`, `delete invite`, `update role`, `disable`, `enable`

Aperto in dev:

- [ ] eventuale staff summary o parity aggiuntiva solo se richiesta dal frontend reale

Prod fuori scope adesso:

- [ ] preferenze profilo avanzate e policy enterprise, solo se nasceranno come esigenza prodotto reale

### Projects Core

Progresso dev: `95%`

Completato in dev:

- [x] lista progetti
- [x] create progetto
- [x] detail progetto
- [x] overview aggregata
- [x] task list
- [x] create task
- [x] patch task
- [x] team list
- [x] add team member
- [x] invite code
- [x] ruolo iniziale progetto coerente con il ruolo workspace del creatore
- [x] role floor automatico per membership progetto interni
- [x] create progetto con geocoding automatico da indirizzo quando mancano latitudine/longitudine
- [x] metadata location progetto `has_coordinates`, `location_source`, `map_url`
- [x] documents list/upload
- [x] photos list
- [x] folders list/create
- [x] alerts list
- [x] gantt read model
- [x] project realtime session
- [x] eventi realtime `task.created/updated` e `activity.created/updated`
- [x] smoke browser Playwright verificato per `create progetto` da wizard UI con indirizzo libero, geocoding automatico backend, overview, mappa e meteo live
- [x] audit route frontend progetto chiuso con `0` dipendenze runtime legacy residue nel perimetro `cantieri/overview/gantt/team`
- [x] audit mutate frontend reale chiuso per il perimetro attuale del dettaglio progetto
- [x] permission audit backend chiuso su progetto/task/membership con regressione dedicata
- [x] smoke browser Playwright verificato sul flow `cantieri -> detail -> overview -> gantt -> team`
- [x] smoke browser Playwright verificato su owner e worker, con gating corretto della CTA invito nel tab team

Aperto in dev:

- [ ] eventuali mutate future del gantt o del dettaglio progetto solo se nasceranno nuove UX oltre il perimetro attuale

Prod fuori scope adesso:

- [ ] nulla di bloccante per il perimetro attuale

### Feed, Post, Commenti e Files

Progresso dev: `96%`

Completato in dev:

- [x] create/list posts su task e activity
- [x] patch/delete post
- [x] create comment
- [x] reply comment annidata
- [x] patch/delete comment
- [x] patch/delete folder
- [x] patch/delete document
- [x] thread commenti serializzato correttamente
- [x] seed demo con documenti, issue aperte/chiuse, commenti e allegati
- [x] eventi realtime pubblicati su `post/comment/folder/document`
- [x] feed globale v3 su `/api/v1/projects/feed`
- [x] proxy Next feed spostato dal legacy alla v3
- [x] ordinamento feed per `effective_last_activity_at` reale del thread
- [x] stato `visto/non visto` persistente per profilo e per post
- [x] reset automatico a `non visto` quando il thread riceve nuova attivita
- [x] mark seen esplicito e mark seen implicito all'apertura thread
- [x] mark-all dei thread visibili dal feed con endpoint bulk dedicato
- [x] refresh live feed via evento realtime `feed.updated`
- [x] timer frontend dinamici basati sul timestamp reale di ultima attivita
- [x] filtro frontend `non visti`
- [x] batching progressivo feed guidato dallo scroll reale del layout, senza precaricare tutte le pagine in cascata
- [x] endpoint backend protetti per download di `documenti`, `foto`, `post attachment` e `comment attachment`
- [x] proxy Next `/api/project-assets/...` applicato a overview, documents, photos, alerts, feed e thread progetto
- [x] riscrittura URL asset verificata runtime su Next locale con cookie auth reale
- [x] smoke browser Playwright verificato su `10 -> 20 -> 25`, filtro `non visti`, mark-all visibili e jump al thread corretto

Aperto in dev:

- [ ] foto/media mutate solo se richieste davvero dal frontend reale

Prod fuori scope adesso:

- [ ] nulla di bloccante per il perimetro attuale

### Notifications e Realtime

Progresso dev: `94%`

Completato in dev:

- [x] ticket realtime notifiche
- [x] ticket realtime progetto
- [x] consumer WebSocket per notifiche e progetto
- [x] connessioni locali WebSocket verificate sul backend Docker
- [x] notification center list
- [x] mark as read
- [x] mark all as read
- [x] modello e persistenza notifiche
- [x] pubblicazione eventi dominio per richiesta accesso workspace, approvazione e rifiuto
- [x] pubblicazione eventi realtime progetto per task/activity/post/comment/folder/document
- [x] frontend notification routes allineate a `/api/v1/notifications`
- [x] notifiche contestuali per `project.mention.*` su post e commenti
- [x] notifiche contestuali per reply al proprio commento e commento sul proprio aggiornamento
- [x] notifiche per `task/activity/document/folder/member added` con metadati di navigazione
- [x] categorizzazione notifiche via `category/action`
- [x] deep-link reali verso `task`, `team` e `documenti`
- [x] highlight del target nei thread task e focus documenti/cartelle nel tab documenti
- [x] test backend estesi su mention, reply, upload documento e add member
- [x] smoke browser Playwright verificato su `localhost:3000` con overview live, notifica live, jump al thread task e refresh realtime documenti

Aperto in dev:

- [ ] eventuali eventi extra-core fuori da workspace/projects solo se servono al frontend reale

Prod fuori scope adesso:

- [ ] preferenze utente email/push/digest e relativi canali

### Search

Progresso dev: `92%`

Completato in dev:

- [x] contratto search allineato al modal globale di `edilcloud-next`
- [x] endpoint v3 `/api/v1/search/global`
- [x] proxy Next search spostato dal legacy alla v3
- [x] fetch secondarie del search index spostate alla v3 per task, documenti, foto e team
- [x] ricerca su progetti, task, attivita, aggiornamenti, documenti, disegni e persone
- [x] filtri per categoria esposti al frontend
- [x] ranking locale/backend piu forte sui match di titolo, prefix match e contesto documento
- [x] snippet contestuali backend per progetti, task, attivita, aggiornamenti, documenti, disegni e persone
- [x] resa frontend del modal search con una riga di contesto aggiuntiva
- [x] hit-highlighting frontend su title, subtitle e snippet
- [x] smoke script `scripts/smoke-global-search.mjs` verificato su Next locale con login reale
- [x] smoke search frontend riallineato a credenziali/query compatibili col dataset dev corrente
- [x] test backend con controllo accessi workspace
- [x] test backend su ordinamento tra title match e description match
- [x] benchmark dedicato `scripts/benchmark_search_global.py` sul percorso reale `frontend -> Next route -> backend v3`
- [x] report search con `p95`, `failure ratio`, `empty ratio`, copertura per query e categoria
- [x] smoke reale del benchmark search verificato su `localhost:3000`
- [x] benchmark search collegato ai baseline bundle tecnici tramite `capture_performance_baseline.py --search-benchmark-report`
- [x] storico prestazionale repo aggiornato per esporre `Search p95` e confronto baseline-vs-current anche sulla search
- [x] benchmark search integrato nel checkpoint tecnico unico di milestone
- [x] benchmark search verificato dentro checkpoint milestone reale con budget runtime del core a `100%`

Aperto in dev:

- [ ] affinare ranking PostgreSQL con full-text/trigram sui dataset piu grandi
- [ ] fare quality pass finale del ranking con dataset piu grande e query piu rappresentative

Prod fuori scope adesso:

- [ ] valutare `pgvector` solo come fase successiva, non come prerequisito

### Assistant e AI Drafting

Progresso dev: `90%`

Completato in dev:

- [x] backend assistant v3 con stato progetto, messaggi persistiti e route dedicate
- [x] proxy Next assistant riallineati alla v3 su `localhost:8001`
- [x] stream backend SSE nativo
- [x] route Next assistant convertite a semplice pass-through del flusso SSE v3
- [x] hosted memory rimossa dal path critico assistant/drafting
- [x] mini-RAG self-hosted con pgvector, embeddings OpenAI e filtro obbligatorio `project_id`
- [x] indicizzazione incrementale per `source_key` con chunking locale, overlap moderato e mapping chunk->point
- [x] worker assistant dedicato per indicizzazione background
- [x] compose locale esteso a `assistant-worker` con Postgres/pgvector
- [x] override compose produzione con volumi persistenti per Postgres/media/static
- [x] note operatore, transcript vocali, draft fragment ed evidence excerpts trattati come sorgenti contestuali locali
- [x] ranking citazioni migliorato con merge tra retrieval pgvector e fallback locale di progetto
- [x] ranking locale e grounding affinati per query su segnalazioni/criticita aperte
- [x] prompt hardening per assistant e drafting contro prompt injection dentro note, transcript, commenti e file
- [x] risposte assistant riallineate a output sempre strutturati per sezioni
- [x] smoke test end-to-end reale verificato su dataset demo ricco per assistant stream e drafting documentale
- [x] script locale di smoke test AI riutilizzabile su `localhost:3000`
- [x] assistant UI ridisegnata come modale grande con sessioni chat dedicate, settings panel e nessuna compressione del layout cantiere
- [x] preferenze assistant per-utente con override per-progetto e isolamento completo tra utenti
- [x] contatore token mensile serializzato alla UI
- [x] selettore modello dummy persistito per utente/progetto
- [x] stream assistant reso progressivo anche in UI con smoothing client-side dei delta
- [x] ordine dei messaggi nello stream UI corretto: la domanda resta sopra alla risposta anche durante il rendering progressivo
- [x] modale assistant riallineata a tutta l'altezza utile disponibile, senza taglio artificiale sul bordo inferiore
- [x] sorgente dedicata `team_directory` aggiunta al RAG locale per rispondere bene a domande su partecipanti, ruoli e workspace coinvolti
- [x] registro documenti di progetto aggiunto al RAG locale per migliorare retrieval e grounding documentale
- [x] estrazione testo locale di base per file PDF/testuali quando i file sono realmente disponibili al runtime
- [x] smoke browser Playwright dedicato per assistant verificato su `localhost:3000`
- [x] roadmap tecnica dedicata assistant/retrieval aggiunta in `docs/ASSISTANT_RETRIEVAL_ROADMAP.md`

Aperto in dev:

- [ ] convertire lo stream backend a iteratore async nativo per eliminare il warning ASGI di `StreamingHttpResponse` su iteratori sincroni
- [ ] affinare ulteriormente la sync incrementale con invalidazioni piu mirate per mutazioni ad alto volume
- [ ] aggiungere parsing/estrazione testo piu profonda per file complessi quando serve
- [ ] collegare una pipeline di trascrizione reale per note vocali/audio, oltre all'ingresso di transcript gia disponibili
- [ ] aggiungere citazioni piu ricche lato UI se serve un contratto finale con highlight o jump-to-source
- [ ] consolidare eval piu ampie su casi di cantiere reali e rubricare i prompt per scenario
- [ ] aggiungere telemetria dedicata a retrieval/indexing pgvector
- [ ] introdurre filtri retrieval piu stretti su `task_id` e `activity_id` per query altamente contestuali

Prod fuori scope adesso:

- [ ] cost guard, monitoraggio modelli/token e policy operative multi-tenant
- [ ] strategia di rebuild globale coordinato al cambio modello embeddings

### Billing

Progresso dev: `0%`

Completato in dev:

- [x] nessun lavoro avviato per scelta esplicita di priorita

Aperto in dev:

- [ ] nessun lavoro pianificato finche il core non e completamente stabile

Prod fuori scope adesso:

- [ ] chiarire esigenze business reali
- [ ] trial/entitlements
- [ ] eventuale Stripe solo se confermato

## Resa Professionale della Piattaforma

### Gia costruito

- [x] un backend dev misurabile, non solo funzionante
- [x] smoke browser ripetibili per feed, notifications/realtime, create progetto, team panel, project detail, search e assistant
- [x] CI dev che controlla non solo test ma anche drift migrazioni e integrita delle CLI operative
- [x] pagina superuser di diagnostica per trovare route CRUD rotte dal frontend reale
- [x] prima strumentazione di capacity planning con differenza esplicita tra `steady-state`, `fresh-login` e `realtime`
- [x] prima formalizzazione di budget runtime misurabili sui path critici del core
- [x] primo layer di baseline prestazionale storicizzabile e confrontabile nel tempo
- [x] primo registro storico delle milestone prestazionali direttamente versionato nel repo
- [x] benchmark dedicato della search reale, non limitato al solo smoke UI del modal
- [x] checkpoint tecnico unico per milestone locali e review prestazionale rapida
- [x] matrice tecnica unificata per `read-heavy`, `auth burst`, `mixed CRUD` e `realtime`
- [x] storico baseline leggibile anche per tipo di run: `checkpoint` vs `scalability-matrix`

### Ancora da alzare di livello in dev

- [ ] agganciare checkpoint e matrice tecnica a branch/milestone automatiche, non solo manuali
- [ ] estendere i guardrail dagli endpoint core attuali a una matrice piu ampia di route e scenari
- [ ] usare summary + budget telemetry per guidare priorita tecniche ricorrenti, non solo debug manuale

## Priorita Operative Aggiornate

### P0 - Misurazione e performance core

Obiettivo:

- capire fino a dove regge davvero il core collaborativo prima di parlare di `3000` utenti contemporanei

Task:

- [x] introdurre seed load-test, runner HTTP staged e benchmark realtime
- [x] introdurre `/api/v1/health/metrics/summary`
- [x] introdurre `/api/v1/health/metrics/budget` e report CLI dei guardrail
- [ ] eseguire la matrice `25 -> 3000` su hardware coerente con il target
- [x] fissare una prima versione dei budget per `overview`, `tasks`, `gantt`, `search`
- [x] introdurre baseline bundle e confronto baseline-vs-current
- [x] introdurre un primo registro storico confrontabile delle run nel repo
- [x] introdurre un checkpoint unico per milestone locali che orchestra summary + budget + search + baseline + history
- [x] far esercitare al checkpoint i path core prima della valutazione dei budget
- [x] introdurre una matrice tecnica unica per `read-heavy`, `auth burst`, `mixed CRUD` e `realtime`
- [x] automatizzare bundle baseline + history anche dalla matrice tecnica
- [ ] agganciare checkpoint e matrice a milestone/branch automatiche

### P1 - Search quality e scala

Obiettivo:

- rendere la search piu robusta su dataset grandi, non solo corretta sul demo set

Task:

- [ ] tuning PostgreSQL full-text/trigram
- [x] benchmark dedicato search
- [x] collegare il benchmark search alle baseline tecniche storiche
- [x] integrare il benchmark search nel checkpoint tecnico unico
- [ ] quality pass finale su ranking/snippet

### P2 - Assistant live e retrieval serio

Obiettivo:

- consolidare il blocco AI lato retrieval self-hosted, citazioni e robustezza runtime

Task:

- [x] sostituire il backend hosted con pgvector + OpenAI embeddings
- [ ] eliminare il warning stream sync/async lato ASGI
- [ ] aumentare parsing file/audio e citazioni ricche
- [ ] consolidare eval e smoke reali su casi di cantiere

### P3 - Hardening prod separato

Obiettivo:

- tenere separato tutto cio che serve alla produzione, senza rallentare il completamento dev

Task:

- [ ] tracing/export metrics esterni
- [ ] immagini prod
- [ ] backup/restore
- [ ] policy sicurezza produzione
- [ ] billing solo dopo stabilita del core

## Ordine di Esecuzione Reale

1. consolidare la baseline di carico progressiva sul core collaborativo
2. chiudere il blocco `Search` sui dataset piu grandi
3. chiudere il blocco `Assistant` su pgvector mini-RAG, stream e citazioni
4. continuare a usare admin diagnostics + smoke browser come rete anti-regressione
5. affrontare il perimetro prod solo dopo stabilizzazione delle metriche dev
6. affrontare billing solo quando il core e stabile

## Note Operative Importanti

- il comando locale di riferimento per il backend e `docker compose up -d` dentro `edilcloud-back-dn`
- il backend locale di riferimento e `http://localhost:8001`
- smoke test AI locale ripetibile: `..\\venv\\Scripts\\python.exe scripts\\smoke_ai_flows.py`
- seed smoke notifiche/realtime: `Get-Content scripts\\seed_notifications_realtime_smoke.py -Raw | docker compose exec -T web python -`
- smoke browser notifiche/realtime: `npm run smoke:notifications-realtime`
- seed feed smoke: `Get-Content scripts\\seed_feed_smoke.py -Raw | docker compose exec -T web python -`
- smoke browser feed: `npm run smoke:feed`
- seed create progetto smoke: `Get-Content scripts\\seed_create_project_smoke.py -Raw | docker compose exec -T web python -`
- smoke browser create progetto: `npm run smoke:create-project`
- seed Team panel smoke: `Get-Content scripts\\seed_team_panel_smoke.py -Raw | docker compose exec -T web python -`
- smoke browser Team panel: `npm run smoke:team-panel`
- seed project detail core smoke: `Get-Content scripts\\seed_project_detail_core_smoke.py -Raw | docker compose exec -T web python -`
- smoke browser project detail core: `npm run smoke:project-detail-core`
- smoke browser admin diagnostics lab: `npm run smoke:admin-diagnostics`
- seed load test: `docker compose exec -T web python /app/scripts/seed_loadtest_fixture.py --users 3000`
- load test staged frontend API: `docker compose exec -T web python /app/scripts/loadtest_frontend_api.py --stages 25,100,250,500,1000,2000,3000 --duration-seconds 60 --spawn-rate 50 --stop-on-fail --base-url http://host.docker.internal:3000`
- benchmark search dedicato: `..\\venv\\Scripts\\python.exe scripts\\benchmark_search_global.py --base-url http://localhost:3000 --format markdown`
- checkpoint tecnico unico: `..\\venv\\Scripts\\python.exe scripts\\run_performance_checkpoint.py --label milestone-local --compare-to-latest --format markdown`
- summary metriche runtime: `http://localhost:8001/api/v1/health/metrics/summary`
- `8000` non deve piu comparire nei flussi runtime del frontend v3
- il progetto demo ricco va mantenuto come dataset ufficiale per smoke test manuali
- ogni nuovo dominio migrato deve avere almeno un test backend e un flusso frontend verificabile

## Decisioni Gia Prese

- cartella backend v3: `edilcloud-back-dn`
- target architetturale: modular monolith
- API target: REST typed + OpenAPI
- local stack: Docker-first
- database: PostgreSQL
- cache/realtime support: Redis
- search classica: PostgreSQL full-text + trigram
- semantic retrieval: `pgvector`, ma non prima di chiudere il core
- project memory / RAG condiviso: pgvector + OpenAI embeddings
- modello operativo AI iniziale: `gpt-4o-mini`
- niente GraphQL come default
- niente microservizi per il core v3
