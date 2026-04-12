# Demo Master Canonico

Ultimo aggiornamento: 2026-04-12

Questo documento definisce la mappa canonica del progetto demo EdilCloud.

La specifica deve guidare:

- seed backend;
- Admin Test Lab;
- playground pubblico senza iscrizione;
- snapshot/freeze point;
- asset reali forniti per demo commerciali;
- scenari di test per notifiche, permessi, feed, realtime, documenti, Gantt, tavole e AI.

## Vincolo production-first

Il Demo Master deve funzionare anche in produzione.

Questo cambia le regole:

- nessuna funzione critica deve dipendere solo da dati fake in memoria Next;
- nessun visitatore pubblico deve poter modificare il Demo Master;
- ogni sessione demo pubblica deve essere isolata;
- ogni reset deve essere limitato a oggetti marcati come demo;
- ogni comando distruttivo deve essere superuser-only e protetto da conferma;
- ogni asset deve avere fallback e validazione;
- AI, realtime e notifiche devono avere limiti e guardrail;
- il cleanup delle sessioni demo deve essere automatico;
- i log devono permettere di capire chi ha generato cosa.

In produzione devono esistere tre livelli distinti:

1. Demo Master
   Stato canonico, curato da superuser, non modificabile dai visitatori.

2. Demo Session
   Copia o overlay temporaneo associato a un visitatore o a una demo commerciale.

3. Admin Test Run
   Esecuzione temporanea e controllata di scenari di test, con cleanup e report.

## Fonte canonica

Decisione: il backend deve diventare la fonte canonica.

Il seed attuale in:

`src/edilcloud/modules/projects/management/commands/seed_rich_demo_project.py`

deve evolvere in Demo Master ufficiale.

La demo frontend in:

`edilcloud-next/src/lib/demo-project`

resta utile come fonte narrativa e come riferimento per:

- 10 fasi operative;
- disegni SVG;
- assistant demo locale;
- conversazioni piu ricche;
- pin locali sulle tavole;
- asset demo generati.

Ma non deve restare la verita definitiva.

## Identita del progetto

Nome canonico:

`Residenza Parco Naviglio - Lotto A`

Descrizione breve:

Nuova costruzione residenziale di 5 piani con 14 unita abitative, autorimessa interrata, corte interna, impianti integrati, facciata ventilata, finiture campione e consegna progressiva.

Tesi narrativa:

Un cantiere multi-azienda in fase avanzata, con involucro quasi chiuso, impianti in coordinamento, finiture avviate, collaudi in avvicinamento e alcune criticita operative aperte.

Perche funziona in demo:

- ci sono lavorazioni gia chiuse, quindi storico e prove;
- ci sono lavorazioni in corso, quindi feed e comunicazioni vive;
- ci sono criticita aperte, quindi alert e responsabilita;
- ci sono documenti e tavole, quindi ricerca e AI hanno materiale;
- ci sono ruoli diversi, quindi permessi e notifiche hanno senso.

Date canoniche:

- data inizio: 2025-08-01;
- data fine prevista: 2026-04-30;
- data narrativa demo: mobile rispetto alla data corrente o congelata su snapshot.

Decisione consigliata:

- il seed deve restare temporalmente mobile per ambienti dev/test;
- lo snapshot production demo deve salvare una `demo_business_date` esplicita;
- UI demo e report devono mostrare date coerenti con lo snapshot attivo.

## Aziende canoniche

Il Demo Master deve avere 8 aziende.

| Codice | Azienda | Ruolo narrativo | Tipo |
| --- | --- | --- | --- |
| `studio` | Studio Tecnico Ferretti Associati | Direzione lavori, BIM, sicurezza | studio tecnico |
| `gc` | Aurora Costruzioni Generali | Impresa affidataria e general contractor | impresa generale |
| `strutture` | Strutture Nord Calcestruzzi | Strutture, fondazioni, solai | impresa esecutrice |
| `elettrico` | Elettroimpianti Lombardi | Elettrico, dati, sicurezza | impresa specialistica |
| `meccanico` | Idrotermica Futura | HVAC, idrico, antincendio | impresa specialistica |
| `serramenti` | Serramenti Milano Contract | Serramenti, controtelai, nastri, facciata | impresa specialistica |
| `finiture` | Interni Bianchi Srl | Cartongessi, massetti, bagni, finiture | impresa esecutrice |
| `committente` | Immobiliare Naviglio Srl | Committente/developer | owner |

