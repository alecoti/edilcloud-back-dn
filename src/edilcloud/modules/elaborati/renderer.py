"""The only final-PDF renderer. HTML is built from a strict JSON allowlist.

Chromium has no network access and never receives user scripts or user HTML.
Images are resolved from authorized storage references and re-encoded locally.
"""

import base64
import html
import io
from datetime import datetime

from django.conf import settings
from PIL import Image, ImageOps
from django.utils import timezone

from .evidence import resolve_evidence_file
from .content import validate_editor
from .pdf_labels import labels


def esc(value):
    return html.escape(str(value), quote=True)


def image_data(field, *, max_pixels=(1600, 1200)):
    if not field:
        return ""
    # Cap compressed bytes as well as decoded pixels to avoid hostile images.
    with field.open("rb") as stream:
        raw = stream.read(15 * 1024 * 1024 + 1)
    if len(raw) > 15 * 1024 * 1024:
        raise ValueError("Immagine troppo grande per la pubblicazione.")
    with Image.open(io.BytesIO(raw)) as original:
        if original.width * original.height > 45_000_000:
            raise ValueError("Risoluzione immagine non supportata.")
        original = ImageOps.exif_transpose(original)
        original.thumbnail(max_pixels, Image.Resampling.LANCZOS)
        # Preserve transparency for branding and signatures.
        transparent = "A" in original.getbands()
        image = original.convert("RGBA" if transparent else "RGB")
        output = io.BytesIO()
        image.save(
            output,
            "PNG" if transparent else "JPEG",
            **({"optimize": True} if transparent else {"quality": 86, "optimize": True}),
        )
        mime = "image/png" if transparent else "image/jpeg"
        return f"data:{mime};base64,{base64.b64encode(output.getvalue()).decode()}"


