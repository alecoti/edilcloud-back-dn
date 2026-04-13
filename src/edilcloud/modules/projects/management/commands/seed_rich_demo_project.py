from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from edilcloud.modules.files.media_optimizer import optimize_media_content
from edilcloud.modules.projects.demo_master_assets import (
    AVATAR_SOURCE_EXTENSIONS,
    DEMO_ASSET_SOURCE_ROOT,
    DEMO_ASSET_VERSION,
    DOCUMENT_SOURCE_EXTENSIONS,
    IMAGE_SOURCE_EXTENSIONS,
    LOGO_SOURCE_EXTENSIONS,
    asset_code_for_filename,
    asset_placeholder_kind,
    find_demo_source_file,
    visual_source_dir_for_filename,
)
from edilcloud.modules.projects.models import (
    CommentAttachment,
    PostAttachment,
    PostComment,
    PostKind,
    ProjectCompanyColor,
    Project,
    ProjectActivity,
    ProjectDocument,
    ProjectFolder,
    ProjectMember,
    ProjectMemberStatus,
    ProjectPhoto,
    ProjectPost,
    ProjectStatus,
    ProjectTask,
    TaskActivityStatus,
)
from edilcloud.modules.workspaces.models import Profile, Workspace, WorkspaceRole


BLUEPRINT_TODAY = date(2026, 4, 4)
DEFAULT_VIEWER_EMAIL = "demo.viewer@edilcloud.local"
DEFAULT_VIEWER_PASSWORD = "demo1234!"

PROJECT_BLUEPRINT = {
    "name": "Residenza Parco Naviglio - Lotto A",
    "description": (
        "Nuova costruzione residenziale con 14 unita, autorimessa interrata, corte interna "
        "e fronti di lavoro paralleli tra involucro, impianti e finiture. Questo seed ricrea "
        "un cantiere vero, con dialoghi coerenti, issue aperte, issue risolte, documenti e allegati."
    ),
    "address": "Via Giuseppe Pezzotti 18, Milano",
    "google_place_id": "demo-via-giuseppe-pezzotti-18-milano",
    "latitude": 45.4462,
    "longitude": 9.1918,
    "date_start": "2025-08-01",
    "date_end": "2026-04-30",
}

DEMO_PROJECT_COMPANY_COLORS: dict[str, str] = {
    "studio": "#51606f",
    "gc": "#2e6f65",
    "strutture": "#3f5f8a",
    "elettrico": "#2b7a91",
    "meccanico": "#9a6536",
    "serramenti": "#6a6487",
    "finiture": "#9a5668",
    "committente": "#6a7352",
}
DEMO_VIEWER_PROJECT_COLOR = "#4b5563"

COMPANIES: list[dict[str, Any]] = [
    {
        "code": "studio",
        "name": "Studio Tecnico Ferretti Associati",
        "email": "studio@ferretti-associati.it",
        "vat": "11873450961",
        "color": "#b45309",
        "people": [
            ("laura-ferretti", "Laura", "Ferretti", "laura.ferretti@ferretti-associati.it", "Direzione lavori", WorkspaceRole.OWNER, ["responsabile_lavori", "cse"]),
            ("davide-sala", "Davide", "Sala", "davide.sala@ferretti-associati.it", "BIM coordinator", WorkspaceRole.MANAGER, ["csp"]),
            ("serena-costantini", "Serena", "Costantini", "serena.costantini@ferretti-associati.it", "Coordinatrice sicurezza", WorkspaceRole.DELEGATE, ["rspp"]),
            ("fabio-conti", "Fabio", "Conti", "fabio.conti@ferretti-associati.it", "Assistente DL", WorkspaceRole.WORKER, ["lavoratore"]),
        ],
    },
    {
        "code": "gc",
        "name": "Aurora Costruzioni Generali",
        "email": "commesse@auroracostruzioni.it",
        "vat": "10866270158",
        "color": "#0f766e",
        "people": [
            ("marco-rinaldi", "Marco", "Rinaldi", "marco.rinaldi@auroracostruzioni.it", "Project manager", WorkspaceRole.OWNER, ["datore_lavoro"]),
            ("luca-gatti", "Luca", "Gatti", "luca.gatti@auroracostruzioni.it", "Capocantiere", WorkspaceRole.MANAGER, ["preposto", "addetto_primo_soccorso"]),
            ("omar-elidrissi", "Omar", "El Idrissi", "omar.elidrissi@auroracostruzioni.it", "Caposquadra opere edili", WorkspaceRole.DELEGATE, ["preposto"]),
            ("enrico-vitali", "Enrico", "Vitali", "enrico.vitali@auroracostruzioni.it", "Gruista", WorkspaceRole.WORKER, ["lavoratore"]),
            ("samuele-rota", "Samuele", "Rota", "samuele.rota@auroracostruzioni.it", "Operaio specializzato", WorkspaceRole.WORKER, ["lavoratore", "addetto_antincendio_emergenza"]),
        ],
    },
    {
        "code": "strutture",
        "name": "Strutture Nord Calcestruzzi",
        "email": "operations@strutturenord.it",
        "vat": "10244710964",
        "color": "#1d4ed8",
        "people": [
            ("elisa-brambilla", "Elisa", "Brambilla", "elisa.brambilla@strutturenord.it", "Responsabile strutture", WorkspaceRole.OWNER, ["datore_lavoro"]),
            ("giorgio-bellini", "Giorgio", "Bellini", "giorgio.bellini@strutturenord.it", "Caposquadra carpentieri", WorkspaceRole.MANAGER, ["preposto"]),
            ("cristian-pavan", "Cristian", "Pavan", "cristian.pavan@strutturenord.it", "Ferrista", WorkspaceRole.WORKER, ["lavoratore"]),
            ("ionut-marin", "Ionut", "Marin", "ionut.marin@strutturenord.it", "Operatore betonpompa", WorkspaceRole.WORKER, ["lavoratore"]),
            ("bogdan-muresan", "Bogdan", "Muresan", "bogdan.muresan@strutturenord.it", "Carpentiere casseri", WorkspaceRole.WORKER, ["lavoratore"]),
        ],
    },
    {
        "code": "elettrico",
        "name": "Elettroimpianti Lombardi",
        "email": "cantieri@elettrolombardi.it",
        "vat": "09761530960",
        "color": "#0ea5e9",
        "people": [
            ("paolo-longhi", "Paolo", "Longhi", "paolo.longhi@elettrolombardi.it", "Capo commessa elettrico", WorkspaceRole.OWNER, ["datore_lavoro"]),
            ("andrea-fontana", "Andrea", "Fontana", "andrea.fontana@elettrolombardi.it", "Caposquadra impianti elettrici", WorkspaceRole.MANAGER, ["preposto"]),
            ("nicolas-moretti", "Nicolas", "Moretti", "nicolas.moretti@elettrolombardi.it", "Impiantista", WorkspaceRole.WORKER, ["lavoratore"]),
            ("marius-dumitru", "Marius", "Dumitru", "marius.dumitru@elettrolombardi.it", "Tiracavi", WorkspaceRole.WORKER, ["lavoratore"]),
            ("matteo-cerri", "Matteo", "Cerri", "matteo.cerri@elettrolombardi.it", "Special systems", WorkspaceRole.DELEGATE, ["addetto_antincendio_emergenza"]),
        ],
    },
    {
        "code": "meccanico",
        "name": "Idrotermica Futura",
        "email": "cantieri@idrotermicafutura.it",
        "vat": "10574490154",
        "color": "#ea580c",
        "people": [
            ("giulia-roversi", "Giulia", "Roversi", "giulia.roversi@idrotermicafutura.it", "Project manager HVAC", WorkspaceRole.OWNER, ["datore_lavoro"]),
            ("stefano-riva", "Stefano", "Riva", "stefano.riva@idrotermicafutura.it", "Caposquadra idraulico", WorkspaceRole.MANAGER, ["preposto"]),
            ("ahmed-bensalem", "Ahmed", "Bensalem", "ahmed.bensalem@idrotermicafutura.it", "Canalista", WorkspaceRole.WORKER, ["lavoratore"]),
            ("filippo-orsenigo", "Filippo", "Orsenigo", "filippo.orsenigo@idrotermicafutura.it", "Frigorista", WorkspaceRole.DELEGATE, ["lavoratore"]),
            ("rachid-ziani", "Rachid", "Ziani", "rachid.ziani@idrotermicafutura.it", "Tubista", WorkspaceRole.WORKER, ["lavoratore"]),
        ],
    },
    {
        "code": "serramenti",
        "name": "Serramenti Milano Contract",
        "email": "cantieri@serramentimilano.it",
        "vat": "11988050966",
        "color": "#7c3aed",
        "people": [
            ("martina-cattaneo", "Martina", "Cattaneo", "martina.cattaneo@serramentimilano.it", "Responsabile commessa serramenti", WorkspaceRole.OWNER, ["datore_lavoro"]),
            ("davide-pini", "Davide", "Pini", "davide.pini@serramentimilano.it", "Caposquadra posa serramenti", WorkspaceRole.MANAGER, ["preposto"]),
            ("cosmin-petrescu", "Cosmin", "Petrescu", "cosmin.petrescu@serramentimilano.it", "Posatore serramenti", WorkspaceRole.WORKER, ["lavoratore"]),
            ("ivan-russo", "Ivan", "Russo", "ivan.russo@serramentimilano.it", "Addetto sigillature e nastri", WorkspaceRole.WORKER, ["lavoratore"]),
        ],
    },
    {
        "code": "finiture",
        "name": "Interni Bianchi Srl",
        "email": "cantieri@internibianchi.it",
        "vat": "11266870963",
        "color": "#be123c",
        "people": [
            ("marta-bianchi", "Marta", "Bianchi", "marta.bianchi@internibianchi.it", "Responsabile finiture", WorkspaceRole.OWNER, ["datore_lavoro"]),
            ("antonio-esposito", "Antonio", "Esposito", "antonio.esposito@internibianchi.it", "Caposquadra pavimenti e bagni", WorkspaceRole.MANAGER, ["preposto"]),
            ("sofia-mancini", "Sofia", "Mancini", "sofia.mancini@internibianchi.it", "Tecnica finiture", WorkspaceRole.DELEGATE, ["lavoratore"]),
            ("lorenzo-gallo", "Lorenzo", "Gallo", "lorenzo.gallo@internibianchi.it", "Cartongessista", WorkspaceRole.WORKER, ["lavoratore"]),
            ("alina-popescu", "Alina", "Popescu", "alina.popescu@internibianchi.it", "Pittura e rasature", WorkspaceRole.WORKER, ["lavoratore"]),
        ],
    },
    {
        "code": "committente",
        "name": "Immobiliare Naviglio Srl",
        "email": "sviluppo@immobiliarenaviglio.it",
        "vat": "12177430964",
        "color": "#64748b",
        "people": [
            ("valentina-neri", "Valentina", "Neri", "valentina.neri@immobiliarenaviglio.it", "Development manager", WorkspaceRole.OWNER, ["committente"]),
            ("riccardo-greco", "Riccardo", "Greco", "riccardo.greco@immobiliarenaviglio.it", "Property operations", WorkspaceRole.MANAGER, ["committente"]),
            ("elena-motta", "Elena", "Motta", "elena.motta@immobiliarenaviglio.it", "Customer handover", WorkspaceRole.DELEGATE, ["committente"]),
        ],
    },
]

