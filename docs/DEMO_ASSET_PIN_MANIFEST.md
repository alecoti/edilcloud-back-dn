# Demo Asset e Pin Manifest

Ultimo aggiornamento: 2026-04-12

Questo manifest descrive gli asset e i pin canonici del Demo Master.

Stato attuale:

- manifest documentale;
- non ancora modello backend;
- non ancora usato dal seed per creare pin persistenti;
- pensato per essere convertito in fixture JSON o modello snapshot.

## Regole production-first

- Gli asset reali non devono essere caricati manualmente in produzione senza una voce manifest.
- Ogni asset deve avere un fallback generabile dal seed.
- Nessun asset demo pubblico deve puntare a file privati di clienti reali.
- Ogni sessione demo deve referenziare asset demo/snapshot, non asset di progetti reali.
- I pin devono essere versionati con lo snapshot, non salvati solo in `localStorage`.

## Asset folders consigliate

Cartella sorgente stabile prevista dal backend seed:

`edilcloud-back-dn/demo-assets/demo-master/v2026.04/`

Quando introduciamo asset reali, usare questa struttura esplicita:

```text
demo-master/
  v2026.04/
    companies/
      studio/logo.png
      gc/logo.png
      strutture/logo.png
      elettrico/logo.png
      meccanico/logo.png
      serramenti/logo.png
      finiture/logo.png
      committente/logo.png
    avatars/
      laura-ferretti.jpg
      marco-rinaldi.jpg
      luca-gatti.jpg
      ...
    documents/
      cronoprogramma-generale-lotto-a.pdf
      registro-criticita-aprile.pdf
      ...
    drawings/
      ar-101-pianta-piano-terra.svg
      fa-312-nodo-serramento-davanzale.svg
      ...
    photos/
      fronte-sud-ovest.jpg
      centrale-termica.jpg
      ...
    audio/
      nota-vocale-copertura-ovest.m4a
      nota-vocale-foro-2b.m4a
      nota-vocale-collaudi.m4a
    video/
      sopralluogo-bagno-2b.mp4
      centrale-termica-precollaudo.mp4
    attachments/
      mockup-facciata-sud-ovest.png
      centrale-termica-precollaudo.jpg
      bagno-campione-2b.jpg
```

## Aziende e loghi

| Codice | Azienda | Asset atteso | Fallback seed |
| --- | --- | --- | --- |
| `studio` | Studio Tecnico Ferretti Associati | `companies/studio/logo.png` | logo SVG generato |
| `gc` | Aurora Costruzioni Generali | `companies/gc/logo.png` | logo SVG generato |
| `strutture` | Strutture Nord Calcestruzzi | `companies/strutture/logo.png` | logo SVG generato |
| `elettrico` | Elettroimpianti Lombardi | `companies/elettrico/logo.png` | logo SVG generato |
| `meccanico` | Idrotermica Futura | `companies/meccanico/logo.png` | logo SVG generato |
| `serramenti` | Serramenti Milano Contract | `companies/serramenti/logo.png` | logo SVG generato |
| `finiture` | Interni Bianchi Srl | `companies/finiture/logo.png` | logo SVG generato |
| `committente` | Immobiliare Naviglio Srl | `companies/committente/logo.png` | logo SVG generato |

## Avatar personas

| Persona | Asset atteso | Fallback |
| --- | --- | --- |
| Laura Ferretti | `avatars/laura-ferretti.jpg` | iniziali LF |
| Marco Rinaldi | `avatars/marco-rinaldi.jpg` | iniziali MR |
| Luca Gatti | `avatars/luca-gatti.jpg` | iniziali LG |
| Paolo Longhi | `avatars/paolo-longhi.jpg` | iniziali PL |
| Giulia Roversi | `avatars/giulia-roversi.jpg` | iniziali GR |
| Martina Cattaneo | `avatars/martina-cattaneo.jpg` | iniziali MC |
| Antonio Esposito | `avatars/antonio-esposito.jpg` | iniziali AE |
| Valentina Neri | `avatars/valentina-neri.jpg` | iniziali VN |

## Documenti canonici

