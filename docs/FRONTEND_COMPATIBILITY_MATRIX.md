# Frontend Compatibility Matrix

Questo documento viene generato da `scripts/audit_frontend_contract.py` e serve come checklist vincolante per la migrazione verso la v3.

## Obiettivo

Ogni modulo del nuovo backend viene considerato pronto solo quando copre il perimetro necessario a far funzionare `edilcloud-next` senza dipendenze residue dal backend legacy per quel dominio.

## Snapshot Attuale

- File frontend con dipendenze backend legacy rilevate: `0`
- Endpoint legacy unici rilevati: `0`
- Backend locale di riferimento: `http://localhost:8001`
- Lo scanner cerca solo dipendenze runtime residue verso `/api/frontend/...`

## Regola di Migrazione

Un bounded context si considera migrato solo quando:

- tutti gli endpoint legacy del suo perimetro hanno un equivalente v3
- `edilcloud-next` smette di fare stitching non necessario per quel dominio
- esistono test backend e smoke path frontend per i flussi critici

## Stato Residuo

- Nessuna dipendenza runtime legacy `/api/frontend/...` rilevata in `edilcloud-next/src`.
- Il frontend locale puo parlare con la v3 su `http://localhost:8001` per i domini core gia migrati.
- I smoke browser ripetibili gia chiusi coprono `notifications/realtime`, `feed`, `search`, `create progetto`, `team panel` e `project detail core` (`cantieri -> overview -> gantt -> team`).
- Sul perimetro progetto il grep runtime e pulito: nessuna dipendenza residua a `/api/frontend/project`, `localhost:8000`, `127.0.0.1:8000` o `target: "legacy"` dentro `edilcloud-next/src`.
- Restano comunque fuori dallo scanner soprattutto il flusso browser completo `assistant`, il tuning qualitativo della search e l'hardening finale.
