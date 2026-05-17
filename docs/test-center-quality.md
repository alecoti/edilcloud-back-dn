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
