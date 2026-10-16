"""Versioned editorial criteria, separate from factual and access controls."""

from collections import Counter
import re

VERSION = "2026.10.7"

BRIEFS = {
    "daily_report": [
        "Sintesi di ciò che risulta effettivamente avvenuto nella giornata, con luoghi e lavorazioni identificabili.",
        "Attività eseguite e comunicazioni delle imprese; distinguere programmi e incarichi dalle esecuzioni registrate. Non dedurre presenze dai membri.",
        "Problemi concreti, comunicazioni, azioni richieste e riscontri; attribuire ogni decisione al suo autore.",
        "Usare solo il meteo salvato e la sua data; non interpolare il meteo di una giornata mancante.",
        "Raccogliere una sola volta le lacune rilevanti, indicando cosa servirebbe per completare il rapporto.",
    ],
    "inspection": [
        "Scopo del sopralluogo, luoghi e data effettivamente dichiarati; il periodo scelto non dimostra che la visita sia avvenuta.",
        "Solo partecipanti esplicitamente dichiarati presenti, con fonte; distinguere autori dei post e persone soltanto citate.",
        "Rilievi concreti raggruppati per zona o lavorazione, separando osservazioni dirette e dichiarazioni altrui.",
        "Decisioni e indicazioni con autore, destinatario e scadenza solo se documentati; le proposte restano proposte.",
        "Controlli ancora aperti e riscontri mancanti. Una verifica richiesta non equivale a verifica eseguita.",
    ],
    "coordination": [
        "Oggetto e circostanze effettivamente registrate, senza inventare una riunione a partire da conversazioni asincrone.",
        "Partecipanti dichiarati, mai dedotti dalla lista membri o dalla firma di un messaggio.",
        "Argomenti distinti, posizioni espresse e interferenze tra lavorazioni, evitando una trascrizione del feed.",
        "Decisioni esplicite con attribuzione, eventuali incarichi e termini documentati; evidenziare modifiche successive.",
        "Questioni irrisolte, risposte attese e responsabilità solo quando risultano dalle fonti.",
    ],
    "periodic_report": [
        "Sintesi direzionale concreta: fatti principali del periodo, criticità aperte ed esito disponibile; niente slogan o valutazioni generiche.",
        "Progressi effettivamente documentati, ordinati per fase o zona; nessuna percentuale ricavata dal numero dei post o dallo stato attuale del Gantt.",
        "Criticità e interferenze, evoluzione ed eventuale chiusura documentata; non classificare chiuso ciò che è soltanto assegnato.",
        "Decisioni, variazioni e azioni concordate, con interlocutori e scadenze soltanto se espliciti.",
        "Documenti e foto pertinenti: revisioni, riferimenti e contesto. Non descrivere visivamente una foto non analizzata.",
        "Informazioni mancanti e verifiche necessarie per il periodo, senza ripetere tutte le altre sezioni.",
    ],
    "photo_report": [
        "Oggetto, intervallo temporale e zone documentate; chiarire se il materiale copre solo parte del periodo.",
        "Ordinare fotografie per evento, area e lavorazione; didascalie specifiche con data e contesto documentato, senza deduzioni visive.",
        "Osservazioni supportate dai messaggi collegati alle foto, con autore e distinzione fra segnalazione e riscontro.",
        "Date, localizzazioni o verifiche mancanti, espresse una volta e senza simulare un'ispezione fotografica.",
    ],
    "issue_report": [
        "Identificare l'evento richiesto, zona, lavorazione e soggetti documentati; non trasformare altri problemi del progetto nello stesso evento.",
        "Cronologia con date e ore delle registrazioni, distinguendole dalle date del fatto narrato. Antecedenti fuori periodo restano contesto.",
        "Evidenze primarie, interlocuzioni e riscontri, conservando contraddizioni e attribuzioni; un duplicato non è una nuova conferma.",
        "Ultimo esito supportato e sua data: separare risoluzione documentata, azione proposta, assegnazione e stato ancora non verificato.",
        "Questioni aperte e riscontri necessari; non inventare cause, responsabilità o impatti contrattuali.",
    ],
}