DOCUMENTS: list[dict[str, Any]] = [
    {
        "folder": ["Direzione Lavori"],
        "title": "Cronoprogramma generale lotto A",
        "filename": "cronoprogramma-generale-lotto-a.pdf",
        "created_at": "2026-03-24",
        "lines": [
            "Milestone generale aggiornata alla settimana del 24 marzo.",
            "Facciata lotto B subordinata alla correzione del foro cucina 2B.",
            "Pre-collaudo centrale termica vincolato alla consegna valvole.",
            "Bagno campione 2B confermato come riferimento finiture.",
        ],
    },
    {
        "folder": ["Direzione Lavori", "Verbali"],
        "title": "Verbale coordinamento impianti settimana 14",
        "filename": "verbale-coordinamento-impianti-settimana-14.pdf",
        "created_at": "2026-04-02",
        "lines": [
            "Presenti: DL, GC, elettrico, meccanico, serramenti e finiture.",
            "Tema 1: valvole di bilanciamento non ancora consegnate.",
            "Tema 2: quote massetti 1A e 3C da riallineare.",
            "Tema 3: rilascio controsoffitti corridoio nord subordinato a chiusura VMC.",
        ],
    },
    {
        "folder": ["Facciata", "Mockup"],
        "title": "Scheda mockup facciata e serramenti",
        "filename": "scheda-mockup-facciata-serramenti.pdf",
        "created_at": "2026-01-31",
        "lines": [
            "Pannello grigio pietra approvato dalla DL.",
            "Nodo serramento-facciata verificato sul prospetto sud-ovest.",
            "Confermata la sequenza montaggio serramenti per livelli abitativi.",
            "Previsto richiamo sui fuori quota del lotto B prima di procedere.",
        ],
    },
    {
        "folder": ["Impianti", "Check e prove"],
        "title": "Piano collaudi integrati",
        "filename": "piano-collaudi-integrati.pdf",
        "created_at": "2026-04-03",
        "lines": [
            "Giorno 1: centrale termica e reti idroniche.",
            "Giorno 2: VMC e prove corridoi comuni.",
            "Giorno 3: rete antincendio box e sistemi speciali.",
            "Ogni giornata apre solo con prerequisiti chiusi e verbale condiviso.",
        ],
    },
    {
        "folder": ["Direzione Lavori"],
        "title": "Registro criticita aprile",
        "filename": "registro-criticita-aprile.pdf",
        "created_at": "2026-04-04",
        "lines": [
            "Aperte: foro cucina 2B, valvole bilanciamento, quote massetti 1A-3C, prerequisiti collaudi integrati.",
            "Chiuse: passaggi impiantistici platea box 03-04, risvolto ovest copertura, schema quadro Q3.",
            "Ogni punto resta collegato a un thread operativo per responsabilita e allegati.",
            "Aggiornamento quotidiano richiesto ai referenti di disciplina.",
        ],
    },
    {
        "folder": ["Sicurezza"],
        "title": "PSC aggiornato rev02",
        "filename": "psc-aggiornato-rev02.pdf",
        "created_at": "2026-01-17",
        "lines": [
            "Aggiornamento accessi facciata lato sud e segregazione area gru.",
            "Fasce orarie consegne materiali confermate con impresa generale.",
            "Percorsi pedonali separati dal varco mezzi.",
            "Coordinamento interferenze tra facciata, copertura e impianti in quota.",
        ],
    },
    {
        "folder": ["Sicurezza", "Verbali"],
        "title": "Verbale briefing avvio e POS imprese",
        "filename": "verbale-briefing-avvio-pos-imprese.pdf",
        "created_at": "2025-08-15",
        "lines": [
            "Briefing iniziale con DL, CSE, impresa affidataria e imprese esecutrici.",
            "POS ricevuti e verificati per le imprese presenti al primo ingresso.",
            "Obbligo aggiornamento POS a cambio lavorazione o ingresso nuovo subappaltatore.",
            "Riunione chiusa con presa visione delle procedure di emergenza.",
        ],
    },
    {
        "folder": ["Facciata", "Rilievi"],
        "title": "Rilievo foro cucina 2B",
        "filename": "rilievo-foro-cucina-2b.pdf",
        "created_at": "2026-04-04",
        "lines": [
            "Rilievo effettuato il 4 aprile alle 08:10.",
            "Scostamento traverso superiore: 18 mm verso basso.",
            "Davanzale prefabbricato da riallineare prima del lotto B.",
            "Richiesta validazione DL entro il giorno successivo.",
        ],
    },
    {
        "folder": ["Impianti", "Check e prove"],
        "title": "Checklist valvole bilanciamento centrale termica",
        "filename": "checklist-valvole-bilanciamento.pdf",
        "created_at": "2026-04-04",
        "lines": [
            "Valvole DN32 e DN40 mancanti in centrale termica.",
            "Impatto diretto sul pre-collaudo idronico del 9 aprile.",
            "Fornitore atteso in cantiere entro 48 ore.",
            "Installazione da concentrare su locale tecnico e piano primo.",
        ],
    },
    {
        "folder": ["Finiture", "Quote"],
        "title": "Verifica quote massetti 1A-3C",
        "filename": "verifica-quote-massetti-1a-3c.pdf",
        "created_at": "2026-04-04",
        "lines": [
            "Scostamento misurato tra 7 e 11 mm nei due alloggi campione.",
            "Verificare subito i riferimenti lasciati da impianti elettrici e idraulici.",
            "Conferma quote richiesta prima del prossimo lotto massetti.",
            "Aggiornare tavola quote interne dopo il sopralluogo con DL.",
        ],
    },
    {
        "folder": ["Consegna", "Punch list"],
        "title": "Punch list parti comuni",
        "filename": "punch-list-parti-comuni.pdf",
        "created_at": "2026-03-24",
        "lines": [
            "Hall ingresso: confermare posizione monitor citofonico.",
            "Vano scala B: chiudere stuccatura giunto verticale.",
            "Autorimessa: tarare chiudiporta locali tecnici.",
            "Corte interna: verificare pendenza ultimo tratto pavimentazione.",
        ],
    },
    {
        "folder": ["Consegna", "As built"],
        "title": "Pacchetto as-built preliminare",
        "filename": "pacchetto-as-built-preliminare.pdf",
        "created_at": "2026-03-27",
        "lines": [
            "Indice preliminare tavole architettoniche, strutturali e impiantistiche.",
            "Schede tecniche apparecchiature in raccolta da elettrico e meccanico.",
            "Manuali manutenzione da completare prima del walkthrough finale.",
            "Versione non valida per consegna definitiva fino a chiusura punch list.",
        ],
    },
    {
        "folder": ["Consegna", "Manutenzione"],
        "title": "Fascicolo manutenzione preliminare",
        "filename": "fascicolo-manutenzione-preliminare.pdf",
        "created_at": "2026-04-05",
        "lines": [
            "Elenco apparecchiature principali centrale termica e sistemi speciali.",
            "Manutenzioni programmate da confermare con gestore entro consegna aree comuni.",
            "Inserire seriali mancanti pompe, inverter e centrali controllo accessi.",
            "Documento in bozza per revisione DL e committente.",
        ],
    },
    {
        "folder": ["Copertura", "Prove"],
        "title": "Verbale prova tenuta copertura ovest",
        "filename": "verbale-prova-tenuta-copertura-ovest.pdf",
        "created_at": "2026-01-24",
        "lines": [
            "Verifica del nodo sfiato lucernario in presenza DL e impresa.",
            "Fascia aggiuntiva posata sul risvolto ovest.",
            "Lattoneria speciale installata sul bordo parapetto.",
            "Nessuna infiltrazione rilevata al test finale.",
        ],
    },
    {
        "folder": ["Impianti", "Elettrico"],
        "title": "Schema aggiornato quadro Q3",
        "filename": "schema-aggiornato-quadro-q3.pdf",
        "created_at": "2026-02-28",
        "lines": [
            "Riposizionamento morsettiere linee speciali.",
            "Separazione tra forza motrice, dati e sicurezza.",
            "Test continuita eseguito e firmato dal capo commessa.",
            "Q3 disponibile per collegamento finale.",
        ],
    },
]

PHOTOS: list[dict[str, str]] = [
    {"filename": "ar-101-pianta-piano-terra.svg", "title": "AR-101 Pianta piano terra e corte interna", "subtitle": "Hall, locale comune, corte interna e autorimessa rampata.", "accent": "#475569", "created_at": "2026-02-10"},
    {"filename": "ar-205-piante-tipo-alloggi.svg", "title": "AR-205 Piante tipo alloggi 1A-2B-3C", "subtitle": "Alloggi campione, quote interne e aree massetti da verificare.", "accent": "#64748b", "created_at": "2026-02-14"},
    {"filename": "st-204-platea-setti.svg", "title": "ST-204 Platea e setti interrati", "subtitle": "Platea, setti scala, vani tecnici e passaggi impiantistici.", "accent": "#1d4ed8", "created_at": "2025-08-18"},
    {"filename": "fa-301-facciata-sud-ovest.svg", "title": "FA-301 Facciata sud-ovest", "subtitle": "Mockup, campitura pannelli, davanzali e nodo copertura.", "accent": "#7c3aed", "created_at": "2026-01-22"},
    {"filename": "fa-312-nodo-serramento-davanzale.svg", "title": "FA-312 Nodo serramento e davanzale", "subtitle": "Dettaglio controtelaio, nastri e foro cucina 2B.", "accent": "#7c3aed", "created_at": "2026-02-03"},
    {"filename": "im-220-centrale-termica.svg", "title": "IM-220 Centrale termica e dorsali", "subtitle": "Centrale termica, collettori, valvole e dorsali principali.", "accent": "#ea580c", "created_at": "2026-02-04"},
    {"filename": "im-245-vmc-corridoi-bagni.svg", "title": "IM-245 VMC corridoi e bagni", "subtitle": "Canali VMC, corridoio nord e locali bagno.", "accent": "#f97316", "created_at": "2026-02-22"},
    {"filename": "el-240-quadri-dorsali.svg", "title": "EL-240 Quadri di piano e dorsali FM", "subtitle": "Quadri Q1-Q3, dorsali forza motrice e linee speciali.", "accent": "#0ea5e9", "created_at": "2026-02-12"},
    {"filename": "el-260-sistemi-speciali-citofonia.svg", "title": "EL-260 Sistemi speciali e citofonia", "subtitle": "Videosorveglianza, controllo accessi e monitor hall.", "accent": "#0284c7", "created_at": "2026-03-01"},
    {"filename": "fn-110-bagno-campione-2b.svg", "title": "FN-110 Bagno campione 2B", "subtitle": "Rivestimenti, sanitari, fughe e tagli di riferimento.", "accent": "#be123c", "created_at": "2026-03-18"},
    {"filename": "fronte-sud-ovest.svg", "title": "Fronte sud-ovest", "subtitle": "Stato facciata, ponteggi e mockup serramenti.", "accent": "#0f766e", "created_at": "2026-04-03"},
    {"filename": "centrale-termica.svg", "title": "Centrale termica", "subtitle": "Dorsali principali e collettori in preparazione pre-collaudo.", "accent": "#ea580c", "created_at": "2026-04-03"},
    {"filename": "bagno-campione-2b-overview.svg", "title": "Bagno campione 2B", "subtitle": "Rivestimenti e sanitari di riferimento per il lotto abitativo.", "accent": "#1d4ed8", "created_at": "2026-04-04"},
    {"filename": "vano-scala-b.svg", "title": "Vano scala B", "subtitle": "Parete campione per rasature e finitura finale.", "accent": "#be123c", "created_at": "2026-04-04"},
    {"filename": "copertura-risvolto-ovest.svg", "title": "Copertura risvolto ovest", "subtitle": "Nodo sfiato lucernario, fascia aggiuntiva e lattoneria speciale.", "accent": "#0891b2", "created_at": "2026-01-24"},
    {"filename": "foro-cucina-2b-rilievo.svg", "title": "Rilievo foro cucina 2B", "subtitle": "Scostamento traverso superiore e controtelaio correttivo.", "accent": "#7c3aed", "created_at": "2026-04-04"},
    {"filename": "massetti-alloggi-1a-3c.svg", "title": "Quote massetti alloggi 1A e 3C", "subtitle": "Picchetti, riferimenti impianti e quote finite da riallineare.", "accent": "#be123c", "created_at": "2026-04-04"},
    {"filename": "quadro-q3-linee-speciali.svg", "title": "Quadro Q3 linee speciali", "subtitle": "Morsettiere riposizionate e separazione reti speciali.", "accent": "#0ea5e9", "created_at": "2026-02-28"},
    {"filename": "vmc-corridoio-nord.svg", "title": "VMC corridoio nord", "subtitle": "Staffaggi coordinati con passerelle elettriche.", "accent": "#f97316", "created_at": "2026-03-10"},
    {"filename": "hall-monitor-citofonico.svg", "title": "Hall monitor citofonico", "subtitle": "Posizione da confermare con committente e sistemi speciali.", "accent": "#0284c7", "created_at": "2026-03-14"},
]

FAMILY_LABELS = {
    "logistics": "accessi, sicurezza, aree operative e avvio documentale",
    "foundation": "quote, ferri, riprese e passaggi impiantistici",
    "structures": "casseri, solai, vani scala, tolleranze e rilievi strutturali",
    "envelope": "tenuta all'acqua, risvolti, lattonerie e nodi di bordo",
    "facade": "quote foro, nastri, allineamenti e nodi di attacco",
    "mechanical": "tenute, staffaggi, valvole e interfacce impiantistiche",
    "electrical": "layout quadri, linee speciali, dorsali e sistemi di sicurezza",
    "interiors": "quote finite, chiusure cavedi e superfici campione",
    "finishes": "bagni campione, pavimenti, tinteggiature, montaggi e punch list",
    "handover": "prerequisiti, verbali, as-built e responsabilita di chiusura",
}

DEMO_TARGET_PROGRESS = 66

ACTIVITY_STATUS_PROGRESS = {
    TaskActivityStatus.COMPLETED: 100,
    TaskActivityStatus.PROGRESS: 55,
    TaskActivityStatus.TODO: 0,
}