| Codice | Titolo | File seed/fallback | Cartella |
| --- | --- | --- | --- |
| `doc-cronoprogramma` | Cronoprogramma generale lotto A | `cronoprogramma-generale-lotto-a.pdf` | Direzione Lavori |
| `doc-verbale-impianti-14` | Verbale coordinamento impianti settimana 14 | `verbale-coordinamento-impianti-settimana-14.pdf` | Direzione Lavori/Verbali |
| `doc-mockup-facciata` | Scheda mockup facciata e serramenti | `scheda-mockup-facciata-serramenti.pdf` | Facciata/Mockup |
| `doc-piano-collaudi` | Piano collaudi integrati | `piano-collaudi-integrati.pdf` | Impianti/Check e prove |
| `doc-registro-criticita` | Registro criticita aprile | `registro-criticita-aprile.pdf` | Direzione Lavori |
| `doc-psc` | PSC aggiornato rev02 | `psc-aggiornato-rev02.pdf` | Sicurezza |
| `doc-pos-briefing` | Verbale briefing avvio e POS imprese | `verbale-briefing-avvio-pos-imprese.pdf` | Sicurezza/Verbali |
| `doc-foro-2b` | Rilievo foro cucina 2B | `rilievo-foro-cucina-2b.pdf` | Facciata/Rilievi |
| `doc-valvole` | Checklist valvole bilanciamento centrale termica | `checklist-valvole-bilanciamento.pdf` | Impianti/Check e prove |
| `doc-massetti` | Verifica quote massetti 1A-3C | `verifica-quote-massetti-1a-3c.pdf` | Finiture/Quote |
| `doc-punch-list` | Punch list parti comuni | `punch-list-parti-comuni.pdf` | Consegna/Punch list |
| `doc-as-built` | Pacchetto as-built preliminare | `pacchetto-as-built-preliminare.pdf` | Consegna/As built |
| `doc-fascicolo` | Fascicolo manutenzione preliminare | `fascicolo-manutenzione-preliminare.pdf` | Consegna/Manutenzione |
| `doc-tenuta-copertura` | Verbale prova tenuta copertura ovest | `verbale-prova-tenuta-copertura-ovest.pdf` | Copertura/Prove |
| `doc-quadro-q3` | Schema aggiornato quadro Q3 | `schema-aggiornato-quadro-q3.pdf` | Impianti/Elettrico |

## Tavole canoniche

| Codice | Titolo | File seed/fallback | Uso demo |
| --- | --- | --- | --- |
| `ar-101` | AR-101 Pianta piano terra e corte interna | `ar-101-pianta-piano-terra.svg` | hall, corte, autorimessa |
| `ar-205` | AR-205 Piante tipo alloggi 1A-2B-3C | `ar-205-piante-tipo-alloggi.svg` | quote alloggi e massetti |
| `st-204` | ST-204 Platea e setti interrati | `st-204-platea-setti.svg` | passaggi platea |
| `fa-301` | FA-301 Facciata sud-ovest | `fa-301-facciata-sud-ovest.svg` | facciata e copertura |
| `fa-312` | FA-312 Nodo serramento e davanzale | `fa-312-nodo-serramento-davanzale.svg` | foro cucina 2B |
| `im-220` | IM-220 Centrale termica e dorsali | `im-220-centrale-termica.svg` | valvole e collaudi |
| `im-245` | IM-245 VMC corridoi e bagni | `im-245-vmc-corridoi-bagni.svg` | VMC corridoio nord |
| `el-240` | EL-240 Quadri di piano e dorsali FM | `el-240-quadri-dorsali.svg` | quadro Q3 |
| `el-260` | EL-260 Sistemi speciali e citofonia | `el-260-sistemi-speciali-citofonia.svg` | monitor hall |
| `fn-110` | FN-110 Bagno campione 2B | `fn-110-bagno-campione-2b.svg` | bagno campione |

## Foto operative canoniche

| Codice | Titolo | File seed/fallback | Collegamento narrativo |
| --- | --- | --- | --- |
| `photo-fronte-sud-ovest` | Fronte sud-ovest | `fronte-sud-ovest.svg` | facciata/serramenti |
| `photo-centrale-termica` | Centrale termica | `centrale-termica.svg` | valvole e collaudi |
| `photo-bagno-2b` | Bagno campione 2B | `bagno-campione-2b-overview.svg` | finiture |
| `photo-vano-scala-b` | Vano scala B | `vano-scala-b.svg` | rasature e parti comuni |
| `photo-copertura-ovest` | Copertura risvolto ovest | `copertura-risvolto-ovest.svg` | issue risolta copertura |
| `photo-foro-2b` | Rilievo foro cucina 2B | `foro-cucina-2b-rilievo.svg` | issue aperta serramenti |
| `photo-massetti-1a-3c` | Quote massetti alloggi 1A e 3C | `massetti-alloggi-1a-3c.svg` | issue aperta finiture |
| `photo-quadro-q3` | Quadro Q3 linee speciali | `quadro-q3-linee-speciali.svg` | issue risolta elettrico |
| `photo-vmc-corridoio` | VMC corridoio nord | `vmc-corridoio-nord.svg` | coordinamento impianti |
| `photo-monitor-hall` | Hall monitor citofonico | `hall-monitor-citofonico.svg` | decisione committente |