def editorial_contract(revision, *, for_review=False, section_keys=None):
    from .document_structure import registers_for

    template = revision.template_snapshot
    if section_keys is not None:
        template = {**template, "sections": [s for s in template["sections"] if s["key"] in section_keys]}
    briefs = BRIEFS[revision.elaborato.document_type]
    result = {
        "version": VERSION,
        "document_structure": {
            "required_tables": registers_for(template),
            "table_contract": "required_tables contiene i registri obbligatori, ognuno con rows di celle nominate secondo columns. Ogni cella contiene paragraphs: affermazioni separate, ciascuna con le proprie fonti e nature. Se nello stesso punto ci sono una proposta, un piano e una decisione, usa paragrafi distinti nella cella, senza assegnare una sola natura a tutti. Il backend costruisce intestazioni e proporzioni. Compila tutte le celle con fatti citati o campi editabili specifici; nessuna presenza o misura inventata. Gli indici table nel layout partono dai registri obbligatori nell'ordine qui indicato, seguiti dalle eventuali tables aggiuntive. Puoi lasciare layout [] per l'ordine standard completo.",
            "block_order": "Ogni sezione può specificare layout con kind/index per alternare paragraph, list, table e photo (indici da 0 per ciascun tipo nella sezione). kind heading con label introduce un gruppo H3. Se layout è valorizzato deve comprendere ogni elemento della sezione esattamente una volta; lascia [] per l'ordine standard. Nelle relazioni fotografiche usa gruppi per area con foto e osservazioni vicine. Le tabelle possono indicare widths come pesi percentuali delle colonne; preferire 3–5 colonne leggibili e intestazioni/campi brevi.",
            "layout": "reference-20261015",
            "required_elements": STRUCTURES[revision.elaborato.document_type] if section_keys is None else [
                "Redigere esclusivamente la porzione assegnata con i suoi registri e fatti; "
                "le altre sezioni e la firma finale vengono assemblate dal backend."
            ],
            "editable_fields": {
                "syntax": "Nello schema API ogni affermazione contiene parts: elementi {text: testo} oppure {field: definizione del campo}. Non scrivere manualmente marcatori {{...}} né una lista separata delle definizioni. Il backend costruisce il formato portabile per l'editor.",
                "kinds": [
                    "text",
                    "person",
                    "company",
                    "date",
                    "time",
                    "hours",
                    "quantity",
                    "signature",
                ],
                "example": {
                    "source_ids": [],
                    "nature": "unverified",
                    "parts": [
                        {
                            "field": {
                                "key": "ore_ordinarie",
                                "label": "Ore ordinarie",
                                "kind": "hours",
                                "unit": "h",
                            }
                        }
                    ],
                },
                "rules": [
                    "Struttura un documento completo, con tabelle e sezioni operative previste, anche se alcuni valori arriveranno in futuro. Per quei valori usa campi editabili, senza inventarli e senza sostituire ogni tabella con prosa sulle lacune.",
                    "Ogni campo ha una chiave unica in tutto il documento. Etichette e testi sono nella lingua richiesta. Una cella contenente solo un placeholder è unverified e non richiede fonti.",
                    "Usa person per partecipanti o referenti da confermare, hours per ore, quantity con unità per quantità; date/time per date e orari. Non compilare un campo mancante col nome di un membro del team.",
                    "Le firme previste dal documento sono campi signature vuoti: non attestano adesione, presenza, firma o approvazione di nessuno. La sottoscrizione effettiva rimane separata e richiede conferma personale.",
                    "Quando un valore è già documentato usa la normale affermazione citata, non un campo vuoto duplicato. I dati futuri sono campi specifici, non un invito generico a raccogliere informazioni.",
                ],
            },
            "photographs": "Inserire fotografie pertinenti nella section_key che le spiega, con titolo specifico, didascalia e provenienza. Usare layout half per confronti a due immagini e full per dettagli. Il renderer numera foto e fonti e separa data del contenuto e caricamento.",
        },
        "sections": [
            {"key": section["key"], "purpose": brief}
            for section in template["sections"]
            for brief in [briefs[int(section["key"].removeprefix("section_")) - 1]]
        ],
        "writing": [
            "Aprire con l'esito operativo utile e le condizioni ancora aperte, evitando una prima frase che ripeta solo titolo o data. Se una fonte impone un prerequisito esplicito, conservarlo fra le condizioni di avanzamento; non negare genericamente ogni decisione perché mancano incarichi nominativi o termini.",
            "Campi da compilare: nei paragrafi e nelle celle usare una formulazione neutra valida anche dopo la compilazione, per esempio «Data dello scatto:» seguita dal campo date. Non scrivere accanto al campo «non documentato», «mancante» o «da confermare»: dopo il completamento quella frase diventerebbe falsa. La natura mancante è già esplicita nel campo vuoto.",
            "Non anteporre «Proposta:», «Decisione:» o altre etichette di classificazione nel testo: le aggiunge la presentazione a partire da nature. Preferire registri azioni a tre o quattro colonne leggibili, riunendo referente e termine oppure stato e riscontro.",
            "Densità editoriale dei documenti ideali: registri sintetici ma completi, con una riga per evento o azione operativa. Riunire i messaggi del medesimo thread e riportare separatamente solo i cambiamenti sostanziali. Non trascrivere il feed né ripetere gli stessi dettagli in sintesi, cronologia, tabella azioni e lacune.",
            "Titolo formale breve del tipo di elaborato, sottotitolo specifico sull'oggetto della commessa. Non ripetere il nome del progetto nel titolo, perché è già nell'intestazione. Non stampare istruzioni di redazione come sottotitolo.",
            "Esprimere le ore nel fuso time_zone del cantiere indicato nelle fonti (Europe/Rome per questi esempi), senza convertirle in UTC o confonderle con l'ora del server.",
            "Sviluppare tutto il contenuto necessario, senza limiti editoriali di token, parole o pagine e senza abbreviare per risparmiare output. Completezza e pertinenza determinano l'estensione; non aggiungere ripetizioni o riempitivi.",
            "Il risultato deve essere operativo: cosa è successo, dove, quando, chi lo dichiara, quale decisione è stata presa, cosa resta aperto e quale riscontro serve. Non riempire sezioni con la sola anagrafica del progetto.",
            "Una data di fine prevista superata non è una criticità da ripetere ovunque: citarla solo quando pertinente a un confronto effettivo con il programma. Non assumere che il cantiere sia concluso da quella data.",
            "Non inventare dati integrativi per mostrare un documento ideale: le integrazioni dimostrative sono ammesse solo se dichiarate esplicitamente dall'utente e devono restare identificate come tali.",
            "Scrivere nella lingua richiesta, con tono professionale chiaro e frasi concrete. Niente marketing, preamboli generici o spiegazioni del motore AI.",
            "Proporzionare il documento alle informazioni: poche fonti non giustificano pagine di riempitivo. Una buona sintesi non deve omettere decisioni o esiti rilevanti.",
            "Ogni sezione deve aggiungere informazione: la sintesi introduce, le sezioni sviluppano. Non copiare lo stesso paragrafo in più sezioni.",
            "Citazioni strutturate, senza stampare ID tecnici nel testo. Conservare nomi, unità, localizzazioni e qualificazioni presenti nelle fonti.",
            "Liste per rilievi o azioni distinti; tabelle soltanto per confronti realmente utili, con celle tutte supportate. Non creare tabelle ornamentali.",
            "Distinguere data del messaggio, data dell'evento e data di acquisizione. Non usare aggiornamenti odierni come avanzamento storico.",
            "Per gli stati del periodo usare «ultimo stato registrato il ...»: senza un nuovo riscontro non attestare che lo stato persista fino alla data finale. L'assenza di una chiusura documentata non dimostra che la chiusura non sia avvenuta.",
            "Una dichiarazione in un post è una fonte operativa utilizzabile: attribuirla quando rilevante, senza richiedere verifiche indipendenti o certificati non previsti dal template o richiesti esplicitamente nelle fonti. Non trasformare questi controlli ulteriori in lacune del cantiere.",
            "La copertina contiene già cantiere e periodo. Riunire le informazioni mancanti nella sezione dedicata; evitare di ripetere le medesime cautele in sintesi, criticità, decisioni e conclusioni. Distinguere autorizzazione a riprendere e ripresa effettiva con una sola precisazione, dove serve.",
        ],
    }
    if for_review:
        structure = result["document_structure"]
        registers = structure.pop("required_tables")
        structure.pop("table_contract")
        structure.pop("block_order")
        structure["operational_registers"] = {
            key: [{"purpose": r["purpose"], "concepts": r["labels"]} for r in tables]
            for key, tables in registers.items()
        }
        structure["table_review"] = (
            "Verifica le informazioni operative, non il numero o i nomi esatti delle colonne. "
            "L'editor permette di unire celle e riorganizzare colonne: stato e riscontro possono "
            "stare nella stessa cella se restano distinguibili e completi. Una differenza di "
            "presentazione non è una falsità. Segnala carenze di leggibilità come warning; "
            "mantieni blocking per perdita sostanziale di informazioni, attribuzioni false "
            "e contraddizioni. La sintassi API del generatore non è un requisito documentale."
        )
    return result