THREAD_COMMUNICATIONS: dict[str, dict[str, str]] = {
    "logistics": {
        "watcher": "serena-costantini",
        "stakeholder": "marco-rinaldi",
        "field": "luca-gatti",
        "checkpoint": "PSC e accessi restano il riferimento: teniamo separati varco mezzi e ingresso pedonale, con verifica fotografica a fine turno.",
        "decision": "Ok per procedere. Chiedo solo che ogni variazione su accessi o stoccaggi venga riportata qui prima di modificare la planimetria logistica.",
        "next_action": "Aggiungo controllo giornaliero del varco nord e registro eventuali anomalie nel briefing delle 17:00.",
    },
    "foundation": {
        "watcher": "davide-sala",
        "stakeholder": "elisa-brambilla",
        "field": "giorgio-bellini",
        "checkpoint": "Prima di chiudere il fronte voglio un passaggio su quote, passaggi impiantistici e interferenze con le gabbie.",
        "decision": "Condivido. Le modifiche minori restano in campo solo se tracciate con foto e conferma DL nello stesso thread.",
        "next_action": "Tengo la squadra sui capisaldi segnati e allego rilievo se troviamo scostamenti oltre tolleranza.",
    },
    "structures": {
        "watcher": "davide-sala",
        "stakeholder": "laura-ferretti",
        "field": "elisa-brambilla",
        "checkpoint": "Allineo modello e campo: vani scala, cavedi e quote ascensore devono tornare prima di autorizzare il prossimo getto.",
        "decision": "Procediamo solo con verifica dimensionale firmata dalla squadra strutture e foto delle predisposizioni.",
        "next_action": "Passo con il capo squadra prima del getto e chiudo qui eventuali rettifiche.",
    },
    "envelope": {
        "watcher": "serena-costantini",
        "stakeholder": "marco-rinaldi",
        "field": "omar-elidrissi",
        "checkpoint": "Nodo acqua e sicurezza lavori in quota sono i due punti sensibili: serve evidenza chiara prima di liberare il fronte.",
        "decision": "Il fronte resta aperto solo se la prova di tenuta e caricata e se i parapetti temporanei sono confermati.",
        "next_action": "Aggiorno il registro copertura a fine turno e fotografo i risvolti prima della lattoneria.",
    },
    "facade": {
        "watcher": "davide-sala",
        "stakeholder": "martina-cattaneo",
        "field": "davide-pini",
        "checkpoint": "Il controllo quota foro deve diventare visibile a tutti: pin sulla tavola, foto campo e decisione DL nello stesso punto.",
        "decision": "Confermo. Senza validazione quote non facciamo partire il lotto successivo di serramenti.",
        "next_action": "Preparo controtelaio correttivo e aggiorno il thread con misura finale e foto del traverso.",
    },
    "mechanical": {
        "watcher": "giulia-roversi",
        "stakeholder": "laura-ferretti",
        "field": "stefano-riva",
        "checkpoint": "Valvole, staffaggi e passaggi VMC vanno letti insieme: un ritardo qui impatta collaudi e chiusure interne.",
        "decision": "Priorita alla centrale e ai corridoi tecnici. Ogni blocco fornitura deve avere una data certa e un piano B.",
        "next_action": "Raccolgo conferma fornitore e aggiorno qui appena ho lotto, orario scarico e squadra installazione.",
    },
    "electrical": {
        "watcher": "paolo-longhi",
        "stakeholder": "davide-sala",
        "field": "matteo-cerri",
        "checkpoint": "Quadri, dati e sicurezza speciale devono restare separati anche nel racconto: foto prima/dopo e schema aggiornato.",
        "decision": "Bene, teniamo schema e rilievo nello stesso thread cosi il tester puo verificare allegati e ricerca.",
        "next_action": "Carico evidenza del Q3 e controllo che linee speciali e dorsali risultino leggibili anche in as-built.",
    },
    "interiors": {
        "watcher": "sofia-mancini",
        "stakeholder": "laura-ferretti",
        "field": "antonio-esposito",
        "checkpoint": "Quote finite, cavedi e superfici campione devono essere chiusi prima di coprire: niente decisioni fuori thread.",
        "decision": "Confermo. Bagno campione e massetti diventano riferimenti per il resto del lotto abitativo.",
        "next_action": "Faccio nuova battuta quote e aggiungo foto dei picchetti prima del getto finale.",
    },
    "finishes": {
        "watcher": "valentina-neri",
        "stakeholder": "marta-bianchi",
        "field": "antonio-esposito",
        "checkpoint": "Per la demo commerciale voglio vedere decisioni su finiture, punch list e responsabilita in modo immediato.",
        "decision": "Allineato. Le scelte campione restano tracciate qui, con foto e impatto su tempi di consegna.",
        "next_action": "Aggiorno la lista alloggi campione e segnalo subito eventuali materiali mancanti.",
    },
    "handover": {
        "watcher": "valentina-neri",
        "stakeholder": "riccardo-greco",
        "field": "serena-costantini",
        "checkpoint": "Consegna significa prove, manuali e responsabilita chiuse: serve una lettura unica per committente e gestore.",
        "decision": "Ok, voglio che ogni prerequisito abbia owner, scadenza e documento collegato prima del walkthrough.",
        "next_action": "Preparo matrice prerequisiti e aggiorno il fascicolo quando ogni test passa da aperto a chiuso.",
    },
}


def parse_day(value: str | date) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


def aware(day: date, hour: int, minute: int = 0) -> datetime:
    return timezone.make_aware(datetime.combine(day, time(hour=hour, minute=minute)))


def seed_project_progress() -> int:
    if not TASKS:
        return 0
    return round(sum(int(task["progress"]) for task in TASKS) / len(TASKS))


def pdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_pdf(title: str, lines: list[str]) -> bytes:
    stream_lines = ["BT", "/F1 18 Tf", "72 742 Td", f"({pdf_escape(title)}) Tj", "/F1 11 Tf"]
    first = True
    for line in lines:
        stream_lines.append(f"0 {'-28' if first else '-18'} Td")
        stream_lines.append(f"({pdf_escape(line)}) Tj")
        first = False
    stream_lines.append("ET")
    stream = "\n".join(stream_lines).encode("utf-8")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    parts = [b"%PDF-1.4\n"]
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(sum(len(part) for part in parts))
        parts.append(f"{index} 0 obj\n".encode("ascii"))
        parts.append(body)
        parts.append(b"\nendobj\n")
    xref = sum(len(part) for part in parts)
    parts.append(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    parts.append(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        parts.append(f"{offset:010d} 00000 n \n".encode("ascii"))
    parts.append(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode("ascii"))
    return b"".join(parts)


def build_logo(label: str, accent: str) -> bytes:
    initials = "".join(chunk[0] for chunk in label.split()[:2]).upper() or "EC"
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">'
        '<rect width="512" height="512" rx="120" fill="#f5f5f4"/>'
        f'<rect x="36" y="36" width="440" height="440" rx="110" fill="{accent}"/>'
        f'<text x="256" y="296" text-anchor="middle" font-size="176" font-family="Arial" font-weight="700" fill="#fff">{initials}</text>'
        "</svg>"
    )
    return svg.encode("utf-8")


def build_scene(title: str, subtitle: str, accent: str, *, asset_code: str = "", asset_kind: str = "") -> bytes:
    badge = ""
    if asset_code or asset_kind:
        badge = (
            '<rect x="1160" y="732" width="312" height="88" rx="18" fill="rgba(17,24,39,0.68)" stroke="rgba(255,255,255,0.28)"/>'
            f'<text x="1192" y="776" font-size="22" font-family="Arial" font-weight="700" fill="#ffffff">{asset_code or "demo-asset"}</text>'
            f'<text x="1192" y="806" font-size="16" font-family="Arial" fill="rgba(255,255,255,0.82)">{asset_kind or "placeholder"}</text>'
        )
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" viewBox="0 0 1600 900">'
        '<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0%" stop-color="{accent}"/><stop offset="100%" stop-color="#111827"/></linearGradient></defs>'
        '<rect width="1600" height="900" fill="#f5f5f4"/>'
        '<rect x="48" y="48" width="1504" height="804" rx="42" fill="url(#bg)"/>'
        '<path d="M160 650 L420 420 L610 510 L810 310 L1060 460 L1260 250 L1440 390" fill="none" stroke="rgba(255,255,255,0.45)" stroke-width="20" stroke-linecap="round"/>'
        f'<text x="128" y="188" font-size="56" font-family="Arial" font-weight="700" fill="#ffffff">{title}</text>'
        f'<text x="128" y="252" font-size="28" font-family="Arial" fill="rgba(255,255,255,0.88)">{subtitle}</text>'
        f"{badge}"
        "</svg>"
    )
    return svg.encode("utf-8")


def resolve_logo_source(company_code: str, slug: str, label: str, accent: str) -> tuple[str, bytes]:
    source = find_demo_source_file(
        relative_dir=f"companies/{company_code}",
        preferred_filename="logo.svg",
        extensions=LOGO_SOURCE_EXTENSIONS,
    )
    if source is not None:
        return source.name, source.read_bytes()
    return f"{slug}-logo.svg", build_logo(label, accent)


def resolve_avatar_source(person_code: str) -> tuple[str, bytes] | None:
    source = find_demo_source_file(
        relative_dir="avatars",
        preferred_filename=f"{person_code}.jpg",
        extensions=AVATAR_SOURCE_EXTENSIONS,
    )
    if source is None:
        return None
    return source.name, source.read_bytes()


def resolve_document_source(filename: str, title: str, lines: list[str]) -> tuple[str, bytes]:
    source = find_demo_source_file(
        relative_dir="documents",
        preferred_filename=filename,
        extensions=DOCUMENT_SOURCE_EXTENSIONS,
    )
    if source is not None:
        return source.name, source.read_bytes()
    return filename, build_pdf(title, lines)


def resolve_visual_source(
    filename: str,
    title: str,
    subtitle: str,
    accent: str,
    *,
    source_dir: str | None = None,
    category: str | None = None,
) -> tuple[str, bytes]:
    chosen_source_dir = source_dir or visual_source_dir_for_filename(filename)
    source = find_demo_source_file(
        relative_dir=chosen_source_dir,
        preferred_filename=filename,
        extensions=IMAGE_SOURCE_EXTENSIONS,
    )
    if source is not None:
        return source.name, source.read_bytes()
    return (
        filename,
        build_scene(
            title,
            subtitle,
            accent,
            asset_code=asset_code_for_filename(filename, category=category),
            asset_kind=asset_placeholder_kind(filename, category=category),
        ),
    )


ROLE_AUTHOR_CODES = {
    "dl": "laura-ferretti",
    "bim": "davide-sala",
    "safety": "serena-costantini",
}


STANDARD_DIALOGUES: dict[str, list[dict[str, Any]]] = {
    "phase": [
        {
            "author": "dl",
            "hour": 9,
            "minute": 20,
            "text": "Ricevuto. Per me qui contano tre cose: prossima scadenza, blocchi reali e decisioni da portare in riunione.",
        },
        {
            "author": "lead",
            "hour": 9,
            "minute": 42,
            "text": "Da parte nostra il quadro e chiaro. Tengo fuori dal rumore solo le criticita vere e aggiorno qui se cambia qualcosa.",
            "parent": "previous",
        },
        {
            "author": "watcher",
            "hour": 10,
            "minute": 15,
            "text": "{checkpoint}",
            "checkpoint_attachment": True,
        },
        {
            "author": "stakeholder",
            "hour": 11,
            "minute": 5,
            "text": "{decision}",
            "parent": "previous",
        },
        {
            "author": "field",
            "hour": 15,
            "minute": 35,
            "text": "@{watcher_name} {next_action}",
        },
        {
            "author": "bim",
            "hour": 16,
            "minute": 10,
            "text": "Segno il punto anche su Gantt e tavole. Se arriva una foto utile la collego, cosi poi la ritroviamo in ricerca e assistant.",
            "parent": "previous",
        },
        {
            "author": "dl",
            "hour": 17,
            "minute": 25,
            "text": "Perfetto. Domani in briefing guardiamo solo variazioni, allegati nuovi e decisioni ancora senza owner.",
        },
    ],
    "completed": [
        {
            "author": "dl",
            "hour": 9,
            "minute": 30,
            "text": "Bene, chiudiamola senza lasciare pezzi in sospeso. Mi basta evidenza chiara e nessun impatto sul passaggio successivo.",
        },
        {
            "author": "field",
            "hour": 9,
            "minute": 48,
            "text": "Sul posto e tutto rientrato. Le foto sono coerenti con quanto visto in campo; non ho rilievi da aggiungere.",
            "parent": "previous",
        },
        {
            "author": "lead",
            "hour": 10,
            "minute": 12,
            "text": "Confermo chiusura operativa. Materiali e area lasciati in ordine, nessuna squadra ferma per questo punto.",
        },
        {
            "author": "watcher",
            "hour": 11,
            "minute": 5,
            "text": "{checkpoint}",
            "parent": "previous",
        },
        {
            "author": "stakeholder",
            "hour": 14,
            "minute": 20,
            "text": "{decision}",
        },
        {
            "author": "bim",
            "hour": 16,
            "minute": 5,
            "text": "Ho allineato il fascicolo di commessa: evidenza fotografica, nota campo e stato lavorazione sono coerenti.",
        },
        {
            "author": "dl",
            "hour": 17,
            "minute": 15,
            "text": "Ok per archiviazione. Non apriamo altri commenti salvo varianti o contestazioni successive.",
            "parent": "previous",
        },
    ],
    "progress": [
        {
            "author": "dl",
            "hour": 9,
            "minute": 25,
            "text": "Ho visto l'avanzamento. Mi serve una lettura semplice: cosa resta aperto oggi e cosa puo bloccare domani.",
        },
        {
            "author": "lead",
            "hour": 9,
            "minute": 50,
            "text": "Il fronte procede. Lascio in evidenza solo il punto operativo scritto nella nota, il resto non sta creando interferenze.",
            "parent": "previous",
        },
        {
            "author": "field",
            "hour": 10,
            "minute": 28,
            "text": "@{watcher_name} dal campo confermo: {next_action}",
        },
        {
            "author": "watcher",
            "hour": 11,
            "minute": 2,
            "text": "{checkpoint}",
            "parent": "previous",
        },
        {
            "author": "stakeholder",
            "hour": 14,
            "minute": 18,
            "text": "{decision}",
        },
        {
            "author": "bim",
            "hour": 15,
            "minute": 45,
            "text": "Tengo agganciati tavole, foto e avanzamento. Se cambia sequenza aggiorno anche il Gantt, non solo il thread.",
        },
        {
            "author": "lead",
            "hour": 17,
            "minute": 18,
            "text": "A fine turno rientro qui con stato reale, materiali usati e prossimo accesso necessario.",
            "parent": "previous",
        },
        {
            "author": "dl",
            "hour": 17,
            "minute": 44,
            "text": "Va bene. Tengo il punto in osservazione finche non vedo evidenza di chiusura o nuovo blocco.",
            "parent": "previous",
        },
    ],
    "todo": [
        {
            "author": "dl",
            "hour": 9,
            "minute": 10,
            "text": "Prima di partire non voglio sorprese: prerequisiti, materiali e interferenze devono essere scritti qui.",
        },
        {
            "author": "lead",
            "hour": 9,
            "minute": 34,
            "text": "Ricevuto. Entro oggi verifico disponibilita materiali e squadra, poi confermo se la data tiene.",
            "parent": "previous",
        },
        {
            "author": "watcher",
            "hour": 10,
            "minute": 22,
            "text": "{checkpoint}",
        },
        {
            "author": "stakeholder",
            "hour": 11,
            "minute": 0,
            "text": "{decision}",
            "parent": "previous",
        },
        {
            "author": "field",
            "hour": 15,
            "minute": 20,
            "text": "Mi prendo il giro in campo prima di confermare. Se manca qualcosa lo scrivo qui, senza passaggi a voce.",
        },
        {
            "author": "bim",
            "hour": 16,
            "minute": 0,
            "text": "Tengo la data provvisoria sul Gantt. La fisso solo dopo conferma materiali e nulla osta operativo.",
            "parent": "previous",
        },
        {
            "author": "dl",
            "hour": 17,
            "minute": 5,
            "text": "Ok. Nessuna partenza senza evidenze minime: foto, documento o conferma del referente.",
        },
    ],
}


