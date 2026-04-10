# Assistant Backend: Architettura Attuale

Questo documento descrive **come funziona oggi davvero** l'assistant backend, senza parlare di roadmap o desiderata futuri.

L'obiettivo e' semplice: capire da dove arrivano i dati, come vengono indicizzati, quando viene usato il database, quando entra in gioco il retrieval e dove passa l'LLM.

## TL;DR

Oggi l'assistant funziona cosi':

1. il frontend chiama le API assistant del backend
2. il backend carica lo stato assistant del progetto
3. se l'indice e' sporco o mancante, sincronizza le sorgenti
4. classifica la domanda con un router
5. decide forma e lunghezza della risposta con un planner
6. se la domanda e' strutturata usa read models deterministici dal DB
7. se la domanda e' semantica usa retrieval su `pgvector` in Postgres
8. costruisce il contesto finale
9. genera la risposta con OpenAI, oppure rende una risposta deterministica se il caso e' semplice
10. salva messaggi, metriche, evaluation e metadati di run

## Stack vettoriale attuale

- Il vector store attuale e' `pgvector` su Postgres.
- Gli embeddings attuali sono OpenAI, default `text-embedding-3-large`.

## Stack reale di oggi

### API layer

File principale: `src/edilcloud/modules/assistant/api.py`

Espone gli endpoint principali:

- `GET /{project_id}/assistant`
- `POST /{project_id}/assistant`
- `POST /{project_id}/assistant/stream`
- `POST /{project_id}/assistant/threads`
- `PATCH /{project_id}/assistant/settings`
- `POST /{project_id}/assistant/drafting-context`

Questi endpoint non fanno tutta la logica direttamente: delegano quasi tutto ai servizi.

### Orchestrazione principale

File principale: `src/edilcloud/modules/assistant/services.py`

Questo e' il centro del sistema. Qui ci sono i passaggi piu' importanti:

- costruzione snapshot sorgenti
- sincronizzazione indice assistant
- retrieval locale e `pgvector`
- costruzione prompt
- generazione finale
- salvataggio thread, messaggi e run log

Le funzioni chiave sono:

- `build_project_source_snapshot`
- `index_project_assistant_state`
- `sync_project_assistant_sources`
- `retrieve_project_knowledge`
- `prepare_project_assistant_run`
- `generate_assistant_completion`
- `get_project_assistant_state`
- `ask_project_assistant`

## I dati da dove arrivano

Le sorgenti reali del progetto vengono prese dal dominio applicativo, non da un archivio separato.

In pratica l'assistant legge soprattutto da:

- progetto
- membri del progetto
- task
- attivita'
- post
- commenti
- documenti
- foto
- allegati dei post
- allegati dei commenti

Queste sorgenti vengono trasformate in una snapshot assistant attraverso `build_project_source_snapshot`.

## Cosa viene salvato nel DB assistant

File principale: `src/edilcloud/modules/assistant/models.py`

Le tabelle principali sono queste:

### `ProjectAssistantState`

Rappresenta lo stato assistant del progetto.

Contiene per esempio:

- versione indice
- embedding model
- stato dirty / processing / failed
- numero chunk
- ultimo sync
- ultimo errore

E' la tabella che dice se l'indice del progetto e' consistente oppure no.

### `ProjectAssistantSourceState`

Tiene traccia delle singole sorgenti che compongono l'indice assistant.

Serve a capire:

- quali sorgenti sono state viste
- quali versioni sono attuali
- quali vanno aggiornate o rimosse

### `ProjectAssistantChunkSource`

E' il cuore del retrieval su Postgres.

Qui vengono salvati i chunk indicizzati con:

- testo chunk
- metadata
- embedding vector
- project id
- source key
- source type
- riferimenti contestuali come `task_id`, `activity_id`, `post_id`, `document_id`

### `ProjectAssistantChunkMap`

Mappa i chunk verso la sorgente originale e aiuta a sapere da dove arriva ogni pezzo recuperato.

### `ProjectAssistantThread`

E' la conversazione assistant per progetto.

### `ProjectAssistantMessage`

Sono i singoli messaggi del thread.

Qui si salvano:

- domanda utente
- risposta assistant
- citations
- metadata di contesto

### `ProjectAssistantRunLog`

E' il log tecnico di ogni esecuzione assistant.

Contiene per esempio:

- domanda originale
- domanda normalizzata
- intent
- strategy
- retrieval query
- provider usato
- top results
- durata
- token usage
- output finale
- evaluation score

## Come nasce l'indice assistant

Il flusso e' questo:

1. si costruisce la snapshot delle sorgenti del progetto
2. ogni sorgente produce un testo normalizzato e metadata strutturati
3. i contenuti lunghi vengono spezzati in chunk
4. per ogni chunk si chiede l'embedding a OpenAI
5. il vettore viene salvato in Postgres con `pgvector`
6. lo stato assistant viene aggiornato con versione e contatori

### Dove vive il vector store

