"""Human references, dated assignments and revision manifests without AI calls."""

from collections import Counter
from copy import deepcopy

from .content import digest


def claim_source_ids(editor):
    from .fields import fields_in, field_source_id

    used = set()

    def scan(node):
        attrs = node.get("attrs") or {}
        used.update(attrs.get("sourceIds", []))
        if node.get("type") == "evidencePhoto" and attrs.get("sourceId"):
            used.add(attrs["sourceId"])
        if (
            node.get("type") == "documentField"
            and attrs.get("value")
            and attrs.get("personSourceId")
        ):
            used.add(attrs["personSourceId"])
        for child in node.get("content", []):
            scan(child)

    scan(editor)
    used.update(field_source_id(field) for field in fields_in(editor) if field.get("value"))
    return used


def people_sources(bundle):
    """Only dated professional assignments; never label the site team 'present'."""
    rows = []
    for source in bundle.get("sources", []):
        data = source["data"]
        if source["kind"] != "member" or not data.get("assignment_is_not_attendance"):
            continue
        rows.append(source)
    return sorted(
        rows, key=lambda value: (value["data"].get("name", ""), value["data"].get("valid_from", ""))
    )


def people_register(bundle, used):
    """Frozen identities, with current catalogues kept distinct from dated roles."""
    from ..projects.participations import role_labels

    rows = {}

    def add(data, source_id, scope, *, actor=None):
        actor = actor or {}
        name = data.get("name") or actor.get("person_name")
        if not name:
            return
        row = {
            "name": name,
            "company": data.get("company") or actor.get("company_name", ""),
            "qualification": data.get("qualification") or actor.get("qualification", ""),
            "function": data.get("function", ""),
            "professional_role_labels": data.get("professional_role_labels") or actor.get("role_labels") or role_labels(data.get("professional_roles") or []),
            "valid_from": data.get("valid_from", ""),
            "valid_to": data.get("valid_to", ""),
            "appointment_reference": data.get("appointment_reference", ""),
            "status": data.get("status") or actor.get("identity_state", ""),
            "scope": scope,
        }
        # Never combine a later company/role with an earlier attribution.
        key = digest(row)
        if key not in rows:
            rows[key] = {**row, "source_ids": []}
        if source_id not in rows[key]["source_ids"]:
            rows[key]["source_ids"].append(source_id)

    for source in bundle.get("sources", []):
        if source["kind"] == "member":
            data = source["data"]
            if data.get("assignment_is_not_attendance"):
                add(data, source["id"], "assignment")
            elif data.get("roles_are_current_catalogue"):
                add(data, source["id"], "catalogue")
        if source["id"] in used and source.get("actor", {}).get("person_name"):
            add({}, source["id"], "source", actor=source["actor"])

    # A source actor is already represented when its exact professional identity
    # is present in a dated assignment. Keep all other snapshots separately.
    def identity(row):
        return (row["name"], row["company"], row["qualification"], tuple(sorted(row["professional_role_labels"])))
    assignments = {identity(row) for row in rows.values() if row["scope"] == "assignment"}
    return sorted(
        (row for row in rows.values() if row["scope"] == "assignment" or identity(row) not in assignments),
        key=lambda row: (row["name"].casefold(), row["scope"], row["valid_from"]),
    )


def coverage(bundle, used):
    sources = bundle.get("sources", [])
    states = Counter(source.get("reading_state", "") for source in sources)
    census = bundle.get("census", {})
    total = census.get("total", len(sources))
    unreadable = states["unreadable"] + states["failed"]
    # V1 persists extraction markers rather than per-source reader states.
    if not any(states.get(key) for key in ("read", "excluded", "unreadable", "failed")):
        examined = sum(
            not source.get("file_ref")
            or bool(source["data"].get("file_content_extracted"))
            or bool(source["data"].get("visual_analysis"))
            or bool(source["data"].get("transcript"))
            for source in sources
        )
    else:
        examined = sum(states[key] for key in ("read", "excluded", "unreadable", "failed"))
    selected = {source["id"] for source in sources}
    return {
        "censused": total,
        "census_complete": census.get("complete", not bundle.get("truncated", False)),
        "examined": examined,
        "used": len(used & selected),
        "excluded": states["excluded"] + census.get("excluded_from_selection", 0),
        "unreadable": unreadable,
        "not_examined": max(0, total - examined - census.get("excluded_from_selection", 0)),
        "selection_partial": bool(bundle.get("truncated")),
    }


