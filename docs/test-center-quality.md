# Test Center quality suite

La quality suite produce artefatti JSON normalizzati letti dal Test Center.
Copre backend, frontend Next e Flutter con target Android/iOS separati.

## Comando base

```powershell
..\venv\Scripts\python.exe scripts\run_quality_suite.py --suite all
```

Gli artefatti vengono scritti in:

```text
.tmp/test-center/quality/<timestamp>--<platform>/quality-report.json
```

Il backend Test Center legge automaticamente:

- `.tmp/test-center/quality/**/*.json`
- `docs/performance-history/quality/**/*.json`

## Suite disponibili

- `backend`: Ruff + pytest backend mirati.
- `frontend-next`: ESLint mirato + `pnpm build`.
- `flutter-android`: `flutter analyze`, `flutter test`, build APK debug.
- `flutter-ios`: `flutter analyze`, `flutter test`, build iOS debug no-codesign.
- `flutter`: Android + iOS.
- `all`: tutte le suite.

## iOS

Su Windows e Linux il build iOS viene marcato come `skipped`, perche richiede
macOS e Xcode. Su runner macOS usare:

```powershell
..\venv\Scripts\python.exe scripts\run_quality_suite.py `
  --suite flutter-ios `
  --force-ios-build `
  --fail-on-threshold
```

## CI e job schedulati

Usare `--fail-on-threshold` per rendere il processo bloccante quando una suite
fallisce:

```powershell
..\venv\Scripts\python.exe scripts\run_quality_suite.py `
  --suite frontend-next `
  --fail-on-threshold
```

Per uno storico versionabile, promuovere i report piu importanti dentro:

```text
docs/performance-history/quality/<yyyy-mm-dd>/<run-id>/quality-report.json
```

La dashboard mostra il report piu recente per ogni superficie:

- Backend
- Frontend Next
- Flutter Android
- Flutter iOS

Nel dettaglio piattaforma mostra anche `stdout` e `stderr` finali di ogni
comando, cosi l'indagine parte dalla UI senza entrare nel server.

## Catalogo lanciabile da frontend

Il Test Center espone anche:

```text
GET /api/v1/test-center/catalog
POST /api/v1/test-center/catalog/{suite_id}/runs/launch
```

Le suite locali partono direttamente dal backend production:

- `backend-quality`
- `locust-auth-burst`
- `locust-read-heavy`
- `locust-mixed-crud`

Le suite remote usano runner dedicati GitHub Actions:

- `frontend-next-quality`
- `flutter-android-quality`
- `flutter-ios-quality`

Per abilitare il dispatch remoto servono:

- `TEST_CENTER_GITHUB_TOKEN`
- `TEST_CENTER_INGEST_TOKEN`

La stessa `TEST_CENTER_INGEST_TOKEN` va salvata come secret GitHub nei repository
`edilcloud-next` ed `edilcloud-flutter`, cosi i workflow remoti possono
autenticare l'upload dei report senza ricevere token sensibili come input visibili.

I workflow remoti inviano il report normalizzato a:

```text
POST /api/v1/test-center/ingest/quality
```

con header:

```text
X-Test-Center-Ingest-Token
X-Test-Center-Run-Name
```

In questo modo la dashboard mostra un solo catalogo operativo, ma ogni suite gira
nel contesto tecnico corretto: backend e Locust sul server backend, Next su Node
runner, Flutter Android su Linux e Flutter iOS su macOS.