Il vector store vive in Postgres.

La parte di integrazione e' distribuita tra:

- `src/edilcloud/modules/assistant/services.py`
- `src/edilcloud/modules/assistant/pgvector_store.py`

La health API riporta `vector_store = "pgvector"` quando l'assistant semantico e' attivo.

## Come si aggiorna l'indice

L'indice non viene ricostruito a mano ogni volta.

Quando cambiano entita' di progetto, i segnali Django marcano il progetto come sporco.

File principale: `src/edilcloud/modules/assistant/signals.py`

I segnali osservano almeno:

- progetto
- membri progetto
- folder
- documenti
- foto
- task
- attivita'
- workers delle attivita'
- post
- allegati post
- commenti
- allegati commenti

Quando cambia una di queste entita':

1. lo stato assistant diventa `dirty`
2. il sistema programma una sincronizzazione
3. il worker o il comando di indexing aggiorna l'indice

Lato servizio, questo giro passa da:

- `indexing_service.py`
- `run_assistant_indexer`
- `rebuild_assistant_index`

## Cosa succede quando fai una domanda

Il percorso vero e' questo.

### 1. Arriva la richiesta API

L'endpoint `POST /{project_id}/assistant` riceve:

- project id
- question
- eventuale `thread_id`
- eventuale `response_mode`
- eventuale contesto aggiuntivo

### 2. Il backend prepara il run

`ask_project_assistant` chiama `prepare_project_assistant_run`.

Qui vengono raccolti:

- thread corrente
- messaggi recenti
- stato assistant del progetto
- contesto conversazionale

### 3. Se serve, sincronizza l'indice

Se il progetto e' `dirty`, o se l'indice non e' allineato, il backend passa da `sync_project_assistant_sources`.

Questa fase:

- costruisce la nuova snapshot
- confronta vecchie e nuove sorgenti
- aggiorna chunk e metadata
- elimina chunk stantii

### 4. Il router classifica la domanda

File principale: `src/edilcloud/modules/assistant/query_router.py`

Il router prova a capire:

- qual e' l'intent
- quale strategia usare
- quali source types sono piu' probabili
- se la domanda e' un follow-up
- se c'e' un perimetro temporale

Intent gestiti oggi:

- `project_summary`
- `company_count`
- `company_list`
- `team_count`
- `team_list`
- `task_count`
- `task_list`
- `task_status`
- `activity_by_date`
- `timeline_summary`
- `open_alerts`
- `resolved_issues`
- `document_list`
- `document_search`
- `generic_semantic`

Strategie possibili:

- `deterministic_db`
- `hybrid_db_retrieval`
- `semantic_retrieval`

### 5. Il planner decide come scrivere

File principale: `src/edilcloud/modules/assistant/answer_planner.py`

Il planner decide:

- `target_length`
- `response_structure`
- `citation_density`
- `answer_mode`
- `answer_sections`

Questo e' il motivo per cui alcune risposte escono con strutture preimpostate come:

- `Sintesi operativa`
- `Evidenze rilevanti`
- `Criticita aperte`
- `Prossimi passi`

Quella forma non nasce dal retrieval: nasce dal planner.

### 6. Il sistema cerca contesto esplicito o implicito

File principale: `src/edilcloud/modules/assistant/retrieval_service.py`

Qui viene risolto il contesto di retrieval:

- `task_id`
- `activity_id`
- contesto thread
- citazioni dell'ultimo messaggio
- follow-up tipo "e per quella task?"

Il retrieval context prova a restringere il perimetro quando possibile.

Questo e' importante: non tutte le domande cercano su tutto il progetto.

### 7. Se la domanda e' strutturata, legge dal DB

File principale: `src/edilcloud/modules/assistant/read_models.py`

Qui ci sono i read models deterministici.

Servono per domande come:

- quanti partecipanti ci sono
- quali aziende ci sono
- quante task ci sono
- quali documenti ci sono
- cosa e' successo ieri

In questi casi il sistema dovrebbe usare il DB operativo, non il retrieval vettoriale.

I read models costruiscono:

- count
- liste
- facts strutturati
- timeline
- perimetro documentale
- riepiloghi affidabili su dati gia' strutturati

### 8. Se la domanda e' semantica, usa pgvector

Se la domanda richiede ricerca su contenuti testuali, entra `retrieve_project_knowledge`.

Qui il sistema puo' combinare:

- facts strutturati
- retrieval locale
- retrieval `pgvector`
- citazioni dai chunk piu' rilevanti

Il retrieval su `pgvector` funziona sui chunk indicizzati del progetto.

In pratica:

1. prende la query normalizzata
2. genera l'embedding query
3. esegue similarity search su Postgres
4. applica i filtri di progetto e, se presenti, di task/activity
5. restituisce citations e snippet

## Come viene costruita la risposta finale

Dopo routing, planning, facts e retrieval, il sistema costruisce il contesto finale per la generazione.