## Audio e video futuri

Questi asset non sono ancora generati dal seed.

| Codice | Tipo | File atteso | Collegamento |
| --- | --- | --- | --- |
| `audio-copertura-ovest` | audio | `nota-vocale-copertura-ovest.m4a` | commento su impermeabilizzazione |
| `audio-foro-2b` | audio | `nota-vocale-foro-2b.m4a` | issue foro cucina 2B |
| `audio-collaudi` | audio | `nota-vocale-collaudi.m4a` | prerequisiti collaudi |
| `video-bagno-2b` | video | `sopralluogo-bagno-2b.mp4` | bagno campione |
| `video-centrale-termica` | video | `centrale-termica-precollaudo.mp4` | centrale termica |

## Pin canonici

I pin devono diventare entita snapshot/backend. Per ora sono manifestati qui.

| Pin | Tavola | X | Y | Stato | Thread/tema |
| --- | --- | ---: | ---: | --- | --- |
| `pin-foro-cucina-2b` | `fa-312` | 62 | 38 | aperto | fuori quota foro cucina 2B |
| `pin-copertura-ovest` | `fa-301` | 74 | 18 | risolto | nodo risvolto ovest copertura |
| `pin-valvole-centrale` | `im-220` | 34 | 46 | aperto | valvole bilanciamento mancanti |
| `pin-vmc-corridoio-nord` | `im-245` | 56 | 42 | aperto | VMC corridoio nord |
| `pin-quadro-q3` | `el-240` | 66 | 34 | risolto | riallineamento linee speciali Q3 |
| `pin-monitor-hall` | `el-260` | 28 | 52 | aperto | posizione monitor citofonico hall |
| `pin-massetto-1a` | `ar-205` | 42 | 58 | aperto | quota massetto unita 1A |
| `pin-massetto-3c` | `ar-205` | 72 | 61 | aperto | quota massetto unita 3C |
| `pin-bagno-2b` | `fn-110` | 48 | 44 | informativo | bagno campione 2B |
| `pin-passaggi-box-03-04` | `st-204` | 58 | 63 | risolto | passaggi impiantistici platea box 03-04 |

## Mapping futuro pin -> dati applicativi

Quando verra' creato il modello backend o fixture snapshot, ogni pin dovra' mappare:

- `snapshot_version`;
- `project_id`;
- `drawing_asset_code`;
- `task_family`;
- `activity_title` o identificatore stabile;
- `post_kind`;
- `post_title`/snippet;
- `document_code`;
- `status`;
- `x_percent`;
- `y_percent`;
- `created_by_person_code`.

## Prossimo passo tecnico

Prima versione implementabile:

1. creare fixture JSON da questo manifest;
2. aggiungere loader seed per creare tavole/foto/documenti da manifest;
3. aggiungere endpoint read-only per pin demo;
4. modificare il tab disegni per leggere pin dal backend quando disponibili;
5. mantenere `localStorage` solo come fallback playground/sessione.

## Workflow pratico di sostituzione asset

Obiettivo: non inseguire file casuali dentro il backend, ma sostituire una sorgente stabile e poi rigenerare il Demo Master.

Passi:

1. metti il file reale nella cartella `demo-assets/demo-master/v2026.04/` mantenendo lo stesso `file-stem`;
2. puoi cambiare estensione se il file e' coerente:
   - foto/tavole: `.svg`, `.png`, `.jpg`, `.jpeg`, `.webp`;
   - documenti: `.pdf`, `.docx`, `.xlsx`, `.zip`;
3. rilancia il seed demo;
4. verifica i path finali con:

```bash
PYTHONPATH=src python manage.py report_demo_master_assets
PYTHONPATH=src python manage.py report_demo_master_assets --format json
```

Il report mostra:

- codice asset;
- categoria;
- file sorgente atteso;
- path relativo attuale nel backend;
- URL attuale;
- presenza o meno del file sorgente reale.

Nota importante:

- i path finali nel backend restano legati al `project_id` del progetto seedato;
- la sorgente in `demo-assets/demo-master/v2026.04/` invece e' stabile e va trattata come punto di verita per le sostituzioni.
