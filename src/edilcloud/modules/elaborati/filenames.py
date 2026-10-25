"""Human download names independent of private storage UUIDs."""

from django.utils.text import slugify


def pdf_filename(revision):
    document = revision.elaborato
    title = (revision.editor_doc.get("attrs") or {}).get("documentTitle") or document.title
    title_slug = slugify(title, allow_unicode=True)
    project_slug = slugify(document.project.name, allow_unicode=True)
    if project_slug and title_slug.endswith("-" + project_slug):
        title_slug = title_slug[:-(len(project_slug) + 1)]
    parts = [
        f"EL-{document.created_at.year}-{document.number:04d}",
        f"Rev-{revision.number}",
        title_slug[:75] or "Elaborato",
        project_slug[:65] or "Cantiere",
        f"{document.period_start:%Y-%m-%d}_{document.period_end:%Y-%m-%d}",
    ]
    return "_".join(parts) + ".pdf"
