# Demo Master Asset Source

Questa cartella e' la sorgente stabile degli asset demo reali.

Il seed `seed_rich_demo_project` cerca qui prima di generare i fallback placeholder.

Struttura consigliata:

```text
demo-assets/demo-master/v2026.04/
  companies/<company-code>/logo.(svg|png|jpg|jpeg|webp)
  avatars/<person-code>.(jpg|jpeg|png|webp)
  documents/<file-stem>.*
  drawings/<file-stem>.*
  photos/<file-stem>.*
  attachments/<file-stem>.*
```

Regole pratiche:

- mantieni lo stesso `file-stem` del placeholder;
- puoi cambiare estensione se il file e' davvero del tipo giusto;
- dopo ogni sostituzione rilancia il seed demo;
- per vedere dove ogni asset finisce nel backend usa:

```bash
PYTHONPATH=src python manage.py report_demo_master_assets
PYTHONPATH=src python manage.py report_demo_master_assets --format json
```

Esempi:

- `drawings/fa-312-nodo-serramento-davanzale.jpg`
- `photos/fronte-sud-ovest.jpg`
- `attachments/mockup-facciata-sud-ovest.png`
- `attachments/foundation-box-03-04-field-note.wav`
- `documents/rilievo-foro-cucina-2b.pdf`
- `companies/serramenti/logo.png`
- `avatars/laura-ferretti.jpg`

## Generazione da blueprint editoriale

Per generare gli asset media del demo a partire dal blueprint editoriale usando Gemini:

```bash
cd edilcloud-back-dn
PYTHONPATH=src python manage.py generate_demo_master_blueprint_media
```

Opzioni utili:

```bash
PYTHONPATH=src python manage.py generate_demo_master_blueprint_media --dry-run
PYTHONPATH=src python manage.py generate_demo_master_blueprint_media --document-ref punch-list-parti-comuni.pdf
PYTHONPATH=src python manage.py generate_demo_master_blueprint_media --skip-drawings --skip-images --skip-audio
PYTHONPATH=src python manage.py generate_demo_master_blueprint_media --drawing-code st-204
PYTHONPATH=src python manage.py generate_demo_master_blueprint_media --asset-stem mockup-facciata-sud-ovest
PYTHONPATH=src python manage.py generate_demo_master_blueprint_media --audio-ref foundation-box-03-04-field-note
PYTHONPATH=src python manage.py generate_demo_master_blueprint_media --limit-documents 2 --limit-drawings 2 --limit-images 3 --limit-audio 3
```

Il comando:

- legge `demo-assets/demo-master/blueprints/v2026.04/editorial-project-blueprint.json`;
- genera PDF di sopralluoghi, rapportini, checklist e verbali in `demo-assets/demo-master/v2026.04/documents/`;
- genera disegni planimetrici plausibili in `demo-assets/demo-master/v2026.04/drawings/`;
- genera immagini e audio nelle cartelle sorgente stabili del demo;
- conserva nel blueprint i summary contestuali che spiegano perche' lo stesso documento puo' comparire in piu' fasi o lavorazioni;
- scrive un manifest in `demo-assets/demo-master/blueprints/v2026.04/generated-media-manifest.json`.
