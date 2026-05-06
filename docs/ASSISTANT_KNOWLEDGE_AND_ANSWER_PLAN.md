# Assistant Knowledge and Answer Plan

Questo file e il binario operativo per evolvere l'assistant EdilCloud da mini-RAG e demo scripted a sistema di conoscenza di progetto con risposte naturali, utili e verificabili.

L'obiettivo non e cambiare nome al RAG. L'obiettivo e costruire un assistant che risponde bene nella realta: dati certi dal DB, prove puntuali dal retrieval, memoria compilata tramite wiki di progetto, relazioni tramite graph leggero, e una forma di risposta libera ma ben leggibile.

## Stato attuale sintetico

### Backend reale

Il backend ha gia una base solida:

- router intent/strategy
- answer planner
- read models deterministici
- retrieval pgvector
- fallback locale/sparse
- chunk con metadata di progetto
- run log
- evaluation euristica
- citations

Il problema principale non e la mancanza totale di architettura. Il problema e che retrieval, planner e prompt non sono ancora abbastanza selettivi e il formato risposta viene forzato troppo spesso.

### Demo assistant

La demo e piu debole del backend reale:

- usa `demo-retrieval-local`
- usa `demo-tfidf-v1`
- usa chunk e cosine similarity sparse in TypeScript
- usa risposte molto template-based
- usa la data reale corrente per domande tipo "oggi"
- puo sembrare una wiki, ma non ha una vera memoria compilata

Quindi la demo oggi rischia di svalutare il prodotto anche quando il backend reale e concettualmente piu forte.

### Risposte attuali

La forma risposta e troppo rigida:

- il planner impone sezioni tipo `Sintesi operativa`, `Evidenze rilevanti`, `Criticita aperte`, `Prossimi passi`
- il prompt rinforza "Always organize the answer with explicit section headings"
- il frontend renderizza markdown minimale
- le fonti sono utili ma non ancora abbastanza eleganti come esperienza ChatGPT/Gemini

La forma corretta deve essere libera, ma non caotica.

## North star

L'assistant deve sembrare un capo commessa digitale capace:

- risponde breve quando la domanda e semplice
- spiega bene quando la domanda e ampia
- non forza sezioni inutili
- usa heading solo quando aiutano
- mostra le fonti senza appesantire
- distingue fatti certi, segnalazioni e inferenze
- usa il DB per numeri e stati
- usa il retrieval per prove testuali
- usa la wiki per memoria sintetica
- usa il graph per relazioni tra entita
- ammette quando non ha prove sufficienti

## Architettura target

```text
User Question
  -> Query Router
  -> Answer Shape Planner
  -> Context Orchestrator
       -> Operational DB
       -> Evidence Retrieval
       -> Project Wiki
       -> Project Graph
       -> Recent Thread Context
  -> Evidence Quality Check
  -> Answer Generator
  -> Claim/Citation Check
  -> Rich UI Renderer
  -> Run Log + Eval
```

### 1. Operational DB

Fonte corretta per:

- count
- liste
- stati task/activity
- aziende
- persone
- ruoli
- date
- timeline operative strutturate
- document register

Regola: mai usare retrieval semantico per contare o fare distinct quando il DB puo rispondere.

### 2. Evidence Retrieval

Fonte corretta per:

- documenti lunghi
- testo estratto da PDF/RTF/HTML/TXT
- post
- commenti
- note vocali trascritte
- allegati testuali
- evidenze puntuali

Target:

- contextual chunks
- dense search
- BM25/lexical search
- rank fusion
- reranking
- filtri forti su `project_id`, `task_id`, `activity_id`, `document_id`

### 3. Project Wiki

Memoria compilata per progetto, non sostituto delle fonti raw.

Pagine minime:

- overview
- timeline
- open issues
- decisions
- risks
- documents
- companies
- people
- tasks
- activities

Regola: ogni claim importante della wiki deve avere source links o provenance.

### 4. Project Graph

Graph leggero e domain-aware.

Entita minime:

- project
- company
- person
- task
- activity
- document
- post
- comment
- issue
- decision
- risk

Relazioni minime:

- company works_on task
- person assigned_to activity
- activity belongs_to task
- post reports_on task/activity
- document supports task/activity/issue
- issue blocks task/activity
- decision resolves issue
- risk affects milestone

### 5. Answer Engine

Il generatore non deve ricevere una struttura obbligatoria fissa. Deve ricevere un `answer_shape` dinamico.

Shape iniziali:

- `direct`: risposta breve, una o due frasi
- `brief`: risposta compatta con mini elenco se utile
- `narrative`: spiegazione fluida
- `timeline`: eventi ordinati
- `table`: confronto o elenco tabellare
- `checklist`: azioni operative
- `deep_report`: sintesi ampia
- `document_brief`: risposta documentale

## Regole di prodotto per la risposta

### Non fare piu

- Non forzare sempre quattro sezioni.
- Non usare "Sintesi operativa" per domande semplici.
- Non trasformare ogni domanda in mini-report.
- Non mettere fonti ovunque se peggiorano la lettura.
- Non rispondere con liste se una frase chiara basta.
- Non nascondere incertezza o assenza di prove.

### Fare invece

- Aprire con la risposta piu utile.
- Aggiungere struttura solo se aiuta.
- Usare paragrafi brevi.
- Usare liste solo per piu elementi comparabili.
- Usare timeline quando la domanda e temporale.
- Usare tabelle quando serve confronto.
- Usare callout per rischi, blocchi o mancanza dati.
- Tenere le citazioni nel layer UI quando possibile.

## Percorso operativo

## Fase 0 - Baseline, dataset e diagnosi

Obiettivo: sapere esattamente cosa stiamo migliorando.

Interventi:

- Creare o estendere un dataset di domande reali.
- Separare domande demo e domande backend reale.
- Classificare ogni domanda per intent, answer shape, fonti attese e livello di dettaglio.
- Registrare esempi di risposta attuale considerati brutti o inutili.
- Misurare almeno manualmente: correttezza, utilita, forma, fonti.

Domande minime:

- chi lavora oggi?
- cosa e successo oggi?
- quali criticita sono aperte?
- quali documenti parlano del foro cucina 2B?
- cosa blocca i collaudi?
- quali aziende sono coinvolte?
- fammi il quadro del cantiere
- cosa e cambiato negli ultimi giorni?
- quali rischi vedi prima della consegna?
- quali prove supportano questa risposta?

Output atteso:

- dataset versionato
- baseline prima/dopo
- elenco failure mode prioritari

Acceptance criteria:

- Abbiamo almeno 50 domande rappresentative.
- Ogni domanda ha intent atteso e answer shape atteso.
- Ogni domanda critica ha fonti attese o criterio di verifica.

## Fase 1 - Answer shape planner e prompt meno rigido

Obiettivo: rendere le risposte naturali e adeguate alla domanda.

Interventi:

- Sostituire il concetto dominante di `response_structure` con `answer_shape`.
- Lasciare `response_mode` esplicito come override, non come default invasivo.
- Rimuovere o attenuare regole tipo "Always organize with headings".
- Rendere le sezioni suggerite, non obbligatorie.
- Introdurre regole di lunghezza piu elastiche.
- Aggiornare prompt per "free but structured".

File probabili:

- `src/edilcloud/modules/assistant/answer_planner.py`
- `src/edilcloud/modules/assistant/services.py`
- `src/edilcloud/modules/assistant/data/assistant_eval_dataset.json`
- test assistant router/eval

Acceptance criteria:

- Una domanda semplice produce risposta semplice.
- Una domanda ampia produce risposta ricca.
- Le sezioni fisse compaiono solo quando servono o quando richieste.
- Le risposte non sembrano tutte lo stesso template.

## Fase 2 - Rich answer rendering frontend

Obiettivo: far sembrare le risposte un prodotto moderno, non testo grezzo dentro una bubble.

Interventi:

- Migliorare renderer markdown.
- Supportare heading veri.
- Supportare blockquote/callout.
- Supportare tabelle semplici.
- Migliorare liste ordinate e non ordinate.
- Rendere fonti come pannello elegante e source chips.
- Valutare citazioni inline leggere tipo `[S1]`.
- Mostrare badge provider/memoria in modo meno rumoroso.

File probabili:

- `edilcloud-next/src/components/cantieri/detail/project-assistant-tab.tsx`
- `edilcloud-next/src/lib/project-assistant/types.ts`

Acceptance criteria:

- Una risposta lunga resta leggibile.
- Le fonti non spezzano il flusso.
- Timeline, checklist e document brief hanno resa visiva distinta.
- Mobile e desktop restano comodi.

## Fase 3 - Demo assistant credibile

Obiettivo: la demo deve dimostrare il prodotto, non sabotarlo.

Interventi:

- Introdurre una data demo fissa o derivata dal progetto demo.
- Evitare che "oggi" usi sempre la data reale se il demo e storico.
- Ridurre risposte template-based.
- Allineare topic/answer shape del demo al planner reale.
- Migliorare retrieval demo almeno con BM25-like e scoring su metadata.
- Aggiungere memoria demo compilata: stato, criticita, decisioni, timeline.
- Valutare se far passare la demo attraverso backend reale quando possibile.

File probabili:

- `edilcloud-next/src/lib/demo-project/assistant.ts`
- `edilcloud-next/src/lib/demo-project/data.ts`
- `edilcloud-next/src/lib/demo-project/store.ts`

Acceptance criteria:

- "Oggi" nel demo restituisce una situazione coerente.
- Le risposte non sembrano generate da template statici.
- Le fonti demo sono pertinenti.
- Il demo mostra bene criticita, timeline, documenti e prossimi passi.

## Fase 4 - Contextual retrieval e hybrid search

Obiettivo: aumentare drasticamente recall e pertinenza.

Interventi:

- Aggiungere contesto breve a ogni chunk prima di embedding e BM25.
- Indicizzare sia chunk raw sia contextual chunk.
- Introdurre BM25/lexical search reale o equivalente solido.
- Usare rank fusion tra dense e sparse.
- Recuperare molti candidati e poi filtrare/rerankare.
- Promuovere metadata importanti top-level.
- Stringere filtri su task/activity/document quando il contesto e noto.

File probabili:

- `src/edilcloud/modules/assistant/services.py`
- `src/edilcloud/modules/assistant/pgvector_store.py`
- `src/edilcloud/modules/assistant/retrieval_service.py`
- `src/edilcloud/modules/assistant/models.py`
- migrations assistant

Acceptance criteria:

- Migliora recall@k su documenti e post.
- Query con nomi propri, sigle, file name e numeri funzionano meglio.
- Il retrieval non recupera solo chunk generici.
- Il run log mostra dense, lexical, fused e final candidates.

## Fase 5 - Reranking e retrieval quality check

Obiettivo: evitare che il generatore riceva contesto rumoroso.

Interventi:

- Aggiungere reranking dopo candidate retrieval.
- Aggiungere score di pertinenza fonte/domanda.
- Se il retrieval e debole, rispondere con incertezza o rilanciare una ricerca piu mirata.
- Separare prove forti da prove deboli.
- Evitare che fonti metadata-only vengano presentate come testo letto.

Acceptance criteria:

- Meno risposte basate su fonti marginali.
- Le citazioni supportano davvero le frasi importanti.
- Le domande documentali dichiarano quando il testo documento non e disponibile.

## Fase 6 - Project wiki per cantiere

Obiettivo: costruire memoria compilata per progetto.

Interventi:

- Definire modello wiki: pagine, source links, versioni, stato rebuild.
- Generare overview iniziale da snapshot progetto.
- Generare pagine per criticita, decisioni, rischi, documenti, aziende, persone, task.
- Aggiornare wiki quando cambiano fonti.
- Rendere la wiki interrogabile dal context orchestrator.
- Non usare wiki come unica fonte di verita.

Struttura logica:

```text
project_wiki
  overview
  timeline
  open_issues
  decisions
  risks
  documents
  companies
  people
  tasks
  activities
```

Acceptance criteria:

- Domande ampie migliorano per completezza e coerenza.
- Ogni pagina wiki ha provenance.
- La wiki non inventa stati o date.
- Se la wiki e stale, il sistema lo sa.

## Fase 7 - Project graph leggero

Obiettivo: rispondere meglio a domande trasversali.

Interventi:

- Estrarre entita e relazioni dal DB operativo prima che dal testo libero.
- Collegare task, activity, company, person, document, issue, decision.
- Usare graph per query tipo "cosa blocca cosa", "chi e coinvolto", "quali documenti supportano questa criticita".
- Evitare graph generico troppo ambizioso.

Acceptance criteria:

- Risposte cross-module diventano piu precise.
- Le relazioni importanti sono interrogabili.
- Il graph resta incrementale e spiegabile.

## Fase 8 - Evaluation continua e quality gate

Obiettivo: non decidere a sensazione.

Metriche minime:

- intent accuracy
- strategy accuracy
- answer shape accuracy
- context relevance
- groundedness
- answer relevance
- citation support
- recall@k
- nDCG@k
- zero-result rate
- noisy-context rate

Interventi:

- Estendere `run_assistant_eval`.
- Aggiungere judge offline o euristiche piu forti.
- Creare report prima/dopo per ogni fase.
- Bloccare regressioni gravi.

Acceptance criteria:

- Ogni fase produce report.
- Le regressioni vengono individuate prima di andare avanti.
- La demo ha un dataset dedicato.

## Ordine consigliato di esecuzione

1. Fase 0 - Baseline, dataset e diagnosi
2. Fase 1 - Answer shape planner e prompt meno rigido
3. Fase 2 - Rich answer rendering frontend
4. Fase 3 - Demo assistant credibile
5. Fase 4 - Contextual retrieval e hybrid search
6. Fase 5 - Reranking e retrieval quality check
7. Fase 6 - Project wiki per cantiere
8. Fase 7 - Project graph leggero
9. Fase 8 - Evaluation continua e quality gate

## Aggiornamento operativo 2026-05-05

Completato in modo incrementale:

- Fase 1: planner e prompt non forzano piu una struttura fissa di risposta.
- Fase 1: eval backend controlla anche `expected_answer_shape`.
- Fase 2: renderer Next supporta heading, tabelle markdown e callout.
- Fase 2: bubble Flutter supporta heading, liste, callout e inline emphasis senza cambiare layout base.
- Fase 3: demo assistant usa una data demo fissa coerente con il progetto.
- Fase 3: demo assistant indicizza una wiki demo compilata con overview, timeline, criticita, documenti e team.
- Fase 3: ranking demo usa boost su topic, date, alert, source type e metadata.
- Fase 4: backend reale usa chunk contestuali `assistant-chunk-schema:v3` con header di retrieval da metadata.
- Fase 4: pgvector puo filtrare direttamente per source type oltre che task/activity.
- Fase 4: sparse/local retrieval cercano anche nei metadata normalizzati, non solo nel testo grezzo.
- Fase 4: metriche retrieval includono candidate pool, pool contestuale, scope, filtri e risultati finali.
- Fase 5: evaluation backend misura supporto per singola citazione, fonti deboli, fonti metadata-only e noisy-context rate.
- Fase 5: quality report aggrega citation support, noisy context e weak evidence per intent.
- Fase 5: quality gate puo bloccare regressioni su citation support, noisy context e weak evidence quando i run log hanno metriche nuove.
- Fase 8: aggiunto quality gate demo ripetibile con 12 domande rappresentative.

Comandi di verifica aggiunti:

- `npm run quality:demo-assistant` in `edilcloud-next`
- `python -m pytest tests/test_assistant_router.py tests/test_assistant_eval.py -q` in `edilcloud-back-dn`

Risultato ultimo gate demo:

- 12/12 casi passati
- backend assistant mirato: 27 test passati

