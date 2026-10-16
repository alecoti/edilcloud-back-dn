"""Production layout derived from the six approved reference documents.

Only escaped document content is supplied; the paginator is trusted local code,
not generated HTML or a script stored in an editor document.
"""

from pathlib import Path
from html import escape

ASSETS = Path(__file__).parent / "assets"


def layout_html(
    *,
    language,
    company,
    logo,
    title,
    subtitle,
    project,
    address,
    code,
    state,
    period,
    prepared,
    author,
    words,
    body,
    style="corporate",
):
    def esc(value):
        return escape(str(value), quote=True)

    branding = (
        f'<img src="{logo}" alt="">' if logo else ""
    ) + f'<div class="firm">{esc(company)}</div>'
    intro = f"""<div class="eyebrow">{esc(code)} · {esc(state)}</div>
      <h1 class="title">{esc(title)}</h1>
      {f'<p class="subtitle">{esc(subtitle)}</p>' if subtitle else ""}
      <p class="project">{esc(project)}</p><p class="address">{esc(address)}</p>
      <div class="meta"><div><label>{esc(words["period"])}</label><strong>{esc(period)}</strong></div>
      <div><label>{esc(words["prepared"])}</label><strong>{esc(prepared)}</strong></div>
      <div><label>{esc(words["author"])}</label><strong>{esc(author)}</strong></div></div>"""
    css = (ASSETS / "document-reference.css").read_text(encoding="utf-8")
    return f'''<!doctype html><html lang="{esc(language)}" dir="{"rtl" if language == "ar" else "ltr"}"><head>
      <meta charset="utf-8"><title>{esc(title)}</title>
      <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; font-src data:; style-src 'unsafe-inline'">
      <style>{css}</style></head><body class="{esc(style)}"><section class="sheet">
      <header class="letterhead"><div class="identity">{branding}</div><div class="brand">EDILCLOUD<small><br>{esc(words["managed"])}</small></div></header>
      <main class="content"><div class="intro">{intro}</div><div class="body">{body}</div></main>
      <footer class="footer"><span>{esc(code)} · {esc(state)}</span><span></span></footer>
      </section></body></html>'''


def paginate(page):
    return page.evaluate((ASSETS / "document-paginate.js").read_text(encoding="utf-8"))