Dentro il prompt finiscono almeno:

- intent
- strategy
- target length
- answer mode
- contesto temporale
- facts strutturati
- memoria progetto
- risultati retrieval
- ultimi messaggi del thread
- domanda corrente

Poi ci sono tre uscite possibili:

### Risposta deterministica

Per alcuni casi semplici il backend puo' usare `build_deterministic_assistant_completion`.

Qui non c'e' bisogno del modello per inventare la struttura: la risposta viene assemblata direttamente dai facts.

### Risposta LLM grounded

Per domande piu' aperte il backend chiama OpenAI in `generate_assistant_completion`.

In questo caso il modello non parte da zero: riceve gia' route, piano, facts e citations.

### Fallback

Se qualcosa va storto, il backend puo' usare `build_fallback_assistant_completion`.

## Dove entra la valutazione qualita'

File principale: `src/edilcloud/modules/assistant/evaluation_service.py`

Dopo la generazione il sistema puo' valutare la risposta con euristiche tipo:

- `source_relevance_score`
- `answer_grounding_score`
- `answer_source_coverage`
- `mismatch_rate`
- `hallucination_risk`

Questi dati vengono salvati nel run log e usati dai comandi di report/gating.

## Perche' a volte sembra tutto "fumoso"

La complessita' percepita nasce dal fatto che oggi convivono tre piani diversi.

### Piano 1: DB operativo

E' il piano giusto per:

- count
- liste
- task
- attivita'
- persone
- aziende
- timeline

### Piano 2: indice semantico su pgvector

E' il piano giusto per:

- documenti lunghi
- allegati
- post
- commenti
- testo non strutturato

### Piano 3: LLM

Serve per:

- interpretare la domanda
- sintetizzare
- spiegare
- mantenere una forma conversazionale

Quando questi tre piani sono ben allineati, l'assistant sembra intelligente.

Quando non sono ben allineati, succede la sensazione di "giro del fumo":

- il router manda nel ramo sbagliato
- il planner impone una struttura innaturale
- il retrieval trova solo metadata o chunk deboli
- il modello cerca di riempire i buchi

## Punto importante sui documenti

Il fatto che un documento esista nel progetto non significa automaticamente che l'assistant ne possa leggere bene il contenuto.

Ci sono almeno quattro casi diversi:

1. il documento esiste nel catalogo
2. il file fisico esiste davvero nello storage
3. il testo e' stato estratto correttamente
4. il testo e' stato chunkato e indicizzato

Se uno di questi passaggi manca, puoi avere:

- conteggio documenti corretto
- nome file corretto
- ma contenuto poco o per nulla interrogabile

Questa e' una delle principali cause delle risposte documentali deboli.

## Punto importante sulla conversazione

Il thread assistant aiuta a capire i follow-up, ma non e' la fonte della verita'.

Il thread serve per:

- capire a cosa si riferisce un "e quello?"
- riusare `task_id` o `activity_id` emersi nel messaggio precedente
- mantenere continuita' nella conversazione

Pero' il dato vero deve sempre arrivare da:

- DB operativo
- indice pgvector
- sorgenti di progetto effettive

## Mappa mentale semplice

Se vuoi una versione super compatta, pensa all'assistant cosi':

### Livello 1: sorgenti

Il progetto produce dati grezzi:

- task
- attivita'
- membri
- documenti
- post
- commenti

### Livello 2: preparazione

Il backend trasforma questi dati in:

- facts strutturati
- documenti/chunk indicizzati
- stato assistant del progetto

### Livello 3: decisione

Quando arriva una domanda, il sistema decide:

- questa risposta la prendo dal DB?
- dal retrieval?
- da entrambi?

### Livello 4: scrittura

Infine il sistema costruisce la risposta:

- direttamente dai facts
- oppure con LLM grounded su facts + citations

## File guida da leggere se vuoi orientarti nel codice

Se vuoi riprendere in mano il backend assistant senza perderti, l'ordine giusto e' questo:

1. `src/edilcloud/modules/assistant/api.py`
2. `src/edilcloud/modules/assistant/services.py`
3. `src/edilcloud/modules/assistant/models.py`
4. `src/edilcloud/modules/assistant/query_router.py`
5. `src/edilcloud/modules/assistant/answer_planner.py`
6. `src/edilcloud/modules/assistant/read_models.py`
7. `src/edilcloud/modules/assistant/retrieval_service.py`
8. `src/edilcloud/modules/assistant/evaluation_service.py`
9. `src/edilcloud/modules/assistant/signals.py`
10. `src/edilcloud/modules/assistant/indexing_service.py`

## In una frase

Oggi l'assistant non e' "un semplice RAG".

E' un sistema a tre strati:

- DB deterministico per i dati strutturati
- `pgvector` per il retrieval semantico
- OpenAI per interpretazione e scrittura finale

Il punto difficile non e' solo recuperare dati, ma fare in modo che questi tre strati restino sempre coerenti tra loro.
