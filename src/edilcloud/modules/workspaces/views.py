from django.http import HttpResponse
from django.utils.html import escape

from edilcloud.modules.workspaces.services import (
    approve_workspace_access_request,
    refuse_workspace_access_request,
)


def render_access_request_decision_page(*, title: str, detail: str, status_code: int = 200) -> HttpResponse:
    safe_title = escape(title)
    safe_detail = escape(detail)
    html = f"""
<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title}</title>
  <style>
    body {{
      margin: 0;
      font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f4f4f5;
      color: #18181b;
      display: flex;
      min-height: 100vh;
      align-items: center;
      justify-content: center;
      padding: 24px;
    }}
    .card {{
      width: min(560px, 100%);
      background: #fff;
      border: 1px solid #e4e4e7;
      border-radius: 18px;
      padding: 32px;
      box-shadow: 0 18px 40px rgba(24, 24, 27, 0.08);
    }}
    h1 {{ margin: 0 0 14px; font-size: 28px; }}
    p {{ margin: 0; font-size: 16px; line-height: 1.65; color: #52525b; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>{safe_title}</h1>
    <p>{safe_detail}</p>
  </div>
</body>
</html>
"""
    return HttpResponse(html, status=status_code)


def approve_access_request_view(_request, request_id: int, token: str) -> HttpResponse:
    try:
        result = approve_workspace_access_request(request_id=request_id, token=token)
    except ValueError as exc:
        return render_access_request_decision_page(
            title="Richiesta non disponibile",
            detail=str(exc),
            status_code=400,
        )

    return render_access_request_decision_page(
        title="Accesso approvato",
        detail=result["detail"],
    )


def refuse_access_request_view(_request, request_id: int, token: str) -> HttpResponse:
    try:
        result = refuse_workspace_access_request(request_id=request_id, token=token)
    except ValueError as exc:
        return render_access_request_decision_page(
            title="Richiesta non disponibile",
            detail=str(exc),
            status_code=400,
        )

    return render_access_request_decision_page(
        title="Richiesta rifiutata",
        detail=result["detail"],
    )
