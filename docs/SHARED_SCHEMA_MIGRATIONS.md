# Aggiornamento coordinato Django/Rust

Per un database condiviso usare `python manage.py migrate_shared`: senza
`--apply` mostra il piano senza scrivere. `python manage.py migrate_shared
--apply` verifica le sole adozioni native note e poi esegue le normali migrazioni
Django, sotto lo stesso lock di coordinamento del runner Rust.

La migrazione nativa delle assegnazioni di fase può essere adottata soltanto
con ricevuta/checksum corrispondenti e schema effettivo verificato. La sola
presenza della colonna `inherit_workers` non basta. La correzione dei lavoratori
storici non viene rieseguita: le scelte successive dell'utente restano intatte.

Il riferimento per i dati applicativi pubblici resta il modello/storia Django;
la distribuzione delle nuove versioni deve includere una migrazione compatibile
per entrambi i runtime. Il bootstrap Rust e la cache condivisa hanno controlli
distinti. Non eseguire automaticamente entrambi i runner all'avvio dei container.

Sequenza, lock, compatibilità dell'indice PostgreSQL 18, limiti di adozione e
rollback applicativo sono descritti nel repository Rust, documento
`docs/SHARED_SCHEMA_MIGRATIONS.md`. Non alterare migrazioni distribuite o usare
un `--fake` generale per nascondere divergenze. Nessuna modifica viene eseguita
sui database reali dal banco di prova di questo lavoro.