ISSUE_DIALOGUE: list[dict[str, Any]] = [
    {
        "author": "dl",
        "hour": 17,
        "minute": 25,
        "text": "Questo punto va trattato come blocco operativo. Mi serve sapere cosa manca, chi lo chiude e quando posso liberare il fronte.",
    },
    {
        "author": "lead",
        "hour": 17,
        "minute": 42,
        "text": "Vado in verifica adesso. Rientro qui con misura, foto e proposta, cosi non resta una decisione a voce.",
        "parent": "previous",
    },
    {
        "author": "field",
        "hour": 18,
        "minute": 4,
        "text": "Confermo dal campo: {issue_impact}",
        "parent": "previous",
    },
    {
        "author": "watcher",
        "hour": 18,
        "minute": 14,
        "text": "{checkpoint}",
        "parent": "previous",
    },
    {
        "author": "stakeholder",
        "hour": 18,
        "minute": 26,
        "text": "Per me va bene procedere solo se restano tracciati responsabilita, data di rientro e impatto su SAL.",
    },
    {
        "author": "bim",
        "hour": 18,
        "minute": 40,
        "text": "Ho caricato il documento tecnico e tengo pronto l'aggiornamento tavole/pin se la soluzione cambia geometria o sequenza.",
        "attachment": "issue_document",
    },
    {
        "author": "lead",
        "hour": 19,
        "minute": 6,
        "text": "Piano operativo: {issue_action}",
        "parent": "previous",
    },
    {
        "author": "field",
        "hour": 19,
        "minute": 14,
        "text": "Mi coordino con la squadra e mando evidenza appena il punto e fisicamente chiuso.",
        "parent": "previous",
    },
    {
        "author": "dl",
        "hour": 19,
        "minute": 24,
        "text": "{issue_closeout}",
        "parent": "previous",
    },
]


def demo_image_attachment(name: str, title: str, subtitle: str, accent: str) -> dict[str, str]:
    return {
        "kind": "image",
        "name": name,
        "title": title,
        "subtitle": subtitle,
        "accent": accent,
        "source_dir": "attachments",
    }


ACTIVITY_EVIDENCE_ASSETS: dict[str, list[dict[str, str]]] = {
    "logistics": [
        demo_image_attachment("accesso-pedonale-varco-nord.svg", "Varco nord separato", "Percorso mezzi e ingresso pedonale con segnaletica.", "#0f766e"),
        demo_image_attachment("baraccamenti-linea-acqua.svg", "Baraccamenti lato nord", "Ufficio cantiere, spogliatoi e linea acqua provvisoria.", "#0f766e"),
        demo_image_attachment("capisaldi-tracciamento-iniziale.svg", "Capisaldi iniziali", "Rilievo e tracciamento condivisi prima degli scavi.", "#0f766e"),
        demo_image_attachment("briefing-pos-ingressi.svg", "Briefing POS imprese", "Ingresso imprese e presa visione procedure sicurezza.", "#0f766e"),
    ],
    "foundation": [
        demo_image_attachment("scavo-fronte-nord.svg", "Scavo fronte nord", "Pulizia fronte e percorso camion libero.", "#1d4ed8"),
        demo_image_attachment("platea-passaggi-box-03-04.svg", "Passaggi box 03-04", "Manicotti, ferri integrativi e verifica prima del getto.", "#1d4ed8"),
        demo_image_attachment("getto-platea-maturazione.svg", "Getto platea", "Sequenza di getto e maturazione controllata.", "#1d4ed8"),
    ],
    "structures": [
        demo_image_attachment("pilastri-solaio-terra.svg", "Pilastri e solaio terra", "Giunti e cavedi predisposti prima del getto.", "#1d4ed8"),
        demo_image_attachment("vano-scala-ascensore-controllo.svg", "Vano scala e ascensore", "Controllo dimensionale prima del secondo getto.", "#1d4ed8"),
        demo_image_attachment("solaio-piano-secondo-passaggi.svg", "Passaggi solaio secondo", "Aperture tecniche verificate con impianti.", "#1d4ed8"),
        demo_image_attachment("cordoli-copertura-rilievo.svg", "Cordoli copertura", "Rilievo finale per passaggio a copertura e facciata.", "#1d4ed8"),
    ],
    "envelope": [
        demo_image_attachment("tamponamenti-fronte-scala.svg", "Tamponamenti fronte scala", "Allineamento falsi telai e ritocchi lato scala.", "#0891b2"),
        demo_image_attachment("risvolto-ovest-lucernario.svg", "Risvolto ovest lucernario", "Nodo guaina, sfiato e parapetto.", "#0891b2"),
        demo_image_attachment("pluviali-corpo-scala-corte.svg", "Pluviali lato corte", "Raccordo finale sul corpo scala.", "#0891b2"),
    ],
    "facade": [
        demo_image_attachment("mockup-facciata-sud-ovest.svg", "Mockup facciata sud-ovest", "Pannello campione, nodo serramento e lattoneria.", "#7c3aed"),
        demo_image_attachment("foro-cucina-2b-misura.svg", "Misura foro cucina 2B", "Traverso superiore e controtelaio correttivo.", "#7c3aed"),
        demo_image_attachment("posa-serramenti-lotto-a.svg", "Posa serramenti lotto A", "Sequenza posa per non fermare massetti e finiture.", "#7c3aed"),
    ],
    "mechanical": [
        demo_image_attachment("colonne-scarico-prova-tenuta.svg", "Prova tenuta colonne", "Verifica prima della chiusura cavedi.", "#ea580c"),
        demo_image_attachment("centrale-termica-precollaudo.svg", "Centrale termica", "Dorsali principali e area collettori in allestimento.", "#ea580c"),
        demo_image_attachment("vmc-corridoio-nord-staffaggi.svg", "Staffaggi VMC corridoio nord", "Coordinamento con passerelle elettriche.", "#ea580c"),
    ],
    "electrical": [
        demo_image_attachment("passerelle-interrato-antincendio.svg", "Passerelle interrato", "Coordinamento con rete antincendio.", "#0ea5e9"),
        demo_image_attachment("quadro-q3-linee-speciali.svg", "Quadro Q3", "Linee speciali e dorsali forza motrice separate.", "#0ea5e9"),
        demo_image_attachment("monitor-citofonico-hall.svg", "Monitor citofonico hall", "Posizione da confermare con committenza.", "#0ea5e9"),
    ],
    "interiors": [
        demo_image_attachment("cavedi-foto-prima-chiusura.svg", "Cavedi prima chiusura", "Predisposizioni fotografate prima del cartongesso.", "#be123c"),
        demo_image_attachment("picchetti-quote-massetti.svg", "Picchetti quote massetti", "Riferimenti impianti e quote finite da riallineare.", "#be123c"),
        demo_image_attachment("bagno-campione-2b.svg", "Bagno campione 2B", "Rivestimenti e sanitari di riferimento.", "#be123c"),
    ],
    "finishes": [
        demo_image_attachment("rivestimento-bagno-campione-tagli.svg", "Tagli bagno campione", "Fughe e tagli di riferimento per il lotto.", "#be123c"),
        demo_image_attachment("campioni-tinte-parti-comuni.svg", "Campioni tinte parti comuni", "Tonalita finali da validare prima della seconda mano.", "#be123c"),
        demo_image_attachment("porte-sanitari-lotto-campione.svg", "Porte e sanitari lotto campione", "Consegna materiali in due lotti.", "#be123c"),
        demo_image_attachment("pulizie-check-alloggi.svg", "Check alloggi campione", "Punch list prima del walkthrough.", "#be123c"),
    ],
    "handover": [
        demo_image_attachment("precollaudo-vmc-antincendio-prerequisiti.svg", "Prerequisiti pre-collaudo", "VMC, valvole e rete antincendio da chiudere.", "#64748b"),
        demo_image_attachment("punch-list-parti-comuni-foto.svg", "Punch list parti comuni", "Responsabilita e tempi di chiusura.", "#64748b"),
        demo_image_attachment("asbuilt-seriali-centrali.svg", "As-built e seriali", "Indice manuali e apparecchiature.", "#64748b"),
    ],
}


ISSUE_EVIDENCE_ASSETS: dict[str, dict[str, str]] = {
    "foundation": demo_image_attachment("interferenza-passaggi-box-03-04.svg", "Interferenza box 03-04", "Manicotto scarico e gabbia armatura prima della correzione.", "#1d4ed8"),
    "envelope": demo_image_attachment("dettaglio-risvolto-ovest-sfiato.svg", "Dettaglio risvolto ovest", "Nodo sfiato lucernario prima della fascia aggiuntiva.", "#0891b2"),
    "facade": demo_image_attachment("fuori-quota-foro-cucina-2b.svg", "Fuori quota foro cucina 2B", "Scostamento traverso superiore rilevato in campo.", "#7c3aed"),
    "mechanical": demo_image_attachment("valvole-mancanti-centrale-termica.svg", "Valvole mancanti centrale", "Lotto valvole non disponibile per il pre-collaudo.", "#ea580c"),
    "electrical": demo_image_attachment("q3-linee-speciali-prima-dopo.svg", "Quadro Q3 prima/dopo", "Riallineamento morsettiere e linee speciali.", "#0ea5e9"),
    "interiors": demo_image_attachment("quote-massetti-1a-3c-rilievo.svg", "Rilievo quote massetti", "Scostamenti misurati negli alloggi 1A e 3C.", "#be123c"),
    "handover": demo_image_attachment("prerequisiti-vmc-antincendio.svg", "Prerequisiti VMC e antincendio", "Punti aperti prima del calendario collaudi.", "#64748b"),
}


