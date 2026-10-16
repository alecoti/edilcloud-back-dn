"""Documentary registers are part of the template, independent of prose length.

The provider fills named cells; the application owns columns and proportions.
Missing facts can therefore remain typed inputs in a useful complete structure.
"""

LANGUAGES = ("it", "en", "fr", "ro", "ru", "ar")
COLUMNS = {
    "time": (
        "Data / ora",
        "Date / time",
        "Date / heure",
        "Data / ora",
        "Дата / время",
        "التاريخ / الوقت",
    ),
    "work_front": (
        "Fronte / lavorazione",
        "Area / work",
        "Zone / travaux",
        "Zonă / lucrare",
        "Участок / работы",
        "المنطقة / الأعمال",
    ),
    "record": (
        "Registrazione documentata",
        "Documented record",
        "Fait documenté",
        "Înregistrare documentată",
        "Документированная запись",
        "السجل الموثق",
    ),
    "company": ("Impresa", "Company", "Entreprise", "Întreprindere", "Организация", "الشركة"),
    "person": (
        "Persona / addetti",
        "Person / workers",
        "Personne / effectif",
        "Persoană / lucrători",
        "Лицо / работники",
        "الشخص / العمال",
    ),
    "hours": (
        "Ore ordinarie / extra",
        "Regular / extra hours",
        "Heures normales / supplémentaires",
        "Ore normale / suplimentare",
        "Обычные / сверхурочные часы",
        "الساعات العادية / الإضافية",
    ),
    "quantity": (
        "Quantità / unità",
        "Quantity / unit",
        "Quantité / unité",
        "Cantitate / unitate",
        "Количество / единица",
        "الكمية / الوحدة",
    ),
    "criterion": (
        "Punto / criterio di controllo",
        "Item / check criterion",
        "Point / critère de contrôle",
        "Punct / criteriu de control",
        "Пункт / критерий проверки",
        "البند / معيار الفحص",
    ),
    "finding": (
        "Riscontro documentato",
        "Documented finding",
        "Constat documenté",
        "Constatare documentată",
        "Документированное наблюдение",
        "النتيجة الموثقة",
    ),
    "outcome": (
        "Esito / verifica da completare",
        "Outcome / check to complete",
        "Résultat / contrôle à compléter",
        "Rezultat / verificare de completat",
        "Результат / проверка к заполнению",
        "النتيجة / الفحص المطلوب استكماله",
    ),
    "action": (
        "Azione / disposizione",
        "Action / instruction",
        "Action / instruction",
        "Acțiune / dispoziție",
        "Действие / указание",
        "الإجراء / التوجيه",
    ),
    "owner_due": (
        "Referente / termine",
        "Owner / due date",
        "Responsable / échéance",
        "Responsabil / termen",
        "Ответственный / срок",
        "المسؤول / الموعد",
    ),
    "closure": (
        "Riscontro per la chiusura",
        "Closure evidence",
        "Constat de clôture",
        "Dovadă pentru închidere",
        "Подтверждение закрытия",
        "دليل الإغلاق",
    ),
    "role": (
        "Ruolo professionale",
        "Professional role",
        "Fonction professionnelle",
        "Rol profesional",
        "Профессиональная роль",
        "الدور المهني",
    ),
    "attendance": (
        "Presenza dichiarata",
        "Declared attendance",
        "Présence déclarée",
        "Prezență declarată",
        "Заявленное присутствие",
        "الحضور المصرح به",
    ),
    "topic": (
        "Punto / area",
        "Item / area",
        "Point / zone",
        "Punct / zonă",
        "Пункт / участок",
        "البند / المنطقة",
    ),
    "last_state": (
        "Ultimo stato registrato",
        "Last recorded status",
        "Dernier état enregistré",
        "Ultima stare înregistrată",
        "Последний зарегистрированный статус",
        "آخر حالة مسجلة",
    ),
    "programme": (
        "Riferimento di programma",
        "Programme reference",
        "Référence du programme",
        "Referință de program",
        "Ссылка на график",
        "مرجع البرنامج",
    ),
    "photo": (
        "Fotografia / fonte",
        "Photograph / source",
        "Photographie / source",
        "Fotografie / sursă",
        "Фотография / источник",
        "الصورة / المصدر",
    ),
    "context": (
        "Luogo / contesto",
        "Location / context",
        "Lieu / contexte",
        "Loc / context",
        "Место / контекст",
        "المكان / السياق",
    ),
    "capture_date": (
        "Data dello scatto",
        "Capture date",
        "Date de prise de vue",
        "Data fotografierii",
        "Дата съёмки",
        "تاريخ التصوير",
    ),
}

