from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from edilcloud.modules.projects.models import (
    CommentAttachment,
    PostAttachment,
    PostComment,
    PostKind,
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

COMPANIES: list[dict[str, Any]] = [
    {
        "code": "studio",
        "name": "Studio Tecnico Ferretti Associati",
        "email": "studio@ferretti-associati.it",
        "vat": "11873450961",
        "color": "#b45309",
        "people": [
            ("laura-ferretti", "Laura", "Ferretti", "laura.ferretti@ferretti-associati.it", "Direzione lavori", WorkspaceRole.OWNER),
            ("davide-sala", "Davide", "Sala", "davide.sala@ferretti-associati.it", "BIM coordinator", WorkspaceRole.MANAGER),
            ("serena-costantini", "Serena", "Costantini", "serena.costantini@ferretti-associati.it", "Coordinatrice sicurezza", WorkspaceRole.DELEGATE),
        ],
    },
    {
        "code": "gc",
        "name": "Aurora Costruzioni Generali",
        "email": "commesse@auroracostruzioni.it",
        "vat": "10866270158",
        "color": "#0f766e",
        "people": [
            ("marco-rinaldi", "Marco", "Rinaldi", "marco.rinaldi@auroracostruzioni.it", "Project manager", WorkspaceRole.OWNER),
            ("luca-gatti", "Luca", "Gatti", "luca.gatti@auroracostruzioni.it", "Capocantiere", WorkspaceRole.MANAGER),
            ("omar-elidrissi", "Omar", "El Idrissi", "omar.elidrissi@auroracostruzioni.it", "Caposquadra opere edili", WorkspaceRole.DELEGATE),
            ("samuele-rota", "Samuele", "Rota", "samuele.rota@auroracostruzioni.it", "Operaio specializzato", WorkspaceRole.WORKER),
        ],
    },
    {
        "code": "strutture",
        "name": "Strutture Nord Calcestruzzi",
        "email": "operations@strutturenord.it",
        "vat": "10244710964",
        "color": "#1d4ed8",
        "people": [
            ("elisa-brambilla", "Elisa", "Brambilla", "elisa.brambilla@strutturenord.it", "Responsabile strutture", WorkspaceRole.OWNER),
            ("giorgio-bellini", "Giorgio", "Bellini", "giorgio.bellini@strutturenord.it", "Caposquadra carpentieri", WorkspaceRole.MANAGER),
            ("cristian-pavan", "Cristian", "Pavan", "cristian.pavan@strutturenord.it", "Ferrista", WorkspaceRole.WORKER),
            ("ionut-marin", "Ionut", "Marin", "ionut.marin@strutturenord.it", "Operatore betonpompa", WorkspaceRole.WORKER),
        ],
    },
    {
        "code": "elettrico",
        "name": "Elettroimpianti Lombardi",
        "email": "cantieri@elettrolombardi.it",
        "vat": "09761530960",
        "color": "#0ea5e9",
        "people": [
            ("paolo-longhi", "Paolo", "Longhi", "paolo.longhi@elettrolombardi.it", "Capo commessa elettrico", WorkspaceRole.OWNER),
            ("andrea-fontana", "Andrea", "Fontana", "andrea.fontana@elettrolombardi.it", "Caposquadra impianti elettrici", WorkspaceRole.MANAGER),
            ("nicolas-moretti", "Nicolas", "Moretti", "nicolas.moretti@elettrolombardi.it", "Impiantista", WorkspaceRole.WORKER),
            ("matteo-cerri", "Matteo", "Cerri", "matteo.cerri@elettrolombardi.it", "Special systems", WorkspaceRole.DELEGATE),
        ],
    },
    {
        "code": "meccanico",
        "name": "Idrotermica Futura",
        "email": "cantieri@idrotermicafutura.it",
        "vat": "10574490154",
        "color": "#ea580c",
        "people": [
            ("giulia-roversi", "Giulia", "Roversi", "giulia.roversi@idrotermicafutura.it", "Project manager HVAC", WorkspaceRole.OWNER),
            ("stefano-riva", "Stefano", "Riva", "stefano.riva@idrotermicafutura.it", "Caposquadra idraulico", WorkspaceRole.MANAGER),
            ("ahmed-bensalem", "Ahmed", "Bensalem", "ahmed.bensalem@idrotermicafutura.it", "Canalista", WorkspaceRole.WORKER),
            ("filippo-orsenigo", "Filippo", "Orsenigo", "filippo.orsenigo@idrotermicafutura.it", "Frigorista", WorkspaceRole.DELEGATE),
        ],
    },
    {
        "code": "finiture",
        "name": "Facciate e Interni Bianchi",
        "email": "project@bianchifacade.it",
        "vat": "11266870963",
        "color": "#be123c",
        "people": [
            ("marta-bianchi", "Marta", "Bianchi", "marta.bianchi@bianchifacade.it", "Responsabile serramenti e finiture", WorkspaceRole.OWNER),
            ("davide-pini", "Davide", "Pini", "davide.pini@bianchifacade.it", "Caposquadra serramenti", WorkspaceRole.MANAGER),
            ("cosmin-petrescu", "Cosmin", "Petrescu", "cosmin.petrescu@bianchifacade.it", "Cartongessista", WorkspaceRole.WORKER),
            ("ivan-russo", "Ivan", "Russo", "ivan.russo@bianchifacade.it", "Pittore finiture", WorkspaceRole.DELEGATE),
            ("antonio-esposito", "Antonio", "Esposito", "antonio.esposito@bianchifacade.it", "Pavimentista", WorkspaceRole.WORKER),
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
            "Presenti: DL, GC, elettrico, meccanico e finiture.",
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
]

PHOTOS: list[dict[str, str]] = [
    {"filename": "fronte-sud-ovest.svg", "title": "Fronte sud-ovest", "subtitle": "Stato facciata, ponteggi e mockup serramenti.", "accent": "#0f766e", "created_at": "2026-04-03"},
    {"filename": "centrale-termica.svg", "title": "Centrale termica", "subtitle": "Dorsali principali e collettori in preparazione pre-collaudo.", "accent": "#ea580c", "created_at": "2026-04-03"},
    {"filename": "bagno-campione-2b-overview.svg", "title": "Bagno campione 2B", "subtitle": "Rivestimenti e sanitari di riferimento per il lotto abitativo.", "accent": "#1d4ed8", "created_at": "2026-04-04"},
    {"filename": "vano-scala-b.svg", "title": "Vano scala B", "subtitle": "Parete campione per rasature e finitura finale.", "accent": "#be123c", "created_at": "2026-04-04"},
]

FAMILY_LABELS = {
    "foundation": "quote, ferri, riprese e passaggi impiantistici",
    "envelope": "tenuta all'acqua, risvolti, lattonerie e nodi di bordo",
    "facade": "quote foro, nastri, allineamenti e nodi di attacco",
    "mechanical": "tenute, staffaggi, valvole e interfacce impiantistiche",
    "electrical": "layout quadri, linee speciali, dorsali e sistemi di sicurezza",
    "interiors": "quote finite, chiusure cavedi e superfici campione",
    "handover": "prerequisiti, verbali, as-built e responsabilita di chiusura",
}


def parse_day(value: str | date) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


def aware(day: date, hour: int, minute: int = 0) -> datetime:
    return timezone.make_aware(datetime.combine(day, time(hour=hour, minute=minute)))


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


def build_scene(title: str, subtitle: str, accent: str) -> bytes:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" viewBox="0 0 1600 900">'
        '<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0%" stop-color="{accent}"/><stop offset="100%" stop-color="#111827"/></linearGradient></defs>'
        '<rect width="1600" height="900" fill="#f5f5f4"/>'
        '<rect x="48" y="48" width="1504" height="804" rx="42" fill="url(#bg)"/>'
        '<path d="M160 650 L420 420 L610 510 L810 310 L1060 460 L1260 250 L1440 390" fill="none" stroke="rgba(255,255,255,0.45)" stroke-width="20" stroke-linecap="round"/>'
        f'<text x="128" y="188" font-size="56" font-family="Arial" font-weight="700" fill="#ffffff">{title}</text>'
        f'<text x="128" y="252" font-size="28" font-family="Arial" fill="rgba(255,255,255,0.88)">{subtitle}</text>'
        "</svg>"
    )
    return svg.encode("utf-8")


TASKS: list[dict[str, Any]] = [
    {
        "family": "foundation",
        "name": "Fondazioni, platea e interrato",
        "company": "strutture",
        "start": "2025-08-01",
        "end": "2025-09-12",
        "progress": 100,
        "note": "Scavi, platea, setti interrati e passaggi impiantistici coordinati al millimetro.",
        "activities": [
            {
                "title": "Scavo sbancamento e pulizia fronte nord",
                "status": TaskActivityStatus.COMPLETED,
                "start": "2025-08-01",
                "end": "2025-08-12",
                "workers": ["giorgio-bellini", "ionut-marin", "samuele-rota"],
                "note": "Percorso camion tenuto libero senza impatti sulla viabilita del lotto.",
            },
            {
                "title": "Magrone, ferri platea e passaggi impiantistici",
                "status": TaskActivityStatus.COMPLETED,
                "start": "2025-08-13",
                "end": "2025-08-28",
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
                "start": "2025-08-29",
                "end": "2025-09-12",
                "workers": ["elisa-brambilla", "giorgio-bellini", "ionut-marin"],
                "note": "Getto unico avviato alle 05:30 con sequenza e maturazione registrate nel verbale di giornata.",
            },
        ],
    },
    {
        "family": "envelope",
        "name": "Tamponamenti, copertura e impermeabilizzazioni",
        "company": "gc",
        "start": "2025-12-01",
        "end": "2026-01-31",
        "progress": 88,
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
        "company": "finiture",
        "start": "2026-01-20",
        "end": "2026-03-21",
        "progress": 67,
        "note": "Rilievi, controtelai, serramenti e facciata ventilata con controllo dei nodi di attacco.",
        "activities": [
            {
                "title": "Rilievo facciate, campionatura pannelli e mockup",
                "status": TaskActivityStatus.COMPLETED,
                "start": "2026-01-20",
                "end": "2026-01-31",
                "workers": ["davide-sala", "marta-bianchi", "davide-pini"],
                "note": "Mockup sud-ovest approvato con nodo serramento-facciata validato dalla DL.",
                "attachment": {
                    "kind": "image",
                    "name": "mockup-facciata-sud-ovest.svg",
                    "title": "Mockup facciata sud-ovest",
                    "subtitle": "Pannello campione, nodo serramento e lattoneria.",
                    "accent": "#0f766e",
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
                "workers": ["marta-bianchi", "davide-pini", "cosmin-petrescu"],
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
        "progress": 74,
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
        "progress": 71,
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
        "progress": 54,
        "note": "Partizioni, chiusure cavedi, massetti e controsoffitti coordinati con gli impianti.",
        "activities": [
            {
                "title": "Tramezzi cartongesso e chiusure cavedi",
                "status": TaskActivityStatus.PROGRESS,
                "start": "2026-02-01",
                "end": "2026-02-18",
                "workers": ["cosmin-petrescu", "ivan-russo"],
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
                "workers": ["antonio-esposito", "ivan-russo", "cosmin-petrescu"],
                "note": "Bagno campione usato come riferimento per fughe, tagli, sanitari e chiusura delle finiture.",
                "attachment": {
                    "kind": "image",
                    "name": "bagno-campione-2b.svg",
                    "title": "Bagno campione 2B",
                    "subtitle": "Rivestimenti e sanitari di riferimento per il lotto abitativo.",
                    "accent": "#1d4ed8",
                },
            },
        ],
    },
    {
        "family": "handover",
        "name": "Collaudi integrati, documentazione finale e consegna",
        "company": "studio",
        "start": "2026-04-01",
        "end": "2026-04-30",
        "progress": 8,
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
            workspace.logo.save("edilcloud-demo-access-logo.svg", ContentFile(build_logo("Demo Access", "#475569")), save=True)
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
            if not workspace.logo:
                workspace.logo.save(f"{slug}-logo.svg", ContentFile(build_logo(company["name"], company["color"])), save=True)
            self.workspaces[company["code"]] = workspace
            for code, first_name, last_name, email, position, role in company["people"]:
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
                self.profiles[code] = profile

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
        )

    def attach_members(self) -> None:
        assert self.project is not None
        membership_date = aware(self.project.date_start - timedelta(days=10), 9, 0)
        for profile in self.profiles.values():
            member = ProjectMember.objects.create(
                project=self.project,
                profile=profile,
                role=profile.role,
                status=ProjectMemberStatus.ACTIVE,
                disabled=False,
                is_external=profile.workspace_id != self.project.workspace_id,
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
            document.document.save(blueprint["filename"], ContentFile(build_pdf(blueprint["title"], blueprint["lines"])), save=False)
            document.save()
            created_at = aware(self.shift_day(blueprint["created_at"]), 10, 30)
            ProjectDocument.objects.filter(pk=document.pk).update(created_at=created_at, updated_at=created_at)

    def create_photos(self) -> None:
        assert self.project is not None
        for blueprint in PHOTOS:
            photo = ProjectPhoto(project=self.project, title=blueprint["title"])
            photo.photo.save(blueprint["filename"], ContentFile(build_scene(blueprint["title"], blueprint["subtitle"], blueprint["accent"])), save=False)
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
        if attachment:
            upload = PostAttachment(post=post)
            if attachment["kind"] == "image":
                upload.file.save(attachment["name"], ContentFile(build_scene(attachment["title"], attachment["subtitle"], attachment["accent"])), save=False)
            else:
                upload.file.save(attachment["name"], ContentFile(build_pdf(attachment["title"], attachment["lines"])), save=False)
            upload.save()
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
        if attachment:
            upload = CommentAttachment(comment=comment)
            upload.file.save(attachment["name"], ContentFile(build_pdf(attachment["title"], attachment["lines"])), save=False)
            upload.save()
        comment.refresh_from_db()
        return comment

    def activity_text(self, task_blueprint: dict[str, Any], activity_blueprint: dict[str, Any], worker_names: str) -> str:
        label = FAMILY_LABELS[task_blueprint["family"]]
        title = activity_blueprint["title"]
        if activity_blueprint["status"] == TaskActivityStatus.COMPLETED:
            return (
                f'Attivita "{title}" chiusa nella fase "{task_blueprint["name"]}". Squadra in campo: {worker_names}. '
                f'Confermate {label}. {activity_blueprint["note"]}'
            )
        if activity_blueprint["status"] == TaskActivityStatus.PROGRESS:
            return (
                f'Produzione attiva su "{title}" nella fase "{task_blueprint["name"]}". Squadra in campo: {worker_names}. '
                f'Oggi il presidio e su {label}. {activity_blueprint["note"]}'
            )
        return (
            f'Attivita pianificata "{title}" nella fase "{task_blueprint["name"]}". Prima della partenza vanno confermati '
            f'{label}. {activity_blueprint["note"]}'
        )

    def create_standard_thread(self, post: ProjectPost, *, lead_code: str, family: str, note: str) -> None:
        label = FAMILY_LABELS[family]
        day = post.published_date.date()
        first = self.create_comment(
            post=post,
            author_code="laura-ferretti",
            when=aware(day, 9, 35),
            text=f"Ricevuto aggiornamento. Voglio tenere presidio su {label} e chiudere bene il punto: {note}",
        )
        self.create_comment(
            post=post,
            author_code=lead_code,
            when=aware(day, 10, 5),
            text="Confermato. Allineo la squadra sul punto aperto e aggiorno il thread appena il fronte e stabilizzato.",
            parent=first,
        )
        self.create_comment(
            post=post,
            author_code="davide-sala",
            when=aware(day, 11, 20),
            text=f"Traccio il passaggio nel coordinamento di commessa. Questo thread resta il riferimento su {label}.",
        )

    def create_issue_thread(self, post: ProjectPost, *, lead_code: str, family: str, issue: dict[str, Any]) -> None:
        label = FAMILY_LABELS[family]
        day = post.published_date.date()
        first = self.create_comment(
            post=post,
            author_code="laura-ferretti",
            when=aware(day, 17, 35),
            text=f'Ricevuto il punto aperto su {issue["title"].lower()}. Voglio impatto aggiornato sul cronoprogramma e una chiusura leggibile per {label}.',
        )
        self.create_comment(
            post=post,
            author_code=lead_code,
            when=aware(day, 17, 58),
            text="Confermato. Tengo la squadra sul fronte e torno qui con tempi, contromisure ed evidenze appena il punto e verificato in campo.",
            parent=first,
        )
        review = self.create_comment(
            post=post,
            author_code="davide-sala",
            when=aware(day, 18, 18),
            text=f"Allego il documento di supporto e aggiorno il quadro tecnico. Il presidio resta su {label} fino a chiusura del punto.",
            attachment=issue["document"],
        )
        final_text = (
            "Punto chiuso e confermato. Manteniamo il thread come storico della soluzione adottata."
            if issue["status"] != "open"
            else "Perfetto, teniamo questo thread come riferimento unico fino alla chiusura operativa."
        )
        self.create_comment(
            post=post,
            author_code="serena-costantini",
            when=aware(day, 18, 42),
            text=final_text,
            parent=review,
        )

    def seed_tasks(self) -> None:
        assert self.project is not None
        for task_blueprint in TASKS:
            task = ProjectTask.objects.create(
                project=self.project,
                name=task_blueprint["name"],
                assigned_company=self.workspaces[task_blueprint["company"]],
                date_start=self.shift_day(task_blueprint["start"]),
                date_end=self.shift_day(task_blueprint["end"]),
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
                text=f'Coordinamento fase "{task_blueprint["name"]}": {task_blueprint["note"]}',
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
                    attachment=activity_blueprint.get("attachment"),
                )
                self.create_standard_thread(post, lead_code=lead_code, family=task_blueprint["family"], note=activity_blueprint["note"])

                if activity_blueprint.get("issue"):
                    issue = activity_blueprint["issue"]
                    issue_post = self.create_post(
                        author_code=lead_code,
                        when=aware(report_day, 16, 10 + index),
                        text=(
                            f'{"Segnalazione aperta" if issue["status"] == "open" else "Segnalazione risolta"} su "{activity_blueprint["title"]}" '
                            f'nella fase "{task_blueprint["name"]}": {issue["title"]}. Impatto: {issue["impact"]} '
                            f'{"Azione richiesta" if issue["status"] == "open" else "Chiusura"}: {issue["action"]}'
                        ),
                        task=task,
                        activity=activity,
                        post_kind=PostKind.ISSUE,
                        alert=issue["status"] == "open",
                        is_public=False,
                        add_weather=issue["status"] == "open",
                    )
                    self.create_issue_thread(issue_post, lead_code=lead_code, family=task_blueprint["family"], issue=issue)

    def run(self) -> dict[str, Any]:
        self.ensure_viewer_profile()
        self.ensure_companies()
        self.create_project()
        self.attach_members()
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
            f'Documenti: {summary["documents"]} | Foto: {summary["photos"]}\n'
            f'Post: {summary["posts"]} | Commenti: {summary["comments"]}\n'
            f'Issue aperte: {summary["open_issues"]} | Issue risolte: {summary["resolved_issues"]}'
        )
