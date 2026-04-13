# EdilCloud Demo Master e Admin Tester Roadmap

Ultimo aggiornamento: 2026-04-12

Questo documento e' il punto vivo di lavoro per costruire:

- un Demo Master realistico e versionato;
- un playground demo sicuro per clienti senza iscrizione;
- un Admin Test Lab superuser per verificare notifiche, permessi, feed, documenti, Gantt, tavole, AI e realtime.
- una demo/tester che possa funzionare anche in produzione con isolamento, guardrail e cleanup.

Ogni volta che viene chiuso un task operativo, questo documento va aggiornato con:

- stato della fase;
- decisioni prese;
- file/moduli toccati;
- test o verifiche eseguite;
- prossima azione consigliata.

## Principio guida

Demo commerciale e tester tecnico devono usare la stessa verita' di prodotto, ma con runtime diversi.

- Demo commerciale: deve far capire EdilCloud in pochi minuti, con un cantiere vivo, credibile e guidato.
- Tester tecnico: deve dire se qualcosa si e' rotto, con scenari ripetibili e risultati attesi.
- Demo Master: deve essere la fonte canonica da cui nascono sia il playground sia i test.
- Production-first: nessun visitatore pubblico modifica il master, nessun reset colpisce dati reali, ogni sessione demo e' isolata.

## Stato attuale

## Log operativo

- 2026-04-12: rivista la comunicazione delle segnalazioni critiche nel Demo Master per renderla piu naturale e dialogata; aumentati i commenti nei thread issue e aggiornati i testi smoke/test di supporto.
- 2026-04-12: sbloccato nel frontend l'editing di post/commenti quando il backend espone `can_edit`, cosi owner/superadmin del demo possono modificare contenuti creati da altri autori senza cambiare la firma originale; aggiunto anche il supporto seed per avatar persone da `demo-assets/demo-master/v2026.04/avatars/`.

### Fase 1 - Audit iniziale

Stato: completata.

Esito sintetico:

- esiste gia' un seed backend ricco in `src/edilcloud/modules/projects/management/commands/seed_rich_demo_project.py`;
- esiste gia' una demo frontend simulata in `edilcloud-next/src/lib/demo-project`;
- esiste gia' una pagina superuser di diagnostica in `edilcloud-next/src/app/dashboard/admin/tests/page.tsx`;
- il sistema e' promettente, ma oggi backend demo e frontend demo sono due verita' diverse;
- manca ancora un freeze point unico, versionato e validabile;
- manca ancora un percorso pubblico no-login realmente isolato per cliente;
- manca ancora uno scenario engine che verifichi notifiche e permessi per attore.

Decisione iniziale:

- il backend seed deve diventare la base canonica del futuro Demo Master;
- la demo frontend simulata va considerata una fonte narrativa utile, non la fonte definitiva;
- l'Admin Test Lab esistente va evoluto da diagnostica endpoint a tester di scenari.

## Roadmap

### Fase 2 - Demo Master canonico

Stato: completata per il Demo Master seed; restano freeze point e tester nelle fasi successive.

Obiettivo: fondere la ricchezza del demo frontend dentro una fonte backend unica e mantenibile.

Task:

- [x] definire schema narrativo del cantiere demo ufficiale;
- [x] scegliere nome definitivo, descrizione, date e stato demo;
- [x] documentare vincolo production-first per demo, tester e snapshot;
- [x] portare il seed backend da 6 a 8 aziende;
- [x] aggiungere committente/developer come azienda/persona separata;
- [x] separare meglio serramenti, facciate e finiture se utile per la demo;
- [x] assegnare ruoli workspace coerenti a tutti gli utenti;
- [x] assegnare `project_role_codes` di sicurezza e responsabilita';
- [x] allineare fasi backend e frontend in un solo elenco canonico;
- [x] tarare avanzamento progetto al 66% con fasi chiuse, in corso e in avvio;
- [x] aumentare documenti, foto e tavole fallback del seed backend;
- [x] aumentare allegati e conversazioni del seed backend;
- [x] decidere come gestire asset reali forniti da Antonio: loghi, avatar, foto, audio, video, tavole.

Criterio di completamento:

- il backend puo' generare un progetto demo completo e coerente senza dipendere dal fake store frontend;
- aziende, utenti, ruoli, task, attivita', documenti, post e commenti sono sufficienti per una demo commerciale.

### Fase 3 - Asset manifest

Stato: avviata.

Obiettivo: rendere tutti gli asset demo espliciti, sostituibili e verificabili.

Task:

- [x] creare un manifest asset demo iniziale;
- [x] mappare loghi aziende attesi;
- [x] mappare avatar persone attesi;
- [x] mappare foto cantiere e fallback SVG;
- [x] mappare audio/video demo previsti;
- [x] mappare documenti PDF/XLSX/ZIP attesi;
- [x] mappare tavole/disegni e primi pin canonici;
- [x] definire fallback generati per asset mancanti;
- [x] aggiungere una prima reportistica backend per asset mancanti o rotti.

Criterio di completamento:

- ogni asset usato nella demo ha una voce nel manifest;
- il tester puo' dire se un asset manca, e dove viene usato.