def render_html(*, revision, profile, signature=None, publication_state=None):
    validate_editor(revision.editor_doc, revision.evidence, revision.template_snapshot)
    document = revision.elaborato
    words = labels(document.language)
    rendered_state = publication_state or revision.state
    sources = {s["id"]: s for s in revision.evidence["sources"]}
    company = document.created_by.workspace if document.created_by else document.project.workspace
    logo = image_data(company.logo, max_pixels=(1000, 400)) if company.logo else ""
    used = set()
    photo_count = 0
    numbers = {}

    def index(node):
        attrs = node.get("attrs") or {}
        ids = list(attrs.get("sourceIds", []))
        if node["type"] == "evidencePhoto":
            ids.insert(0, attrs["sourceId"])
        for sid in ids:
            if sid in sources and sid not in numbers:
                numbers[sid] = len(numbers) + 1
        for child in node.get("content", []):
            index(child)

    index(revision.editor_doc)

    def citations(ids):
        return " ".join(
            f'<a class="citations" href="#source-{numbers[sid]}">[{numbers[sid]}]</a>'
            for sid in dict.fromkeys(ids)
            if sid in numbers
        )

    def render(node, header=False):
        nonlocal photo_count
        kind = node["type"]
        attrs = node.get("attrs") or {}
        if kind == "doc":
            blocks = []
            previous = None
            for child in node.get("content", []):
                if (
                    previous
                    and previous["type"] == child["type"] == "heading"
                    and (previous.get("attrs") or {}).get("level") == 2
                    and (child.get("attrs") or {}).get("level") == 3
                    and previous.get("content") == child.get("content")
                ):
                    # Older drafts sometimes repeat the section title as an
                    # immediate subheading. Preserve the editor JSON and facts.
                    continue
                blocks.append(render(child))
                previous = child
            return "".join(blocks)
        content = "".join(
            render(c, header=header or kind == "tableHeader") for c in node.get("content", [])
        )
        if kind == "documentField":
            if attrs["kind"] == "signature":
                if signature and attrs["fieldId"] == "document_author_signature":
                    return f'<span class="field-filled">{esc(words["signed_via"])} · {esc(signature["name"])}</span>'
                return f'<span class="signature-slot">{esc(attrs["label"])}</span>'
            if attrs.get("value"):
                return f'<span class="field-filled">{esc(attrs["value"])}{(" " + esc(attrs["unit"])) if attrs.get("unit") else ""}</span>'
            return f'<span class="field-pending">[{esc(attrs["label"])}{(" · " + esc(attrs["unit"])) if attrs.get("unit") else ""}]</span>'
        if kind == "text":
            value = esc(node["text"])
            for mark in node.get("marks", []):
                if mark["type"] == "link":
                    value = f'<a href="{esc(mark["attrs"]["href"])}" rel="noopener noreferrer">{value}</a>'
                    continue
                tag = {
                    "bold": "strong",
                    "italic": "em",
                    "underline": "u",
                    "strike": "s",
                    "code": "code",
                    "highlight": "mark",
                }[mark["type"]]
                value = f"<{tag}>{value}</{tag}>"
            return value
        if kind == "heading":
            level = attrs.get("level", 2)
            return f'<h{level} style="text-align:{attrs.get("textAlign") or "left"}">{content}</h{level}>'
        if kind == "paragraph":
            refs = attrs.get("sourceIds", [])
            from .fields import fields_in, field_source_id

            refs = list(
                dict.fromkeys(
                    [*refs, *[field_source_id(f) for f in fields_in(node) if f.get("value")]]
                )
            )
            used.update(refs)
            refs_html = citations(refs)
            nature = attrs.get("nature", "reported")
            plain = "".join(c.get("text", "") for c in node.get("content", [])).lstrip()
            already_labelled = plain.casefold().startswith(
                (words.get(nature, nature) + ":").casefold()
            )
            badge = (
                f'<span class="nature">{esc(words[nature])} · </span>'
                if nature in {"unverified", "proposed", "decided"}
                and not header
                and not already_labelled
                and not (nature == "unverified" and list(fields_in(node)))
                else ""
            )
            classification = "" if header else nature
            alignment = attrs.get("textAlign") or ("right" if document.language == "ar" else "left")
            return f'<p class="claim {classification}" style="text-align:{alignment}">{badge}{content} {refs_html}</p>'
        if kind == "hardBreak":
            return "<br>"
        if kind in {"bulletList", "orderedList", "listItem"}:
            tag = {"bulletList": "ul", "orderedList": "ol", "listItem": "li"}[kind]
            if kind == "orderedList":
                style = f' type="{esc(attrs["type"])}"' if attrs.get("type") else ""
                return f'<ol start="{attrs.get("start", 1)}"{style}>{content}</ol>'
            return f"<{tag}>{content}</{tag}>"
        if kind == "table":
            rows = node.get("content", [])
            widths = (
                [
                    ((c.get("attrs") or {}).get("colwidth") or [0])[0]
                    for c in rows[0].get("content", [])
                ]
                if rows
                else []
            )
            cols = (
                f"<colgroup>{''.join(f'<col style="width:{100 * width / sum(widths):.2f}%">' for width in widths)}</colgroup>"
                if widths and all(widths)
                else ""
            )
            if rows and all(c["type"] == "tableHeader" for c in rows[0].get("content", [])):
                return f"<table>{cols}<thead>{render(rows[0])}</thead><tbody>{''.join(render(row) for row in rows[1:])}</tbody></table>"
            return f"<table>{cols}<tbody>{content}</tbody></table>"
        if kind == "tableRow":
            return f"<tr>{content}</tr>"
        if kind in {"tableCell", "tableHeader"}:
            tag = "th" if kind == "tableHeader" else "td"
            return f'<{tag} colspan="{attrs.get("colspan", 1)}" rowspan="{attrs.get("rowspan", 1)}">{content}</{tag}>'
        if kind == "evidencePhoto":
            photo_count += 1
            if photo_count > 24:
                raise ValueError("Un elaborato può contenere al massimo 24 fotografie.")
            source = sources[attrs["sourceId"]]
            field = resolve_evidence_file(
                profile=profile, project_id=document.project_id, source=source
            )
            uri = image_data(field)
            used.update([source["id"], *attrs.get("sourceIds", [])])
            caption = (
                attrs.get("caption")
                or source["data"].get("title")
                or source["data"].get("filename")
                or words["photo"]
            )
            title = attrs.get("title") or f"{words['photo']} {photo_count:02d}"
            event_date = source["data"].get("event_date_from_parent") or ""
            uploaded = (
                source.get("at") if source["data"].get("uploaded_at_is_not_event_date") else ""
            )
            dates = f"{words['content_date']}: {date_label(event_date)}" if event_date else ""
            if source["kind"] == "photo":
                uploaded = source.get("at") or ""
            if uploaded:
                dates += f"{' · ' if dates else ''}{words['uploaded']}: {date_label(uploaded)}"
            return f'<figure class="evidence-photo {esc(attrs.get("layout", "full"))}"><img src="{uri}" alt=""><figcaption><b>F{photo_count:02d} · {esc(title)}</b><br>{esc(caption)} {citations([source["id"], *attrs.get("sourceIds", [])])}<span class="photo-date">{esc(dates)}</span></figcaption></figure>'
        raise ValueError("Elemento editor non supportato dal renderer.")

    def date_label(value):
        try:
            at = datetime.fromisoformat(value)
            if timezone.is_aware(at):
                at = timezone.localtime(at)
            return at.strftime("%d/%m/%Y %H:%M") + (
                " " + (at.tzname() or "") if timezone.is_aware(at) else ""
            )
        except (ValueError, TypeError):
            return value or ""

    # Include attributed field values in the numbered source register.
    from .fields import fields_in, field_source_id

    for field in fields_in(revision.editor_doc):
        sid = field_source_id(field)
        if field.get("value") and sid in sources and sid not in numbers:
            numbers[sid] = len(numbers) + 1
    content = render(revision.editor_doc)
    code = f"EL-{document.created_at.year}-{document.number:04d} · Rev.{revision.number}"
    created = timezone.localtime(document.created_at)
    author = document.created_by.member_name if document.created_by else ""
    signature_html = ""
    if signature:
        signature_html = f'<section class="signature"><h2>{esc(words["signature"])}</h2><p><strong>{esc(signature["name"])}</strong><br>{esc(signature["role"])} · {esc(signature["company"])}</p><img src="{signature["image_data"]}" alt="{esc(words["signature"])}"><p>{esc(words["signed_via"])}<br>{esc(signature["confirmed_at"])}</p></section>'

    def source_row(sid):
        source = sources[sid]
        data = source["data"]
        label = (
            (words["request"] if source["kind"] == "request" else "")
            or data.get("title")
            or (data.get("text", "")[:400] if source["kind"] == "declaration" else "")
            or data.get("filename")
            or data.get("author")
            or data.get("name")
            or sid
        )
        description = f"<b>{esc(label)}</b>"
        if source["kind"] != "request":
            description += f"<br><small>{esc(sid)}</small>"
        at = date_label(source.get("at"))
        if data.get("uploaded_at_is_not_event_date"):
            at = f"{esc(words['content_date'])}: {esc(date_label(data.get('event_date_from_parent')))}<br>{esc(words['uploaded'])}: {esc(at)}"
        else:
            at = esc(at)
        pages = sorted({e["page"] for e in data.get("excerpts", []) if e.get("page")})
        if pages:
            description += "<br><small>p. " + esc(", ".join(map(str, pages))) + "</small>"
        return f'<tr id="source-{numbers[sid]}"><td>[{numbers[sid]}]</td><td>{description}</td><td>{at}</td><td>{esc(source["hash"][:16])}</td></tr>'

    references = "".join(
        source_row(sid) for sid in sorted(used, key=lambda sid: numbers[sid]) if sid in sources
    )
    history = "".join(
        f"<tr><td>Rev.{r.number}</td><td>{esc(words.get(rendered_state if r.pk == revision.pk else r.state, r.state))}</td><td>{esc(date_label(r.published_at.isoformat()) if r.published_at else (created.strftime('%d/%m/%Y %H:%M') if r.pk == revision.pk else words['draft']))}</td></tr>"
        for r in document.revisions.order_by("number")
    )
    from .reference_layout import layout_html

    reference_body = f"""{content}<p class="closing">{esc(revision.template_snapshot["closing"])}</p>{signature_html}
      <h2 class="references-title">{esc(words["sources"])}</h2><p class="closing">{esc(words["used"])}: {len(used)} · {esc(words["captured"])}: {esc(date_label(revision.evidence["captured_at"]))}</p>
      <table class="source-table"><thead><tr><th>#</th><th>{esc(words["source"])}</th><th>{esc(words["recorded"])}</th><th>{esc(words["hash"])}</th></tr></thead><tbody>{references}</tbody></table>
      <h2>{esc(words["history"])}</h2><table><tbody>{history}</tbody></table><p class="closing">{esc(words["note"])}</p>"""
    return layout_html(
        language=document.language,
        company=company.name,
        logo=logo,
        title=(revision.editor_doc.get("attrs") or {}).get("documentTitle") or document.title,
        subtitle=(revision.editor_doc.get("attrs") or {}).get("subtitle", ""),
        project=document.project.name,
        address=document.project.address,
        code=code,
        state=words.get(rendered_state, rendered_state),
        period=f"{document.period_start:%d/%m/%Y} — {document.period_end:%d/%m/%Y}",
        prepared=f"{created:%d/%m/%Y %H:%M} {created.tzname()}",
        author=author,
        words=words,
        body=reference_body,
        style=document.style,
    )


def render_pdf(*, revision, profile, signature=None, publication_state=None):
    from playwright.sync_api import sync_playwright

    markup = render_html(
        revision=revision, profile=profile, signature=signature, publication_state=publication_state
    )
    executable = getattr(settings, "ELABORATI_CHROMIUM_EXECUTABLE", "")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            **({"executable_path": executable} if executable else {}),
            args=["--disable-dev-shm-usage"],
        )
        try:
            context = browser.new_context(java_script_enabled=False, service_workers="block")
            context.route("**/*", lambda route: route.abort())
            page = context.new_page()
            page.set_content(markup, wait_until="load", timeout=30_000)
            from .reference_layout import paginate

            paginate(page)
            return page.pdf(
                format="A4",
                print_background=True,
                prefer_css_page_size=True,
                display_header_footer=False,
                header_template="<div></div>",
                footer_template=f'<div style="width:100%;padding:0 17mm;font:8px Arial;color:#68766f;display:flex;justify-content:space-between"><span>{esc(labels(revision.elaborato.language)["managed"])}</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>',
            )
        finally:
            browser.close()