# key, columns, relative widths, editorial purpose. These describe registers,
# not facts or assignments; the latter always come from evidence or input fields.
ACTIONS = (
    "actions",
    ("action", "owner_due", "last_state", "closure"),
    (34, 22, 22, 22),
    "Una riga per azione o disposizione pertinente. Distinguere proposta, incarico ed esecuzione. Referente e termine mancanti sono campi person/date; il riscontro per chiudere è esplicito.",
)
PARTICIPANTS = (
    "participants",
    ("person", "company", "role", "attendance"),
    (27, 25, 25, 23),
    "Solo presenti dichiarati. Quando mancano, predisporre campi compilabili senza usare i membri come presenze. I ruoli professionali sono distinti dai permessi dell'app.",
)
TIMELINE = (
    "timeline",
    ("time", "work_front", "record"),
    (20, 28, 52),
    "Eventi e comunicazioni con date distinte. Se una riga riunisce più messaggi usare le rispettive ore o un intervallo, mai la sola ora del primo post.",
)
REGISTERS = {
    "daily_report": {
        "section_2": [
            TIMELINE,
            (
                "resources",
                ("company", "person", "hours", "quantity"),
                (25, 25, 25, 25),
                "Imprese e risorse effettivamente registrate, oppure campi persona/ore ordinarie/ore extra/quantità-unità da compilare. Nessuna presenza o produzione dedotta dalla conversazione.",
            ),
        ],
        "section_3": [ACTIONS],
    },
    "inspection": {
        "section_2": [PARTICIPANTS],
        "section_3": [
            (
                "checks",
                ("criterion", "finding", "outcome"),
                (30, 45, 25),
                "Una riga per punto/criterio controllato. Distinguere il precedente documentale dal riscontro della visita richiesta. Quando manca il riscontro o l'esito predisporre campi specifici compilabili, conservando i rilievi effettivi.",
            )
        ],
        "section_4": [ACTIONS],
    },
    "coordination": {"section_2": [PARTICIPANTS], "section_4": [ACTIONS]},
    "periodic_report": {
        "section_2": [
            (
                "progress",
                ("work_front", "programme", "record"),
                (25, 35, 40),
                "Avanzamenti e riferimenti di programma alla data. Quando assenti usare quantità/unità o avanzamento storico compilabili, senza inventare percentuali.",
            )
        ],
        "section_3": [
            (
                "issues",
                ("topic", "last_state", "closure"),
                (25, 45, 30),
                "Ultimo stato effettivamente registrato, con la sua data. L'assenza di aggiornamenti non prova che il punto fosse ancora aperto alla fine del periodo; distinguere esito non documentato e stato registrato.",
            )
        ],
        "section_4": [ACTIONS],
    },
    "photo_report": {
        "section_2": [
            (
                "photo_index",
                ("photo", "context", "capture_date"),
                (25, 45, 30),
                "Indice delle fotografie effettivamente inserite. Identificare fonte e contesto; la data di scatto assente è un campo date, distinto da post e caricamento.",
            )
        ],
        "section_3": [
            (
                "observations",
                ("topic", "finding", "last_state", "action"),
                (20, 35, 25, 20),
                "Rilievi per area, ultimo stato datato e azioni documentate o proposte esplicite. Nessuna misura o verifica dedotta dalle fotografie.",
            )
        ],
    },
    "issue_report": {"section_2": [TIMELINE], "section_4": [ACTIONS]},
}


def registers_for(template):
    language = template.get("language", "it")
    index = LANGUAGES.index(language) if language in LANGUAGES else 1
    return {
        section: [
            {
                "key": key,
                "columns": list(columns),
                "labels": [COLUMNS[c][index] for c in columns],
                "widths": list(widths),
                "purpose": purpose,
            }
            for key, columns, widths, purpose in tables
        ]
        for section, tables in REGISTERS.get(template.get("key"), {}).items()
    }


def decode_registers(value, template):
    for section in value.get("sections", []):
        if "required_tables" not in section:
            continue  # Existing portable fixtures and stored documents.
        definitions = registers_for(template).get(section["key"], [])
        supplied = section.pop("required_tables")
        if set(supplied) != {d["key"] for d in definitions}:
            raise ValueError("Registri obbligatori del documento incompleti.")
        tables = []
        for definition in definitions:
            rows = supplied[definition["key"]]["rows"]
            if not rows or any(set(row) != set(definition["columns"]) for row in rows):
                raise ValueError("Celle del registro documentale incomplete.")
            tables.append(
                {
                    "columns": definition["labels"],
                    "widths": definition["widths"],
                    "rows": [[row[key] for key in definition["columns"]] for row in rows],
                }
            )
        section["tables"] = [*tables, *section.get("tables", [])]
    return value


def deduplicate_initial_tables(composition, template):
    """Fold exact repeated generated registers, never manually saved inputs.

    The caller limits this to initial generation. Placeholder identifiers and
    column proportions do not add facts; labels, types, units and citations do.
    """
    import re
    from .content import ClaimCell

    def claim_key(claim):
        fields = {field.key: field for field in claim.fields}
        ordered = []

        def marker(match):
            field = fields[match[1]]
            ordered.append((field.label, field.kind, field.unit))
            return "{{field_" + str(len(ordered)) + "}}"

        text = re.sub(r"\{\{([a-z][a-z0-9_.-]{0,99})\}\}", marker, claim.text)
        return (text, tuple(sorted(claim.source_ids)), claim.nature, tuple(ordered))

    def table_key(table):
        return (
            tuple(table.columns),
            tuple(
                tuple(
                    tuple(
                        claim_key(c)
                        for c in (cell.paragraphs if isinstance(cell, ClaimCell) else [cell])
                    )
                    for cell in row
                )
                for row in table.rows
            ),
        )

    changes = []
    required = registers_for(template)
    for section in composition.sections:
        primary_count = len(required.get(section.key, []))
        kept = []
        seen = {}
        remap = {}
        removed = 0
        for index, table in enumerate(section.tables):
            key = table_key(table)
            if index >= primary_count and key in seen:
                remap[index] = seen[key]
                removed += 1
            else:
                remap[index] = len(kept)
                seen[key] = len(kept)
                kept.append(table)
        if removed:
            section.tables = kept
            for block in section.layout:
                if block.kind == "table" and block.index in remap:
                    block.index = remap[block.index]
            changes.append({"section_key": section.key, "tables": removed})
    return changes
