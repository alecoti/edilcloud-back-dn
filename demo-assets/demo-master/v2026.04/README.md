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
- `documents/rilievo-foro-cucina-2b.pdf`
- `companies/serramenti/logo.png`
- `avatars/laura-ferretti.jpg`