Nota di migrazione:

- oggi backend ha `Facciate e Interni Bianchi`;
- in Fase 2 va deciso se rinominarla in `Interni Bianchi Srl` e spostare serramenti/facciata nella nuova `Serramenti Milano Contract`.

Decisione consigliata:

- separare serramenti/facciata da finiture, perche produce piu conflitti realistici: quote fori, nastri, controtelai, campionature, facciata, finiture interne.

## Persone canoniche

### Studio Tecnico Ferretti Associati

| Codice | Persona | Posizione | Workspace role | Project role codes |
| --- | --- | --- | --- | --- |
| `laura-ferretti` | Laura Ferretti | Direzione lavori | owner | `responsabile_lavori`, `cse` |
| `davide-sala` | Davide Sala | BIM coordinator | manager | `csp` |
| `serena-costantini` | Serena Costantini | Coordinatrice sicurezza | delegate | `rspp` |
| `fabio-conti` | Fabio Conti | Assistente DL | worker | `lavoratore` |

### Aurora Costruzioni Generali

| Codice | Persona | Posizione | Workspace role | Project role codes |
| --- | --- | --- | --- | --- |
| `marco-rinaldi` | Marco Rinaldi | Project manager | owner | `datore_lavoro` |
| `luca-gatti` | Luca Gatti | Capocantiere | manager | `preposto`, `addetto_primo_soccorso` |
| `omar-elidrissi` | Omar El Idrissi | Caposquadra opere edili | delegate | `preposto` |
| `enrico-vitali` | Enrico Vitali | Gruista | worker | `lavoratore` |
| `samuele-rota` | Samuele Rota | Operaio specializzato | worker | `lavoratore`, `addetto_antincendio_emergenza` |

### Strutture Nord Calcestruzzi

| Codice | Persona | Posizione | Workspace role | Project role codes |
| --- | --- | --- | --- | --- |
| `elisa-brambilla` | Elisa Brambilla | Responsabile strutture | owner | `datore_lavoro` |
| `giorgio-bellini` | Giorgio Bellini | Caposquadra carpentieri | manager | `preposto` |
| `cristian-pavan` | Cristian Pavan | Ferrista | worker | `lavoratore` |
| `ionut-marin` | Ionut Marin | Operatore betonpompa | worker | `lavoratore` |
| `bogdan-muresan` | Bogdan Muresan | Carpentiere casseri | worker | `lavoratore` |

### Elettroimpianti Lombardi

| Codice | Persona | Posizione | Workspace role | Project role codes |
| --- | --- | --- | --- | --- |
| `paolo-longhi` | Paolo Longhi | Capo commessa elettrico | owner | `datore_lavoro` |
| `andrea-fontana` | Andrea Fontana | Caposquadra impianti elettrici | manager | `preposto` |
| `nicolas-moretti` | Nicolas Moretti | Impiantista | worker | `lavoratore` |
| `marius-dumitru` | Marius Dumitru | Tiracavi | worker | `lavoratore` |
| `matteo-cerri` | Matteo Cerri | Special systems | delegate | `addetto_antincendio_emergenza` |

### Idrotermica Futura

| Codice | Persona | Posizione | Workspace role | Project role codes |
| --- | --- | --- | --- | --- |
| `giulia-roversi` | Giulia Roversi | Project manager HVAC | owner | `datore_lavoro` |
| `stefano-riva` | Stefano Riva | Caposquadra idraulico | manager | `preposto` |
| `ahmed-bensalem` | Ahmed Bensalem | Canalista | worker | `lavoratore` |
| `filippo-orsenigo` | Filippo Orsenigo | Frigorista | delegate | `lavoratore` |
| `rachid-ziani` | Rachid Ziani | Tubista | worker | `lavoratore` |

### Serramenti Milano Contract

| Codice | Persona | Posizione | Workspace role | Project role codes |
| --- | --- | --- | --- | --- |
| `martina-cattaneo` | Martina Cattaneo | Responsabile commessa serramenti | owner | `datore_lavoro` |
| `davide-pini` | Davide Pini | Caposquadra posa serramenti | manager | `preposto` |
| `cosmin-petrescu` | Cosmin Petrescu | Posatore serramenti | worker | `lavoratore` |
| `ivan-russo` | Ivan Russo | Addetto sigillature e nastri | worker | `lavoratore` |

### Interni Bianchi Srl

