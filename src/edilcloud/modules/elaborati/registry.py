"""Versioned editorial templates, NOT a certification of legal compliance."""

from copy import deepcopy

STYLES = ("technical", "corporate", "photographic")
TYPES = {
    "daily_report": (
        "Rapporto giornaliero di cantiere",
        (
            "Sintesi",
            "Lavorazioni e imprese",
            "Criticità e comunicazioni",
            "Meteo registrato",
            "Dati mancanti",
        ),
        ("Report di cantiere", "Giornalieri"),
    ),
    "inspection": (
        "Verbale di sopralluogo",
        (
            "Oggetto e luoghi",
            "Partecipanti dichiarati",
            "Rilievi",
            "Decisioni e indicazioni",
            "Punti da verificare",
        ),
        ("Verbali", "Sopralluoghi"),
    ),
    "coordination": (
        "Verbale di coordinamento",
        (
            "Oggetto",
            "Partecipanti dichiarati",
            "Argomenti trattati",
            "Decisioni",
            "Questioni aperte",
        ),
        ("Verbali", "Coordinamento"),
    ),
    "periodic_report": (
        "Relazione periodica stato cantiere",
        (
            "Sintesi direzionale",
            "Avanzamenti documentati",
            "Criticità",
            "Decisioni",
            "Documenti e fotografie",
            "Punti da verificare",
        ),
        ("Report di cantiere", "Periodici"),
    ),
    "photo_report": (
        "Relazione fotografica",
        ("Oggetto e periodo", "Contesto delle fotografie", "Osservazioni", "Dati mancanti"),
        ("Relazioni", "Fotografiche"),
    ),
    "issue_report": (
        "Relazione evento / criticità",
        (
            "Oggetto della criticità",
            "Cronologia",
            "Evidenze e interlocuzioni",
            "Esito disponibile",
            "Questioni aperte",
        ),
        ("Relazioni", "Eventi e criticità"),
    ),
}