### Fase 4 - Freeze point e snapshot

Stato: avviata.

Obiettivo: poter ripristinare sempre il Demo Master a uno stato certo.

Task:

- [x] definire modello/versione snapshot;
- [x] decidere formato snapshot: seed deterministico, export JSON, dump DB o ibrido;
- [x] aggiungere `demo_snapshot_version`;
- [x] aggiungere hash seed e hash asset;
- [x] costruire comando/servizio di reset Demo Master canonico;
- [x] costruire comando/servizio di export freeze point;
- [x] costruire comando/servizio di restore da snapshot versionato;
- [ ] impedire che utenti demo pubblici modifichino il master;
- [ ] definire policy per "Salva nuovo freeze point".

Criterio di completamento:

- il superuser puo' ripristinare il Demo Master in modo deterministico;
- un nuovo freeze point puo' essere salvato solo dopo validazione.

### Fase 5 - Admin Test Lab evoluto

Obiettivo: trasformare la diagnostica esistente in un laboratorio scenario-based.

Task:

- [x] mantenere i test tecnici gia' presenti;
- [x] aggiungere sezione stato Demo Master;
- [x] aggiungere sezione snapshot attivo;
- [x] aggiungere pulsante "Salva freeze point";
- [x] aggiungere pulsante "Ripristina seed canonico";
- [x] aggiungere pulsante "Ripristina snapshot";
- [ ] aggiungere pulsante "Crea sessione demo pulita";
- [ ] aggiungere pulsante "Esegui suite scenari";
- [ ] aggiungere risultati con atteso/ottenuto;
- [ ] collegare ogni errore a rotta, attore e oggetto coinvolto;
- [x] mantenere gating superuser frontend e backend.

Criterio di completamento:

- un superuser capisce in una schermata se demo, notifiche, permessi e flussi core sono sani.

### Fase 6 - Scenario engine

Obiettivo: testare EdilCloud come prodotto, non solo come insieme di endpoint.

Task foundation:

- [x] aggiungere una prima suite readiness read-only nel Test Lab per misurare la qualita' del Demo Master su notifiche, feed, documenti e permessi;

Ogni scenario deve definire:

- attore;
- prerequisiti;
- azione;
- risultato atteso;
- notifiche attese;
- notifiche non attese;
- feed atteso;
- permessi attesi;
- cleanup/reset.

Scenari minimi:

- [x] menzione in post operativo;
- [ ] menzione in segnalazione critica;
- [ ] commento su thread proprio;
- [ ] risposta a commento;
- [ ] creazione task assegnato ad azienda;
- [ ] aggiornamento task;
- [ ] creazione attivita' assegnata a lavoratori;
- [ ] aggiornamento attivita';
- [ ] apertura issue;
- [ ] risoluzione issue;
- [ ] upload documento;
- [ ] aggiornamento documento;
- [ ] eliminazione documento;
- [ ] creazione cartella;
- [ ] aggiornamento ruolo team progetto;
- [ ] richiesta accesso workspace;
- [ ] approvazione/rifiuto richiesta accesso;
- [ ] verifica realtime progetto;
- [ ] verifica realtime notifiche;
- [ ] verifica ricerca globale;
- [ ] verifica assistant su fonti demo.

Criterio di completamento:

- ogni scenario produce un report leggibile e ripetibile;
- il report dice chi ha ricevuto cosa e perche'.

### Fase 7 - Playground demo pubblico

Obiettivo: far provare EdilCloud senza iscrizione, senza sporcare il master.

Decisione architetturale consigliata:

- sessione demo isolata per visitatore;
- clone temporaneo del Demo Master;
- `demo_session_id` nel browser;
- TTL automatico;
- reset demo manuale;
- cleanup sessioni scadute.

Task:

- [ ] definire route pubblica demo;
- [ ] definire profili/personas demo apribili;
- [ ] decidere se la demo mantiene la sessione al refresh o resetta sempre;
- [ ] impedire scritture sul master;
- [ ] isolare modifiche per visitatore;
- [ ] aggiungere cleanup sessioni demo;
- [ ] aggiungere eventuale modal "Stai provando una copia demo";
- [ ] aggiungere cambio persona guidato: DL, impresa, operaio, committente.

Criterio di completamento:

- due visitatori contemporanei non si influenzano;
- il cliente puo' giocare senza account;
- il master resta intatto.

### Fase 8 - Tavole, pin, Gantt e media reali

Obiettivo: rendere la demo memorabile e utile in vendita.

Task:

- [ ] portare tavole/disegni demo a backend o snapshot;
- [ ] rendere i pin parte del demo snapshot, non solo localStorage;
- [ ] collegare pin a post/commenti/task/documenti;
- [ ] aggiungere vincoli Gantt demo;
- [ ] rendere import/apply Gantt testabile o simulabile in modo esplicito;
- [ ] aggiungere foto reali;
- [ ] aggiungere audio reali;
- [ ] aggiungere video reali;
- [ ] verificare preview media su post/commenti/documenti.

Criterio di completamento:

- la demo mostra il cantiere come sistema operativo visuale: tavole, pin, thread, media e programma lavori sono collegati.

### Fase 9 - Notifiche e permessi completi

