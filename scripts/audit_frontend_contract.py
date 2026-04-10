from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


ENDPOINT_PATTERN = re.compile(r"/api/frontend[^\"'`\r\n]+")


@dataclass(frozen=True)
class CategoryConfig:
    title: str
    status: str
    summary: str


CATEGORY_CONFIG: dict[str, CategoryConfig] = {
    "identity": CategoryConfig(
        title="Identity e Onboarding",
        status="mostly_covered",
        summary="La v3 copre login, access code, Google, sessione e onboarding. Restano soprattutto hardening e sicurezza finale.",
    ),
    "workspaces": CategoryConfig(
        title="Workspaces e Profili",
        status="partial",
        summary="La v3 copre workspace, team, inviti, aziende e profilo corrente. Restano audit permessi e qualche dettaglio di parita finale.",
    ),
    "projects": CategoryConfig(
        title="Projects Core",
        status="mostly_covered",
        summary="La v3 copre progetti, overview, team, task, documents, photos, gantt e invite code. Restano smoke browser e audit permessi.",
    ),
    "collaboration": CategoryConfig(
        title="Feed, Post, Commenti e Attivita",
        status="mostly_covered",
        summary="Feed, post, commenti, attivita e unread state sono in v3. Restano tuning UX finale e smoke browser completo.",
    ),
    "files": CategoryConfig(
        title="Files, Documenti e Cartelle",
        status="mostly_covered",
        summary="Documenti, cartelle e foto sono su v3. Restano verifiche end-to-end su media/permessi e rifiniture.",
    ),
    "assistant": CategoryConfig(
        title="Assistant e AI Drafting",
        status="partial",
        summary="Assistant, streaming e drafting sono su v3. Restano memoria hosted live, smoke visuale e affinamento finale del retrieval.",
    ),
    "notifications": CategoryConfig(
        title="Notifications e Realtime",
        status="mostly_covered",
        summary="Notification center, realtime e deep-link core sono su v3. Restano smoke browser live e preferenze/canali extra.",
    ),
    "search": CategoryConfig(
        title="Search",
        status="mostly_covered",
        summary="La search globale usa la v3. Restano tuning ranking/snippet e smoke browser del modal.",
    ),
    "uncategorized": CategoryConfig(
        title="Da Categorizzare",
        status="review",
        summary="Endpoint trovati ma da assegnare meglio a un bounded context.",
    ),
}


def normalize_path(path: Path, base: Path) -> str:
    return path.relative_to(base).as_posix()


def classify_endpoint(endpoint: str) -> str:
    if endpoint.startswith("/api/frontend/user/"):
        return "identity"
    if endpoint.startswith("/api/frontend/profile/"):
        return "workspaces"
    if endpoint.startswith("/api/frontend/notify/"):
        return "notifications"
    if endpoint.startswith("/api/frontend/project/search/"):
        return "search"
    if "/assistant/" in endpoint or "/ai-draft" in endpoint:
        return "assistant"
    if endpoint.startswith("/api/frontend/document/") or endpoint.startswith("/api/frontend/media/"):
        return "files"
    if endpoint.startswith("/api/frontend/project/feed/"):
        return "collaboration"
    if endpoint.startswith("/api/frontend/project/post/"):
        return "collaboration"
    if endpoint.startswith("/api/frontend/project/comment/"):
        return "collaboration"
    if endpoint.startswith("/api/frontend/project/activity/"):
        return "collaboration"
    if endpoint.startswith("/api/frontend/project/task/"):
        return "projects"
    if endpoint.startswith("/api/frontend/project/gantt/"):
        return "projects"
    if endpoint.startswith("/api/frontend/project/project/"):
        if "/assistant/" in endpoint or "/realtime/" in endpoint:
            return "assistant" if "/assistant/" in endpoint else "notifications"
        return "projects"
    return "uncategorized"