LOCALIZED = {
    "en": {
        "daily_report": (
            "Daily site report",
            (
                "Summary",
                "Work and companies",
                "Issues and communications",
                "Recorded weather",
                "Missing information",
            ),
        ),
        "inspection": (
            "Site inspection minutes",
            (
                "Scope and locations",
                "Declared attendees",
                "Observations",
                "Decisions and instructions",
                "Points to verify",
            ),
        ),
        "coordination": (
            "Coordination meeting minutes",
            ("Subject", "Declared attendees", "Topics discussed", "Decisions", "Open questions"),
        ),
        "periodic_report": (
            "Periodic site status report",
            (
                "Executive summary",
                "Documented progress",
                "Issues",
                "Decisions",
                "Documents and photographs",
                "Points to verify",
            ),
        ),
        "photo_report": (
            "Photographic report",
            ("Scope and period", "Photograph context", "Observations", "Missing information"),
        ),
        "issue_report": (
            "Event / issue report",
            (
                "Issue description",
                "Chronology",
                "Evidence and communications",
                "Available outcome",
                "Open questions",
            ),
        ),
    },
    "fr": {
        "daily_report": (
            "Rapport journalier de chantier",
            (
                "Synthèse",
                "Travaux et entreprises",
                "Difficultés et communications",
                "Météo enregistrée",
                "Informations manquantes",
            ),
        ),
        "inspection": (
            "Compte rendu de visite",
            (
                "Objet et lieux",
                "Participants déclarés",
                "Constats",
                "Décisions et indications",
                "Points à vérifier",
            ),
        ),
        "coordination": (
            "Compte rendu de coordination",
            ("Objet", "Participants déclarés", "Sujets abordés", "Décisions", "Questions ouvertes"),
        ),
        "periodic_report": (
            "Rapport périodique de chantier",
            (
                "Synthèse de direction",
                "Avancement documenté",
                "Difficultés",
                "Décisions",
                "Documents et photographies",
                "Points à vérifier",
            ),
        ),
        "photo_report": (
            "Rapport photographique",
            (
                "Objet et période",
                "Contexte des photographies",
                "Observations",
                "Informations manquantes",
            ),
        ),
        "issue_report": (
            "Rapport d'événement / difficulté",
            (
                "Objet de la difficulté",
                "Chronologie",
                "Éléments et échanges",
                "Résultat disponible",
                "Questions ouvertes",
            ),
        ),
    },
    "ro": {
        "daily_report": (
            "Raport zilnic de șantier",
            (
                "Sinteză",
                "Lucrări și firme",
                "Probleme și comunicări",
                "Condiții meteo înregistrate",
                "Date lipsă",
            ),
        ),
        "inspection": (
            "Proces-verbal de inspecție",
            (
                "Obiect și locuri",
                "Participanți declarați",
                "Constatări",
                "Decizii și indicații",
                "Puncte de verificat",
            ),
        ),
        "coordination": (
            "Proces-verbal de coordonare",
            (
                "Obiect",
                "Participanți declarați",
                "Subiecte discutate",
                "Decizii",
                "Întrebări deschise",
            ),
        ),
        "periodic_report": (
            "Raport periodic privind șantierul",
            (
                "Sinteză executivă",
                "Progres documentat",
                "Probleme",
                "Decizii",
                "Documente și fotografii",
                "Puncte de verificat",
            ),
        ),
        "photo_report": (
            "Raport fotografic",
            ("Obiect și perioadă", "Contextul fotografiilor", "Observații", "Date lipsă"),
        ),
        "issue_report": (
            "Raport eveniment / problemă",
            (
                "Descrierea problemei",
                "Cronologie",
                "Dovezi și comunicări",
                "Rezultat disponibil",
                "Întrebări deschise",
            ),
        ),
    },
    "ru": {
        "daily_report": (
            "Ежедневный отчёт по стройплощадке",
            (
                "Сводка",
                "Работы и организации",
                "Проблемы и сообщения",
                "Зафиксированная погода",
                "Недостающие сведения",
            ),
        ),
        "inspection": (
            "Протокол осмотра",
            (
                "Предмет и места",
                "Заявленные участники",
                "Наблюдения",
                "Решения и указания",
                "Вопросы для проверки",
            ),
        ),
        "coordination": (
            "Протокол координационного совещания",
            (
                "Предмет",
                "Заявленные участники",
                "Обсуждённые вопросы",
                "Решения",
                "Открытые вопросы",
            ),
        ),
        "periodic_report": (
            "Периодический отчёт о состоянии объекта",
            (
                "Краткий обзор",
                "Документированный ход работ",
                "Проблемы",
                "Решения",
                "Документы и фотографии",
                "Вопросы для проверки",
            ),
        ),
        "photo_report": (
            "Фотоотчёт",
            ("Предмет и период", "Контекст фотографий", "Наблюдения", "Недостающие сведения"),
        ),
        "issue_report": (
            "Отчёт о событии / проблеме",
            (
                "Описание проблемы",
                "Хронология",
                "Доказательства и переписка",
                "Имеющийся результат",
                "Открытые вопросы",
            ),
        ),
    },
    "ar": {
        "daily_report": (
            "التقرير اليومي للموقع",
            (
                "ملخص",
                "الأعمال والشركات",
                "المشكلات والمراسلات",
                "الطقس المسجل",
                "المعلومات الناقصة",
            ),
        ),
        "inspection": (
            "محضر معاينة الموقع",
            (
                "الموضوع والمواقع",
                "المشاركون المصرح بهم",
                "الملاحظات",
                "القرارات والتعليمات",
                "نقاط تحتاج إلى تحقق",
            ),
        ),
        "coordination": (
            "محضر اجتماع التنسيق",
            (
                "الموضوع",
                "المشاركون المصرح بهم",
                "الموضوعات المناقشة",
                "القرارات",
                "المسائل المفتوحة",
            ),
        ),
        "periodic_report": (
            "التقرير الدوري لحالة الموقع",
            (
                "الملخص التنفيذي",
                "التقدم الموثق",
                "المشكلات",
                "القرارات",
                "المستندات والصور",
                "نقاط تحتاج إلى تحقق",
            ),
        ),
        "photo_report": (
            "التقرير المصور",
            ("الموضوع والفترة", "سياق الصور", "الملاحظات", "المعلومات الناقصة"),
        ),
        "issue_report": (
            "تقرير حدث / مشكلة",
            (
                "وصف المشكلة",
                "التسلسل الزمني",
                "الأدلة والمراسلات",
                "النتيجة المتاحة",
                "المسائل المفتوحة",
            ),
        ),
    },
}

CLOSINGS = {
    "en": "Prepared from the cited records and attributed declarations. Unverified points remain explicitly identified.",
    "fr": "Document rédigé à partir des sources et déclarations citées. Les points non vérifiés restent explicitement signalés.",
    "ro": "Document întocmit pe baza surselor și declarațiilor citate. Punctele neverificate rămân semnalate explicit.",
    "ru": "Документ подготовлен на основе указанных источников и заявлений. Непроверенные сведения отмечены явно.",
    "ar": "أُعدّ المستند استناداً إلى المصادر والإفادات المذكورة، مع توضيح النقاط التي لم يتم التحقق منها.",
}


def template_for(document_type: str, language="it") -> dict:
    if document_type not in TYPES:
        raise ValueError("Tipo di elaborato non supportato.")
    label, sections, folder = TYPES[document_type]
    if language != "it":
        label, sections = LOCALIZED.get(language, LOCALIZED["en"])[document_type]
    return deepcopy(
        {
            "key": document_type,
            "version": "2026.10.3",
            "country": "IT",
            "context": "Documentazione operativa di cantiere",
            "label": label,
            "sections": [
                {"key": f"section_{i + 1}", "label": title, "required": True}
                for i, title in enumerate(sections)
            ],
            "allowed_regulatory_references": [],
            "compliance_validated": False,
            "signatory_roles": ["o", "d", "m"],
            "drive_folder": list(folder),
            "language": language,
            "closing": CLOSINGS.get(
                language,
                "Documento redatto sulla base delle fonti e delle dichiarazioni indicate. I punti non verificati restano esplicitamente segnalati.",
            ),
        }
    )