def manifest(revision, *, pdf_hash=""):
    sources = revision.evidence.get("sources", [])
    used = claim_source_ids(revision.editor_doc)
    used.update(sid for row in people_register(revision.evidence, used) for sid in row["source_ids"])
    entries = [
        {
            key: deepcopy(source.get(key))
            for key in (
                "id",
                "source_uuid",
                "source_version",
                "reference",
                "version_hash",
                "hash",
                "file_sha256",
                "original_sha256",
                "recorded_at",
                "actor",
                "original_state",
                "relations",
                "capture_metadata",
            )
        }
        for source in sources
        if source["id"] in used
    ]
    content = {
        "schema_version": 1,
        "revision_uuid": str(revision.pk),
        "revision": revision.number,
        "pdf_hash": pdf_hash,
        "editor_hash": digest(revision.editor_doc),
        "author": deepcopy(revision.elaborato.author_snapshot),
        "bundle_hash": revision.evidence.get("bundle_hash"),
        "sources": entries,
        "coverage": coverage(revision.evidence, used),
    }
    return {**content, "manifest_hash": digest(content)}


def labels(locale):
    keys = (
        "people",
        "people_note",
        "person",
        "company",
        "qualification",
        "roles",
        "validity",
        "reconstructed",
        "unknown_actor",
        "open_evidence",
        "coverage",
        "censused",
        "examined",
        "used",
        "excluded",
        "unreadable",
        "not_examined",
        "partial",
        "image_date_unknown",
        "exif_date",
    )
    values = {
        "it": (
            "Soggetti e incarichi di riferimento",
            "Anagrafica e incarichi validi nel periodo: non attestano la presenza in cantiere o alla riunione.",
            "Persona",
            "Azienda",
            "Qualifica / funzione",
            "Incarichi",
            "Validità",
            "Attribuzione ricostruita",
            "Autore non documentato",
            "Apri evidenza in EdilCloud",
            "Copertura delle fonti",
            "Censite",
            "Esaminate",
            "Utilizzate",
            "Escluse",
            "Illeggibili",
            "Non ancora esaminate",
            "Selezione parziale: parte delle fonti non è stata ammessa alla redazione.",
            "Data dello scatto non documentata",
            "Data immagine da EXIF, non verificata",
        ),
        "en": (
            "People and project appointments",
            "People and appointments valid during the period; this does not establish attendance on site or at a meeting.",
            "Person",
            "Company",
            "Qualification / function",
            "Appointments",
            "Validity",
            "Reconstructed attribution",
            "Author not documented",
            "Open evidence in EdilCloud",
            "Source coverage",
            "Inventoried",
            "Examined",
            "Used",
            "Excluded",
            "Unreadable",
            "Not yet examined",
            "Partial selection: some sources were not admitted to drafting.",
            "Photograph date not documented",
            "Image date from EXIF, unverified",
        ),
        "fr": (
            "Personnes et fonctions de référence",
            "Personnes et fonctions valides sur la période ; cela n'atteste pas leur présence sur le chantier ou à la réunion.",
            "Personne",
            "Entreprise",
            "Qualification / fonction",
            "Fonctions",
            "Validité",
            "Attribution reconstituée",
            "Auteur non documenté",
            "Ouvrir la preuve dans EdilCloud",
            "Couverture des sources",
            "Recensées",
            "Examinées",
            "Utilisées",
            "Exclues",
            "Illisibles",
            "Non encore examinées",
            "Sélection partielle : certaines sources n'ont pas été retenues pour la rédaction.",
            "Date de prise de vue non documentée",
            "Date EXIF de l'image, non vérifiée",
        ),
        "ro": (
            "Persoane și funcții de referință",
            "Persoane și funcții valabile în perioadă; acestea nu atestă prezența în șantier sau la ședință.",
            "Persoană",
            "Companie",
            "Calificare / funcție",
            "Funcții",
            "Valabilitate",
            "Atribuire reconstituită",
            "Autor nedocumentat",
            "Deschide dovada în EdilCloud",
            "Acoperirea surselor",
            "Inventariate",
            "Examinate",
            "Utilizate",
            "Excluse",
            "Ilizibile",
            "Neexaminate încă",
            "Selecție parțială: unele surse nu au fost admise la redactare.",
            "Data fotografiei nedocumentată",
            "Data imaginii din EXIF, neverificată",
        ),
        "ru": (
            "Участники и назначения по проекту",
            "Лица и назначения за указанный период не подтверждают присутствие на объекте или совещании.",
            "Лицо",
            "Компания",
            "Квалификация / функция",
            "Назначения",
            "Период действия",
            "Восстановленная атрибуция",
            "Автор не документирован",
            "Открыть подтверждение в EdilCloud",
            "Охват источников",
            "Учтено",
            "Проверено",
            "Использовано",
            "Исключено",
            "Нечитаемые",
            "Ещё не проверено",
            "Частичная выборка: часть источников не допущена к составлению.",
            "Дата съёмки не документирована",
            "Дата изображения из EXIF, не проверена",
        ),
        "ar": (
            "الأشخاص والتكليفات المرجعية",
            "الأشخاص والتكليفات السارية خلال الفترة لا تثبت الحضور في الموقع أو الاجتماع.",
            "الشخص",
            "الشركة",
            "المؤهل / الوظيفة",
            "التكليفات",
            "مدة السريان",
            "نسبة مستعادة",
            "المؤلف غير موثق",
            "فتح الدليل في EdilCloud",
            "تغطية المصادر",
            "المحصورة",
            "المفحوصة",
            "المستخدمة",
            "المستبعدة",
            "غير المقروءة",
            "لم تُفحص بعد",
            "اختيار جزئي: لم تُدرج بعض المصادر في الصياغة.",
            "تاريخ التصوير غير موثق",
            "تاريخ الصورة من EXIF غير متحقق منه",
        ),
    }
    result = dict(zip(keys, values.get(locale, values["en"]), strict=True))
    attribution = {
        "it": ("Registrato da", "Autore immagine dichiarato", "Data contenuto dichiarata"),
        "en": ("Registered by", "Declared photographer", "Declared content date"),
        "fr": ("Enregistré par", "Auteur de l'image déclaré", "Date du contenu déclarée"),
        "ro": ("Înregistrat de", "Autorul imaginii declarat", "Data conținutului declarată"),
        "ru": ("Зарегистрировал", "Заявленный автор изображения", "Заявленная дата содержания"),
        "ar": ("سجله", "مؤلف الصورة المصرح به", "تاريخ المحتوى المصرح به"),
    }
    result.update(
        zip(
            ("registered_by", "photographer", "declared_date"),
            attribution.get(locale, attribution["en"]),
            strict=True,
        )
    )
    additions = {
        "it": ("Identità e incarichi dalle fonti conservate: non attestano la presenza in cantiere o alla riunione. I dati di anagrafica alla raccolta non provano incarichi nel periodo analizzato.", "Anagrafica alla raccolta; validità nel periodo non documentata", "Attribuzione nelle fonti citate", "Non documentato"),
        "en": ("Identities and appointments from retained sources; not evidence of attendance. Catalogue data at collection does not prove appointments during the reporting period.", "Catalogue at collection; validity during the period not documented", "Attribution in cited sources", "Not documented"),
        "fr": ("Identités et fonctions des sources conservées ; sans attestation de présence. Le catalogue à la collecte ne prouve pas les fonctions pendant la période.", "Catalogue à la collecte ; validité sur la période non documentée", "Attribution dans les sources citées", "Non documenté"),
        "ro": ("Identități și funcții din sursele păstrate; nu atestă prezența. Catalogul la colectare nu dovedește funcțiile din perioada analizată.", "Catalog la colectare; valabilitate în perioadă nedocumentată", "Atribuire în sursele citate", "Nedocumentat"),
        "ru": ("Лица и назначения из сохранённых источников не подтверждают присутствие. Справочник на дату сбора не доказывает назначения в отчётном периоде.", "Справочник на дату сбора; действие в периоде не подтверждено", "Атрибуция в цитируемых источниках", "Не подтверждено"),
        "ar": ("الهويات والأدوار من المصادر المحفوظة لا تثبت الحضور. بيانات الدليل عند الجمع لا تثبت الأدوار خلال فترة التقرير.", "الدليل عند الجمع؛ الصلاحية خلال الفترة غير موثقة", "النسبة في المصادر المستشهد بها", "غير موثق"),
    }
    result.update(zip(("people_note", "catalogue_scope", "source_scope", "not_documented"), additions.get(locale, additions["en"]), strict=True))
    return result