| Codice | Persona | Posizione | Workspace role | Project role codes |
| --- | --- | --- | --- | --- |
| `marta-bianchi` | Marta Bianchi | Responsabile finiture | owner | `datore_lavoro` |
| `antonio-esposito` | Antonio Esposito | Caposquadra pavimenti e bagni | manager | `preposto` |
| `sofia-mancini` | Sofia Mancini | Tecnica finiture | delegate | `lavoratore` |
| `lorenzo-gallo` | Lorenzo Gallo | Cartongessista | worker | `lavoratore` |
| `alina-popescu` | Alina Popescu | Pittura e rasature | worker | `lavoratore` |

### Immobiliare Naviglio Srl

| Codice | Persona | Posizione | Workspace role | Project role codes |
| --- | --- | --- | --- | --- |
| `valentina-neri` | Valentina Neri | Development manager | owner | `committente` |
| `riccardo-greco` | Riccardo Greco | Property operations | manager | `committente` |
| `elena-motta` | Elena Motta | Customer handover | delegate | `committente` |

## Personas demo

Queste sono le persone da aprire velocemente nel playground e nell'Admin Test Lab.

| Persona | Profilo | Cosa deve mostrare |
| --- | --- | --- |
| Laura Ferretti | Direzione lavori | overview, alert, issue, documenti, chiusure |
| Marco Rinaldi | Impresa generale | feed operativo, coordinamento multi-azienda |
| Luca Gatti | Capocantiere | attivita, post, foto, commenti, risposte |
| Paolo Longhi | Impiantista elettrico | task assegnati, notifiche mirate, documenti tecnici |
| Giulia Roversi | Meccanico/HVAC | criticita collaudi, prerequisiti e allegati |
| Martina Cattaneo | Serramenti | fuori quota, tavole facciata, pin |
| Antonio Esposito | Finiture | bagno campione, foto prove, punch list |
| Valentina Neri | Committente | vista controllata, stato avanzamento, documenti approvati |

## Fasi operative canoniche

Il Demo Master deve avere 10 fasi.

Avanzamento canonico:

- target demo/homepage/feed: 66%;
- calcolo backend attuale: media aritmetica dei progressi delle 10 fasi operative;
- formula seed: `(100 + 100 + 100 + 86 + 64 + 72 + 68 + 48 + 18 + 4) / 10 = 66`;
- lettura narrativa: 3 fasi chiuse, 5 fasi in corso con criticita e coordinamento, 2 fasi in avvio/future;
- le lavorazioni interne mantengono stato proprio: chiuse, in corso o pianificate, con progress operativo coerente.

| Codice | Fase | Azienda guida | Stato narrativo | Perche serve in demo |
| --- | --- | --- | --- | --- |
| `avvio-logistica` | Avvio cantiere e logistica operativa | Aurora | chiusa | storico, sicurezza, documenti iniziali |
| `scavi-fondazioni` | Scavi, opere geotecniche e fondazioni | Strutture Nord | chiusa | issue risolte, prove, allegati tecnici |
| `strutture` | Strutture verticali, solai e vani scala | Strutture Nord | chiusa | avanzamento e memoria tecnica |
| `involucro` | Tamponamenti, copertura e impermeabilizzazioni | Aurora | in corso avanzato | alert impermeabilizzazione, foto e meteo |
| `serramenti-facciata` | Facciata ventilata e serramenti esterni | Serramenti Milano | in corso | quote foro, tavole, pin, issue aperta |
| `meccanico` | Impianto meccanico, idrico e antincendio | Idrotermica | in corso | prerequisiti collaudi, valvole, VMC |
| `elettrico` | Impianto elettrico, dati e sistemi sicurezza | Elettroimpianti | in corso | quadri, linee speciali, sistemi sicurezza |
| `interni` | Partizioni interne, massetti e controsoffitti | Interni Bianchi | in corso | foto prima chiusura, quote, coordinamento |
| `finiture` | Finiture interne, arredi fissi e pre-collaudi | Interni Bianchi | avvio | bagno campione, punch list, committente |
| `consegna` | Collaudi integrati, documentazione finale e consegna | Studio Ferretti | critica | AI, documenti, as-built, alert finale |

## Criticita narrative minime

Il Demo Master deve avere criticita aperte e risolte.

### Aperte

