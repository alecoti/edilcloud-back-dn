# Test Center Action Registry

Il registro azioni e il secondo livello del percorso agentico del Test Center.
Dopo la normalizzazione delle issue, il sistema costruisce piani di remediation
in modalita `dry_run`.

## Endpoint

```text
GET /api/v1/test-center/actions
GET /api/v1/test-center/actions/{action_id}
```

Le route frontend corrispondenti sono:

```text
/dashboard/admin/test-center/actions
/dashboard/admin/test-center/actions/[actionId]
```

## Scopo

Il registro azioni risponde a domande operative:

- quale issue puo generare una remediation
- quale rischio ha l'intervento
- quali precondizioni devono essere vere
- quali operazioni sono consentite
- quali comandi verificano il risultato
- quali criteri dichiarano risolta la issue
- se serve review umana prima di procedere

## Stati azione

| Stato | Significato |
| --- | --- |
| `ready_for_dry_run` | il piano puo essere simulato o rilanciato senza modifiche al codice |
| `needs_human_review` | serve analisi umana prima di agire |
| `blocked` | mancano dati, artifact o prerequisiti |

## Guardrail iniziali

In questa fase ogni azione ha:

- `mode: dry_run`
- `audit.will_modify_code: false`
- `audit.will_touch_production: false`
- lista esplicita di `allowed_operations`
- lista esplicita di `blocked_by`
- criteri di successo verificabili

Questo impedisce al futuro agente di confondere una proposta con una correzione
automatica.

## Relazione con le issue

Ogni azione deriva da una issue e contiene un blocco `source_issue`.

Il flusso e:

```text
report/log/metriche -> issue -> action plan -> dry-run -> verifica -> eventuale remediation
```

## Prossimo step

Il blocco successivo e il run ledger:

1. creare un record di tentativo
2. salvare input, comando, log e output
3. distinguere dry-run da apply
4. rendere ogni tentativo auditabile
5. permettere al frontend di mostrare lo storico dei tentativi per azione

Solo dopo questo ledger avra senso introdurre un esecutore automatico vero.

## Executor controllato

Il primo wrapper operativo e:

```text
scripts/run_test_center_action.py
```

Lo script puo eseguire solo operazioni presenti in `allowed_operations` della
action e supportate dal wrapper:

| Operazione | Comando prodotto |
| --- | --- |
| `rerun_quality_suite` | `scripts/run_quality_suite.py --suite <suite> --fail-on-threshold` |
| `rerun_loadtest_suite` | `scripts/run_locust_suite.py --profile <profile> --fail-on-threshold` |

Esempio:

```powershell
..\venv\Scripts\python.exe scripts\run_test_center_action.py `
  --action-id <action_id> `
  --operation rerun_quality_suite `
  --approved-by ops@example.com
```

Guardrail:

- non modifica codice
- non tocca produzione
- registra sempre un artifact nel run ledger
- rifiuta action `blocked`
- rifiuta operazioni non presenti in `allowed_operations`
- richiede `--approved-by` se la action e in `needs_human_review`

## Avvio da frontend

Le action possono ora essere gestite anche dalla dashboard:

```text
POST /api/v1/test-center/actions/{action_id}/runs/plan
POST /api/v1/test-center/actions/{action_id}/runs/launch
```

- `plan` registra soltanto una run `planned`;
- `launch` registra subito una run `running` e avvia in background il runner
  controllato;
- il runner scrive poi il risultato finale nella stessa run del ledger,
  trasformandola in `pass` o `fail`.

La pagina frontend di dettaglio action espone entrambe le scelte:

- `Prepara dry-run`
- `Avvia test`

In questo modo il Test Center non e piu solo consultivo: il superuser puo
rilanciare dal browser le operazioni whitelisted gia collegate alle issue,
seguire l'esecuzione e leggere stdout/stderr senza entrare nel server.

Per preparare un tentativo senza eseguire il comando:

```powershell
..\venv\Scripts\python.exe scripts\run_test_center_action.py `
  --action-id <action_id> `
  --operation rerun_quality_suite `
  --plan-only
```
