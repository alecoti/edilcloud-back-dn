# Test Center Issues

Questo documento descrive il primo livello del percorso verso il Test Center agentico:
trasformare segnali tecnici in casi operativi leggibili da persone e, in seguito,
da un agente di remediation.

## Obiettivo

La dashboard non deve limitarsi a mostrare report separati. Ogni anomalia deve
diventare una issue normalizzata con:

- severita
- piattaforma e target
- categoria
- evidenza
- sorgente tecnica
- playbook
- comandi suggeriti
- stato di automazione

Il primo endpoint e:

```text
GET /api/v1/test-center/issues
```

L'endpoint e riservato ai superuser e viene consumato dalla route Next:

```text
/dashboard/admin/test-center/issues
```

## Modello issue

Ogni issue contiene:

| Campo | Scopo |
| --- | --- |
| `id` | identificatore stabile derivato da categoria, piattaforma e target logico |
| `status` | stato operativo della issue, oggi sempre `open` |
| `severity` | `critical`, `warning` o `info` |
| `platform` | `backend`, `frontend-next`, `flutter` o altra piattaforma futura |
| `target` | `android`, `ios` o `null` |
| `category` | `quality`, `performance`, `runtime-budget`, `instrumentation` |
| `summary` | spiegazione breve leggibile in dashboard |
| `source` | report o segnale che ha generato il caso |
| `evidence` | prove testuali estratte da report, focus e metriche |
| `playbook` | sequenza di passi da seguire |
| `suggested_commands` | comandi sicuri da rilanciare manualmente |
| `automation` | stato e limiti per futura esecuzione automatica |
| `lifecycle` | aging, ricorrenza e stato SLA derivati dallo storico |

## Stati di automazione

| Stato | Significato |
| --- | --- |
| `candidate` | l'azione puo diventare automatica dopo ulteriori guardrail |
| `manual_review_required` | serve lettura umana prima di modificare codice o performance |
| `blocked` | manca una sorgente dati stabile o un prerequisito operativo |

Questa distinzione impedisce all'agente futuro di agire in modo impulsivo:
prima osserva, poi classifica, poi propone, poi verifica.

## Sorgenti attuali

Il builder legge l'overview del Test Center e genera issue da:

- runtime budget backend fuori soglia
- load test Locust non verde
- quality suite backend/frontend/flutter non verde
- piattaforme ancora in `pending_instrumentation`

## Ciclo di vita

Le issue correnti espongono ora anche `verification`, cioe l'ultima run del
ledger associata allo stesso identificatore stabile. Questo permette di leggere:

- quale tentativo ha verificato per ultimo la issue;
- se l'ultima verifica e stata `pass`, `fail`, `planned` o `running`;
- quale operazione e stata eseguita;
- quale action ha prodotto la run.

La risposta dell'endpoint include inoltre `recently_resolved`: issue che non
sono piu presenti tra i segnali correnti e la cui ultima run collegata e `pass`.
Questa lista chiude il primo ciclo operativo:

```text
issue aperta -> action -> run -> nuova lettura segnali -> issue ancora aperta o risolta di recente
```

Perche questo funzioni nel tempo gli ID non dipendono piu dal singolo artifact o
dal valore puntuale di p95: una quality issue frontend, una runtime rule o un
profilo Locust mantengono la stessa identita logica attraverso piu report.

## Memoria persistente

Ogni lettura della coda issue produce ora uno snapshot semantico deduplicato in:

```text
.tmp/test-center/issues/<timestamp>--<signature>/issue-snapshot.json
```

La firma ignora il semplice timestamp e cambia solo se cambia davvero lo stato
operativo: issue aperte, verifica collegata o issue recentemente risolte. In
questo modo refresh ripetuti della dashboard non gonfiano lo storico.

Gli snapshot espongono:

- stato e summary della coda al momento della cattura;
- issue aperte compatte;
- issue recentemente risolte compatte;
- transizioni derivate rispetto allo snapshot precedente:
  - `opened`
  - `verified`
  - `resolved`
  - `reopened`

Lo storico si legge con:

```text
GET /api/v1/test-center/issues/history
```

e dalla route frontend:

```text
/dashboard/admin/test-center/issues/history
```

Questo rende possibile distinguere una issue che non e mai stata affrontata da
una issue verificata, risolta e poi riaperta dal ritorno della stessa anomalia.

## Aging e SLA

Le issue aperte espongono ora anche `lifecycle`:

| Campo | Scopo |
| --- | --- |
| `first_seen_at` | prima comparsa nota nello storico |
| `last_seen_at` | ultima comparsa nota |
| `age_hours` | eta corrente della issue |
| `seen_in_snapshots` | quante fotografie la contengono |
| `reopen_count` | quante volte e stata riaperta |
| `sla_hours` | soglia operativa assegnata |
| `sla_state` | `within_sla`, `breached` o `unknown` |
| `escalation_state` | `due` quando la issue supera SLA |

Soglie iniziali:

- `critical`: 4 ore
- `warning`: 24 ore
- `info`: 72 ore

La summary dell'endpoint include `sla_breached`, cosi il centro operativo puo
evidenziare subito i casi che non sono solo aperti, ma anche troppo vecchi per
restare silenziosi.

## Agent queue

Il Test Center espone anche una coda decisionale per il futuro agente:

```text
GET /api/v1/test-center/agent/queue
```

La coda non applica correzioni: classifica le issue aperte in modo eseguibile e
leggibile:

- `auto_dry_run_candidate`: si puo rilanciare una verifica sicura in dry-run;
- `human_review_required`: serve revisione prima di qualunque modifica;
- `blocked`: manca un prerequisito;
- `escalation_due`: la issue ha superato SLA e va portata in priorita.

Ogni item contiene `issue_id`, `action_id`, `next_operation`, `priority`,
`guardrails`, `lifecycle` e l'ultima `verification`. Per ora la modalita resta
`dry_run_only`: l'agente futuro potra partire da questa coda senza inventarsi
priorita o permessi.

## Prossimo passo agentico

Il prossimo blocco naturale e aggiungere esecuzione controllata sopra la coda:

Il primo endpoint del ciclo e:

```text
GET /api/v1/test-center/agent/cycle/plan
```

e lo script operativo e:

```text
python scripts/run_test_center_agent_cycle.py --record
```

Il planner legge solo item `auto_dry_run_candidate`, applica rate limit per
totale, piattaforma e categoria, rispetta un cooldown sulle ultime run collegate
alla stessa issue e produce un piano `plan_only`. Non lancia processi e non
modifica codice: registra al massimo un artifact del piano in
`.tmp/test-center/agent-cycles`.

Restano da aggiungere:

1. esecuzione controllata dei soli item selezionati;
2. confronto tra verifica passata e nuova evidenza;
3. notifica/assegnazione quando una issue supera SLA.

L'agente non deve modificare codice finche non ha:

- issue normalizzata
- sorgente verificabile
- playbook associato
- test di conferma
- rollback o confine di modifica chiaro
