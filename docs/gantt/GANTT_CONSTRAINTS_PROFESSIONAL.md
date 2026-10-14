# Gantt professionale: vincoli, importazione e rischi

Data: 14 ottobre 2026. Stato: implementazione e regressione completate; verifica della distribuzione in corso.

## Baseline recuperabile

Il goal precedente è concluso. Prima di modificare codice sono state create copie ZIP dei sorgenti Git dei tre repository in `.dev-logs/gantt-professional-20261014/baseline/`. Il manifest contiene commit, dimensioni e SHA-256. Riferimenti:

| Repository | Commit conservato |
| --- | --- |
| Backend | `9a75dddb37ed1d2d2ceaaf09110f304d5f7aed3e` |
| Web | `2212ab0b09e3669cbdbdd0e76fc7ad49ec9add65` |
| Flutter | `a5207e046334c68d179e600c4a62eef2b0b4bc20` |

La nuova versione deve aggiungere strumenti al Gantt moderno, conservando meteo, demo, drawer, performance, autorizzazioni e terminologia del goal precedente.

## Risultato dell'ispezione iniziale

Il backend ha collegamenti fine-inizio, inizio-inizio, fine-fine e inizio-fine, controlli contro cicli espliciti e propagazione dei ritardi. Sono funzionalità reali, ma non costituiscono ancora una pianificazione equivalente a Microsoft Project.

Problemi verificati nel codice precedente:

1. MPP e XML leggono date, avanzamento e predecessori, ma non conservano vincolo di data, data del vincolo, scadenza, modalità manuale, calendario, milestone o baseline.
2. I lag sono arrotondati a giorni interi; ore, frazioni, unità lavorative/trascorse e percentuali possono perdere significato.
3. Nell'XML, il tipo di relazione `0` (fine-fine) passa attraverso `raw_type or 1` e diventa erroneamente fine-inizio.
4. I predecessori delle attività riepilogative sono saltati. Le sottofasi vengono appiattite sulla fase superiore: non è corretto attribuire alla fase superiore il significato di tutti i vincoli delle sottofasi.
5. L'applicazione dell'importazione ignora alcuni errori di collegamento e riporta il numero teorico di relazioni invece di quello realmente creato.
6. Il ricalcolo corrente usa giorni di calendario, soltanto spostamenti in avanti e una convenzione fine-inizio di giorno successivo; non calcola CPM, margini o un piano a ritroso.
7. La sostituzione elimina task esistenti tramite cascade: va protetto il lavoro operativo già collegato al piano.

## Semantica da rispettare

Vincoli di data e dipendenze sono concetti distinti. Occorre conservare gli otto tipi: ASAP, ALAP, SNET, SNLT, FNET, FNLT, MSO e MFO. I sei tipi legati a una data devono avere la data; una scadenza è un indicatore separato, non un vincolo rigido. L'interfaccia deve mostrare nome comprensibile, tipo, data e conseguenze. [Microsoft: tipi di vincolo](https://support.microsoft.com/en-us/project/constraint-type-task-field), [definizioni matematiche](https://learn.microsoft.com/en-us/office/troubleshoot/project/definition-of-project-constraints).

