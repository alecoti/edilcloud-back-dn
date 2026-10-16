# Persone, incarichi e versioni delle evidenze

Rilascio del 16 ottobre 2026. Backend, web e Flutter condividono la stessa anagrafica documentale e le stesse API delle evidenze.

## Contenuto

- Persone e aziende del workspace; incarichi di progetto con qualifica, funzione, ruoli professionali e validità temporale. Sono ammesse persone esterne senza account, senza concedere loro accesso applicativo.
- Fonti con UUID permanente, riferimento umano, attribuzione registrata, versioni immutabili e SHA-256. Le modifiche successive non riscrivono gli snapshot precedenti.
- Conservazione privata dei file ricevuti prima dell'ottimizzazione; originale e derivato rimangono distinti. Il download e il renderer verificano l'integrità dei byte conservati.
- PDF con soggetti e incarichi, attribuzioni fotografiche, origine delle date, registro delle evidenze, copertura e link autenticati alla versione esatta della fonte.
- Manifest della revisione pubblicata con fonti, versioni, attribuzioni e hash del PDF. Consultazione, salvataggio, anteprima e pubblicazione non aggiungono chiamate AI.

## Messa in esercizio

Le migrazioni aggiuntive sono `projects.0026`, `projects.0027`, `elaborati.0010` e `elaborati.0011`. Il comando di avvio dei container applica le migrazioni prima dell'avvio del nuovo slot. Conservare e includere nei backup il volume di `PRIVATE_STORAGE_ROOT`, che contiene anche le copie delle evidenze.

Il recupero delle fonti pregresse è esplicito e ripetibile per progetto:

```text
python manage.py backfill_documentary_sources --project <id>
python manage.py backfill_documentary_sources --project <id> --apply
python manage.py backfill_documentary_sources --project <id> --apply --metadata-only
```

La prima forma è una simulazione. Il comando non modifica Elaborati pubblicati e non inventa originali mancanti, fotografi o incarichi storici. Non è stato eseguito sui dati di produzione durante la preparazione del rilascio.

## Limiti conosciuti

- I bundle delle bozze generate prima degli UUID richiedono ancora un aggiornamento conservativo e una prova dedicata di pubblicazione. Associare i vecchi ID ai dati correnti non ricostruisce la fonte storica utilizzata.
- Le revisioni già pubblicate mantengono i PDF esistenti; i manifest mancanti non vengono creati retroattivamente.
- L'estensione completa a revisioni delle tavole e pin è rinviata. BIM escluso dal prossimo intervento richiesto.
- Non è stato generato un nuovo APK con questo rilascio.

## Verifiche

- Backend: 288 test passati, 4 test di concorrenza PostgreSQL saltati nell'ambiente SQLite locale; controllo migrazioni senza differenze.
- Web: build di produzione, TypeScript ed ESLint delle aree modificate riusciti; 10 controlli browser su anagrafica, permessi, versioni, file originali e schermate strette.
- Flutter: 20 test per anagrafica, impostazioni ed evidenze; 85 test aggiuntivi per traduzioni offline e localizzazione. Verifica runtime della schermata anagrafica in Chrome, senza prova su Android o iPad fisici.
- Sei PDF sintetici prodotti dal renderer applicativo con attribuzioni, copertura, collegamenti alle versioni delle evidenze e hash coerenti con il manifest. Non sono un benchmark della redazione AI.