STRUCTURES = {
    "daily_report": [
        "Sintesi operativa con esito e impedimenti della giornata.",
        "Registro cronologico: ora, fronte/lavorazione/impresa, attività effettiva e fonte.",
        "Tabella imprese e risorse: impresa, persona/addetti dichiarati, ore ordinarie e straordinarie, quantità/unità; usare placeholder specifici per i dati futuri.",
        "Meteo registrato e sua ora, fotografie dei rilievi, azioni con referente/termine e criterio di chiusura.",
        "Quantità e impatti documentati; campi di completamento e spazi per redattore e presa visione.",
    ],
    "inspection": [
        "Esito, oggetto, luoghi e scopo circoscritti; data e orari della visita da confermare quando assenti.",
        "Tabella presenti dichiarati con persona, impresa, ruolo professionale e presenza da confermare; autori dei messaggi distinti dai partecipanti.",
        "Antecedenti separati dai riscontri attuali, fotografie dei punti controllati e tabella criteri/riscontro/esito.",
        "Disposizioni, registro azioni con referente/termine/criterio di chiusura; esiti interni distinti da collaudi o accettazioni contrattuali.",
        "Allegati, punti da completare e sottoscrizioni previste ancora da acquisire.",
    ],
    "coordination": [
        "Identificazione della riunione: oggetto, data, luogo/modalità, orari, convocante e verbalizzante.",
        "Partecipanti effettivi e rispettive imprese/ruoli da dichiarare, ordine degli argomenti e posizioni espresse.",
        "Registro dei punti trattati, decisioni e prerequisiti espliciti, interferenze e condizioni di avanzamento.",
        "Tabella azioni: azione, referente, termine, stato e riscontro necessario; placeholder per incarichi e termini non documentati.",
        "Questioni aperte, obiezioni/modifiche, distribuzione e presa visione; nessuna riunione o adesione inventata.",
    ],
    "periodic_report": [
        "Sintesi direzionale con stato alla fine del periodo, risultati e principali impedimenti.",
        "Perimetro temporale e registro avanzamenti/risultati per zona e lavorazione.",
        "Confronto col programma: versione/data di stato e quantità/percentuali solo se documentate, altrimenti campi compilabili; nessun SAL dedotto.",
        "Registro criticità alla data di riferimento, evidenze fotografiche e stato aperto/chiuso motivato.",
        "Decisioni da conservare, registro azioni/responsabili/termini, dati consuntivi da integrare e sottoscrizioni.",
    ],
    "photo_report": [
        "Oggetto, periodo e aree documentate; registro delle fotografie numerate con contesto e fonte.",
        "Gruppi per luogo/lavorazione/evento, immagini effettive grandi e leggibili, titoli e didascalie specifiche.",
        "Data del contenuto, data di caricamento e data dello scatto distinte: se lo scatto non è noto predisporre un campo data e non attribuire il giorno del post allo scatto.",
        "Per ogni gruppo: rilievo documentato, eventuale azione, stato alla data e limiti dell'osservazione; nessuna misura o certificazione dedotta visivamente.",
        "Destinazione del documento, allegati, registro fonti e firme da acquisire.",
    ],
    "issue_report": [
        "Identificazione tecnica della criticità: luogo, lavorazione, requisito/riferimento e stato aperto o chiuso alla data.",
        "Cronologia datata di segnalazioni, proposte, decisioni e riscontri, conservando gli antecedenti pertinenti.",
        "Immagini leggibili del rilievo e collegamento a tavole/posizioni/documenti quando disponibili.",
        "Impatto e priorità documentati, tabella piano di trattamento con azione, referente, termine e condizione di chiusura.",
        "Riscontro conclusivo e verificatore solo se attestati; altrimenti campi specifici e firma da acquisire. Non trasformare la proposta in correzione eseguita.",
    ],
}