Calendari lavorativi, orari ed eccezioni incidono sulle date. Una durata lavorativa non coincide con la stessa durata trascorsa. Le informazioni originali devono restare recuperabili, senza conversioni silenziose. [MPXJ: calendari](https://www.mpxj.org/howto-use-calendars/).

La libreria MPXJ già installata dispone di `MicrosoftScheduler`, un motore CPM che cerca di riprodurre il comportamento di Project. Non garantisce identità dei risultati. Il suo calcolo parte dalla data di inizio e non include livellamento delle risorse; attività suddivise, ricorrenti e riepiloghi con vincoli richiedono particolare cautela. La nuova versione deve distinguere conservazione del file, rappresentazione operativa e ricalcolo verificabile. [MPXJ: motore CPM e limiti](https://www.mpxj.org/howto-use-cpm/), [campi letti dai formati MPP](https://www.mpxj.org/mpp-field-guide/).

## Strategia della nuova versione

- Conservare file originale, impronta e rappresentazione Microsoft Project XML, oltre ai dati operativi EdilCloud. Mantenere gerarchia e riferimenti originali per l'ispezione completa.
- Rendere espliciti i vincoli di data e i dettagli delle dipendenze; mostrare registro dei vincoli, scadenze, calendario, origine e conflitti sul Gantt.
- Separare simulazione e applicazione del ricalcolo. Una simulazione non deve modificare il cantiere; applicare soltanto un risultato ancora corrispondente alla revisione corrente, con backup delle date e delle regole precedenti.
- Non promuovere a ricalcolo affidabile un piano contenente funzionalità non supportate. Conservare tali dati, spiegare il limite e bloccare l'applicazione quando la fedeltà non è verificabile.
- Condividere lo stesso contratto backend tra web e APK; caricare i dettagli di pianificazione quando si apre la relativa vista, evitando di gonfiare feed e avvio.

## Dati per la futura AI

L'AI dovrà ricevere evidenze strutturate: identificatori stabili, grafo dei predecessori, tipo e data del vincolo, calendario e unità del lag, date previste/effettive/originali, scadenze, margini e criticità con provenienza del calcolo. Ogni rischio deve riportare attività coinvolte, relazione o regola che lo produce, scarto temporale e livello di affidabilità. I risultati del motore deterministico sono verificabili; l'AI potrà interpretarli e proporre alternative, senza riscrivere autonomamente il piano.

## Verifiche previste

Importazione MPP reale e XML con tutti gli otto vincoli; relazione FF numerica zero; lag negativi e frazionari; riepiloghi e calendari; conflitti tra vincoli rigidi e predecessori; scadenze separate; permessi; simulazione senza scritture; rifiuto di revisioni obsolete; recupero della baseline; osservazione delle schermate web e Flutter.

## Versione implementata

Il comando **Piano e vincoli** apre una vista dedicata sia nel web sia nell'app Flutter. Il backend e le regole sono condivisi. Le quattro sezioni sono Vincoli, Gantt completo, Segnalazioni e Versioni. Il caricamento è su richiesta: i dati di pianificazione non vengono aggiunti al feed o al normale avvio dell'app.

Sono disponibili gli otto vincoli di data, scadenze separate, modalità manuale/automatica, date effettive e durate eseguite/residue. Le dipendenze FS, SS, FF e SF conservano tipo, segno, frazioni e unità: giorni, ore, minuti lavorativi o trascorsi e percentuale della durata del predecessore. I riepiloghi originali e i loro collegamenti rimangono identificabili anche quando non coincidono con le due dimensioni operative fase/lavorazione di EdilCloud.

MPP e Microsoft Project XML conservano il file originale, SHA-256, gerarchia, UID, calendari ed eccezioni e metadati di pianificazione. Il file originale è in storage privato, persistente nei container, scaricabile soltanto con autenticazione e permesso di modifica del cantiere. La sostituzione di un piano viene rifiutata quando eliminerebbe lavorazioni con post o avanzamenti.

La simulazione usa MPXJ 16.1.0 in un processo isolato, con limite di memoria e tempo. Non scrive sul database. Mostra le date proposte, percorso critico/margini e conflitti. L'applicazione ricalcola sul server, verifica nuovamente la revisione e conserva un backup prima di scrivere. Modifiche concorrenti vengono rifiutate: è necessario ricaricare. Un trascinamento su un'attività automatica libera produce un vincolo SNET esplicito; un vincolo rigido incompatibile blocca anche la modifica diretta.

Le versioni conservano date, regole, dipendenze e XML. Il ripristino crea prima un backup dello stato corrente e richiede che le entità operative siano le stesse. Non ricrea attività eliminate e non cancella post. È sempre possibile scaricare il backup per ispezionarlo.

## Verifiche eseguite

| Verifica | Evidenza |
| --- | --- |
| Regressione backend, inclusa migrazione AI | **455 passati, 1 saltato**, 8 min 30 s; `backend-regression-final.log` |
| Contratto e API di pianificazione | 20 test: permessi, revisioni, backup/ripristino, rollback, import MPP reale, download privato, protezione post |
| Motore CPM | 20 test: risultati degli otto vincoli, quattro relazioni, lag frazionari/negativi/percentuali, cicli, festività, aggiunta di attività native a calendari importati, ripetizione del calcolo |
| Flutter | 45 test mirati passati, inclusi 6 lingue in tema chiaro/scuro su telefono e tablet; analisi dei file nuovi senza errori |
| Web reale su backend QA locale | Apertura della gerarchia completa, modifica SNET, simulazione, applicazione, backup e ripristino verificati nel browser; temi e larghezze 1024/1440 senza overflow |
| Runtime Flutter Web | Applicazione avviata e osservata; Dart MCP collegato, driver e albero widget verificati; revisione concorrente rifiutata e simulazione API 200 |

Le evidenze locali sono in `.dev-logs/gantt-professional-20261014/`. Il telefono è scollegato: non si dichiara una verifica runtime su Android/iPad fisici. Sul web a 390 px rimane il comportamento preesistente che porta alla vista delle lavorazioni; il Gantt completo per telefono è disponibile nell'app Flutter.

Il controllo del browser ha rilevato e corretto un errore nella timeline: l'espansione dei nodi foglia faceva ricorrere SVAR su figli nulli. Ora si espandono soltanto i nodi con figli; la verifica del flusso completo include questa regressione.

## Limiti dichiarati e protezioni

Questa versione non è una replica completa di Microsoft Project. Conservare un MPP originale non significa poterne ricalcolare ogni funzionalità. Il motore non implementa il livellamento delle risorse né la pianificazione dalla fine del progetto. Attività suddivise, ricorrenti, riferimenti esterni, date/calendari mancanti, vincoli di data sui riepiloghi e dati effettivi insufficienti impediscono un'applicazione non verificabile. Le attività manuali non possono essere spostate automaticamente senza un controllo che blocchi il risultato.

È stato verificato un limite di MPXJ sulle relazioni SF con lag zero al confine di un turno: può proporre una fine precedente all'inizio effettivo del predecessore. Il controllo indipendente delle dipendenze segnala il conflitto e impedisce di applicarlo. La relazione e il file rimangono conservati. Per questo caso non viene dichiarata equivalenza con Project.

L'originale binario è recuperabile byte per byte; l'XML prodotto dalla libreria non è un'esportazione garantita senza perdite di tutti i campi MPP. Unità e percentuali precise restano nel grafo JSON canonico per evitare arrotondamenti nei ricalcoli successivi. Per i piani nativi la durata iniziale è inferita dalle date inclusive, con 8 ore al giorno anche nel weekend: questa convenzione viene indicata nella vista Calendari, mentre un piano importato mantiene il suo calendario lavorativo.

Se una lavorazione importata viene eliminata, il legame con la riga originale viene conservato e il ricalcolo viene bloccato fino alla riconciliazione tramite importazione. La timeline Flutter mostra gerarchia, date, criticità e predecessori nelle schede; non disegna ancora frecce di collegamento. L'AI predittiva sui rischi non viene aggiunta in questo goal: vengono preparati dati e risultati deterministici verificabili.

## Migrazione delle chiamate AI

Le chiamate testuali precedentemente configurate su `gpt-4o-mini`, incluse varianti datate e preferenze salvate, vengono normalizzate a **gpt-6-luna**. Chat assistente e bozze documentali usano ragionamento `low`; la traduzione del contenuto usa `none`. La configurazione conserva modelli alternativi scelti esplicitamente. Gli esempi di ambiente e il selettore sono aggiornati.

La trascrizione audio usa **gpt-4o-transcribe**, perché Luna non accetta audio: sostituire anche quella chiamata con Luna interromperebbe la funzione. Nessuna chiamata effettiva usa più il vecchio modello mini per queste funzioni. I nomi storici nei report/migrazioni e negli alias di compatibilità non sono chiamate attive.

Il modello Luna è stato verificato sul provider: risposte HTTP 200 sia con `none` sia con `low`; nel secondo caso sono presenti token di ragionamento. La prova contiene soltanto un esempio fittizio di pianificazione. [OpenAI: modello Luna](https://developers.openai.com/api/docs/models/gpt-6-luna), [modelli di ragionamento](https://developers.openai.com/api/docs/guides/reasoning).