## Aggiornamento operativo 2026-05-06

Completato per rendere il progetto demo piu credibile e piacevole:

- Fase 3: il demo assistant non usa piu post/commenti futuri rispetto alla data demo `15 aprile 2026`.
- Fase 3: le domande su "oggi" iniettano evidenze strutturate decisive prima del ranking, cosi il post del giorno e le attivita pianificate finiscono nelle fonti top.
- Fase 3: le risposte su collaudi, rischi e consegna sono piu operative: distinguono prerequisiti, punch list, as-built/manuali, pulizie/check e nodo foro cucina 2B.
- Fase 3: le risposte documentali mettono la fonte diretta piu forte davanti, evitando doppioni e collegando post/attivita di supporto.
- Fase 8: il quality gate demo controlla anche keyword nelle prime citazioni, non solo nell'insieme completo delle fonti.

Risultato ultimo gate demo dopo il controllo manuale delle risposte:

- 12/12 casi passati con primary-source check attivo.

Completato per la Fase 6 - Project wiki per cantiere:

- Decisione prodotto confermata: DB come fonte primaria della wiki, Markdown solo come export/audit.
- Aggiunto modello `ProjectAssistantWikiPage` con slug, page type, body Markdown, summary, provenance, schema version, generated version e stato stale.
- Aggiunto compilatore deterministico `project-wiki:v1` con pagine overview, timeline, open issues, decisions, risks, documents, companies, people, tasks e activities.
- La wiki viene ricompilata quando il progetto cambia e viene inclusa nel source snapshot come fonte `project_wiki`.
- Router e retrieval considerano `project_wiki` per domande ampie, timeline, criticita, documenti, team e ricerca semantica.
- Aggiunto export Markdown via comando `export_project_wiki`, mantenendo il DB come fonte autorevole.

Verifica Fase 6:

- `python manage.py check --settings=edilcloud.settings.test`: pass
- `python manage.py makemigrations --check --dry-run --settings=edilcloud.settings.test`: pass
- `python -m pytest tests/test_assistant_eval.py tests/test_assistant_router.py tests/test_assistant_api.py::test_project_assistant_state_and_ask_routes_work_with_shared_memory tests/test_assistant_api.py::test_pgvector_sync_is_incremental_and_tracks_real_file_backed_sources tests/test_assistant_api.py::test_assistant_quality_report_command_aggregates_persisted_metadata tests/test_assistant_api.py::test_assistant_quality_gate_command_passes_for_green_dataset_and_run_logs -q`: 31 passed

Secondo avanzamento 2026-05-06:

- Fase 0/Fase 8: dataset demo esteso da 12 a 29 domande, coprendo varianti su avanzamento, percentuale, prossime lavorazioni, consegna, prerequisiti collaudi, foro cucina 2B, squadre di oggi, team, aziende, documenti e ultimi giorni.
- Fase 0/Fase 8: dataset backend router/planner esteso da 5 a 21 domande, con verifica `run_assistant_eval` su dataset sorgente e test.
- Fase 4: sparse retrieval backend ora combina scoring esistente con BM25-like sui chunk e registra `lexical_provider=bm25_like`.
- Fase 4/Fase 5: merge dense/sparse/local ora registra Reciprocal Rank Fusion nelle metadata `rank_fusion`, con provider e base score.
- Fase 1/Fase 4: router backend tratta domande tipo "chi lavora oggi?" e "quali squadre sono in programma oggi?" come `activity_by_date`, non come elenco team generico.
- Fase 1: aggiunto marker "elenca/elencami" per classificare correttamente liste documentali e operative.

Verifica secondo avanzamento:

- `npm run quality:demo-assistant`: 29/29 casi passati.
- `npx tsc --noEmit`: pass.
- `python manage.py run_assistant_eval --settings=edilcloud.settings.test`: 21/21 casi passati.
- `python manage.py run_assistant_eval --dataset tests\data\assistant_eval_dataset.json --settings=edilcloud.settings.test`: 21/21 casi passati.
- `python -m pytest tests/test_assistant_eval.py tests/test_assistant_router.py tests/test_assistant_api.py::test_project_assistant_state_and_ask_routes_work_with_shared_memory tests/test_assistant_api.py::test_pgvector_sync_is_incremental_and_tracks_real_file_backed_sources tests/test_assistant_api.py::test_assistant_quality_report_command_aggregates_persisted_metadata tests/test_assistant_api.py::test_assistant_quality_gate_command_passes_for_green_dataset_and_run_logs -q`: 32 passed.

Terzo avanzamento 2026-05-06:

- Fase 7: aggiunto `ProjectAssistantGraphSnapshot` come graph leggero per progetto, persistito in DB con nodes, edges, provenance, schema version, generated version e stato stale.
- Fase 7: aggiunto compilatore deterministico `project-graph:v1` basato prima sul DB operativo: project, company, person, task, activity, document, post, issue, decision e risk.
- Fase 7: il graph esplicita relazioni domain-aware come `works_on`, `assigned_to`, `has_activity`, `reports_on`, `supports`, `blocks`, `affects`, `resolves`.
- Fase 7: il graph viene ricompilato in indicizzazione e preparazione run, diventa stale quando cambiano fonti di progetto, ed entra nel source snapshot come fonte `project_graph`.
- Fase 4/Fase 5: retrieval, pgvector filter, sparse/local scoring, reranking e context markdown considerano `project_graph` per domande su blocchi, relazioni, coinvolgimenti, rischi e supporto documentale.
- Fase 8: aggiunti test su persistenza graph, refresh stale, inclusione nello snapshot sorgenti e retrieval su domande tipo "cosa blocca la task ponteggi?".

Verifica terzo avanzamento:

- `python manage.py check --settings=edilcloud.settings.test`: pass.
- `python manage.py makemigrations --check --dry-run --settings=edilcloud.settings.test`: pass.
- `python -m pytest tests/test_assistant_eval.py -q`: 24 passed.
- `python -m pytest tests/test_assistant_router.py -q`: 7 passed.
- `python -m pytest tests/test_assistant_api.py -q`: 13 passed.
- `python manage.py run_assistant_eval --settings=edilcloud.settings.test`: 21/21 casi passati.
- `python manage.py run_assistant_eval --dataset tests\data\assistant_eval_dataset.json --settings=edilcloud.settings.test`: 21/21 casi passati.
- `python -m pytest tests/test_assistant_api.py::test_project_assistant_state_and_ask_routes_work_with_shared_memory tests/test_assistant_api.py::test_pgvector_sync_is_incremental_and_tracks_real_file_backed_sources tests/test_assistant_api.py::test_assistant_quality_report_command_aggregates_persisted_metadata tests/test_assistant_api.py::test_assistant_quality_gate_command_passes_for_green_dataset_and_run_logs -q`: 4 passed.
- `npm run quality:demo-assistant`: 29/29 casi passati.
- `npx tsc --noEmit`: pass.
- `dart analyze lib\src\features\dashboard\project_detail_screen.dart`: pass.

Quarto avanzamento 2026-05-06:

- Pipeline resa `worker-first`: i segnali assistant ora usano `transaction.on_commit` e schedulano l'indicizzazione dopo il salvataggio effettivo, senza fare lavoro pesante nel path di scrittura.
- Le mutazioni progetto creano/schedulano lo `ProjectAssistantState` anche se l'assistente non e mai stato aperto, cosi la memoria puo prepararsi in background appena il progetto cambia.
- Apertura tab assistant alleggerita: `get_project_assistant_state` legge stato, conteggi e scheduling, ma non ricostruisce piu source snapshot/wiki/graph inline.
- Richiesta assistant normale resa non bloccante: se l'indice e stale o assente viene schedulato il worker e la risposta usa DB live + ultimo indice valido/fallback locale; la sync forzata resta esplicita via `force_sync`.
- Retrieval pgvector evita chiamate embedding quando il progetto non ha ancora chunk indicizzati, riducendo latenza e costi sul primo utilizzo.
- Aggiunti test anti-regressione su enqueue background senza apertura assistant, apertura tab non bloccante, domanda assistant senza sync inline e fallback senza embedding prima del primo indice.