Obiettivo: usare il Demo Master per validare tutto il sistema operativo di collaborazione.

Task:

- [ ] creare matrice notifiche attive;
- [ ] creare matrice notifiche mancanti;
- [ ] creare matrice permessi per ruolo workspace;
- [ ] creare matrice permessi per ruolo progetto;
- [ ] testare click di ogni notifica verso la destinazione corretta;
- [ ] testare "chi vede cosa";
- [ ] testare "chi puo' modificare cosa";
- [ ] testare che actor non riceva notifiche inutili da se stesso;
- [ ] testare digest/alert futuri quando verranno implementati.

Criterio di completamento:

- le notifiche non sono solo presenti: sono corrette, utili e navigabili.

## Backlog decisioni aperte

- [ ] il Demo Master deve vivere solo su backend o anche essere esportabile come JSON condiviso con Next?
- [ ] il playground pubblico deve mantenere modifiche dopo refresh nello stesso browser o resettare sempre?
- [ ] quanto deve durare una demo session prima del cleanup?
- [ ] il bottone "Salva nuovo freeze point" deve esportare da DB o aggiornare il seed sorgente?
- [ ] i pin tavole devono diventare modello backend dedicato?
- [ ] le notifiche demo devono essere generate via servizi reali o pre-seedate?
- [ ] serve una modal di impersonificazione superuser per aprire il progetto come persone diverse?

## Registro avanzamento

### 2026-04-12 - Fase 1 completata

Completato audit iniziale.

File principali analizzati:

- `edilcloud-back-dn/src/edilcloud/modules/projects/management/commands/seed_rich_demo_project.py`
- `edilcloud-next/src/lib/demo-project/data.ts`
- `edilcloud-next/src/lib/demo-project/store.ts`
- `edilcloud-next/src/lib/demo-project/assistant.ts`
- `edilcloud-next/src/app/dashboard/admin/tests/page.tsx`
- `edilcloud-next/src/app/api/admin/dev-diagnostics/route.ts`

Risultato:

- confermata presenza di seed backend ricco;
- confermata presenza di demo frontend simulata;
- confermata presenza di Admin Diagnostics Lab;
- identificato gap principale: due fonti demo divergenti;
- identificato prossimo passo: progettare Demo Master canonico backend-first.

Prossima azione consigliata:

- avviare Fase 2 con una mappa canonica del progetto demo: aziende, persone, ruoli, fasi, attivita', scenari e asset richiesti.

### 2026-04-12 - Fase 2 avviata: specifica canonica Demo Master

Creata la specifica canonica:

- `edilcloud-back-dn/docs/DEMO_MASTER_SPEC.md`

Decisioni prese:

- nome canonico confermato: `Residenza Parco Naviglio - Lotto A`;
- backend seed come fonte canonica futura;
- demo frontend simulata trattata come fonte narrativa utile ma non definitiva;
- target definitivo a 8 aziende;
- separazione consigliata tra serramenti/facciata e finiture;
- introdotto vincolo production-first: sessioni demo isolate, master non modificabile dai visitatori, reset limitato a oggetti demo, feature flag e cleanup;
- definiti personas, fasi operative, criticita, documenti, tavole, pin, media e scenari minimi.

File creati:

- `edilcloud-back-dn/docs/DEMO_MASTER_SPEC.md`

Test/verifiche:

- non eseguiti test automatici; modifica solo documentale.

Prossima azione consigliata:

- aggiornare `seed_rich_demo_project.py` per allinearlo alla specifica canonica: 8 aziende, project role codes, 10 fasi operative e primi asset/tavole canonici.

### 2026-04-12 - Fase 2: primo allineamento seed backend

Aggiornato il seed backend:

- `edilcloud-back-dn/src/edilcloud/modules/projects/management/commands/seed_rich_demo_project.py`

Completato:

- portato il seed da 6 a 8 aziende;
- aggiunta `Immobiliare Naviglio Srl` come committente/developer;
- aggiunta `Serramenti Milano Contract` come azienda separata da finiture;
- rinominata l'area finiture in `Interni Bianchi Srl`;
- aggiunti profili canonici mancanti;
- aggiunti `project_role_codes` su ProjectMember per committente, CSE/CSP, RSPP, datore lavoro, preposti, lavoratori e addetti emergenza;
- portate le fasi operative backend a 10:
  - avvio/logistica;
  - scavi/fondazioni;
  - strutture;
  - involucro;
  - serramenti/facciata;
  - meccanico;
  - elettrico;
  - interni;
  - finiture/pre-collaudi;
  - consegna.

Verifiche:

- `python -m py_compile edilcloud-back-dn/src/edilcloud/modules/projects/management/commands/seed_rich_demo_project.py`
- controllo strutturale AST: 8 aziende, 36 persone, 10 task/fasi, 93 riferimenti worker, 0 worker mancanti.

Note:

- non e' ancora stato eseguito il management command sul DB;
- documenti, foto, tavole, pin e asset reali restano da estendere nelle prossime sottofasi;
- il seed e' piu vicino alla specifica canonica, ma non e' ancora un freeze point production-ready.

Prossima azione consigliata:

- estendere documenti/foto/tavole del seed e introdurre un primo manifest demo per asset e pin canonici.

### 2026-04-12 - Fase 2/Fase 3: asset seed e manifest pin iniziale

Aggiornato il seed backend e creato il manifest asset:

- `edilcloud-back-dn/src/edilcloud/modules/projects/management/commands/seed_rich_demo_project.py`
- `edilcloud-back-dn/docs/DEMO_ASSET_PIN_MANIFEST.md`

Completato:

- portati i documenti demo da 5 a 15, coprendo DL, sicurezza, impianti, finiture, as-built, manutenzione e collaudi;
- portati foto/tavole fallback da 4 a 20, con 10 tavole operative e 10 scene/foto di cantiere;
- definito il manifest iniziale per loghi aziende, avatar persone, documenti, tavole, foto, audio/video previsti e pin canonici;
- definiti 10 pin canonici con tavola, coordinate percentuali, stato, severita, owner e collegamento futuro a post/task/documenti;
- confermata una strategia production-first per asset reali: asset referenziati da manifest, fallback generato se mancano, validazione dedicata nel tester.

Verifiche:

- `python -m py_compile edilcloud-back-dn/src/edilcloud/modules/projects/management/commands/seed_rich_demo_project.py`
- controllo strutturale AST: 8 aziende, 36 persone, 10 task/fasi, 15 documenti, 20 foto/tavole.

Note:

- non e' ancora stato eseguito il management command sul DB;
- le conversazioni post/commenti devono ancora essere arricchite con thread profondi e allegati;
- la validazione automatica degli asset mancanti o rotti e' ancora da implementare.

Prossima azione consigliata:

- proseguire con l'arricchimento di post/commenti/allegati nel seed, poi introdurre il primo modello tecnico per snapshot/freeze point.

### 2026-04-12 - Fase 2 completata: thread operativi piu profondi

Aggiornato il seed backend:

- `edilcloud-back-dn/src/edilcloud/modules/projects/management/commands/seed_rich_demo_project.py`

Completato:

- aggiunta una matrice `THREAD_COMMUNICATIONS` per le 10 famiglie operative;
- ogni thread standard ora coinvolge DL, referente impresa, figura di controllo, stakeholder e campo;
- ogni kickoff di fase genera anche un memo PDF di coordinamento allegato al commento;
- i thread issue ora hanno piu passaggi: presa in carico, lettura di campo, richiesta stakeholder, documento tecnico allegato e chiusura/storico;
- predisposte menzioni testuali nei commenti, utili per leggere bene demo, feed e futuri scenari notifiche.

Verifiche:

- `python -m py_compile edilcloud-back-dn/src/edilcloud/modules/projects/management/commands/seed_rich_demo_project.py`
- controllo strutturale AST: 8 aziende, 36 persone, 10 task/fasi, 15 documenti, 20 foto/tavole, 10 contesti thread.

Note:

- non e' ancora stato eseguito il management command sul DB;
- il seed ora e' una base commerciale molto piu credibile, ma le notifiche reali non vengono ancora generate dal seed diretto;
- per testare notifiche e permessi serve il prossimo layer: snapshot/freeze point e scenario engine.

Prossima azione consigliata:

- avviare Fase 4: definire freeze point/snapshot versionato, con reset sicuro e prerequisiti production-first.

### 2026-04-12 - Fase 2 rifinita: avanzamento 66% e dialoghi abbondanti

Aggiornati seed e specifica:

- `edilcloud-back-dn/src/edilcloud/modules/projects/management/commands/seed_rich_demo_project.py`
- `edilcloud-back-dn/docs/DEMO_MASTER_SPEC.md`

Completato:

- tarato l'avanzamento demo al 66% tramite media aritmetica delle 10 fasi: 660 punti / 10 fasi;
- rese esplicite 3 fasi chiuse, 5 fasi in corso e 2 fasi in avvio/future;
- impostato `date_completed` sulle fasi chiuse;
- impostato `progress` anche sulle lavorazioni, coerente con stato chiuso/in corso/pianificato;
- aumentata ulteriormente la densita dei dialoghi: 8 commenti attesi per ogni thread generato;
- resa esplicita nei commenti la lettura operativa: cosa e chiuso, cosa resta aperto, cosa va deciso e chi deve aggiornare.

Verifiche:

- `python -m py_compile edilcloud-back-dn/src/edilcloud/modules/projects/management/commands/seed_rich_demo_project.py`
- controllo strutturale AST: 10 fasi, 33 lavorazioni, 7 issue, progressi fase `[100, 100, 100, 86, 64, 72, 68, 48, 18, 4]`, avanzamento progetto 66%, 50 post attesi, 400 commenti attesi.

Note:

- il management command non e' stato eseguito sul DB;
- i 400 commenti sono attesi dalla logica seed, non ancora materializzati in database locale;
- questo rende la demo molto piu vicina a un cantiere usato davvero.

Prossima azione consigliata:

- passare a Fase 4: snapshot/freeze point e reset sicuro del Demo Master.

### 2026-04-12 - Fase 3 rifinita: asset sorgente stabili e report backend

Aggiornati:

- `edilcloud-back-dn/src/edilcloud/modules/projects/demo_master_assets.py`
- `edilcloud-back-dn/src/edilcloud/modules/projects/management/commands/seed_rich_demo_project.py`
- `edilcloud-back-dn/src/edilcloud/modules/projects/management/commands/report_demo_master_assets.py`
- `edilcloud-back-dn/docs/DEMO_ASSET_PIN_MANIFEST.md`
- `edilcloud-back-dn/demo-assets/demo-master/v2026.04/README.md`

Completato:

- introdotta una root sorgente stabile per asset reali: `demo-assets/demo-master/v2026.04/`;
- il seed demo ora cerca prima asset reali in quella root e solo dopo genera fallback placeholder;
- i placeholder visuali generati mostrano codice asset e tipo placeholder, cosi diventano riconoscibili anche a colpo d'occhio;
- separati i sorgenti `photos`, `drawings`, `attachments`, `documents`, `companies`, `avatars`;
- aggiunto comando backend `report_demo_master_assets` per vedere asset correnti, path relativi backend e sorgenti attese;
- resi stabili i memo di coordinamento (`memo-coordinamento-<family>.pdf`) evitando filename dipendenti da `post.id`.

Verifiche:

- `python -m py_compile src/edilcloud/modules/projects/demo_master_assets.py src/edilcloud/modules/projects/management/commands/seed_rich_demo_project.py src/edilcloud/modules/projects/management/commands/report_demo_master_assets.py`
- `PYTHONPATH=src python manage.py help report_demo_master_assets` verificato con successo nel backend locale.

Note:

- il report runtime completo `report_demo_master_assets --format json` in questo ambiente ha superato il timeout disponibile e resta da rieseguire come smoke test applicativo;
- la sostituzione corretta degli asset va fatta nella root sorgente stabile, non inseguendo i path finali legati al `project_id`.

Prossima azione consigliata:

- tornare alla Fase 4: definire snapshot/freeze point versionato e reset sicuro del Demo Master.

### 2026-04-12 - Fase 4 avviata: modello snapshot e comando freeze point

Aggiornati:

- `edilcloud-back-dn/src/edilcloud/modules/projects/models.py`
- `edilcloud-back-dn/src/edilcloud/modules/projects/demo_master_snapshot.py`
- `edilcloud-back-dn/src/edilcloud/modules/projects/management/commands/create_demo_master_snapshot.py`
- `edilcloud-back-dn/src/edilcloud/modules/projects/management/commands/reset_demo_master_project.py`
- `edilcloud-back-dn/src/edilcloud/modules/projects/management/commands/seed_rich_demo_project.py`
- `edilcloud-back-dn/src/edilcloud/modules/projects/migrations/0012_project_demo_snapshot_version_project_is_demo_master_and_more.py`
- `edilcloud-back-dn/docs/DEMO_SNAPSHOT_WORKFLOW.md`

Completato:

- introdotti marker backend sul progetto demo:
  - `is_demo_master`
  - `demo_snapshot_version`
- introdotto modello `DemoProjectSnapshot` con:
  - `version`
  - `business_date`
  - `schema_version`
  - `seed_hash`
  - `asset_manifest_hash`
  - `payload_hash`
  - `validation_status`
  - `active_in_production`
  - `notes`
  - `payload`
- deciso formalmente il formato snapshot ibrido:
  - seed deterministico come base riproducibile;
  - metadata snapshot a DB;
  - export JSON opzionale;
  - asset manifest versionato separato;
- aggiunto comando `create_demo_master_snapshot` per creare/aggiornare un freeze point versionato;
- aggiunto comando `reset_demo_master_project` per ripristinare il Demo Master al seed canonico corrente;
- documentato il workflow snapshot in un file dedicato.

Verifiche:

- `python -m py_compile src/edilcloud/modules/projects/models.py src/edilcloud/modules/projects/demo_master_snapshot.py src/edilcloud/modules/projects/management/commands/create_demo_master_snapshot.py src/edilcloud/modules/projects/management/commands/seed_rich_demo_project.py`
- `PYTHONPATH=src python manage.py help create_demo_master_snapshot`
- `PYTHONPATH=src python manage.py help reset_demo_master_project`
- generata migrazione Django `0012_project_demo_snapshot_version_project_is_demo_master_and_more.py`

Note:

- `makemigrations` ha generato la migrazione corretta ma nel backend locale ha emesso warning di timeout sul controllo della history del database PostgreSQL di default;
- il reset reale da payload snapshot non e' ancora implementato;
- il seed attuale resta il ripristino canonico, mentre lo snapshot e' il primo layer di freeze point/versioning.

Prossima azione consigliata:

- collegare snapshot attivo e reset all'Admin Test Lab, poi introdurre il reset da payload snapshot/versione esplicita.

### 2026-04-12 - Fase 5 avviata: Demo Master dentro l'Admin Test Lab

Aggiornati:

- `edilcloud-back-dn/src/edilcloud/modules/projects/demo_master_admin.py`
- `edilcloud-back-dn/src/edilcloud/modules/projects/api.py`
- `edilcloud-back-dn/src/edilcloud/modules/projects/schemas.py`
- `edilcloud-back-dn/src/edilcloud/modules/projects/management/commands/create_demo_master_snapshot.py`
- `edilcloud-back-dn/src/edilcloud/modules/projects/management/commands/reset_demo_master_project.py`
- `edilcloud-next/src/app/api/admin/demo-master/route.ts`
- `edilcloud-next/src/components/admin/demo-master-control-panel.tsx`
- `edilcloud-next/src/components/admin/admin-diagnostics-lab.tsx`
- `edilcloud-next/src/lib/admin-diagnostics/client.ts`
- `edilcloud-next/src/lib/admin-diagnostics/types.ts`

Completato:

- estratta una logica backend condivisa per stato Demo Master, salvataggio freeze point e reset canonico;
- aggiunti endpoint backend superuser-only per:
  - stato Demo Master;
  - creazione snapshot/freeze point;
  - reset del Demo Master al seed canonico;
- collegati i management command al nuovo layer condiviso;
- aggiunta route Next admin dedicata che normalizza le risposte backend;
- aggiunto pannello `Demo Master` nell'Admin Test Lab con:
  - stato progetto demo;
  - freeze point attivo;
  - snapshot recenti;
  - form per salvare un nuovo freeze point;
  - bottone per ripristinare il seed canonico;
- mantenuto il doppio gating superuser:
  - pagina admin frontend;
  - route Next admin;
  - endpoint backend v3.

Verifiche:

- `python -m py_compile src/edilcloud/modules/projects/demo_master_admin.py src/edilcloud/modules/projects/api.py src/edilcloud/modules/projects/schemas.py src/edilcloud/modules/projects/management/commands/create_demo_master_snapshot.py src/edilcloud/modules/projects/management/commands/reset_demo_master_project.py`
- `npx tsc --noEmit` in `edilcloud-next`

Note:

- il bottone "Ripristina snapshot" inteso come restore da payload/versione specifica non e' ancora presente: oggi il reset riporta il progetto al seed canonico corrente e riaggancia opzionalmente lo snapshot attivo;
- la policy finale di promozione freeze point verso produzione resta ancora da rifinire;
- la sezione scenario-based del Test Lab non e' ancora iniziata.

Prossima azione consigliata:

- implementare il restore da snapshot/versione esplicita, poi aggiungere la suite scenari con atteso/ottenuto per notifiche, permessi e feed.

### 2026-04-12 - Fase 4/Fase 5: restore snapshot versionato end-to-end

Aggiornati:

- `edilcloud-back-dn/src/edilcloud/modules/projects/demo_master_admin.py`
- `edilcloud-back-dn/src/edilcloud/modules/projects/api.py`
- `edilcloud-back-dn/src/edilcloud/modules/projects/schemas.py`
- `edilcloud-back-dn/src/edilcloud/modules/projects/management/commands/restore_demo_master_snapshot.py`
- `edilcloud-next/src/app/api/admin/demo-master/route.ts`
- `edilcloud-next/src/components/admin/demo-master-control-panel.tsx`
- `edilcloud-next/src/lib/admin-diagnostics/types.ts`

Completato:

- introdotto il restore vero di una snapshot specifica del Demo Master;
- il restore ricrea il progetto demo da payload snapshot, non solo dal seed canonico corrente;
- aggiunta esportazione degli asset binari della snapshot in un bundle dedicato, utile per rendere il restore piu' stabile anche quando il master viene ricreato;
- aggiunto endpoint backend superuser-only per il restore da versione;
- aggiunta route Next admin per propagare il restore snapshot;
- aggiunto nel pannello Admin Test Lab:
  - selettore snapshot recenti;
  - bottone `Ripristina snapshot`;
  - riepilogo ultimo restore con conteggi principali e asset mancanti.
- aggiunto management command `restore_demo_master_snapshot`.

Verifiche:

- `python -m py_compile edilcloud-back-dn/src/edilcloud/modules/projects/demo_master_admin.py edilcloud-back-dn/src/edilcloud/modules/projects/api.py edilcloud-back-dn/src/edilcloud/modules/projects/schemas.py edilcloud-back-dn/src/edilcloud/modules/projects/management/commands/restore_demo_master_snapshot.py`
- `PYTHONPATH=src python manage.py help restore_demo_master_snapshot`
- `PYTHONPATH=src python manage.py help create_demo_master_snapshot`
- `npx tsc --noEmit` in `edilcloud-next`

Note:

- il restore e' progettato per essere production-friendly: usa snapshot versionate e un bundle asset dedicato, cosi' il freeze point non dipende solo dallo stato corrente dei file media;
- restano ancora fuori da questo step l'isolamento della demo pubblica e la suite scenari notifiche/permessi.

Prossima azione consigliata:

- avviare la Fase 6 con il primo scenario engine leggibile da admin, iniziando da notifiche, feed e permessi su post/commenti/documenti.

### 2026-04-12 - Fase 6 avviata: readiness suite scenario-based

Aggiornati:

- `edilcloud-back-dn/src/edilcloud/modules/projects/demo_master_admin.py`
- `edilcloud-back-dn/src/edilcloud/modules/projects/api.py`
- `edilcloud-next/src/app/api/admin/demo-master/scenarios/route.ts`
- `edilcloud-next/src/components/admin/demo-master-scenarios-panel.tsx`
- `edilcloud-next/src/components/admin/admin-diagnostics-lab.tsx`
- `edilcloud-next/src/lib/admin-diagnostics/client.ts`
- `edilcloud-next/src/lib/admin-diagnostics/types.ts`

Completato:

- introdotta una prima suite scenari read-only del Demo Master, eseguibile dal Superuser Lab;
- aggiunto backend report con scenari strutturati e `atteso / osservato` per:
  - triage issue aperte;
  - loop menzioni e risposte;
  - revisione documenti e allegati;
  - matrice permessi e ruoli;
- aggiunto endpoint backend superuser-only per i report scenario-based;
- aggiunta route Next dedicata alla normalizzazione del report scenari;
- aggiunto pannello UI dedicato nel lab admin con:
  - bottone di esecuzione;
  - riepilogo pass / warn / fail;
  - cards scenario con prerequisiti, atteso, osservato, notifiche, feed e permessi.

Verifiche:

- `python -m py_compile edilcloud-back-dn/src/edilcloud/modules/projects/demo_master_admin.py edilcloud-back-dn/src/edilcloud/modules/projects/api.py`
- `npx tsc --noEmit` in `edilcloud-next`

Note:

- questa prima suite misura la readiness del Demo Master; non genera ancora eventi reali e non sostituisce la futura suite con azioni e cleanup scenario per scenario;
- la fase successiva dovra' trasformare questi scenari in prove operative con attori, azioni, risultato atteso e controllo delle notifiche realmente emesse.

Prossima azione consigliata:

- introdurre il primo scenario attivo end-to-end, partendo da `menzione in post operativo` con verifica di feed, notifica e visibilita' per attore.

### 2026-04-12 - Fase 6: primo scenario attivo end-to-end

Aggiornati:

- `edilcloud-back-dn/src/edilcloud/modules/projects/demo_master_admin.py`
- `edilcloud-back-dn/src/edilcloud/modules/projects/api.py`
- `edilcloud-back-dn/src/edilcloud/modules/projects/schemas.py`
- `edilcloud-next/src/app/api/admin/demo-master/scenarios/run/route.ts`
- `edilcloud-next/src/components/admin/demo-master-scenarios-panel.tsx`
- `edilcloud-next/src/lib/admin-diagnostics/client.ts`
- `edilcloud-next/src/lib/admin-diagnostics/types.ts`

Completato:

- introdotto un runner backend per scenari attivi del Demo Master;
- implementato il primo scenario reale `mention_post`;
- lo scenario:
  - crea un post operativo reale sul Demo Master;
  - menziona un membro attivo del progetto;
  - verifica la notifica di menzione;
  - verifica l'assenza di self-notification per l'attore;
  - verifica la presenza del post nel feed del destinatario come non letto;
  - verifica il blocco accesso per un profilo outsider demo;
  - esegue cleanup di post e notifiche di test;
- aggiunto endpoint backend superuser-only per eseguire scenari attivi;
- aggiunta route Next dedicata all'esecuzione del runner scenario;
- esteso il pannello `Scenario Engine` con una sezione per il primo test attivo end-to-end.

Verifiche:

- `python -m py_compile edilcloud-back-dn/src/edilcloud/modules/projects/demo_master_admin.py edilcloud-back-dn/src/edilcloud/modules/projects/api.py edilcloud-back-dn/src/edilcloud/modules/projects/schemas.py`
- `npx tsc --noEmit` in `edilcloud-next`

Note:

- questo scenario usa i servizi reali di feed e notifiche, quindi testa davvero il comportamento dell'applicazione e non solo una simulazione di stato;
- il cleanup e' mirato al `post_id` generato dal test per non sporcare il Demo Master.

Prossima azione consigliata:

- implementare il secondo scenario attivo `menzione in segnalazione critica`, cosi' possiamo confrontare il ramo `project.mention.issue` con il ramo standard `project.mention.post`.

### 2026-04-12 - Media optimization backend

Aggiornati:

- `edilcloud-back-dn/src/edilcloud/modules/files/media_optimizer.py`
- `edilcloud-back-dn/src/edilcloud/modules/projects/services.py`
- `edilcloud-back-dn/src/edilcloud/modules/identity/services.py`
- `edilcloud-back-dn/src/edilcloud/modules/workspaces/services.py`
- `edilcloud-back-dn/src/edilcloud/modules/projects/demo_master_admin.py`
- `edilcloud-back-dn/src/edilcloud/modules/projects/management/commands/seed_rich_demo_project.py`
- `edilcloud-back-dn/src/edilcloud/settings/base.py`
- `edilcloud-back-dn/pyproject.toml`
- `edilcloud-back-dn/Dockerfile`
- `edilcloud-back-dn/tests/test_media_optimizer.py`

Completato:

- introdotta una pipeline backend unica per ottimizzare media prima del salvataggio;
- immagini raster ottimizzate in modo conservativo:
  - JPEG progressivo con `optimize`;
  - PNG ottimizzato;
  - WEBP lossless quando conviene;
  - nessuna sostituzione se il file finale non e' piu piccolo;
