"""The only final-PDF renderer. HTML is built from a strict JSON allowlist.

Chromium has no network access and never receives user scripts or user HTML.
Images are resolved from authorized storage references and re-encoded locally.
"""

import base64
import html
import io
from pathlib import Path

from django.conf import settings
from PIL import Image, ImageOps

from .evidence import resolve_evidence_file


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


def render_html(*, revision, profile, signature=None):
    document = revision.elaborato
    sources = {s["id"]: s for s in revision.evidence["sources"]}
    company = document.created_by.workspace if document.created_by else document.project.workspace
    logo = image_data(company.logo, max_pixels=(1000, 400)) if company.logo else ""
    used = set()
    photo_count = 0

    def render(node):
        nonlocal photo_count
        kind = node["type"]
        attrs = node.get("attrs") or {}
        content = "".join(render(c) for c in node.get("content", []))
        if kind == "doc":
            return content
        if kind == "text":
            value = esc(node["text"])
            for mark in node.get("marks", []):
                tag = {"bold": "strong", "italic": "em", "strike": "s", "code": "code"}[
                    mark["type"]
                ]
                value = f"<{tag}>{value}</{tag}>"
            return value
        if kind == "heading":
            level = attrs.get("level", 2)
            return f"<h{level}>{content}</h{level}>"
        if kind == "paragraph":
            refs = attrs.get("sourceIds", [])
            used.update(refs)
            citations = (
                f'<span class="citations"> [{", ".join(esc(s) for s in refs)}]</span>'
                if refs
                else ""
            )
            nature = attrs.get("nature", "reported")
            label = {
                "unverified": "Da verificare",
                "proposed": "Proposta",
                "reported": "Dichiarato",
                "decided": "Decisione",
                "observed": "Registrato",
            }[nature]
            return f'<p class="claim {nature}"><span class="nature">{label} · </span>{content}{citations}</p>'
        if kind == "hardBreak":
            return "<br>"
        if kind in {"bulletList", "orderedList", "listItem"}:
            tag = {"bulletList": "ul", "orderedList": "ol", "listItem": "li"}[kind]
            return f"<{tag}>{content}</{tag}>"
        if kind == "table":
            rows = node.get("content", [])
            if rows and all(c["type"] == "tableHeader" for c in rows[0].get("content", [])):
                return f"<table><thead>{render(rows[0])}</thead><tbody>{''.join(render(row) for row in rows[1:])}</tbody></table>"
            return f"<table><tbody>{content}</tbody></table>"
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
                or "Fotografia allegata"
            )
            return f'<figure><img src="{uri}" alt=""><figcaption>{esc(caption)} <span class="citations">[{esc(source["id"])}]</span></figcaption></figure>'
        raise ValueError("Elemento editor non supportato dal renderer.")

    content = render(revision.editor_doc)
    title = esc(document.title)
    code = f"EL-{document.created_at.year}-{document.number:04d} · Rev.{revision.number}"
    # An authenticated link, not a public sharing capability.
    url = f"{settings.APP_FRONTEND_URL.rstrip('/')}/dashboard?tab=elaborati&revision={revision.pk}"
    import qrcode

    output = io.BytesIO()
    qrcode.make(url, box_size=3, border=2).save(output, format="PNG")
    qr = base64.b64encode(output.getvalue()).decode()
    font_path = Path(__file__).parent / "assets" / "Inter-Regular.ttf"
    font_css = ""
    if font_path.exists():
        font_css = (
            "@font-face{font-family:Inter;src:url(data:font/ttf;base64,"
            + base64.b64encode(font_path.read_bytes()).decode()
            + ") format('truetype');font-weight:100 900;}"
        )
    brand = (
        f'<img class="logo" src="{logo}" alt="">'
        if logo
        else f'<div class="company">{esc(company.name)}</div>'
    )
    cover = f'<header class="cover">{brand}<div class="eyebrow">{esc(code)}</div><h1>{title}</h1><p>{esc(document.project.name)}</p><p>{document.period_start:%d/%m/%Y} — {document.period_end:%d/%m/%Y}</p><p>{esc(document.project.address)}</p><img class="qr" src="data:image/png;base64,{qr}" alt="Apri elaborato in EdilCloud"></header>'
    signature_html = ""
    if signature:
        signature_html = f'<section class="signature"><h2>Sottoscrizione</h2><p><strong>{esc(signature["name"])}</strong><br>{esc(signature["role"])} · {esc(signature["company"])}</p><img src="{signature["image_data"]}" alt="Firma"><p>Sottoscritto tramite EdilCloud<br>{esc(signature["confirmed_at"])}</p></section>'
    references = "".join(
        f"<tr><td>{esc(sid)}</td><td>{esc(sources[sid]['kind'])}</td><td>{esc(sources[sid].get('at') or '')}</td><td>{esc(sources[sid]['hash'][:16])}</td></tr>"
        for sid in sorted(used)
        if sid in sources
    )
    history = "".join(
        f"<tr><td>Rev.{r.number}</td><td>{esc(r.get_state_display())}</td><td>{esc(r.published_at.isoformat() if r.published_at else 'Bozza corrente')}</td></tr>"
        for r in document.revisions.order_by("number")
    )
    return f'''<!doctype html><html lang="{esc(document.language)}"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; font-src data:; style-src 'unsafe-inline'"><style>
    {font_css}
    @page {{ size:A4; margin:20mm 17mm 22mm; }}
    *{{box-sizing:border-box}} body{{font:10pt/1.6 Inter,'Noto Sans',Arial,sans-serif;color:#243d35;margin:0}}
    h1{{font-size:27pt;line-height:1.2;margin:12mm 0 7mm}} h2{{font-size:14pt;border-bottom:1px solid #dce7e0;padding-bottom:2mm;margin-top:9mm;break-after:avoid}} h3{{font-size:12pt;break-after:avoid}}
    p{{orphans:3;widows:3}} .cover{{min-height:240mm;break-after:page;padding-top:10mm}} .technical .cover{{min-height:0;break-after:auto;padding:0 0 7mm;border-bottom:2px solid #243d35}}
    .logo{{max-width:95mm;max-height:35mm;object-fit:contain;object-position:left}} .company{{font-size:21pt;font-weight:bold}} .eyebrow{{margin-top:22mm;color:#76867c;letter-spacing:1px}}
    .technical .eyebrow{{margin-top:5mm}} .technical .qr{{display:none}} .qr{{width:27mm;margin-top:12mm}}
    .citations{{color:#6f7c75;font-size:7pt}} .nature{{font-size:8pt;color:#63756a}} .unverified{{border-left:2px solid #d79525;padding-left:3mm}}
    figure{{margin:7mm 0;break-inside:avoid}} figure img{{width:100%;max-height:130mm;object-fit:contain;background:#f6f8f5}} .photographic figure img{{max-height:175mm}} figcaption{{font-size:9pt;margin-top:2mm}}
    table{{width:100%;border-collapse:collapse;font-size:8pt}} td,th{{text-align:left;border-bottom:1px solid #e3e9e4;padding:2mm;overflow-wrap:anywhere}} thead{{display:table-header-group}}
    .references{{break-before:page}} .signature{{break-inside:avoid;margin-top:12mm}} .signature img{{max-width:65mm;height:22mm;object-fit:contain;object-position:left}}
    .closing{{margin-top:10mm;font-size:9pt;color:#64776d}}
    </style></head><body class="{esc(document.style)}">{cover}<main>{content}</main><p class="closing">{esc(revision.template_snapshot["closing"])}</p>{signature_html}<section class="references"><h2>Registro delle fonti</h2><p>Fonti utilizzate: {len(used)} · Acquisizione: {esc(revision.evidence["captured_at"])}</p><table><thead><tr><th>Fonte</th><th>Tipo</th><th>Data registrata</th><th>Impronta fonte</th></tr></thead><tbody>{references}</tbody></table><h2>Registro revisioni</h2><table>{history}</table><p class="closing">Documento operativo. Il template non costituisce una certificazione di conformità normativa. La sottoscrizione in-app non è una firma elettronica qualificata.</p></section></body></html>'''


def render_pdf(*, revision, profile, signature=None):
    from playwright.sync_api import sync_playwright

    markup = render_html(revision=revision, profile=profile, signature=signature)
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
            return page.pdf(
                format="A4",
                print_background=True,
                prefer_css_page_size=True,
                display_header_footer=True,
                header_template="<div></div>",
                footer_template='<div style="width:100%;padding:0 17mm;font:8px Arial;color:#68766f;display:flex;justify-content:space-between"><span>Gestito con EdilCloud</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>',
            )
        finally:
            browser.close()