TASKS: list[dict[str, Any]] = [
    {
        "family": "logistics",
        "name": "Avvio cantiere e logistica operativa",
        "company": "gc",
        "start": "2025-08-01",
        "end": "2025-08-15",
        "progress": 100,
        "note": "Allestimento area, accessi, servizi provvisori, briefing sicurezza e presa in consegna del lotto.",
        "activities": [
            {
                "title": "Recinzioni, varco mezzi e segnaletica temporanea",
                "status": TaskActivityStatus.COMPLETED,
                "start": "2025-08-01",
                "end": "2025-08-04",
                "workers": ["luca-gatti", "omar-elidrissi", "samuele-rota"],
                "note": "Separati accesso pedonale e percorso mezzi con cartellonistica di sicurezza aggiornata.",
            },
            {
                "title": "Baraccamenti, quadri provvisori e linea acqua",
                "status": TaskActivityStatus.COMPLETED,
                "start": "2025-08-05",
                "end": "2025-08-08",
                "workers": ["luca-gatti", "andrea-fontana", "stefano-riva"],
                "note": "Ufficio cantiere, spogliatoi e sottoservizi provvisori operativi sul lato nord.",
            },
            {
                "title": "Rilievo iniziale e tracciamento capisaldi",
                "status": TaskActivityStatus.COMPLETED,
                "start": "2025-08-08",
                "end": "2025-08-12",
                "workers": ["davide-sala", "fabio-conti", "luca-gatti"],
                "note": "Capisaldi condivisi su AR-101 e ST-204 prima dell'avvio scavi.",
            },
            {
                "title": "PSC, POS e briefing di avvio commessa",
                "status": TaskActivityStatus.COMPLETED,
                "start": "2025-08-12",
                "end": "2025-08-15",
                "workers": ["laura-ferretti", "serena-costantini", "marco-rinaldi"],
                "note": "Verbale di avvio condiviso con imprese e referenti sicurezza.",
            },
        ],
    },
    {
        "family": "foundation",
        "name": "Scavi, opere geotecniche e fondazioni",
        "company": "strutture",
        "start": "2025-08-18",
        "end": "2025-09-12",
        "progress": 100,
        "note": "Scavi, platea, setti interrati e passaggi impiantistici coordinati al millimetro.",
        "activities": [
            {
                "title": "Scavo sbancamento e pulizia fronte nord",
                "status": TaskActivityStatus.COMPLETED,
                "start": "2025-08-18",
                "end": "2025-08-22",
                "workers": ["giorgio-bellini", "ionut-marin", "enrico-vitali"],
                "note": "Percorso camion tenuto libero senza impatti sulla viabilita del lotto.",
            },
            {
                "title": "Magrone, ferri platea e passaggi impiantistici",
                "status": TaskActivityStatus.COMPLETED,
                "start": "2025-08-25",
                "end": "2025-09-04",
                "workers": ["giorgio-bellini", "cristian-pavan", "stefano-riva"],
                "note": "Coordinati passaggi impiantistici dei box e ricontrollate quote prima del getto.",
                "issue": {
                    "status": "resolved",
                    "title": "Interferenza passaggi impiantistici box 03-04",
                    "impact": "Durante il prefisso ferri e emersa una sovrapposizione tra manicotto scarico e gabbia armatura.",
                    "action": "Dettaglio rivisto, foro spostato di 12 cm e ferri integrativi posati prima del getto.",
                    "document": {
                        "name": "scheda-passaggi-platea-box-03.pdf",
                        "title": "Scheda passaggi platea box 03-04",
                        "lines": [
                            "Rilievo campo del 28 agosto.",
                            "Spostamento manicotto scarico di 12 cm verso est.",
                            "Ferri integrativi posati e verificati dalla DL.",
                            "Nulla osta al getto del 29 agosto.",
                        ],
                    },
                },
            },
            {
                "title": "Getto platea, setti interrati e maturazione",
                "status": TaskActivityStatus.COMPLETED,
                "start": "2025-09-05",
                "end": "2025-09-12",
                "workers": ["elisa-brambilla", "giorgio-bellini", "bogdan-muresan"],
                "note": "Getto unico avviato alle 05:30 con sequenza e maturazione registrate nel verbale di giornata.",
            },
        ],
    },
    {
        "family": "structures",
        "name": "Strutture verticali, solai e vani scala",
        "company": "strutture",
        "start": "2025-09-15",
        "end": "2025-11-28",
        "progress": 100,
        "note": "Carpenteria, ferri e getti fino alla copertura con controllo quote, vani scala e tolleranze ascensore.",
        "activities": [
            {
                "title": "Pilastri interrato e solaio piano terra",
                "status": TaskActivityStatus.COMPLETED,
                "start": "2025-09-15",
                "end": "2025-10-03",
                "workers": ["giorgio-bellini", "cristian-pavan", "bogdan-muresan"],
                "note": "Predisposti giunti e cavedi prima del getto solaio piano terra.",
            },
            {
                "title": "Scale, vani ascensore e pareti setto",
                "status": TaskActivityStatus.COMPLETED,
                "start": "2025-10-06",
                "end": "2025-10-24",
                "workers": ["elisa-brambilla", "giorgio-bellini", "bogdan-muresan"],
                "note": "Controllo dimensionale eseguito prima del secondo getto del vano guida.",
            },
            {
                "title": "Solai piano primo e secondo",
                "status": TaskActivityStatus.COMPLETED,
                "start": "2025-10-27",
                "end": "2025-11-12",
                "workers": ["giorgio-bellini", "cristian-pavan", "ionut-marin"],
                "note": "Aperture tecniche verificate con impianti prima dei getti.",
            },
            {
                "title": "Travi di copertura, cordoli e chiusura strutture",
                "status": TaskActivityStatus.COMPLETED,
                "start": "2025-11-13",
                "end": "2025-11-28",
                "workers": ["elisa-brambilla", "giorgio-bellini", "cristian-pavan"],
                "note": "Rilievo finale aggiornato per passaggio a copertura e facciata.",
            },
        ],
    },
    {
        "family": "envelope",
        "name": "Tamponamenti, copertura e impermeabilizzazioni",
        "company": "gc",
        "start": "2025-12-01",
        "end": "2026-01-31",
        "progress": 86,
        "note": "Chiusura involucro con laterizi, copertura, risvolti e lattonerie di bordo.",
        "activities": [
            {
                "title": "Tamponamenti esterni in laterizio porizzato",
                "status": TaskActivityStatus.COMPLETED,
                "start": "2025-12-01",
                "end": "2025-12-23",
                "workers": ["luca-gatti", "omar-elidrissi", "samuele-rota"],
                "note": "Falsi telai allineati ai prospetti serramenti con ritocchi minimi sul fronte scala.",
            },
            {
                "title": "Impermeabilizzazione copertura piana e risvolti",
                "status": TaskActivityStatus.PROGRESS,
                "start": "2026-01-07",
                "end": "2026-01-24",
                "workers": ["luca-gatti", "omar-elidrissi", "davide-pini"],
                "note": "Tratto ovest chiuso dopo confronto sul nodo tra lucernario, sfiato e parapetto.",
                "issue": {
                    "status": "resolved",
                    "title": "Dettaglio risvolto ovest in corrispondenza dello sfiato lucernario",
                    "impact": "Il primo sviluppo della guaina lasciava un nodo poco leggibile nel bordo ovest.",
                    "action": "Nodo aggiornato con fascia aggiuntiva e lattoneria speciale. Prova di tenuta chiusa positivamente.",
                    "document": {
                        "name": "verbale-tenuta-copertura-ovest.pdf",
                        "title": "Verbale tenuta copertura ovest",
                        "lines": [
                            "Verifica del 24 gennaio in presenza DL e impresa.",
                            "Nodo sfiato lucernario ripreso con fascia aggiuntiva.",
                            "Lattoneria speciale installata sul bordo ovest.",
                            "Nessuna infiltrazione rilevata al test finale.",
                        ],
                    },
                },
            },
            {
                "title": "Lattonerie e scarichi pluviali",
                "status": TaskActivityStatus.PROGRESS,
                "start": "2026-01-15",
                "end": "2026-01-31",
                "workers": ["omar-elidrissi", "stefano-riva", "davide-pini"],
                "note": "Resta solo il raccordo finale sul corpo scala lato corte prima del rilascio del fronte facciata.",
            },
        ],
    },
    {
        "family": "facade",
        "name": "Facciata ventilata e serramenti esterni",
        "company": "serramenti",
        "start": "2026-01-20",
        "end": "2026-03-21",
        "progress": 64,
        "note": "Rilievi, controtelai, serramenti e facciata ventilata con controllo dei nodi di attacco.",
        "activities": [
            {
                "title": "Rilievo facciate, campionatura pannelli e mockup",
                "status": TaskActivityStatus.COMPLETED,
                "start": "2026-01-20",
                "end": "2026-01-31",
                "workers": ["davide-sala", "martina-cattaneo", "davide-pini"],
                "note": "Mockup sud-ovest approvato con nodo serramento-facciata validato dalla DL.",
                "attachment": {
                    "kind": "image",
                    "name": "mockup-facciata-sud-ovest.svg",
                    "title": "Mockup facciata sud-ovest",
                    "subtitle": "Pannello campione, nodo serramento e lattoneria.",
                    "accent": "#0f766e",
                    "source_dir": "attachments",
                },
            },
            {
                "title": "Controtelai, davanzali prefabbricati e nastri",
                "status": TaskActivityStatus.PROGRESS,
                "start": "2026-02-03",
                "end": "2026-02-21",
                "workers": ["davide-pini", "cosmin-petrescu"],
                "note": "Da correggere la quota del foro cucina 2B prima del secondo lotto serramenti.",
                "issue": {
                    "status": "open",
                    "title": "Fuori quota foro cucina unita 2B",
                    "impact": "Il rilievo del 4 aprile conferma un disallineamento di 18 mm sul traverso superiore lato sud.",
                    "action": "Serve controtelaio correttivo e validazione DL prima del montaggio del lotto B serramenti.",
                    "document": {
                        "name": "rilievo-foro-cucina-2b.pdf",
                        "title": "Rilievo foro cucina 2B",
                        "lines": [
                            "Rilievo effettuato il 4 aprile alle 08:10.",
                            "Scostamento traverso superiore: 18 mm verso basso.",
                            "Davanzale prefabbricato da riallineare prima del lotto B.",
                            "Richiesta validazione DL entro il giorno successivo.",
                        ],
                    },
                },
            },
            {
                "title": "Montaggio serramenti esterni dei livelli abitativi",
                "status": TaskActivityStatus.PROGRESS,
                "start": "2026-02-22",
                "end": "2026-03-21",
                "workers": ["martina-cattaneo", "davide-pini", "cosmin-petrescu"],
                "note": "Cronoprogramma scaglionato per non fermare massetti e finiture dei livelli gia pronti.",
            },
        ],
    },
    {
        "family": "mechanical",
        "name": "Impianto meccanico, idrico e antincendio",
        "company": "meccanico",
        "start": "2026-01-07",
        "end": "2026-03-28",
        "progress": 72,
        "note": "Reti scarico, adduzioni, centrale termica, VMC e antincendio box con pre-collaudi progressivi.",
        "activities": [
            {
                "title": "Colonne di scarico e reti verticali bagni",
                "status": TaskActivityStatus.COMPLETED,
                "start": "2026-01-07",
                "end": "2026-01-24",
                "workers": ["stefano-riva", "filippo-orsenigo"],
                "note": "Tenuta verificata prima della chiusura cavedi e foto archiviate nella cartella impianti.",
            },
            {
                "title": "Centrale termica, dorsali e collettori di piano",
                "status": TaskActivityStatus.PROGRESS,
                "start": "2026-01-25",
                "end": "2026-02-21",
                "workers": ["giulia-roversi", "stefano-riva", "filippo-orsenigo"],
                "note": "Attese le ultime valvole di bilanciamento e la conferma staffaggi nel locale tecnico.",
                "attachment": {
                    "kind": "image",
                    "name": "centrale-termica-precollaudo.svg",
                    "title": "Centrale termica",
                    "subtitle": "Dorsali principali e area collettori in allestimento.",
                    "accent": "#ea580c",
                    "source_dir": "attachments",
                },
                "issue": {
                    "status": "open",
                    "title": "Valvole di bilanciamento non ancora consegnate",
                    "impact": "L'assenza del lotto valvole blocca il bilanciamento definitivo e sposta il pre-collaudo della centrale.",
                    "action": "Serve conferma consegna fornitore e piano di installazione accelerato prima di aprire i test integrati.",
                    "document": {
                        "name": "checklist-valvole-bilanciamento.pdf",
                        "title": "Checklist valvole bilanciamento",
                        "lines": [
                            "Valvole DN32 e DN40 mancanti in centrale termica.",
                            "Impatto diretto sul pre-collaudo idronico del 9 aprile.",
                            "Fornitore atteso in cantiere entro 48 ore.",
                            "Installazione da concentrare su locale tecnico e piano primo.",
                        ],
                    },
                },
            },
            {
                "title": "VMC, canali corridoi e rete antincendio box",
                "status": TaskActivityStatus.PROGRESS,
                "start": "2026-02-22",
                "end": "2026-03-28",
                "workers": ["stefano-riva", "ahmed-bensalem", "filippo-orsenigo"],
                "note": "Staffaggi coordinati con passerelle elettriche, resta aperto il corridoio nord del piano secondo.",
            },
        ],
    },
    {
        "family": "electrical",
        "name": "Impianto elettrico, dati e sistemi di sicurezza",
        "company": "elettrico",
        "start": "2026-01-10",
        "end": "2026-03-31",
        "progress": 68,
        "note": "Passerelle, montanti, quadri di piano, reti dati e sistemi speciali con verifiche continue.",
        "activities": [
            {
                "title": "Cavidotti, passerelle e montanti tecnici",
                "status": TaskActivityStatus.COMPLETED,
                "start": "2026-01-10",
                "end": "2026-01-27",
                "workers": ["andrea-fontana", "nicolas-moretti", "matteo-cerri"],
                "note": "Interrato completato e coordinato con antincendio senza rilievi aperti.",
            },
            {
                "title": "Quadri elettrici di piano e dorsali forza motrice",
                "status": TaskActivityStatus.PROGRESS,
                "start": "2026-01-28",
                "end": "2026-02-28",
                "workers": ["paolo-longhi", "andrea-fontana", "nicolas-moretti"],
                "note": "Quadro Q3 chiuso dopo riallineamento delle linee speciali del vano tecnico.",
                "issue": {
                    "status": "resolved",
                    "title": "Riallineamento linee speciali quadro Q3",
                    "impact": "Le linee speciali del vano tecnico interferivano con il layout iniziale del quadro di piano Q3.",
                    "action": "Schema rivisto, morsettiere riposizionate e chiusura quadro confermata con test continuita.",
                    "document": {
                        "name": "schema-aggiornato-quadro-q3.pdf",
                        "title": "Schema aggiornato quadro Q3",
                        "lines": [
                            "Riposizionamento morsettiere linee speciali.",
                            "Separazione chiara tra FM, dati e sicurezza.",
                            "Test continuita eseguito e firmato dal capo commessa.",
                            "Q3 disponibile per collegamento finale.",
                        ],
                    },
                },
            },
            {
                "title": "Impianto dati, videosorveglianza e controllo accessi",
                "status": TaskActivityStatus.PROGRESS,
                "start": "2026-03-01",
                "end": "2026-03-31",
                "workers": ["andrea-fontana", "matteo-cerri"],
                "note": "Da confermare soltanto la posizione definitiva del monitor citofonico nella hall principale.",
            },
        ],
    },
    {
        "family": "interiors",
        "name": "Partizioni interne, massetti e controsoffitti",
        "company": "finiture",
        "start": "2026-02-01",
        "end": "2026-03-29",
        "progress": 48,
        "note": "Partizioni, chiusure cavedi, massetti e controsoffitti coordinati con gli impianti.",
        "activities": [
            {
                "title": "Tramezzi cartongesso e chiusure cavedi",
                "status": TaskActivityStatus.PROGRESS,
                "start": "2026-02-01",
                "end": "2026-02-18",
                "workers": ["lorenzo-gallo", "alina-popescu"],
                "note": "Foto delle predisposizioni archiviate prima della chiusura di ogni cavedio.",
            },
            {
                "title": "Sottofondi impianti e massetti dei livelli abitativi",
                "status": TaskActivityStatus.PROGRESS,
                "start": "2026-02-19",
                "end": "2026-03-08",
                "workers": ["antonio-esposito", "stefano-riva", "andrea-fontana"],
                "note": "Da ricontrollare i picchetti di quota in 1A e 3C prima del lotto massetti finali.",
                "issue": {
                    "status": "open",
                    "title": "Scostamento quota massetto unita 1A e 3C",
                    "impact": "Il controllo del 4 aprile segnala differenze tra quota prevista e picchetti di campo nei due alloggi campione.",
                    "action": "Serve nuova battuta quote con impianti e finiture prima di completare il massetto finale.",
                    "document": {
                        "name": "verifica-quote-massetti-1a-3c.pdf",
                        "title": "Verifica quote massetti 1A-3C",
                        "lines": [
                            "Scostamento misurato tra 7 e 11 mm nei due alloggi campione.",
                            "Verificare subito i riferimenti lasciati da impianti elettrici e idraulici.",
                            "Conferma quote richiesta prima del prossimo lotto massetti.",
                            "Aggiornare tavola quote interne dopo il sopralluogo con DL.",
                        ],
                    },
                },
            },
            {
                "title": "Bagno campione 2B e superfici di riferimento",
                "status": TaskActivityStatus.PROGRESS,
                "start": "2026-03-09",
                "end": "2026-03-29",
                "workers": ["antonio-esposito", "sofia-mancini", "alina-popescu"],
                "note": "Bagno campione usato come riferimento per fughe, tagli, sanitari e chiusura delle finiture.",
                "attachment": {
                    "kind": "image",
                    "name": "bagno-campione-2b.svg",
                    "title": "Bagno campione 2B",
                    "subtitle": "Rivestimenti e sanitari di riferimento per il lotto abitativo.",
                    "accent": "#1d4ed8",
                    "source_dir": "attachments",
                },
            },
        ],
    },
    {
        "family": "finishes",
        "name": "Finiture interne, arredi fissi e pre-collaudi",
        "company": "finiture",
        "start": "2026-03-16",
        "end": "2026-04-24",
        "progress": 18,
        "note": "Pavimenti, rivestimenti, tinteggiature, montaggi finali e pulizie tecniche degli alloggi campione.",
        "activities": [
            {
                "title": "Pavimenti gres e rivestimenti bagni",
                "status": TaskActivityStatus.PROGRESS,
                "start": "2026-03-16",
                "end": "2026-03-31",
                "workers": ["antonio-esposito", "alina-popescu"],
                "note": "Bagno campione 2B usato come riferimento per fughe, tagli e posa rivestimenti.",
            },
            {
                "title": "Tinteggiature, smalti ringhiere e parti comuni",
                "status": TaskActivityStatus.TODO,
                "start": "2026-03-28",
                "end": "2026-04-08",
                "workers": ["alina-popescu", "sofia-mancini"],
                "note": "Confermare tonalita finali con committenza prima della seconda mano.",
            },
            {
                "title": "Montaggio porte interne, sanitari e arredi fissi",
                "status": TaskActivityStatus.TODO,
                "start": "2026-04-01",
                "end": "2026-04-15",
                "workers": ["stefano-riva", "davide-pini", "antonio-esposito"],
                "note": "Porte e sanitari in consegna in due lotti, con priorita agli alloggi campione.",
            },
            {
                "title": "Pulizie tecniche e check appartamenti campione",
                "status": TaskActivityStatus.TODO,
                "start": "2026-04-14",
                "end": "2026-04-24",
                "workers": ["samuele-rota", "sofia-mancini", "valentina-neri"],
                "note": "Lista punch per ogni alloggio campione prima del walkthrough con committenza.",
            },
        ],
    },
    {
        "family": "handover",
        "name": "Collaudi integrati, documentazione finale e consegna",
        "company": "studio",
        "start": "2026-04-01",
        "end": "2026-04-30",
        "progress": 4,
        "note": "Collaudi progressivi, punch list finale, as-built e passaggio documentale verso committenza e gestore.",
        "alert": True,
        "activities": [
            {
                "title": "Collaudi impiantistici integrati",
                "status": TaskActivityStatus.TODO,
                "start": "2026-04-01",
                "end": "2026-04-12",
                "workers": ["laura-ferretti", "paolo-longhi", "giulia-roversi"],
                "note": "Attivita critica legata ai prerequisiti impiantistici e alla chiusura delle ultime valvole.",
                "issue": {
                    "status": "open",
                    "title": "Prerequisiti incompleti per pre-collaudo VMC e antincendio",
                    "impact": "Senza chiusura delle valvole meccaniche e conferma rete antincendio box non e possibile avviare il calendario collaudi.",
                    "action": "Aggiornare piano azioni, bloccare nuove interferenze e confermare le prove con tutti i referenti presenti.",
                    "document": {
                        "name": "piano-azioni-precollaudo-vmc-antincendio.pdf",
                        "title": "Piano azioni pre-collaudo VMC e antincendio",
                        "lines": [
                            "Chiudere consegna valvole e installazione entro 48 ore.",
                            "Confermare test rete antincendio box con idrotermica e GC.",
                            "Riallineare agenda collaudi solo dopo evidenze e verbali.",
                            "Aggiornare registro criticita alla chiusura di ogni prerequisito.",
                        ],
                    },
                },
            },
            {
                "title": "Punch list direzione lavori e sicurezza",
                "status": TaskActivityStatus.TODO,
                "start": "2026-04-09",
                "end": "2026-04-18",
                "workers": ["laura-ferretti", "serena-costantini", "marco-rinaldi"],
                "note": "Preparare elenco alloggi e parti comuni con responsabilita e tempi di chiusura.",
            },
            {
                "title": "As-built, manuali e formazione gestore",
                "status": TaskActivityStatus.TODO,
                "start": "2026-04-18",
                "end": "2026-04-30",
                "workers": ["davide-sala", "matteo-cerri", "filippo-orsenigo"],
                "note": "Raccolta seriali apparecchiature e indice manuali entro il 18 aprile, briefing finale incluso.",
            },
        ],
    },
]


