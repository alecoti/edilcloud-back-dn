# Elaborati

Area globale di redazione documentale, esposta da `/api/v1/elaborati` con la stessa autenticazione e gli stessi confini di accesso ai cantieri delle API esistenti. Comprende sei template versionati, fonti tracciate, proposte editoriali, firma personale, anteprima PDF e pubblicazione nel Drive con revisioni immutabili.

## Esecuzione

Le richieste HTTP accodano lavori persistenti. Avviare `python manage.py process_elaborati --interval 2` con le stesse impostazioni, database e volumi privati del backend. I compose includono il worker e il deploy blue/green ne gestisce l'avvicendamento. Le quattro migrazioni del modulo vengono applicate dal normale avvio del backend.

Il renderer richiede Chromium. L'immagine Docker installa browser e font e imposta `ELABORATI_CHROMIUM_EXECUTABLE=/usr/bin/chromium`. Fuori da Docker, installare il browser con `python -m playwright install --with-deps chromium`, oppure impostare un eseguibile compatibile. I test CI installano il browser e verificano un PDF reale.

L'AI usa `gpt-6-luna` attraverso la configurazione OpenAI esistente: reasoning, composizione e controllo sono richieste strutturate separate. Il worker registra consumo effettivo, budget prenotato e stato; non ripete automaticamente richieste AI di esito ambiguo.

## Integrità e limiti

- Bozze modificabili solo da chi può modificare il cantiere; pubblicazioni leggibili dai membri autorizzati. Firma privata per utente.
- Fonti deterministiche limitate a 450 elementi e 150.000 caratteri; eventuali troncamenti vengono dichiarati. I documenti riusano soltanto estratti indicizzati aggiornati. Le foto non vengono dichiarate analizzate visivamente.
- Salvataggi con versione ottimistica, azioni idempotenti, lease del worker e controllo dei permessi anche al completamento.
- Anteprima privata valida 20 minuti; la pubblicazione controlla hash, contenuto e consenso. Il PDF pubblicato è quello visualizzato, senza una seconda generazione lato client.
- Nessun caricamento remoto o JavaScript nel PDF. Lo schema dell'editor ammette esclusivamente contenuti validati, citazioni, tabelle e foto autorizzate.
- Le pubblicazioni non sono sovrascrivibili dalle API del Drive. Le nuove revisioni non ereditano una firma applicata.
- Il worker pulisce ogni ora i soli file privati orfani più vecchi di 24 ore. È disponibile `cleanup_elaborati --dry-run` per l'ispezione.

## Verifiche del 15 ottobre 2026

Suite specifica: 21 test passati, inclusi autorizzazioni, isolamento, idempotenza, tre passaggi AI, conflitti, firma, PDF Chromium reale, storico e protezione del Drive. Build Next di produzione e lint superati (rimangono avvisi preesistenti). Pipeline Luna e flussi di redazione, salvataggio, anteprima, pubblicazione e nuova revisione osservati su dati sintetici in web e Flutter Web. Non è stata verificata l'esecuzione nativa Android/iPad e non è stato generato un APK.
