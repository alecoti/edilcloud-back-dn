# Demo Snapshot Workflow

Ultimo aggiornamento: 2026-04-12

Questo documento descrive il primo workflow backend per il freeze point del Demo Master.

## Stato attuale

Implementato:

- marker progetto demo:
  - `Project.is_demo_master`
  - `Project.demo_snapshot_version`
- modello snapshot:
  - `DemoProjectSnapshot`
- comando di creazione snapshot:
  - `create_demo_master_snapshot`
- export JSON opzionale del freeze point
- hash separati per:
  - definizione seed
  - manifest asset demo
  - payload snapshot esportato

Non ancora implementato:

- ripristino dal payload snapshot;
- clone sessione demo da snapshot;
- pin persistenti come entita backend;
- pulsanti Admin Test Lab per snapshot/reset.

## Migrazione

Applicare la migrazione progetti:

```bash
cd edilcloud-back-dn
PYTHONPATH=src python manage.py migrate
```

## Seed del Demo Master

Rigenera il progetto demo canonico:

```bash
cd edilcloud-back-dn
PYTHONPATH=src python manage.py seed_rich_demo_project
```

Il seed marca il progetto come Demo Master (`is_demo_master=True`).

## Creazione snapshot

Esempio minimo:

```bash
cd edilcloud-back-dn
PYTHONPATH=src python manage.py create_demo_master_snapshot --validate --activate --write-json
```

Esempio con versione esplicita:

```bash
cd edilcloud-back-dn
PYTHONPATH=src python manage.py create_demo_master_snapshot ^
  --snapshot-version v2026.04-freeze01 ^
  --business-date 2026-04-12 ^
  --created-by-email laura.ferretti@ferretti-associati.it ^
  --notes "Primo freeze point demo commerciale" ^
  --validate ^
  --activate ^
  --write-json
```

## Cosa salva lo snapshot

Metadata:

- `version`
- `name`
- `business_date`
- `schema_version`
- `seed_hash`
- `asset_manifest_hash`
- `payload_hash`
- `validation_status`
- `validated_at`
- `active_in_production`
- `notes`
- `export_relative_path`

Payload:

- summary progetto;
- statistiche;
- membri;
- task e lavorazioni;
- documenti;
- foto;
- post;
- commenti;
- allegati post/commenti.

## Export JSON

Se usi `--write-json`, il file viene scritto in:

```text
edilcloud-back-dn/demo-assets/demo-master/snapshots/<snapshot-version>.json
```

## Reset del Demo Master

Reset canonico al seed attuale:

```bash
cd edilcloud-back-dn
PYTHONPATH=src python manage.py reset_demo_master_project
```

Comportamento attuale:

- ricrea il Demo Master dal seed canonico corrente;
- se esiste uno snapshot attivo per quel demo name, riaggancia `demo_snapshot_version` al nuovo progetto;
- non ripristina ancora il payload di uno snapshot specifico.

## Come leggere l'asset state prima del freeze

Per vedere le sorgenti attese e i path correnti dei media:

```bash
cd edilcloud-back-dn
PYTHONPATH=src python manage.py report_demo_master_assets
PYTHONPATH=src python manage.py report_demo_master_assets --format json
```

## Guardrail attuali

- lo snapshot si aggancia al progetto demo corrente ma sopravvive anche a un reseed;
- l'unicita e' su `name + version`, non sul `project_id`;
- attivando uno snapshot, gli altri snapshot con lo stesso nome demo vengono disattivati;
- il reset vero da snapshot non esiste ancora: oggi il ripristino reale resta il seed canonico.

## Prossimo passo tecnico

1. aggiungere comando `reset_demo_master_snapshot` o equivalente;
2. far leggere all'Admin Test Lab lo snapshot attivo;
3. usare `demo_snapshot_version` come riferimento UI/backend per il Demo Master;
4. portare pin e drawing state dentro il payload o in un modello dedicato.