class Seeder:
    def __init__(self, *, viewer_email: str, viewer_password: str):
        self.user_model = get_user_model()
        self.today = timezone.localdate()
        self.shift = self.today - BLUEPRINT_TODAY
        self.viewer_email = viewer_email or DEFAULT_VIEWER_EMAIL
        self.viewer_password = viewer_password or DEFAULT_VIEWER_PASSWORD
        self.workspaces: dict[str, Workspace] = {}
        self.profiles: dict[str, Profile] = {}
        self.project_role_codes: dict[str, list[str]] = {}
        self.viewer_profile: Profile | None = None
        self.project: Project | None = None
        self.folders: dict[str, ProjectFolder] = {}

    def shift_day(self, value: str | date) -> date:
        return parse_day(value) + self.shift

    def clamp_report_day(self, status: str, start_day: date, end_day: date) -> date:
        if status == TaskActivityStatus.COMPLETED:
            return end_day
        if status == TaskActivityStatus.TODO:
            return start_day - timedelta(days=2)
        return min(max(self.today, start_day), end_day)

    def ensure_viewer_profile(self) -> Profile:
        profile = (
            Profile.objects.select_related("workspace", "user")
            .filter(email__iexact=self.viewer_email, is_active=True, workspace__is_active=True)
            .order_by("id")
            .first()
        )
        if profile is not None:
            self.viewer_profile = profile
            return profile
        user = self.user_model.objects.filter(email__iexact=self.viewer_email).first()
        if user is None:
            user = self.user_model.objects.create_user(
                email=self.viewer_email,
                password=self.viewer_password,
                first_name="Demo",
                last_name="Viewer",
                language="it",
            )
        workspace, _ = Workspace.objects.get_or_create(
            slug="edilcloud-demo-access",
            defaults={
                "name": "EdilCloud Demo Access",
                "email": self.viewer_email,
                "workspace_type": "demo",
                "description": "Workspace locale per accedere al progetto demo.",
                "color": "#475569",
            },
        )
        if not workspace.logo:
            optimized_logo = optimize_media_content(
                filename="edilcloud-demo-access-logo.svg",
                content=build_logo("Demo Access", "#475569"),
                content_type="image/svg+xml",
            )
            workspace.logo.save("edilcloud-demo-access-logo.svg", optimized_logo, save=True)
        profile, _ = Profile.objects.get_or_create(
            workspace=workspace,
            user=user,
            defaults={
                "email": self.viewer_email,
                "role": WorkspaceRole.OWNER,
                "first_name": user.first_name or "Demo",
                "last_name": user.last_name or "Viewer",
                "language": "it",
                "position": "Accesso locale demo",
            },
        )
        self.viewer_profile = profile
        return profile

    def ensure_companies(self) -> None:
        for company in COMPANIES:
            slug = slugify(company["name"])
            workspace = Workspace.objects.filter(slug=slug).first() or Workspace(name=company["name"], slug=slug)
            workspace.name = company["name"]
            workspace.email = company["email"]
            workspace.vat_number = company["vat"]
            workspace.color = company["color"]
            workspace.workspace_type = "company"
            workspace.description = company["name"]
            workspace.is_active = True
            workspace.save()
            logo_name, logo_bytes = resolve_logo_source(company["code"], slug, company["name"], company["color"])
            if not workspace.logo or find_demo_source_file(
                relative_dir=f"companies/{company['code']}",
                preferred_filename="logo.svg",
                extensions=LOGO_SOURCE_EXTENSIONS,
            ):
                optimized_logo = optimize_media_content(filename=logo_name, content=logo_bytes)
                workspace.logo.save(
                    Path(getattr(optimized_logo, "name", "") or logo_name).name,
                    optimized_logo,
                    save=True,
                )
            self.workspaces[company["code"]] = workspace
            for code, first_name, last_name, email, position, role, project_role_codes in company["people"]:
                user = self.user_model.objects.filter(email__iexact=email).first()
                if user is None:
                    user = self.user_model.objects.create_user(
                        email=email,
                        password=self.viewer_password,
                        first_name=first_name,
                        last_name=last_name,
                        language="it",
                    )
                profile, _ = Profile.objects.get_or_create(
                    workspace=workspace,
                    user=user,
                    defaults={
                        "email": email,
                        "role": role,
                        "first_name": first_name,
                        "last_name": last_name,
                        "language": "it",
                        "position": position,
                    },
                )
                profile.email = email
                profile.role = role
                profile.first_name = first_name
                profile.last_name = last_name
                profile.language = "it"
                profile.position = position
                profile.is_active = True
                profile.save()
                avatar_source = resolve_avatar_source(code)
                if avatar_source is not None:
                    avatar_name, avatar_bytes = avatar_source
                    optimized_avatar = optimize_media_content(filename=avatar_name, content=avatar_bytes)
                    profile.photo.save(
                        Path(getattr(optimized_avatar, "name", "") or avatar_name).name,
                        optimized_avatar,
                        save=True,
                    )
                self.profiles[code] = profile
                self.project_role_codes[code] = list(project_role_codes)

    def delete_existing_project(self) -> None:
        project = Project.objects.filter(name=PROJECT_BLUEPRINT["name"]).first()
        if project is None:
            return
        for attachment in PostAttachment.objects.filter(post__project=project):
            if attachment.file:
                attachment.file.delete(save=False)
        for attachment in CommentAttachment.objects.filter(comment__post__project=project):
            if attachment.file:
                attachment.file.delete(save=False)
        for document in project.documents.all():
            if document.document:
                document.document.delete(save=False)
        for photo in project.photos.all():
            if photo.photo:
                photo.photo.delete(save=False)
        project.delete()

    def create_project(self) -> None:
        self.delete_existing_project()
        owner = self.profiles["laura-ferretti"]
        self.project = Project.objects.create(
            workspace=owner.workspace,
            created_by=owner,
            name=PROJECT_BLUEPRINT["name"],
            description=PROJECT_BLUEPRINT["description"],
            address=PROJECT_BLUEPRINT["address"],
            google_place_id=PROJECT_BLUEPRINT["google_place_id"],
            latitude=PROJECT_BLUEPRINT["latitude"],
            longitude=PROJECT_BLUEPRINT["longitude"],
            date_start=self.shift_day(PROJECT_BLUEPRINT["date_start"]),
            date_end=self.shift_day(PROJECT_BLUEPRINT["date_end"]),
            status=ProjectStatus.ACTIVE,
            is_demo_master=True,
            demo_snapshot_version="",
        )

    def attach_members(self) -> None:
        assert self.project is not None
        membership_date = aware(self.project.date_start - timedelta(days=10), 9, 0)
        for code, profile in self.profiles.items():
            member = ProjectMember.objects.create(
                project=self.project,
                profile=profile,
                role=profile.role,
                status=ProjectMemberStatus.ACTIVE,
                disabled=False,
                is_external=profile.workspace_id != self.project.workspace_id,
                project_role_codes=self.project_role_codes.get(code, []),
            )
            ProjectMember.objects.filter(pk=member.pk).update(created_at=membership_date, updated_at=membership_date, project_invitation_date=membership_date)
        viewer = self.ensure_viewer_profile()
        if viewer.id not in {profile.id for profile in self.profiles.values()}:
            member = ProjectMember.objects.create(
                project=self.project,
                profile=viewer,
                role=WorkspaceRole.MANAGER,
                status=ProjectMemberStatus.ACTIVE,
                disabled=False,
                is_external=viewer.workspace_id != self.project.workspace_id,
            )
            ProjectMember.objects.filter(pk=member.pk).update(created_at=membership_date, updated_at=membership_date, project_invitation_date=membership_date)

    def ensure_project_workspace_superuser_profiles(self) -> None:
        assert self.project is not None

        superusers = (
            self.user_model.objects.filter(is_superuser=True, is_active=True)
            .exclude(email__iexact=self.viewer_email)
            .order_by("id")
        )
        for user in superusers:
            email = (user.email or "").strip().lower()
            if not email:
                continue

            profile, _ = Profile.objects.get_or_create(
                workspace=self.project.workspace,
                user=user,
                defaults={
                    "email": user.email,
                    "role": WorkspaceRole.OWNER,
                    "first_name": user.first_name or "Super",
                    "last_name": user.last_name or "Admin",
                    "language": getattr(user, "language", "it") or "it",
                    "position": "Superadmin piattaforma",
                    "is_active": True,
                },
            )

            updated = False
            if profile.email != user.email:
                profile.email = user.email
                updated = True
            if profile.role != WorkspaceRole.OWNER:
                profile.role = WorkspaceRole.OWNER
                updated = True
            if not profile.first_name and user.first_name:
                profile.first_name = user.first_name
                updated = True
            if not profile.last_name and user.last_name:
                profile.last_name = user.last_name
                updated = True
            if not profile.position:
                profile.position = "Superadmin piattaforma"
                updated = True
            if not profile.language:
                profile.language = getattr(user, "language", "it") or "it"
                updated = True
            if not profile.is_active:
                profile.is_active = True
                updated = True
            if updated:
                profile.save()

    def attach_workspace_superusers(self) -> None:
        assert self.project is not None
        membership_date = aware(self.project.date_start - timedelta(days=10), 9, 5)
        superuser_profiles = (
            Profile.objects.select_related("user", "workspace")
            .filter(
                workspace=self.project.workspace,
                is_active=True,
                user__is_superuser=True,
                user__is_active=True,
            )
            .exclude(id__in=[profile.id for profile in self.profiles.values()])
        )
        if self.viewer_profile is not None:
            superuser_profiles = superuser_profiles.exclude(id=self.viewer_profile.id)

        for profile in superuser_profiles:
            member, _ = ProjectMember.objects.get_or_create(
                project=self.project,
                profile=profile,
                defaults={
                    "role": profile.role,
                    "status": ProjectMemberStatus.ACTIVE,
                    "disabled": False,
                    "is_external": profile.workspace_id != self.project.workspace_id,
                    "project_role_codes": [],
                },
            )
            ProjectMember.objects.filter(pk=member.pk).update(
                role=profile.role,
                status=ProjectMemberStatus.ACTIVE,
                disabled=False,
                is_external=profile.workspace_id != self.project.workspace_id,
                updated_at=membership_date,
                project_invitation_date=membership_date,
            )

    def apply_demo_project_company_colors(self) -> None:
        assert self.project is not None
        for company in COMPANIES:
            workspace = self.workspaces.get(company["code"])
            fixed_color = DEMO_PROJECT_COMPANY_COLORS.get(company["code"])
            if workspace is None or not fixed_color:
                continue
            ProjectCompanyColor.objects.update_or_create(
                project=self.project,
                workspace=workspace,
                defaults={"color_project": fixed_color},
            )

        if self.viewer_profile is not None:
            ProjectCompanyColor.objects.update_or_create(
                project=self.project,
                workspace=self.viewer_profile.workspace,
                defaults={"color_project": DEMO_VIEWER_PROJECT_COLOR},
            )

    def create_folder(self, chunks: list[str]) -> ProjectFolder:
        assert self.project is not None
        key = "/".join(chunks)
        if key in self.folders:
            return self.folders[key]
        parent = None
        current: list[str] = []
        for chunk in chunks:
            current.append(chunk)
            path = "/".join(current)
            if path in self.folders:
                parent = self.folders[path]
                continue
            folder = ProjectFolder.objects.create(
                project=self.project,
                parent=parent,
                name=chunk,
                path=path,
                is_public=False,
                is_root=parent is None,
            )
            self.folders[path] = folder
            parent = folder
        return self.folders[key]

    def create_documents(self) -> None:
        assert self.project is not None
        for blueprint in DOCUMENTS:
            folder = self.create_folder(blueprint["folder"])
            document = ProjectDocument(project=self.project, folder=folder, title=blueprint["title"], description=blueprint["title"])
            stored_name, stored_bytes = resolve_document_source(blueprint["filename"], blueprint["title"], blueprint["lines"])
            optimized_file = optimize_media_content(filename=stored_name, content=stored_bytes)
            document.document.save(Path(getattr(optimized_file, "name", "") or stored_name).name, optimized_file, save=False)
            document.save()
            created_at = aware(self.shift_day(blueprint["created_at"]), 10, 30)
            ProjectDocument.objects.filter(pk=document.pk).update(created_at=created_at, updated_at=created_at)

    def create_photos(self) -> None:
        assert self.project is not None
        for blueprint in PHOTOS:
            photo = ProjectPhoto(project=self.project, title=blueprint["title"])
            stored_name, stored_bytes = resolve_visual_source(
                blueprint["filename"],
                blueprint["title"],
                blueprint["subtitle"],
                blueprint["accent"],
            )
            optimized_file = optimize_media_content(filename=stored_name, content=stored_bytes)
            photo.photo.save(Path(getattr(optimized_file, "name", "") or stored_name).name, optimized_file, save=False)
            photo.save()
            created_at = aware(self.shift_day(blueprint["created_at"]), 15, 20)
            ProjectPhoto.objects.filter(pk=photo.pk).update(created_at=created_at, updated_at=created_at)

    def weather(self, day: date) -> dict[str, Any]:
        return {
            "source": "google-weather",
            "recordedAt": aware(day, 8, 0).isoformat(),
            "timeZone": "Europe/Rome",
            "summary": "Parzialmente nuvoloso",
            "conditionType": "PARTLY_CLOUDY",
            "isDaytime": True,
            "temperatureC": 16,
            "feelsLikeC": 15,
            "humidity": 63,
            "uvIndex": 3,
            "precipitationProbability": 12,
            "windSpeedKph": 14,
            "windGustKph": 21,
            "windDirection": "NE",
            "latitude": PROJECT_BLUEPRINT["latitude"],
            "longitude": PROJECT_BLUEPRINT["longitude"],
            "googlePlaceId": PROJECT_BLUEPRINT["google_place_id"],
        }

    def company_lead(self, company_code: str) -> str:
        workspace = self.workspaces[company_code]
        candidates = [(code, profile) for code, profile in self.profiles.items() if profile.workspace_id == workspace.id]
        for role in (WorkspaceRole.MANAGER, WorkspaceRole.OWNER, WorkspaceRole.DELEGATE):
            for code, profile in candidates:
                if profile.role == role:
                    return code
        return candidates[0][0]

    def worker_names(self, codes: list[str]) -> str:
        names = [self.profiles[code].member_name for code in codes]
        if len(names) <= 2:
            return ", ".join(names)
        return f"{names[0]}, {names[1]} e altre {len(names) - 2} persone"

    def attachment_items(
        self,
        *,
        attachment: dict[str, Any] | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        if attachment:
            items.append(attachment)
        if attachments:
            items.extend(attachments)
        return items

    def optimized_attachment_file(self, attachment: dict[str, Any]):
        if attachment.get("kind") == "image":
            stored_name, stored_bytes = resolve_visual_source(
                attachment["name"],
                attachment["title"],
                attachment["subtitle"],
                attachment["accent"],
                source_dir=attachment.get("source_dir"),
                category=attachment.get("asset_category", "attachment"),
            )
        else:
            stored_name, stored_bytes = resolve_document_source(attachment["name"], attachment["title"], attachment["lines"])
        optimized_file = optimize_media_content(filename=stored_name, content=stored_bytes)
        return Path(getattr(optimized_file, "name", "") or stored_name).name, optimized_file

    def save_post_attachment(self, post: ProjectPost, attachment: dict[str, Any]) -> None:
        upload = PostAttachment(post=post)
        stored_name, optimized_file = self.optimized_attachment_file(attachment)
        upload.file.save(stored_name, optimized_file, save=False)
        upload.save()

    def save_comment_attachment(self, comment: PostComment, attachment: dict[str, Any]) -> None:
        upload = CommentAttachment(comment=comment)
        stored_name, optimized_file = self.optimized_attachment_file(attachment)
        upload.file.save(stored_name, optimized_file, save=False)
        upload.save()

    def activity_attachments(self, family: str, index: int, activity_blueprint: dict[str, Any]) -> list[dict[str, Any]]:
        explicit_items = self.attachment_items(
            attachment=activity_blueprint.get("attachment"),
            attachments=activity_blueprint.get("attachments"),
        )
        if explicit_items:
            return explicit_items
        assets = ACTIVITY_EVIDENCE_ASSETS.get(family, [])
        if index < len(assets):
            return [assets[index]]
        return []

    def issue_attachments(self, family: str) -> list[dict[str, Any]]:
        asset = ISSUE_EVIDENCE_ASSETS.get(family)
        return [asset] if asset else []

    def author_code_for_dialogue(self, role: str, *, lead_code: str, family: str) -> str:
        context = THREAD_COMMUNICATIONS[family]
        if role == "lead":
            return lead_code
        if role in {"watcher", "stakeholder", "field"}:
            return context[role]
        return ROLE_AUTHOR_CODES.get(role, lead_code)

    def dialogue_values(self, *, lead_code: str, family: str, note: str = "", issue: dict[str, Any] | None = None) -> dict[str, str]:
        context = THREAD_COMMUNICATIONS[family]
        issue_status = (issue or {}).get("status", "")
        issue_closeout = (
            "Resta aperto. Lo tengo visibile in homepage, feed e report finche non arriva evidenza di chiusura."
            if issue_status == "open"
            else "Ok, chiudo la segnalazione e la tengo come storico per SAL, ricerca e assistant."
        )
        return {
            "lead_name": self.profiles[lead_code].member_name,
            "watcher_name": self.profiles[context["watcher"]].member_name,
            "stakeholder_name": self.profiles[context["stakeholder"]].member_name,
            "field_name": self.profiles[context["field"]].member_name,
            "checkpoint": context["checkpoint"],
            "decision": context["decision"],
            "next_action": context["next_action"],
            "note": note,
            "issue_impact": (issue or {}).get("impact", ""),
            "issue_action": (issue or {}).get("action", ""),
            "issue_closeout": issue_closeout,
        }

    def render_dialogue_text(
        self,
        text: str,
        *,
        lead_code: str,
        family: str,
        note: str = "",
        issue: dict[str, Any] | None = None,
    ) -> str:
        return text.format(**self.dialogue_values(lead_code=lead_code, family=family, note=note, issue=issue))

    def standard_dialogue_key(self, post: ProjectPost) -> str:
        if post.activity_id is None:
            return "phase"
        if post.activity.status == TaskActivityStatus.COMPLETED:
            return "completed"
        if post.activity.status == TaskActivityStatus.PROGRESS:
            return "progress"
        return "todo"

    def create_post(
        self,
        *,
        author_code: str,
        when: datetime,
        text: str,
        task: ProjectTask,
        activity: ProjectActivity | None = None,
        post_kind: str = PostKind.WORK_PROGRESS,
        alert: bool = False,
        is_public: bool = True,
        add_weather: bool = False,
        attachment: dict[str, Any] | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> ProjectPost:
        assert self.project is not None
        post = ProjectPost.objects.create(
            project=self.project,
            task=task,
            activity=activity,
            author=self.profiles[author_code],
            post_kind=post_kind,
            text=text,
            original_text=text,
            source_language="it",
            display_language="it",
            alert=alert,
            is_public=is_public,
            weather_snapshot=self.weather(when.date()) if add_weather else {},
        )
        ProjectPost.objects.filter(pk=post.pk).update(created_at=when, updated_at=when, published_date=when)
        for item in self.attachment_items(attachment=attachment, attachments=attachments):
            self.save_post_attachment(post, item)
        post.refresh_from_db()
        return post

    def create_comment(
        self,
        *,
        post: ProjectPost,
        author_code: str,
        when: datetime,
        text: str,
        parent: PostComment | None = None,
        attachment: dict[str, Any] | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> PostComment:
        comment = PostComment.objects.create(
            post=post,
            author=self.profiles[author_code],
            parent=parent,
            text=text,
            original_text=text,
            source_language="it",
            display_language="it",
        )
        PostComment.objects.filter(pk=comment.pk).update(created_at=when, updated_at=when)
        ProjectPost.objects.filter(pk=post.pk).update(updated_at=when)
        for item in self.attachment_items(attachment=attachment, attachments=attachments):
            self.save_comment_attachment(comment, item)
        comment.refresh_from_db()
        return comment

    def activity_text(self, task_blueprint: dict[str, Any], activity_blueprint: dict[str, Any], worker_names: str) -> str:
        del task_blueprint, worker_names
        if activity_blueprint.get("post_text"):
            return activity_blueprint["post_text"]
        if activity_blueprint["status"] == TaskActivityStatus.COMPLETED:
            return (
                "Chiusura confermata dal campo. Evidenze caricate, area lasciata in ordine "
                f"e nessun blocco residuo per il passaggio successivo. {activity_blueprint['note']}"
            )
        if activity_blueprint["status"] == TaskActivityStatus.PROGRESS:
            return (
                "Aggiornamento operativo: il fronte procede, ma tengo visibile il punto da presidiare "
                f"prima di liberare la prossima lavorazione. {activity_blueprint['note']}"
            )
        return (
            "Partenza da confermare. Prima di dare via libera servono materiali disponibili, "
            f"referente presente e interferenze risolte. {activity_blueprint['note']}"
        )

    def create_standard_thread(self, post: ProjectPost, *, lead_code: str, family: str, note: str) -> None:
        context = THREAD_COMMUNICATIONS[family]
        day = post.published_date.date()
        previous: PostComment | None = None
        for line in STANDARD_DIALOGUES[self.standard_dialogue_key(post)]:
            attachment = None
            if line.get("checkpoint_attachment") and post.activity_id is None:
                attachment = {
                    "name": f"memo-coordinamento-{family}.pdf",
                    "title": "Memo coordinamento operativo",
                    "lines": [
                        "Decisioni da tenere in evidenza:",
                        context["checkpoint"],
                        context["decision"],
                        context["next_action"],
                    ],
                }
            comment = self.create_comment(
                post=post,
                author_code=self.author_code_for_dialogue(str(line["author"]), lead_code=lead_code, family=family),
                when=aware(day, int(line["hour"]), int(line["minute"])),
                text=self.render_dialogue_text(str(line["text"]), lead_code=lead_code, family=family, note=note),
                parent=previous if line.get("parent") == "previous" else None,
                attachment=attachment,
            )
            previous = comment

    def create_issue_thread(self, post: ProjectPost, *, lead_code: str, family: str, issue: dict[str, Any]) -> None:
        day = post.published_date.date()
        previous: PostComment | None = None
        for line in ISSUE_DIALOGUE:
            attachment = issue["document"] if line.get("attachment") == "issue_document" else None
            comment = self.create_comment(
                post=post,
                author_code=self.author_code_for_dialogue(str(line["author"]), lead_code=lead_code, family=family),
                when=aware(day, int(line["hour"]), int(line["minute"])),
                text=self.render_dialogue_text(str(line["text"]), lead_code=lead_code, family=family, issue=issue),
                parent=previous if line.get("parent") == "previous" else None,
                attachment=attachment,
            )
            previous = comment

    def seed_tasks(self) -> None:
        assert self.project is not None
        for task_blueprint in TASKS:
            task = ProjectTask.objects.create(
                project=self.project,
                name=task_blueprint["name"],
                assigned_company=self.workspaces[task_blueprint["company"]],
                date_start=self.shift_day(task_blueprint["start"]),
                date_end=self.shift_day(task_blueprint["end"]),
                date_completed=self.shift_day(task_blueprint["end"]) if int(task_blueprint["progress"]) >= 100 else None,
                progress=task_blueprint["progress"],
                status=1,
                share_status=True,
                alert=bool(task_blueprint.get("alert")),
                starred=task_blueprint["progress"] < 100,
                note=task_blueprint["note"],
            )
            created_at = aware(task.date_start, 8, 15)
            ProjectTask.objects.filter(pk=task.pk).update(created_at=created_at, updated_at=created_at)
            lead_code = self.company_lead(task_blueprint["company"])
            kickoff = self.create_post(
                author_code=lead_code,
                when=aware(task.date_start, 8, 30),
                text=f"Apro il coordinamento operativo. Obiettivo: {task_blueprint['note']}",
                task=task,
                post_kind=PostKind.DOCUMENTATION,
                alert=bool(task_blueprint.get("alert")),
                is_public=True,
            )
            self.create_standard_thread(kickoff, lead_code=lead_code, family=task_blueprint["family"], note=task_blueprint["note"])

            for index, activity_blueprint in enumerate(task_blueprint["activities"]):
                start_day = self.shift_day(activity_blueprint["start"])
                end_day = self.shift_day(activity_blueprint["end"])
                activity = ProjectActivity.objects.create(
                    task=task,
                    title=activity_blueprint["title"],
                    description=activity_blueprint["note"],
                    status=activity_blueprint["status"],
                    progress=int(activity_blueprint.get("progress", ACTIVITY_STATUS_PROGRESS.get(activity_blueprint["status"], 0))),
                    datetime_start=aware(start_day, 7, 30),
                    datetime_end=aware(end_day, 17, 30),
                    alert=bool(activity_blueprint.get("issue") and activity_blueprint["issue"]["status"] == "open"),
                    starred=bool(activity_blueprint.get("issue")),
                    note=activity_blueprint["note"],
                )
                activity.workers.set([self.profiles[code] for code in activity_blueprint["workers"]])
                activity_created = aware(start_day, 7, 45 + index)
                ProjectActivity.objects.filter(pk=activity.pk).update(created_at=activity_created, updated_at=activity_created)

                report_day = self.clamp_report_day(activity_blueprint["status"], start_day, end_day)
                post = self.create_post(
                    author_code=lead_code,
                    when=aware(report_day, 8, 20 + index * 8),
                    text=self.activity_text(task_blueprint, activity_blueprint, self.worker_names(activity_blueprint["workers"])),
                    task=task,
                    activity=activity,
                    post_kind=PostKind.DOCUMENTATION if activity_blueprint["status"] == TaskActivityStatus.COMPLETED else PostKind.WORK_PROGRESS,
                    add_weather=activity_blueprint["status"] != TaskActivityStatus.TODO,
                    attachments=self.activity_attachments(task_blueprint["family"], index, activity_blueprint),
                )
                self.create_standard_thread(post, lead_code=lead_code, family=task_blueprint["family"], note=activity_blueprint["note"])

                if activity_blueprint.get("issue"):
                    issue = activity_blueprint["issue"]
                    issue_post = self.create_post(
                        author_code=lead_code,
                        when=aware(report_day, 16, 10 + index),
                        text=(
                            f'{"Blocco aperto" if issue["status"] == "open" else "Nodo chiuso"}. '
                            f'{issue["impact"]} '
                            f'{"Serve" if issue["status"] == "open" else "Chiusura"}: {issue["action"]}'
                        ),
                        task=task,
                        activity=activity,
                        post_kind=PostKind.ISSUE,
                        alert=issue["status"] == "open",
                        is_public=False,
                        add_weather=issue["status"] == "open",
                        attachments=self.issue_attachments(task_blueprint["family"]),
                    )
                    self.create_issue_thread(issue_post, lead_code=lead_code, family=task_blueprint["family"], issue=issue)

    def run(self) -> dict[str, Any]:
        self.ensure_viewer_profile()
        self.ensure_companies()
        self.create_project()
        self.attach_members()
        self.ensure_project_workspace_superuser_profiles()
        self.attach_workspace_superusers()
        self.apply_demo_project_company_colors()
        self.create_documents()
        self.create_photos()
        self.seed_tasks()
        assert self.project is not None
        return {
            "project_id": self.project.id,
            "project_name": self.project.name,
            "viewer_profile_id": self.viewer_profile.id if self.viewer_profile else None,
            "viewer_email": self.viewer_profile.email if self.viewer_profile else self.viewer_email,
            "members": ProjectMember.objects.filter(project=self.project, status=ProjectMemberStatus.ACTIVE).count(),
            "tasks": ProjectTask.objects.filter(project=self.project).count(),
            "activities": ProjectActivity.objects.filter(task__project=self.project).count(),
            "progress_percentage": seed_project_progress(),
            "progress_formula": f"media aritmetica delle fasi: {sum(int(task['progress']) for task in TASKS)} / {len(TASKS)} = {seed_project_progress()}%",
            "target_progress": DEMO_TARGET_PROGRESS,
            "asset_source_root": str(DEMO_ASSET_SOURCE_ROOT),
            "asset_source_version": DEMO_ASSET_VERSION,
            "documents": ProjectDocument.objects.filter(project=self.project).count(),
            "photos": ProjectPhoto.objects.filter(project=self.project).count(),
            "posts": ProjectPost.objects.filter(project=self.project).count(),
            "comments": PostComment.objects.filter(post__project=self.project).count(),
            "open_issues": ProjectPost.objects.filter(project=self.project, post_kind=PostKind.ISSUE, alert=True, is_deleted=False).count(),
            "resolved_issues": ProjectPost.objects.filter(project=self.project, post_kind=PostKind.ISSUE, alert=False, is_deleted=False).count(),
        }


class Command(BaseCommand):
    help = "Create a rich, realistic demo construction project with companies, tasks, documents, threads and attachments."

    def add_arguments(self, parser):
        parser.add_argument("--viewer-email", default=DEFAULT_VIEWER_EMAIL)
        parser.add_argument("--viewer-password", default=DEFAULT_VIEWER_PASSWORD)

    @transaction.atomic
    def handle(self, *args, **options):
        summary = Seeder(
            viewer_email=options["viewer_email"],
            viewer_password=options["viewer_password"],
        ).run()

        self.stdout.write(self.style.SUCCESS("Seed progetto demo completato."))
        self.stdout.write(
            f'Progetto #{summary["project_id"]}: {summary["project_name"]}\n'
            f'Profilo accesso locale: #{summary["viewer_profile_id"]} ({summary["viewer_email"]})\n'
            f'Membri: {summary["members"]} | Task: {summary["tasks"]} | Attivita: {summary["activities"]}\n'
            f'Avanzamento demo: {summary["progress_percentage"]}% ({summary["progress_formula"]})\n'
            f'Asset source: {summary["asset_source_version"]} -> {summary["asset_source_root"]}\n'
            f'Documenti: {summary["documents"]} | Foto: {summary["photos"]}\n'
            f'Post: {summary["posts"]} | Commenti: {summary["comments"]}\n'
            f'Issue aperte: {summary["open_issues"]} | Issue risolte: {summary["resolved_issues"]}'
        )
