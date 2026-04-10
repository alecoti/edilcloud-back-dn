# Assistant Retrieval Roadmap

## Obiettivo

Portare l'assistant di progetto dall'attuale mini-RAG self-hosted a un assistant da produzione, affidabile e adatto a una SaaS professionale per il settore edilizia.

L'assistant deve rispondere bene a domande su:

- progetto
- task
- attivita
- aziende
- persone
- criticita, alert, issue
- documenti e allegati
- contenuto dei documenti
- timeline per giorno o intervallo
- sintesi operative del progetto

L'assistant non deve piu trattare tutto come retrieval generico su un motore vettoriale esterno.

## Principi non negoziabili

- usare `deterministic DB/query layer` per count, distinct, elenchi, timeline giornaliera, filtri temporali e stato entita
- usare `hybrid DB + retrieval` per sintesi operative e domande miste
- usare `semantic retrieval` per documenti, allegati, post, commenti, note e contenuti testuali
- mantenere risposte corte per query semplici e piu ricche per query ampie
- ancorare sempre la risposta alle fonti corrette
- dichiarare quando l'evidenza non e sufficiente
- non usare retrieval per fare count o distinct quando il dato e gia nel DB
- non rompere il dominio esistente: rifactor progressivo e retrocompatibilita ragionevole

## Baseline gia implementata

### Retrieval e indicizzazione

- snapshot progetto riusato da `build_project_source_snapshot`
- retrieval denso su Postgres/pgvector con filtro obbligatorio `project_id`
- chunking locale con overlap moderato e mapping chunk -> point
- indicizzazione incrementale per `source_key`
- merge tra retrieval pgvector e fallback locale
- worker dedicato per indicizzazione background

### Persistenza e stato indice

- `ProjectAssistantState`
- `ProjectAssistantSourceState`
- `ProjectAssistantChunkSource`
- `ProjectAssistantChunkMap`
- stato indice con `is_dirty`, `current_version`, `last_indexed_version`, `last_sync_error`
- segnali che marcano dirty su mutazioni di progetto, task, activity, post, commenti, allegati e documenti

### Prompt e runtime

- prompt assistant gia riallineato a risposte sezionate
- thread summary e follow-up conversation-aware
- compose locale con Postgres/pgvector
- `assistant-worker` dedicato
- compose di produzione separato con volumi persistenti

### Progressi recenti gia integrati

- query router estratto in `query_router.py`
- answer planner estratto in `answer_planner.py`
- read models iniziali per intent strutturati in `read_models.py`
- timeline operativa iniziale in `timeline_service.py`
- contesto retrieval esplicito con `task_id` e `activity_id` da API, thread e citazioni precedenti
- retrieval `deterministic_db` per query strutturate con fatti/citazioni esplicite
- eval euristiche risposta-vs-fonti in `evaluation_service.py`
- telemetria assistant persistita nei metadata di messaggi e usage record
- chunk store pgvector ripulito con campi top-level aggiuntivi come `workspace_id`, `entity_id`, `post_id`, `document_id`, `company_name`, `index_version`
- merge retrieval locale + pgvector usato come base hybrid dense + lexical
- sparse retrieval dedicato a livello chunk per query documentali e match lessicali precisi
- reranking leggero dei risultati in base a intent e contesto task/activity
- renderer deterministico per query `deterministic_db`, senza delegare count/list/timeline al modello
- comando `run_assistant_eval` con dataset versionato per regressione router/planner
- comando `rebuild_assistant_index` e stato indice leggibile (`indexed`, `stale`, `processing`, `failed`)
- `chunk_schema_version` persistito sullo stato assistant e sulle sorgenti/chunk indicizzati
- comando `run_assistant_quality_report` per report aggregato per intent, grounding e mismatch
- comando `run_assistant_quality_gate` per gating automatico su dataset eval e metriche aggregate dei run log

## Gap principali rispetto all'obiettivo finale

- parte della logica resta ancora centralizzata in `services.py`
- i read models coprono gia gli intent principali ma non ancora tutti i casi di business complessi
- la timeline operativa e iniziale e va ancora raffinata su granularita ed eventi
- la telemetria e nei metadata applicativi, non ancora esposta in dashboard dedicate
- l'eval risposta-vs-fonti e presente come euristica, non ancora come scoring offline avanzato
- il chunk store pgvector e molto piu pulito ma non e ancora totalmente normalizzato per ogni source type
- il hybrid search e attualmente ottenuto tramite dense pgvector + sparse chunk retrieval applicativo, non ancora con BM25/sparse vectors nativi