- audio raw (`wav`, `aiff`) convertito in `flac` lossless quando `ffmpeg` e' disponibile;
- video gestito con modalita' sicura lato backend:
  - `mp4/mov/m4v` con `faststart` quando conviene;
  - modalita' `transparent` predisposta via env per transcode visivamente trasparente;
- integrazione attiva su:
  - allegati post/commenti;
  - documenti progetto;
  - onboarding avatar;
  - avatar profilo workspace da URL remoto;
  - logo workspace in creazione;
  - asset demo master, restore snapshot e reseed.

Verifiche:

- `python -m py_compile ...` sui file backend toccati
- `.\venv\Scripts\python.exe -m pytest edilcloud-back-dn\tests\test_media_optimizer.py`
- `.\venv\Scripts\python.exe -m pytest edilcloud-back-dn\tests\test_identity_api.py -k "photo or picture or avatar"`
- `.\venv\Scripts\python.exe -m pytest edilcloud-back-dn\tests\test_workspaces_api.py -k "avatar or photo"`
- smoke audio lossless dentro Docker con `ffmpeg` attivo
- `docker compose -f edilcloud-back-dn\docker-compose.yml exec -T web python manage.py seed_rich_demo_project`

Note:

- compressione "drastica senza alcuna perdita" non e' fisicamente ottenibile per tutti i video/audio gia' compressi; per questo il default backend resta conservativo e non sostituisce mai il file se il risultato non migliora davvero;
- il path per una compressione video piu aggressiva ma visivamente trasparente e' gia' predisposto con `MEDIA_VIDEO_TRANSCODE_MODE=transparent`.

### 2026-04-12 - Demo palette aziende fissata

Aggiornati:

- `edilcloud-back-dn/src/edilcloud/modules/projects/management/commands/seed_rich_demo_project.py`
- `edilcloud-back-dn/docs/DEMO_TESTER_ROADMAP.md`

Completato:

- introdotta una palette fissa e sobria per le aziende del Demo Master;
- i `ProjectCompanyColor` del demo vengono ora creati dal seed con valori canonici, invece di nascere lazily dal primo contesto aperto;
- applicata la stessa palette anche al progetto demo attuale in database, senza ricrearlo.

Palette corrente:

- `studio` -> `#51606f`
- `gc` -> `#2e6f65`
- `strutture` -> `#3f5f8a`
- `elettrico` -> `#2b7a91`
- `meccanico` -> `#9a6536`
- `serramenti` -> `#6a6487`
- `finiture` -> `#9a5668`
- `committente` -> `#6a7352`
- `demo-access` -> `#4b5563`

### 2026-04-12 - Production sync Demo Master

Aggiornati:

- `edilcloud-back-dn/.github/workflows/deploy-production.yml`
- `edilcloud-back-dn/Dockerfile`
- `edilcloud-back-dn/src/edilcloud/modules/projects/demo_master_snapshot.py`
- `edilcloud-back-dn/tests/test_projects_demo_seed.py`
- `edilcloud-back-dn/demo-assets/demo-master/snapshots/v2026.04-freeze01.json`
- `edilcloud-back-dn/docs/DEMO_TESTER_ROADMAP.md`

Completato:

- corretto il payload snapshot del Demo Master, ora JSON-serializable anche con `date` e `datetime`;
- creato il freeze point `v2026.04-freeze01` del demo corrente;
- il Dockerfile backend include ora `demo-assets` e `docs`, cosi' il runtime production ha accesso agli asset/demo metadata necessari;
- il deploy production backend esegue automaticamente `reset_demo_master_project` a fine rilascio, cosi' il Demo Master viene ricreato sul DB production in modo coerente al codice pushato.

Verifiche:

- `docker compose exec -T web python manage.py create_demo_master_snapshot --snapshot-version v2026.04-freeze01 --business-date 2026-04-12 --created-by-email laura.ferretti@ferretti-associati.it --notes "Freeze point production deploy 2026-04-12" --validate --activate --write-json`
- `..\venv\Scripts\python.exe -m pytest -q tests/test_projects_demo_seed.py tests/test_media_optimizer.py`
- `docker compose exec -T web python manage.py check`

### 2026-04-13 - Superuser auto-access al workspace demo

Aggiornati:

- `edilcloud-back-dn/src/edilcloud/modules/projects/management/commands/seed_rich_demo_project.py`
- `edilcloud-back-dn/src/edilcloud/modules/projects/demo_master_admin.py`
- `edilcloud-back-dn/tests/test_projects_demo_seed.py`
- `edilcloud-back-dn/docs/DEMO_TESTER_ROADMAP.md`

Completato:

- i superuser attivi vengono ora materializzati automaticamente anche nel workspace canonico del Demo Master;
- durante seed e restore snapshot il superuser riceve un profilo attivo nel workspace del demo con ruolo `owner`;
- il superuser viene poi aggiunto anche come `ProjectMember`, cosi' vede davvero il doppio workspace e non dipende dal viewer fittizio `demo.viewer@edilcloud.local`.

Verifiche:

- `..\venv\Scripts\python.exe -m pytest -q tests/test_projects_demo_seed.py`