Verifica quarto avanzamento:

- `python -m py_compile src\edilcloud\modules\assistant\signals.py src\edilcloud\modules\assistant\services.py`: pass.
- `python -m pytest tests/test_assistant_api.py::test_project_mutations_enqueue_assistant_indexing_without_opening_assistant tests/test_assistant_api.py::test_project_assistant_state_read_does_not_rebuild_sources_inline tests/test_assistant_api.py::test_project_assistant_ask_schedules_initial_sync_without_blocking tests/test_assistant_api.py::test_pgvector_retrieval_skips_embedding_when_project_has_no_indexed_chunks -q`: 4 passed.
- `python -m pytest tests/test_assistant_eval.py::test_project_wiki_feeds_source_snapshot_and_refreshes_when_project_changes tests/test_assistant_eval.py::test_project_graph_feeds_source_snapshot_and_refreshes_when_project_changes -q`: 2 passed.
- `python -m pytest tests/test_assistant_api.py -q`: 17 passed.
- `python -m pytest tests/test_assistant_eval.py tests/test_assistant_router.py -q`: 32 passed.
- `python manage.py run_assistant_eval --settings=edilcloud.settings.test`: 31/31 casi passati.
- `python manage.py run_assistant_quality_gate --settings=edilcloud.settings.test --limit 50`: pass dataset-only, 31/31.
- `python manage.py check --settings=edilcloud.settings.test`: pass.
- `python manage.py makemigrations --check --dry-run --settings=edilcloud.settings.test`: no changes.

Resta da completare:

- continuare a espandere dataset backend e demo oltre le 50 domande complessive, puntando a copertura piu ampia per singolo progetto e casi reali;
- completare contextual retrieval e hybrid search nel backend reale con metriche recall@k/nDCG e, se confermato, reranking piu forte;
- usare le nuove metriche per report prima/dopo su retrieval, citation support e noisy-context rate.

## Decisioni di prodotto da non prendere da soli

Queste decisioni richiedono conferma prima di implementare:

- usare modelli/costi aggiuntivi per reranking cloud
- rendere visibile la wiki agli utenti finali
- usare un modello LLM diverso per answer generation
- cambiare profondamente il design visuale dell'assistant tab
- introdurre dipendenze infrastrutturali nuove pesanti

## Decisioni tecniche che posso portare avanti autonomamente

Queste decisioni sono sicure e incrementali:

- rendere meno rigido il planner
- aggiungere answer shape
- migliorare il renderer markdown
- sistemare la data demo
- ridurre risposte template nella demo
- aggiungere dataset eval
- aggiungere metriche e log piu espliciti
- migliorare filtri retrieval gia esistenti
- aggiungere test per evitare regressioni

## Definition of done globale

Il lavoro e completo quando:

- il demo risponde in modo credibile e coerente
- le risposte non sono piu tutte impaginate allo stesso modo
- il backend usa la forma giusta per la domanda giusta
- il retrieval recupera prove migliori e meno rumorose
- le fonti supportano davvero le affermazioni principali
- la memoria progetto migliora le domande ampie
- il sistema ammette quando non sa
- esiste un quality report ripetibile
- la roadmap retrieval esistente resta coerente con questo piano

## Note operative per sessioni future

Prima di lavorare su architettura o codice assistant:

- leggere `graphify-out/GRAPH_REPORT.md`
- leggere questo file
- leggere `edilcloud-back-dn/docs/ASSISTANT_ARCHITETTURA_ATTUALE.md`
- leggere `edilcloud-back-dn/docs/ASSISTANT_RETRIEVAL_ROADMAP.md`

Dopo modifiche a codice assistant:

- eseguire test mirati
- aggiornare Graphify con `.\venv\Scripts\graphify.exe update .`
- riportare cosa e cambiato rispetto a questo piano