def coverage(editor, evidence, claims):
    sources = {source["id"]: source for source in evidence.get("sources", [])}
    cited = {sid for claim in claims for sid in claim["source_ids"] if sid in sources}
    return {
        "available_sources": len(sources),
        "cited_sources": len(cited),
        "cited_by_kind": dict(Counter(sources[sid]["kind"] for sid in cited)),
        "claims": len(claims),
        "unverified_claims": sum(claim["nature"] == "unverified" for claim in claims),
    }


def repetition_issues(claims):
    groups = {}
    significant = [
        claim for claim in claims if claim["nature"] != "unverified" and len(claim["text"]) >= 70
    ]
    for claim in significant:
        key = re.sub(r"\W+", " ", claim["text"].casefold()).strip()
        groups.setdefault(key, []).append(claim)
    duplicates = [
        items for items in groups.values() if len({item["section_key"] for item in items}) > 1
    ]
    repeated = sum(len(items) for items in duplicates)
    severe = repeated >= 3 and repeated / max(1, len(significant)) >= 0.6
    return [
        {
            "section_key": items[-1]["section_key"],
            "text": items[-1]["text"],
            "severity": "blocking" if severe else "warning",
            "explanation": "Lo stesso contenuto è ripetuto in più sezioni. Mantenere la sintesi e sviluppare informazioni specifiche nelle sezioni successive.",
        }
        for items in duplicates
    ]
