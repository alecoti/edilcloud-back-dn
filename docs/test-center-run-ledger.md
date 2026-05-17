# Test Center Run Ledger

Il run ledger e lo storico auditabile dei tentativi legati alle azioni del Test
Center. Non esegue comandi: legge artifact JSON prodotti da runner, operatori o
futuri agenti e li rende consultabili via API e dashboard.

## Endpoint

```text
GET /api/v1/test-center/runs
GET /api/v1/test-center/runs?action_id=<action_id>
GET /api/v1/test-center/runs?status=fail
GET /api/v1/test-center/runs/{run_id}
```

Route frontend:

```text
/dashboard/admin/test-center/runs
/dashboard/admin/test-center/runs/[runId]
```

## Posizione artifact

Il backend legge file JSON da:

```text
.tmp/test-center/action-runs/**/*.json
docs/performance-history/action-runs/**/*.json
```

Il file consigliato e:

```text
.tmp/test-center/action-runs/<timestamp>-<action-id>/action-run.json
```

## Schema artifact consigliato

```json
{
  "status": "fail",
  "mode": "dry_run",
  "action_id": "action-frontend-1",
  "issue_id": "issue-frontend-1",
  "operation": "rerun_quality_suite",
  "platform": "frontend-next",
  "target": null,
  "category": "quality",
  "generated_at": "2026-05-17T10:00:00Z",
  "started_at": "2026-05-17T10:00:01Z",
  "finished_at": "2026-05-17T10:00:09Z",
  "duration_seconds": 8.4,
  "actor": {
    "kind": "operator",
    "id": "ops@example.com",
    "label": "Ops"
  },
  "command": "pnpm build",
  "cwd": "edilcloud-next",
  "returncode": 1,
  "summary": "TypeScript build failed.",
  "stdout_tail": "build output",
  "stderr_tail": "Type error",
  "evidence": ["Build non conclusa."],
  "next_step": "Correggere il tipo segnalato e ripetere il dry-run.",
  "audit": {
    "will_modify_code": false,
    "will_touch_production": false,
    "approval_required": true,
    "approved_by": null
  }
}
```

## Stati supportati

| Stato | Significato |
| --- | --- |
| `planned` | tentativo preparato ma non ancora eseguito |
| `running` | tentativo in corso |
| `pass` | verifica completata con successo |
| `fail` | verifica completata con errore |
| `blocked` | tentativo non eseguibile per guardrail o prerequisiti |
| `cancelled` | tentativo annullato |
| `skipped` | tentativo saltato intenzionalmente |

## Guardrail

Ogni run deve dichiarare se:

- modifica codice
- tocca produzione
- richiede approvazione
- e stato approvato

Il ledger rende questi campi visibili per evitare che un futuro agente perda
traccia del confine tra osservazione, dry-run e intervento.

## Prossimo passo

Il prossimo blocco naturale e uno script controllato di registrazione run:

```text
scripts/record_action_run.py
```

Lo script dovra ricevere action id, comando, esito e log, poi scrivere un artifact
compatibile con questo formato. Solo dopo ha senso introdurre un executor che
produca run in automatico.

## Script di registrazione

Lo script disponibile e:

```text
scripts/record_action_run.py
```

Esempio dry-run fallito:

```powershell
..\venv\Scripts\python.exe scripts\record_action_run.py `
  --action-id action-frontend-1 `
  --issue-id issue-frontend-1 `
  --operation rerun_quality_suite `
  --platform frontend-next `
  --category quality `
  --command "pnpm build" `
  --cwd edilcloud-next `
  --returncode 1 `
  --summary "TypeScript build failed." `
  --stdout-file .tmp\frontend-build.stdout.log `
  --stderr-file .tmp\frontend-build.stderr.log `
  --next-step "Correggere il tipo segnalato e ripetere il dry-run."
```

Lo script non esegue il comando. Registra solamente l'esito osservato e produce
un artifact `action-run.json` compatibile con la dashboard.

Per registrare un run in modalita `apply`, serve approvazione esplicita:

```powershell
..\venv\Scripts\python.exe scripts\record_action_run.py `
  --action-id action-backend-1 `
  --operation rerun_quality_suite `
  --platform backend `
  --category quality `
  --mode apply `
  --approved-by ops@example.com `
  --status pass
```

## Executor controllato

Per produrre run ledger partendo da una action esistente si usa:

```text
scripts/run_test_center_action.py
```

Il wrapper esegue solo operazioni whitelisted e poi registra il tentativo usando
lo stesso formato `action-run.json`.

Esempio:

```powershell
..\venv\Scripts\python.exe scripts\run_test_center_action.py `
  --action-id <action_id> `
  --operation rerun_quality_suite `
  --approved-by ops@example.com
```

Per scrivere solo un run `planned`, senza subprocess:

```powershell
..\venv\Scripts\python.exe scripts\run_test_center_action.py `
  --action-id <action_id> `
  --operation rerun_quality_suite `
  --plan-only
```