- fuori quota foro cucina unita 2B;
- valvole di bilanciamento centrale termica non consegnate;
- scostamento quota massetto unita 1A e 3C;
- prerequisiti incompleti per pre-collaudo VMC e antincendio;
- conferma posizione monitor citofonico hall.

### Risolte

- interferenza passaggi impiantistici box 03-04;
- nodo risvolto ovest copertura;
- riallineamento linee speciali quadro Q3;
- controllo armature platea settore est;
- mockup facciata approvato.

## Documenti canonici

Minimo iniziale per seed backend:

- cronoprogramma generale lotto A;
- PSC aggiornato;
- POS/verbale briefing avvio;
- verbale coordinamento impianti settimana 14;
- scheda mockup facciata e serramenti;
- rilievo foro cucina 2B;
- checklist valvole bilanciamento;
- verifica quote massetti 1A-3C;
- piano collaudi integrati;
- registro criticita aprile;
- punch list parti comuni;
- pacchetto as-built preliminare;
- fascicolo manutenzione preliminare;
- verbale prova tenuta copertura;
- schema aggiornato quadro Q3.

## Tavole canoniche

Minimo iniziale:

- AR-101 Pianta piano terra e corte interna;
- AR-205 Piante tipo alloggi 1A/2B/3C;
- ST-204 Platea e setti interrati;
- FA-301 Facciata sud-ovest;
- FA-312 Nodo serramento e davanzale;
- IM-220 Centrale termica e dorsali;
- IM-245 VMC corridoi e bagni;
- EL-240 Quadri di piano e dorsali FM;
- EL-260 Sistemi speciali e citofonia;
- FN-110 Bagno campione 2B.

## Pin canonici sulle tavole

I pin devono diventare parte dello snapshot, non solo localStorage.

Pin minimi:

- foro cucina 2B su FA-312;
- nodo copertura ovest su FA-301;
- valvole centrale termica su IM-220;
- VMC corridoio nord su IM-245;
- quadro Q3 su EL-240;
- monitor citofonico hall su EL-260;
- massetto unita 1A su AR-205;
- massetto unita 3C su AR-205;
- bagno campione 2B su FN-110;
- passaggi platea box 03-04 su ST-204.

Ogni pin deve avere:

- tavola;
- coordinate percentuali;
- titolo;
- post collegato;
- task/attivita collegata;
- stato: aperto, risolto, informativo;
- eventuale documento collegato.

## Media canonici

Minimo iniziale:

- 20 foto cantiere;
- 5 tavole/disegni;
- 3 audio brevi;
- 2 video brevi;
- 15 documenti;
- loghi per 8 aziende;
- avatar per personas principali.

Fino a quando Antonio non fornisce gli asset reali, il seed deve generare fallback coerenti.

In produzione gli asset reali devono essere gestiti come asset demo versionati, non come file casuali caricati a mano.

## Densita conversazioni

La demo non deve sembrare un seed vuoto. Ogni fase e ogni lavorazione devono avere dialoghi abbondanti e verosimili:

- post di kickoff fase con memo PDF di coordinamento;
- post operativo per ogni lavorazione;
- issue dedicate per criticita aperte e risolte;
- almeno 8 commenti per thread generato;
- risposte annidate tra DL, referente impresa, stakeholder, tecnico di controllo e figura di campo;
- messaggi che dichiarano chiaramente se fase/lavorazione e chiusa, aperta, in corso o pianificata;
- allegati nei thread dove ha senso: rilievi, verbali, checklist, memo, foto o tavole fallback;
- testo utile per demo, feed, ricerca e assistant, non frasi riempitive.

## Scenari demo commerciali

### Scenario A - Briefing operativo

Attore: Laura Ferretti.

Flusso:

1. apre dashboard/overview;
2. vede 3 criticita aperte;
3. entra nel thread foro cucina 2B;
4. apre tavola collegata;
5. vede pin e documento di rilievo;
6. chiede all'AI un riepilogo dei punti aperti.

Valore mostrato:

- EdilCloud riduce il tempo per capire cosa richiede attenzione.

### Scenario B - Field-to-office

Attore: Luca Gatti.

Flusso:

1. apre attivita impermeabilizzazione;
2. carica foto o video;
3. commenta la situazione;
4. la DL riceve notifica;
5. il feed risale in cima.

Valore mostrato:

- cio che succede in campo entra subito nel contesto operativo.

### Scenario C - Documento come prova

Attore: Davide Sala.

Flusso:

1. cerca "foro cucina 2B";
2. trova documento, tavola e thread;
3. apre il documento;
4. vede il collegamento con issue e commenti;
5. l'AI usa le stesse fonti.

Valore mostrato:

- documenti, thread e AI condividono la stessa memoria di progetto.

### Scenario D - Permessi e committente

Attore: Valentina Neri.

Flusso:

1. entra come committente;
2. vede stato, documenti approvati e avanzamento;
3. non vede thread interni non pubblici;
4. apre punch list e prossime consegne.

Valore mostrato:

- collaborazione con cliente senza perdere controllo.

## Scenari tester minimi

Questi scenari devono poi diventare test automatici o semi-automatici.

| Scenario | Attore | Azione | Atteso |
| --- | --- | --- | --- |
| `notification.issue.created` | Marco | apre issue critica | Laura e team ricevono notifica, actor escluso |
| `notification.mention.post` | Luca | menziona Laura in post | Laura riceve menzione, deep link al thread |
| `notification.comment.reply` | Laura | risponde a commento Marco | Marco riceve reply |
| `permission.worker.edit` | Operaio | modifica post non suo | bloccato |
| `permission.manager.edit` | Manager | modifica task azienda | consentito se ruolo valido |
| `document.created` | Davide | carica documento | feed, notifica, ricerca aggiornati |
| `issue.resolved` | Laura | chiude issue | alert count cala, notifica risoluzione |
| `drawing.pin.open` | Martina | apre pin foro 2B | thread corretto aperto |
| `assistant.sources` | Laura | chiede punti aperti | risposta con fonti demo |
| `realtime.feed` | Luca | pubblica update | secondo client riceve refresh |

## Requisiti production per tester

Admin Test Lab in produzione deve rispettare queste regole:

- accessibile solo a superuser;
- API admin protette anche lato backend/proxy;
- nessun test deve toccare progetti reali non demo;
- ogni oggetto creato dai test deve avere prefisso o metadata riconoscibile;
- ogni test di mutazione deve avere cleanup;
- le mutazioni distruttive devono essere limitate alla sessione test o a oggetti temporanei;
- i report devono includere `scenario_id`, `actor`, `target`, `expected`, `actual`;
- i test AI devono avere budget e fallback;
- i test realtime devono poter essere saltati se il canale non e' disponibile, ma devono segnalarlo;
- ogni failure deve essere leggibile anche da non sviluppatore.

## Requisiti production per playground

Playground pubblico:

- non deve richiedere iscrizione;
- deve creare una demo session isolata;
- deve impedire accesso a dati non demo;
- deve avere rate limit;
- deve avere TTL;
- deve avere cleanup automatico;
- deve avere modal o banner che spiega che e' una copia demo;
- deve permettere reset manuale;
- deve permettere cambio persona solo tra personas demo autorizzate;
- non deve inviare email reali a utenti esterni;
- non deve generare notifiche verso profili reali;
- deve poter essere disattivato con feature flag.

## Modello snapshot consigliato

Approccio ibrido:

- seed deterministico nel codice come fonte riproducibile;
- snapshot metadata salvato a DB;
- asset manifest versionato;
- export JSON opzionale per confronti e validazioni;
- clone sessione demo generato dal master o da snapshot.

Campi minimi snapshot:

- `snapshot_id`;
- `version`;
- `name`;
- `business_date`;
- `schema_version`;
- `seed_hash`;
- `asset_manifest_hash`;
- `created_by`;
- `created_at`;
- `validated_at`;
- `validation_status`;
- `active_in_production`;
- `notes`.

## Prossima implementazione consigliata

Sequenza operativa immediata:

1. aggiornare il seed backend con 8 aziende e persone canoniche;
2. aggiungere `project_role_codes` nel seed;
3. portare le 10 fasi canoniche nel seed backend;
4. aumentare documenti e tavole nel seed;
5. aggiungere dati minimi per pin canonici, anche se prima solo come manifest;
6. introdurre marker demo/snapshot senza ancora costruire tutto il clone runtime;
7. aggiornare Admin Test Lab per riconoscere il progetto demo canonico.

## Cose da non fare adesso

- non costruire subito il playground pubblico prima di aver reso canonico il Demo Master;
- non lasciare il fake store frontend come fonte principale;
- non introdurre reset production senza guardrail;
- non collegare email reali alla demo pubblica;
- non testare notifiche solo controllando che `/api/notifications` risponda.
