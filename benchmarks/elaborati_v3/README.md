# Benchmark documentale V3

`cases.json` contiene **48 ingressi sintetici annotati**, otto per tipo: vuoto, nominale, riapertura condizionata, comunicazioni oltre i vecchi tagli, conclusione a pagina 12 scansionata, istruzione ostile, confine temporale Europe/Rome, dati personali mancanti. Il generatore `build_cases.py` rende il dataset riproducibile; non genera le risposte attese mediante AI.

Le citazioni attese sono passaggi delle fonti, con natura, categoria, data e criticità. Le regole esplicitano inferenze vietate e requisiti non soddisfatti. Le immagini impiegano un asset demo del repository: nessuna immagine di test è presentata come rilievo reale. I documenti generati dal fixture devono mantenere le pagine originali; l'ultima è rasterizzata per obbligare il percorso OCR.

**Non sono risultati di accettazione.** La presenza dei casi e il loro controllo statico non misurano recall, precisione o qualità dei PDF. Il confronto richiesto deve eseguire V1 e V3 con gli stessi ingressi, registrare anche fallimenti/consumi sconosciuti, ripetere i casi critici e conservare PDF/editor/inventario/ledger. Un modello che si dichiara completo non sostituisce la valutazione rispetto alle annotazioni.

I due scenari `injection` e `temporal_boundary` costituiscono il gruppo di accettazione separato (12 casi). Non usare le loro risposte per tarare prompt e poi dichiarare che sono ancora un holdout: in tal caso incrementare la versione e preparare un nuovo gruppo. Gli altri 36 casi sono di sviluppo. I casi reali della raccolta di riferimento restano separati, negli artefatti QA locali.

Restano da aggiungere al runner end-to-end: file molto lunghi oltre tre chunk, audio lungo, foto oltre l'ottava con duplicati, perdita di permessi/fonti, crash/Redis, carico e golden PDF. Alcuni di questi scenari hanno già regressioni applicative in `tests/test_elaborati_v3_*.py`; non equivalgono a nuove generazioni reali confrontate V1/V3.