## Nota importante sullo stato attuale di `task_id` e `activity_id`

Nel codice attuale i campi `task_id` e `activity_id` sono gia promossi a campi top-level nei chunk indicizzati su Postgres/pgvector. Questa e una buona base, ma non basta ancora.

Manca ancora:

- uso sistematico di filtri retrieval stretti su `task_id` e `activity_id`
- propagazione esplicita del contesto dal chiamante al retrieval principale
- sfruttamento robusto del contesto thread per i follow-up disambiguati
- metriche sui filtri contestuali effettivamente applicati

## Architettura target

L'architettura va separata in layer espliciti:

### A. Query routing / intent classification

Classifica la domanda e sceglie la strategia corretta.

### B. Deterministic operational read models

Servizi/query ORM affidabili per count, distinct, liste, timeline, aziende, persone, task, alert, documenti.

### C. Retrieval layer

pgvector solo dove ha senso:

- documenti
- allegati
- post e commenti testuali
- note e contenuti lunghi
- ricerca semantica

### D. Answer planning / response composition

Decide:

- lunghezza target
- struttura della risposta
- densita citazioni
- modalita di risposta

### E. Assistant generation

LLM usato per:

- interpretazione linguistica
- sintesi
- spiegazione
- follow-up
- confezionamento finale

L'LLM non deve fare il database.

## Moduli target

Il refactor deve convergere verso moduli dedicati:

- `src/edilcloud/modules/assistant/query_router.py`
- `src/edilcloud/modules/assistant/read_models.py`
- `src/edilcloud/modules/assistant/timeline_service.py`
- `src/edilcloud/modules/assistant/retrieval_service.py`
- `src/edilcloud/modules/assistant/answer_planner.py`
- `src/edilcloud/modules/assistant/evaluation_service.py`
- `src/edilcloud/modules/assistant/pgvector_store.py`
- `src/edilcloud/modules/assistant/indexing_service.py`

L'obiettivo e ridurre progressivamente il mega modulo `services.py`, non sostituirlo tutto in un colpo.

## Piano di esecuzione

### Fase 0 - Osservabilita e metriche retrieval

Implementare logging e telemetry per ogni richiesta assistant.

Per ogni domanda salvare almeno:

- `question_original`
- `normalized_question`
- `thread_id`
- `intent`
- `strategy`
- `retrieval_query`
- `retrieval_provider`
- `selected_source_types`
- `context_scope`
- `response_length_mode`
- `answer_sections`
- `assistant_output`
- `token_usage`
- `duration_ms`
- `index_state.is_dirty`
- `index_state.current_version`
- `index_state.last_indexed_version`
- `index_state.last_sync_error`

Per ogni richiesta salvare anche i top risultati retrieval:

- `source_key`
- `source_type`
- `label`
- `score`
- `snippet`
- `task_id`
- `activity_id`
- `post_id`
- `file_name`
- eventuale timestamp contenuto

Metriche obbligatorie dedicate al retrieval vettoriale:

- retrieval latency totale
- embedding latency query
- numero risultati restituiti
- source types dei risultati
- hit rate per `source_type`
- query con zero risultati
- query con risultati solo rumorosi o non pertinenti
- distribuzione score top-k
- numero risultati filtrati per `task_id`
- numero risultati filtrati per `activity_id`
- fallback rate local vs pgvector
- mismatch rate tra intent e source types recuperati

Metriche aggregate desiderate:

- percentuale query documentali corrette
- percentuale query task/activity corrette
- percentuale query temporali corrette

Deliverable:

- telemetria persistente o esportabile
- metriche minime per dashboard o report batch
- tracing chiaro del percorso domanda -> retrieval -> risposta

### Fase 1 - Test suite reale

Creare un dataset di domande reali per:

- progetto
- aziende
- persone
- task
- attivita
- criticita
- documenti
- sintesi
- timeline

Per ogni domanda definire:

- intent atteso
- strategia attesa
- lunghezza attesa
- struttura attesa
- fonti attese
- eventuale perimetro temporale atteso

Deliverable:

- test set versionato
- runner semplice di regressione
- output confrontabile tra release

### Fase 2 - Core refactor assistant

Questa fase costruisce il nucleo dell'assistant da produzione.

#### Fase 2.1 - Query router

Intent minimi:

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

Strategie minime:

- `deterministic_db`
- `hybrid_db_retrieval`
- `semantic_retrieval`

Acceptance:

- le query strutturate non dipendono piu dal retrieval vettoriale
- il router produce intent e strategy espliciti e tracciabili

#### Fase 2.2 - Read models operativi

Creare servizi affidabili per:

- Companies: aziende uniche, membri per azienda, task per azienda, origine membri/task/entrambe
- Team: membri attivi, ruolo progetto, azienda o workspace, esterno si/no, posizione
- Task: aperte, chiuse, in ritardo, con alert, per azienda, per periodo
- Activities: per giorno, intervallo, task, persona
- Alerts / Issues: aperte, chiuse, recenti, per task o activity
- Documents: catalogo, testo estraibile, folder/tipo, aggiornati di recente

Acceptance:

- count, distinct ed elenchi arrivano dal DB
- i risultati sono testabili senza LLM

#### Fase 2.3 - Timeline eventi operativi

Creare un layer tipo `ProjectOperationalEvent` o equivalente read model per domande come:

- cosa e successo ieri
- oggi
- ultimi 7 giorni
- settimana scorsa

Eventi minimi:

- task create/completate
- attivita registrate/concluse
- issue aperte/chiuse
- post pubblicati
- commenti inseriti
- documenti caricati
- foto caricate

Acceptance:

- le query temporali usano questo layer, non retrieval semantico puro

#### Fase 2.4 - Filtri contestuali stretti su `task_id` e `activity_id`

Questa parte e obbligatoria.

Da implementare:

- supporto a filtri espliciti retrieval per `task_id`
- supporto a filtri espliciti retrieval per `activity_id`
- possibilita di passare `task_id` e `activity_id` dal chiamante
- uso del contesto thread per follow-up come "e per quella task?" o "e l'attivita collegata?"
- se il contesto e disambiguato, evitare retrieval sull'intero progetto

Nota:

- il payload top-level esiste gia
- il lavoro qui consiste nel portare quei campi nel path di query, non solo nel payload

Acceptance:

- retrieval filtrato in modo coerente quando task/activity sono noti
- metriche dedicate sui filtri effettivamente applicati

#### Fase 2.5 - Eval automatiche qualita risposta vs fonti

Questa parte e obbligatoria.

Valutazioni minime:

- la risposta usa fonti coerenti con l'intent
- la risposta si appoggia a fonti che contengono davvero il fatto affermato
- la risposta e troppo vaga rispetto alle evidenze
- la risposta contraddice le fonti
- la risposta usa fonti rumorose o non pertinenti
- la risposta ignora la migliore fonte disponibile

Metriche richieste:

- source relevance score
- answer grounding score
- answer-source coverage
- mismatch rate tra risposta e fonti
- hallucination risk heuristics
- percentuale di risposte senza supporto forte
- percentuale di risposte con fonti topiche corrette

Implementazione attesa:

1. euristiche e controlli strutturali
2. opzionalmente evaluator LLM offline o batch

Acceptance:

- eval eseguibili automaticamente sul test set
- report leggibile per intent e failure mode

#### Fase 2.6 - Answer planning e lunghezza corretta

Creare un planner esplicito che decida:

- `target_length`: short / medium / long
- `response_structure`
- `citation_density`
- `answer_mode`

Regole minime:

- query semplici/strutturate: risposta breve con totale, elenco essenziale, nota di perimetro
- query temporali: risposta media con eventi principali, impatti, punti da verificare
- query sintetiche ampie: risposta lunga con sintesi operativa, evidenze, criticita, prossimi passi
- query documentali: risposta media/lunga con documenti trovati, cosa riportano, cosa manca

Acceptance:

- la lunghezza non dipende piu solo dal prompt
- il planner e osservabile e testabile

#### Fase 2.7 - Prompting minimale e robusto

Il prompt deve ricevere gia:

- intent
- strategy
- answer mode
- target length
- facts strutturati
- retrieved evidence pulita
- eventuale perimetro temporale
- eventuale contesto task/activity

Acceptance:

- il prompt non deve piu supplire all'assenza di logica applicativa
- l'LLM sintetizza, non calcola

### Gate prima della Fase 3

La Fase 3 parte solo quando sono stabili e testati:

- query router
- read models
- timeline operativa
- eval base
- filtri contestuali
- answer planning

### Fase 3 - Retrieval avanzato e consolidamento indice

#### Fase 3.1 - Hybrid search dense + sparse

Introdurre ricerca ibrida:

- dense embeddings
- sparse / lexical / BM25-style / keyword matching

Obiettivo:

- migliorare recall su nomi propri, task specifiche, aziende, file name, termini tecnici, sigle, numeri e riferimenti documentali

#### Fase 3.2 - Reranking

Introdurre reranking dopo il candidate retrieval.

Casi prioritari:

- domande su aziende
- domande task/activity specifiche
- query documentali ambigue
- query con rumore da fonti troppo generiche

#### Fase 3.3 - Strategia di rebuild globale su cambio modello embeddings

Questa parte e obbligatoria.

Requisiti:

- versionare `embedding_model_version`
- versionare `chunk_schema_version`
- derivare o esplicitare `index_version`
- rilevare mismatch tra indice e modello attivo
- supportare rebuild globale o per progetto
- supportare stato progressivo del rebuild
- evitare inconsistenze silenziose

Deliverable tecnico minimo:

- `embedding_model_version`
- `chunk_schema_version`
- `index_version`
- job di rebuild
- marcatura `stale`
- rebuild batch

#### Fase 3.4 - Pulizia pipeline pgvector

Ripulire i chunk e promuovere campi top-level chiari almeno per:

- `workspace_id`
- `project_id`
- `scope`
- `source_key`
- `source_type`
- `entity_id`
- `task_id`
- `activity_id`
- `post_id`
- `document_id`
- `author_name`
- `company_name`
- `file_name`
- `post_kind`
- `alert`
- `issue_status`
- `event_at`
- `created_at`
- `updated_at`
- `embedding_model`
- `index_version`

Regola:

- non lasciare le informazioni principali sepolte solo in `metadata`

#### Fase 3.5 - Miglioramento extraction documenti

Migliorare l'estrazione per:

- PDF
- RTF
- testo semplice
- HTML/XML

Salvare stato extraction:

- `success`
- `partial`
- `failed`
- `no_text`

Se possibile aggiungere:

- page references
- section references
- extraction quality

### Fase 4 - Indexing asincrono e produzione

Togliere l'indicizzazione pesante dal request flow.

Flusso target:

- cambiamento dominio -> evento sync
- worker asincrono aggiorna indice
- assistant usa ultimo indice consistente
- stato indice leggibile in API/UI

Stati minimi:

- `indexed`
- `stale`
- `processing`
- `failed`

### Fase 5 - Evaluation continua e gating qualita

Dopo l'implementazione, eseguire il test set e produrre un report con:

- success rate per intent
- errori top
- mismatch fonti/risposta
- query ancora deboli

Focus di qualita:

- query strutturate: target altissimo
- query documentali: target alto ma realistico
- query sintetiche: target di chiarezza, grounding e pertinenza

## Ordine pratico di esecuzione

1. osservabilita e metriche retrieval
2. test suite reale
3. query router
4. read models operativi
5. timeline eventi
6. filtri contestuali su task/activity
7. eval automatiche risposta vs fonti
8. answer planning e lunghezza
9. prompting robusto
10. pulizia chunk store e retrieval pgvector
11. hybrid search dense+sparse
12. reranking
13. rebuild globale su cambio embeddings
14. indexing asincrono
15. report finale di evaluation

## File attualmente coinvolti

### Gia presenti

- `src/edilcloud/modules/assistant/models.py`
- `src/edilcloud/modules/assistant/services.py`
- `src/edilcloud/modules/assistant/signals.py`
- `src/edilcloud/modules/assistant/admin.py`
- `src/edilcloud/modules/assistant/management/commands/run_assistant_indexer.py`
- `src/edilcloud/modules/assistant/management/commands/run_assistant_eval.py`
- `src/edilcloud/modules/assistant/management/commands/run_assistant_quality_report.py`
- `src/edilcloud/modules/assistant/management/commands/run_assistant_quality_gate.py`
- `src/edilcloud/modules/assistant/management/commands/rebuild_assistant_index.py`
- `src/edilcloud/modules/assistant/query_router.py`
- `src/edilcloud/modules/assistant/read_models.py`
- `src/edilcloud/modules/assistant/timeline_service.py`
- `src/edilcloud/modules/assistant/retrieval_service.py`
- `src/edilcloud/modules/assistant/answer_planner.py`
- `src/edilcloud/modules/assistant/evaluation_service.py`
- `src/edilcloud/modules/assistant/pgvector_store.py`
- `src/edilcloud/modules/assistant/indexing_service.py`

## Risultato atteso

Alla fine vogliamo un assistant che:

- risponda correttamente a domande semplici e strutturate
- faccia retrieval bene su documenti e contenuti testuali
- sappia usare filtri contestuali stretti su task/activity
- risponda con lunghezza appropriata
- sia chiaro e ordinato
- abbia metriche retrieval serie
- abbia eval automatiche qualita risposta vs fonti
- abbia un quality gate eseguibile automaticamente per intercettare regressioni
- sia pronto a evolvere con hybrid search, reranking e rebuild indice versionato