def scan_source(source_root: Path) -> tuple[dict[str, set[str]], dict[str, set[str]], set[str]]:
    files_by_category: dict[str, set[str]] = defaultdict(set)
    endpoints_by_category: dict[str, set[str]] = defaultdict(set)
    all_route_files: set[str] = set()

    for path in source_root.rglob("*.ts*"):
        text = path.read_text(encoding="utf-8")
        endpoints = {match.group(0) for match in ENDPOINT_PATTERN.finditer(text)}
        if not endpoints:
            continue

        normalized_file = normalize_path(path, source_root.parent)
        all_route_files.add(normalized_file)

        for endpoint in endpoints:
            category = classify_endpoint(endpoint)
            files_by_category[category].add(normalized_file)
            endpoints_by_category[category].add(endpoint)

    return files_by_category, endpoints_by_category, all_route_files


def render_category_section(
    category: str,
    files: set[str],
    endpoints: set[str],
) -> str:
    config = CATEGORY_CONFIG[category]
    lines = [
        f"## {config.title}",
        "",
        f"Stato v3: `{config.status}`",
        "",
        config.summary,
        "",
        "Frontend files che dipendono da questo perimetro:",
    ]

    if files:
        lines.extend(f"- `{file}`" for file in sorted(files))
    else:
        lines.append("- Nessun file rilevato.")

    lines.extend(
        [
            "",
            "Endpoint legacy rilevati:",
        ]
    )

    if endpoints:
        lines.extend(f"- `{endpoint}`" for endpoint in sorted(endpoints))
    else:
        lines.append("- Nessun endpoint rilevato.")

    lines.append("")
    return "\n".join(lines)


def build_report(next_src_root: Path, output_path: Path) -> None:
    files_by_category, endpoints_by_category, all_route_files = scan_source(next_src_root)
    total_endpoints = sum(len(items) for items in endpoints_by_category.values())
    categories = [
        category
        for category in CATEGORY_CONFIG
        if files_by_category.get(category) or endpoints_by_category.get(category)
    ]

    lines = [
        "# Frontend Compatibility Matrix",
        "",
        "Questo documento viene generato da `scripts/audit_frontend_contract.py` e serve come checklist vincolante per la migrazione verso la v3.",
        "",
        "## Obiettivo",
        "",
        "Ogni modulo del nuovo backend viene considerato pronto solo quando copre il perimetro necessario a far funzionare `edilcloud-next` senza dipendenze residue dal backend legacy per quel dominio.",
        "",
        "## Snapshot Attuale",
        "",
        f"- File frontend con dipendenze backend legacy rilevate: `{len(all_route_files)}`",
        f"- Endpoint legacy unici rilevati: `{total_endpoints}`",
        "- Backend locale di riferimento: `http://localhost:8001`",
        "- Lo scanner cerca solo dipendenze runtime residue verso `/api/frontend/...`",
        "",
        "## Regola di Migrazione",
        "",
        "Un bounded context si considera migrato solo quando:",
        "",
        "- tutti gli endpoint legacy del suo perimetro hanno un equivalente v3",
        "- `edilcloud-next` smette di fare stitching non necessario per quel dominio",
        "- esistono test backend e smoke path frontend per i flussi critici",
        "",
    ]

    if not categories:
        lines.extend(
            [
                "## Stato Residuo",
                "",
                "- Nessuna dipendenza runtime legacy `/api/frontend/...` rilevata in `edilcloud-next/src`.",
                "- Il frontend locale puo parlare con la v3 su `http://localhost:8001` per i domini core gia migrati.",
                "- Restano comunque smoke browser, audit permessi e hardening che questo scanner non puo dedurre.",
                "",
            ]
        )

    for category in categories:
        lines.append(render_category_section(category, files_by_category[category], endpoints_by_category[category]))

    output_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    workspace_root = repo_root.parent
    next_src_root = workspace_root / "edilcloud-next" / "src"
    output_path = repo_root / "docs" / "FRONTEND_COMPATIBILITY_MATRIX.md"

    if not next_src_root.exists():
        raise SystemExit(f"Frontend source root non trovato: {next_src_root}")

    build_report(next_src_root, output_path)
    print(f"Report scritto in: {output_path}")


if __name__ == "__main__":
    main()
