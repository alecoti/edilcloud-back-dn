from __future__ import annotations

import base64
import hashlib
import io
import json
import mimetypes
import os
import time
import wave
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from edilcloud.modules.projects.demo_master_assets import BACKEND_ROOT, DEMO_ASSET_SOURCE_ROOT, DEMO_ASSET_VERSION


GEMINI_API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_GEMINI_DRAWING_MODEL = "gemini-3.1-flash-image-preview"
DEFAULT_GEMINI_IMAGE_MODEL = "gemini-3.1-flash-image-preview"
DEFAULT_GEMINI_TTS_MODEL = "gemini-3.1-flash-tts-preview"
DEFAULT_TIMEOUT_SECONDS = 180
DEFAULT_RETRY_ATTEMPTS = 3

EDITORIAL_BLUEPRINT_PATH = (
    BACKEND_ROOT
    / "demo-assets"
    / "demo-master"
    / "blueprints"
    / DEMO_ASSET_VERSION
    / "editorial-project-blueprint.json"
)
GENERATED_MEDIA_MANIFEST_PATH = (
    BACKEND_ROOT
    / "demo-assets"
    / "demo-master"
    / "blueprints"
    / DEMO_ASSET_VERSION
    / "generated-media-manifest.json"
)
GENERATED_ATTACHMENT_ROOT = DEMO_ASSET_SOURCE_ROOT / "attachments"
GENERATED_DOCUMENT_ROOT = DEMO_ASSET_SOURCE_ROOT / "documents"
GENERATED_DRAWING_ROOT = DEMO_ASSET_SOURCE_ROOT / "drawings"

IMAGE_ASPECT_BY_ORIENTATION = {
    "landscape": "16:9",
    "portrait": "3:4",
    "square": "1:1",
}
IMAGE_EXTENSION_BY_MIME = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
AUDIO_EXTENSION_BY_MIME = {
    "audio/flac": ".flac",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/wave": ".wav",
    "audio/webm": ".webm",
    "audio/x-wav": ".wav",
}
LANGUAGE_LABELS = {
    "de": "German",
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "it": "Italian",
    "nl": "Dutch",
    "pl": "Polish",
    "pt": "Portuguese",
    "ro": "Romanian",
    "ru": "Russian",
    "tr": "Turkish",
    "uk": "Ukrainian",
}
SPEAKER_VOICE_OVERRIDES = {
    "andrea-fontana": "Charon",
    "antonio-esposito": "Gacrux",
    "davide-pini": "Iapetus",
    "davide-sala": "Sadaltager",
    "elisa-brambilla": "Schedar",
    "giorgio-bellini": "Orus",
    "giulia-roversi": "Vindemiatrix",
    "laura-ferretti": "Kore",
    "lorenzo-gallo": "Achird",
    "luca-gatti": "Umbriel",
    "marco-rinaldi": "Rasalgethi",
    "martina-cattaneo": "Leda",
    "omar-elidrissi": "Alnilam",
    "paolo-longhi": "Charon",
    "serena-costantini": "Pulcherrima",
    "sofia-mancini": "Sulafat",
    "stefano-riva": "Achird",
}
VOICE_BY_TONE_KEYWORD = {
    "amichevole": "Achird",
    "attento": "Vindemiatrix",
    "calmo": "Vindemiatrix",
    "chiaro": "Charon",
    "concreto": "Charon",
    "decisionale": "Kore",
    "fermo": "Kore",
    "friendly": "Achird",
    "gentle": "Vindemiatrix",
    "informativo": "Rasalgethi",
    "knowledgeable": "Sadaltager",
    "lineare": "Schedar",
    "lucido": "Iapetus",
    "manageriale": "Sadaltager",
    "mature": "Gacrux",
    "naturale": "Sulafat",
    "operativo": "Schedar",
    "pratico": "Umbriel",
    "rasicura": "Sulafat",
    "risolutivo": "Kore",
    "severo": "Orus",
    "upbeat": "Puck",
    "warm": "Sulafat",
}
VOICE_FALLBACK = "Schedar"

DRAWING_SPECS_BY_CODE = {
    "ar-101": {
        "filename_hint": "ar-101-pianta-piano-terra.png",
        "title": "AR-101 Pianta piano terra e corte interna",
        "subtitle": "Hall, locale comune, corte interna e autorimessa rampata.",
        "sheet_type": "architectural floor plan",
        "orientation": "landscape",
        "subject": "ground floor plan with entrance hall, common room, internal court and garage ramp",
        "drawing_prompt_it": (
            "Planimetria architettonica verosimile di piano terra residenziale in Italia, vista ortogonale "
            "dall'alto, con hall di ingresso, locale comune, corte interna e rampa autorimessa chiaramente "
            "distinguibili, muri e aperture puliti, linguaggio da tavola tecnica contemporanea."
        ),
        "sheet_goal": "Far leggere subito accessi, hall, corte interna e zone comuni.",
    },
    "ar-205": {
        "filename_hint": "ar-205-piante-tipo-alloggi.png",
        "title": "AR-205 Piante tipo alloggi 1A-2B-3C",
        "subtitle": "Alloggi campione, quote interne e aree massetti da verificare.",
        "sheet_type": "architectural apartment plan sheet",
        "orientation": "landscape",
        "subject": "typical apartment plans 1A, 2B and 3C with kitchens, bathrooms, corridors and floor level checkpoints",
        "drawing_prompt_it": (
            "Tavola tecnica con piante tipo di tre unita' abitative residenziali italiane, inclusi cucina, bagno, "
            "corridoio e zone di soglia, con impaginazione credibile da studio tecnico e geometrie pulite pensate "
            "per controlli quote massetti e dettagli bagno campione."
        ),
        "sheet_goal": "Dare un supporto credibile ai pin su massetti, bagno 2B e cavedi.",
    },
    "st-204": {
        "filename_hint": "st-204-platea-setti.png",
        "title": "ST-204 Platea e setti interrati",
        "subtitle": "Platea, setti scala, vani tecnici e passaggi impiantistici.",
        "sheet_type": "structural foundation plan",
        "orientation": "landscape",
        "subject": "foundation slab and underground walls with technical shafts and plant pass-throughs",
        "drawing_prompt_it": (
            "Planimetria strutturale verosimile di interrato con platea, setti, vano scala-ascensore, vani tecnici "
            "e passaggi impiantistici, stile tavola strutturale pulita, segni tecnici credibili e geometria leggibile."
        ),
        "sheet_goal": "Supportare pin su passaggi box 03-04 e core ascensore.",
    },
    "fa-301": {
        "filename_hint": "fa-301-facciata-sud-ovest.png",
        "title": "FA-301 Facciata sud-ovest",
        "subtitle": "Mockup, campitura pannelli, davanzali e nodo copertura.",
        "sheet_type": "facade elevation",
        "orientation": "landscape",
        "subject": "south-west facade elevation with cladding modules, windows, roof edge and pluvial line",
        "drawing_prompt_it": (
            "Prospetto tecnico credibile di facciata sud-ovest residenziale contemporanea, alzato ortogonale non "
            "fotografico, con campiture pannelli, finestre, davanzali, linea copertura e pluviali leggibili."
        ),
        "sheet_goal": "Far stare bene i pin su nodo copertura, serramenti lotto B e pluviali lato corte.",
    },
    "fa-312": {
        "filename_hint": "fa-312-nodo-serramento-davanzale.png",
        "title": "FA-312 Nodo serramento e davanzale",
        "subtitle": "Dettaglio controtelaio, nastri e foro cucina 2B.",
        "sheet_type": "window detail section",
        "orientation": "portrait",
        "subject": "window detail section with counterframe, sill, sealing tapes and kitchen opening reference",
        "drawing_prompt_it": (
            "Dettaglio tecnico verosimile di nodo serramento e davanzale, sezione pulita con controtelaio, nastri, "
            "foro cucina 2B e quote essenziali, stile tavola di dettaglio architettonico leggibile e credibile."
        ),
        "sheet_goal": "Dare al pin del foro cucina 2B un contesto tecnico piu credibile e preciso.",
    },
    "im-220": {
        "filename_hint": "im-220-centrale-termica.png",
        "title": "IM-220 Centrale termica e dorsali",
        "subtitle": "Centrale termica, collettori, valvole e dorsali principali.",
        "sheet_type": "mechanical plant room plan",
        "orientation": "landscape",
        "subject": "technical plant room plan with collectors, balancing valves and main risers",
        "drawing_prompt_it": (
            "Tavola impiantistica verosimile di centrale termica con collettori, valvole di bilanciamento, dorsali "
            "principali e area pre-collaudo, vista tecnica pulita con ingombri e componenti leggibili."
        ),
        "sheet_goal": "Rendere credibili i pin su valvole mancanti e prerequisiti collaudi.",
    },
    "im-245": {
        "filename_hint": "im-245-vmc-corridoi-bagni.png",
        "title": "IM-245 VMC corridoi e bagni",
        "subtitle": "Canali VMC, corridoio nord e locali bagno.",
        "sheet_type": "mechanical distribution plan",
        "orientation": "landscape",
        "subject": "ventilation plan with north corridor, bathroom branches and shafts",
        "drawing_prompt_it": (
            "Planimetria impiantistica verosimile di corridoio nord e locali bagno con canali VMC, staffaggi, "
            "rami secondari e cavedi, stile tavola MEP pulita e leggibile."
        ),
        "sheet_goal": "Supportare i pin di coordinamento VMC e cavedi senza sembrare un render.",
    },
    "el-240": {
        "filename_hint": "el-240-quadri-dorsali.png",
        "title": "EL-240 Quadri di piano e dorsali FM",
        "subtitle": "Quadri Q1-Q3, dorsali forza motrice e linee speciali.",
        "sheet_type": "electrical distribution sheet",
        "orientation": "landscape",
        "subject": "electrical distribution drawing with boards Q1-Q3, main risers and dedicated lines",
        "drawing_prompt_it": (
            "Tavola elettrica verosimile con quadri di piano, dorsali forza motrice, linee speciali e zona Q3, "
            "linguaggio da disegno impiantistico leggibile, ordinato e non fotografico."
        ),
        "sheet_goal": "Dare supporto tecnico ai pin su Q3 e coordinamento con linee speciali.",
    },
    "el-260": {
        "filename_hint": "el-260-sistemi-speciali-citofonia.png",
        "title": "EL-260 Sistemi speciali e citofonia",
        "subtitle": "Videosorveglianza, controllo accessi e monitor hall.",
        "sheet_type": "special systems plan",
        "orientation": "landscape",
        "subject": "special systems plan for hall access control, intercom monitor and surveillance points",
        "drawing_prompt_it": (
            "Tavola tecnica verosimile per sistemi speciali e citofonia con hall, accessi, monitor citofonico e "
            "punti di videosorveglianza, stile schema-planimetria pulito, tecnico e leggibile."
        ),
        "sheet_goal": "Far capire i pin sul monitor hall e sulle scelte impiantistiche correlate.",
    },
    "fn-110": {
        "filename_hint": "fn-110-bagno-campione-2b.png",
        "title": "FN-110 Bagno campione 2B",
        "subtitle": "Rivestimenti, sanitari, fughe e tagli di riferimento.",
        "sheet_type": "interior finish detail sheet",
        "orientation": "portrait",
        "subject": "bathroom sample detail sheet with tiling pattern, sanitary fixtures and reference cuts",
        "drawing_prompt_it": (
            "Tavola finiture verosimile del bagno campione 2B, con sviluppo pareti o vista tecnica pulita, "
            "rivestimenti, sanitari, tagli e fughe di riferimento, impaginazione da tavola interni."
        ),
        "sheet_goal": "Rendere credibile il pin del bagno campione come riferimento operativo reale.",
    },
}


class BlueprintMediaError(RuntimeError):
    pass


def pdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


@dataclass(slots=True)
class MediaUsage:
    task_family: str
    thread_key: str
    placement: str
    scope: str
    slot: str
    activity_key: str | None = None
    comment_key: str | None = None
    brief: str | None = None


@dataclass(slots=True)
class DocumentUsage:
    task_family: str
    thread_key: str
    placement: str
    scope: str
    activity_key: str | None = None
    activity_title: str | None = None
    comment_key: str | None = None
    post_summary_it: str | None = None


@dataclass(slots=True)
class ImageJob:
    asset_stem: str
    prompt_ref: str
    subject: str
    prompt_text: str
    shot_goal: str
    orientation: str
    aspect_ratio: str
    output_path: Path
    usages: list[MediaUsage] = field(default_factory=list)
    briefs: list[str] = field(default_factory=list)
    output_relative_path: str | None = None
    output_mime_type: str | None = None
    output_sha256: str | None = None
    output_size: int | None = None
    status: str = "pending"
    error: str | None = None


@dataclass(slots=True)
class AudioJob:
    audio_ref: str
    speaker_code: str
    language: str
    tone: str
    recording_context: str
    transcript: str
    voice_name: str
    prompt_text: str
    output_path: Path
    usages: list[MediaUsage] = field(default_factory=list)
    output_relative_path: str | None = None
    output_mime_type: str | None = None
    output_sha256: str | None = None
    output_size: int | None = None
    status: str = "pending"
    error: str | None = None


@dataclass(slots=True)
class DrawingJob:
    drawing_code: str
    drawing_stem: str
    filename_hint: str
    title: str
    subtitle: str
    sheet_type: str
    subject: str
    prompt_text: str
    orientation: str
    aspect_ratio: str
    sheet_goal: str
    pin_refs: list[dict[str, Any]] = field(default_factory=list)
    thread_refs: list[str] = field(default_factory=list)
    output_path: Path = Path()
    output_relative_path: str | None = None
    output_mime_type: str | None = None
    output_sha256: str | None = None
    output_size: int | None = None
    status: str = "pending"
    error: str | None = None


@dataclass(slots=True)
class DocumentJob:
    document_ref: str
    title: str
    document_type: str
    folder: list[str]
    created_at: str | None
    phase_targets: list[str]
    activity_targets: list[str]
    lines: list[str]
    output_path: Path
    usages: list[DocumentUsage] = field(default_factory=list)
    output_relative_path: str | None = None
    output_mime_type: str | None = None
    output_sha256: str | None = None
    output_size: int | None = None
    status: str = "pending"
    error: str | None = None


def load_editorial_blueprint(path: Path | None = None) -> dict[str, Any]:
    target_path = path or EDITORIAL_BLUEPRINT_PATH
    return json.loads(target_path.read_text(encoding="utf-8"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def normalize_relative_path(path: Path) -> str:
    return str(path.relative_to(BACKEND_ROOT)).replace("\\", "/")


def infer_image_aspect_ratio(orientation: str | None) -> str:
    return IMAGE_ASPECT_BY_ORIENTATION.get((orientation or "").strip().lower(), "1:1")


def infer_language_label(language: str | None) -> str:
    normalized = (language or "it").split("-")[0].lower()
    return LANGUAGE_LABELS.get(normalized, normalized.upper())


def choose_voice(*, speaker_code: str | None, tone: str | None) -> str:
    if speaker_code and speaker_code in SPEAKER_VOICE_OVERRIDES:
        return SPEAKER_VOICE_OVERRIDES[speaker_code]
    tone_text = (tone or "").lower()
    for keyword, voice_name in VOICE_BY_TONE_KEYWORD.items():
        if keyword in tone_text:
            return voice_name
    return VOICE_FALLBACK


def build_image_prompt(*, blueprint: dict[str, Any], prompt_data: dict[str, Any], briefs: list[str]) -> str:
    profile = blueprint.get("visual_prompt_profiles", {})
    extra_context = []
    for brief in briefs[:3]:
        if brief and brief not in extra_context:
            extra_context.append(brief.strip())
    prompt_parts = [
        "Create a single photorealistic construction-site image asset for a premium demo project.",
        f"Project: {blueprint.get('project_name', 'EdilCloud demo construction project')}.",
        f"Subject: {prompt_data.get('subject', '').strip()}",
        f"Primary scene direction: {prompt_data.get('nano_banana_prompt_it', '').strip()}",
        f"Shot goal: {prompt_data.get('shot_goal', '').strip()}",
        f"Global style: {profile.get('global_style_it', '').strip()}",
        "Keep the image useful as operational evidence, not decorative.",
        "No captions, labels, interface chrome, watermark, poster text, or overlaid annotations.",
        f"Negative guidance: {profile.get('global_negative_prompt_it', '').strip()}",
    ]
    if extra_context:
        prompt_parts.append("Usage context: " + " | ".join(extra_context))
    return "\n".join(part for part in prompt_parts if part)


def build_tts_prompt(*, audio_data: dict[str, Any], transcript: str, voice_name: str) -> str:
    language_label = infer_language_label(audio_data.get("language"))
    recording_context = audio_data.get("recording_context", "").strip()
    tone = audio_data.get("tone", "").strip() or "natural"
    prompt_parts = [
        "Generate a single-speaker, highly natural voice note.",
        f"Language: {language_label}.",
        f"Voice style: {tone}.",
        f"Suggested prebuilt voice: {voice_name}.",
        "Read the transcript exactly as written with believable pacing and short-site-note cadence.",
        "Keep the delivery grounded, human, and not theatrical.",
    ]
    if recording_context:
        prompt_parts.append(f"Recording context: {recording_context}.")
    prompt_parts.append("Transcript:")
    prompt_parts.append(transcript.strip())
    return "\n".join(prompt_parts)


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


def normalize_document_request(item: Any) -> dict[str, Any] | None:
    if isinstance(item, str) and item.strip():
        return {"document_ref": item.strip()}
    if isinstance(item, dict) and str(item.get("document_ref") or item.get("filename") or "").strip():
        payload = dict(item)
        payload["document_ref"] = str(payload.get("document_ref") or payload.get("filename") or "").strip()
        return payload
    return None


def build_document_usage_summary(
    *,
    document_data: dict[str, Any],
    task_family: str,
    activity_title: str | None,
    thread_text: str,
    thread_role: str | None,
) -> str:
    title = str(document_data.get("title") or document_data.get("document_ref") or "documento").strip()
    lead = thread_text.strip().rstrip(".")
    role_hint = ""
    if thread_role == "issue":
        role_hint = " Serve per fissare il punto aperto, la misura condivisa e la regola di chiusura."
    elif thread_role in {"review", "documentation"}:
        role_hint = " Lo allego qui per trasformare la verifica in un riferimento che il lotto puo' riusare."
    else:
        role_hint = " Lo allego qui per tenere il fronte leggibile e non lasciare la decisione solo nei messaggi."
    if activity_title:
        return (
            f"Allego {title} per la lavorazione '{activity_title}': {lead}. "
            f"Nel documento si capisce perche' questo passaggio tocca davvero la fase {task_family} e cosa va letto in dettaglio.{role_hint}"
        )
    return (
        f"Allego {title}: {lead}. Nel documento si capisce perche' questo passaggio resta rilevante per la fase {task_family} "
        f"e cosa conviene approfondire nel testo completo.{role_hint}"
    )


def build_document_pdf(job: DocumentJob) -> bytes:
    header_lines = [
        f"Tipo documento: {job.document_type}",
        f"Cartella demo: {' / '.join(job.folder) if job.folder else 'Documenti di cantiere'}",
    ]
    if job.created_at:
        header_lines.append(f"Data riferimento: {job.created_at}")
    if job.phase_targets:
        header_lines.append(f"Fasi collegate: {', '.join(job.phase_targets)}")
    if job.activity_targets:
        header_lines.append(f"Lavorazioni collegate: {', '.join(job.activity_targets)}")
    usage_summaries = [usage.post_summary_it for usage in job.usages if usage.post_summary_it]
    if usage_summaries:
        header_lines.append("Sintesi usi nel demo:")
        header_lines.extend(f"- {summary}" for summary in usage_summaries[:4])
    if job.lines:
        header_lines.append("Contenuto sintetico:")
        header_lines.extend(f"- {line}" for line in job.lines)
    return build_pdf(job.title, header_lines)


def build_drawing_prompt(
    *,
    blueprint: dict[str, Any],
    drawing_spec: dict[str, Any],
    pin_refs: list[dict[str, Any]],
) -> str:
    def zone_label(x_percent: int, y_percent: int) -> str:
        horizontal = "left" if x_percent < 34 else ("center" if x_percent < 67 else "right")
        vertical = "upper" if y_percent < 34 else ("middle" if y_percent < 67 else "lower")
        return f"{vertical} {horizontal}"

    anchor_lines = []
    for pin in pin_refs[:6]:
        title = str(pin.get("title") or "").strip()
        x_percent = int(pin.get("x_percent") or 0)
        y_percent = int(pin.get("y_percent") or 0)
        anchor_lines.append(f"- keep a recognizable technical zone for {title} in the {zone_label(x_percent, y_percent)} area")
    prompt_parts = [
        "Create a single believable technical drawing sheet for a premium residential construction demo.",
        f"Project: {blueprint.get('project_name', 'EdilCloud demo construction project')}.",
        f"Sheet title: {drawing_spec.get('title', '').strip()}",
        f"Subtitle: {drawing_spec.get('subtitle', '').strip()}",
        f"Drawing type: {drawing_spec.get('sheet_type', '').strip()}",
        f"Subject: {drawing_spec.get('subject', '').strip()}",
        f"Primary direction: {drawing_spec.get('drawing_prompt_it', '').strip()}",
        f"Goal: {drawing_spec.get('sheet_goal', '').strip()}",
        (
            "Style rules: orthographic technical representation, believable linework, white or very light paper "
            "background, dark gray or black drawing lines, subtle muted accent tones only if coherent with a real "
            "architectural or MEP sheet."
        ),
        (
            "This must look like a plausible design-office drawing or exported plan, not a photo, not a 3D render, "
            "not an illustration, not a marketing board."
        ),
        (
            "Do not draw UI elements, map pins, bubbles, legends, logos, watermarks, fake app chrome, stickers, "
            "colored markers, red circles, or presentation callouts. Pins will be overlaid later."
        ),
        "Do not print any words or coordinates taken from these instructions onto the drawing.",
        (
            "Keep the geometry readable around the future pin anchor areas so an overlay can land on believable "
            "rooms, nodes, shafts, collectors, facade areas, or technical details."
        ),
        "Resolved pins will be shown in green later and open issues in red later, but this source sheet must stay clean.",
    ]
    if anchor_lines:
        prompt_parts.append("Invisible composition guidance only, never to be printed as text:")
        prompt_parts.extend(anchor_lines)
    return "\n".join(part for part in prompt_parts if part)


def _root_media_usage(
    *,
    task_family: str,
    thread_key: str,
    placement: str,
    slot: str,
    activity_key: str | None,
    brief: str | None,
    scope: str,
) -> MediaUsage:
    return MediaUsage(
        task_family=task_family,
        thread_key=thread_key,
        placement=placement,
        scope=scope,
        slot=slot,
        activity_key=activity_key,
        brief=brief,
    )


def collect_image_jobs(
    blueprint: dict[str, Any],
    *,
    attachment_root: Path = GENERATED_ATTACHMENT_ROOT,
) -> list[ImageJob]:
    prompt_library = blueprint.get("visual_prompt_library", {})
    jobs: dict[str, ImageJob] = {}

    def register_request(
        *,
        request: dict[str, Any],
        task_family: str,
        thread_key: str,
        activity_key: str | None,
        comment_key: str | None,
        scope: str,
    ) -> None:
        asset_stem = request.get("target_asset_stem")
        if not asset_stem:
            return
        prompt_ref = request.get("prompt_ref") or asset_stem
        prompt_data = prompt_library.get(prompt_ref)
        if prompt_data is None:
            raise BlueprintMediaError(f'Missing prompt library entry "{prompt_ref}" for asset "{asset_stem}".')
        job = jobs.get(asset_stem)
        if job is None:
            output_path = attachment_root / f"{asset_stem}.png"
            job = ImageJob(
                asset_stem=asset_stem,
                prompt_ref=prompt_ref,
                subject=prompt_data.get("subject", ""),
                prompt_text=build_image_prompt(
                    blueprint=blueprint,
                    prompt_data=prompt_data,
                    briefs=[request.get("brief", "")],
                ),
                shot_goal=prompt_data.get("shot_goal", ""),
                orientation=prompt_data.get("orientation", "square"),
                aspect_ratio=infer_image_aspect_ratio(prompt_data.get("orientation")),
                output_path=output_path,
            )
            jobs[asset_stem] = job
        brief = request.get("brief")
        if brief and brief not in job.briefs:
            job.briefs.append(brief)
            job.prompt_text = build_image_prompt(blueprint=blueprint, prompt_data=prompt_data, briefs=job.briefs)
        job.usages.append(
            MediaUsage(
                task_family=task_family,
                thread_key=thread_key,
                activity_key=activity_key,
                comment_key=comment_key,
                placement=request.get("placement", "post"),
                scope=scope,
                slot=request.get("slot", "default"),
                brief=brief,
            )
        )

    for task in blueprint.get("tasks", []):
        task_family = task["task_family"]
        task_thread = task["task_thread"]
        for request in task_thread.get("root_post", {}).get("image_requests", []):
            register_request(
                request=request,
                task_family=task_family,
                thread_key=task_thread["thread_key"],
                activity_key=None,
                comment_key=None,
                scope="task_thread_root_post",
            )
        for activity in task.get("activities", []):
            activity_key = activity["activity_key"]
            for thread in activity.get("threads", []):
                for request in thread.get("root_post", {}).get("image_requests", []):
                    register_request(
                        request=request,
                        task_family=task_family,
                        thread_key=thread["thread_key"],
                        activity_key=activity_key,
                        comment_key=None,
                        scope="thread_root_post",
                    )
                for index, comment in enumerate(thread.get("comment_script", []), start=1):
                    comment_key = comment.get("comment_key") or f'{thread["thread_key"]}-comment-{index}'
                    for request in comment.get("image_requests", []):
                        register_request(
                            request=request,
                            task_family=task_family,
                            thread_key=thread["thread_key"],
                            activity_key=activity_key,
                            comment_key=comment_key,
                            scope="thread_comment",
                        )
    return sorted(jobs.values(), key=lambda item: item.asset_stem)


def collect_drawing_jobs(
    blueprint: dict[str, Any],
    *,
    drawing_root: Path = GENERATED_DRAWING_ROOT,
) -> list[DrawingJob]:
    jobs: dict[str, DrawingJob] = {}
    pin_registry = blueprint.get("pin_registry", [])

    for pin in pin_registry:
        drawing_code = pin.get("drawing_code")
        if not drawing_code:
            continue
        drawing_spec = DRAWING_SPECS_BY_CODE.get(drawing_code)
        if drawing_spec is None:
            raise BlueprintMediaError(f'Missing drawing spec for drawing code "{drawing_code}".')
        job = jobs.get(drawing_code)
        if job is None:
            filename_hint = str(drawing_spec.get("filename_hint") or f"{drawing_code}.png")
            drawing_stem = Path(filename_hint).stem
            job = DrawingJob(
                drawing_code=drawing_code,
                drawing_stem=drawing_stem,
                filename_hint=filename_hint,
                title=str(drawing_spec.get("title") or ""),
                subtitle=str(drawing_spec.get("subtitle") or ""),
                sheet_type=str(drawing_spec.get("sheet_type") or "technical drawing"),
                subject=str(drawing_spec.get("subject") or ""),
                prompt_text="",
                orientation=str(drawing_spec.get("orientation") or "landscape"),
                aspect_ratio=infer_image_aspect_ratio(drawing_spec.get("orientation")),
                sheet_goal=str(drawing_spec.get("sheet_goal") or ""),
                output_path=drawing_root / f"{drawing_stem}.png",
            )
            jobs[drawing_code] = job
        job.pin_refs.append(
            {
                "pin_code": pin.get("pin_code"),
                "title": pin.get("title"),
                "status": pin.get("status"),
                "priority": pin.get("priority"),
                "x_percent": pin.get("x_percent"),
                "y_percent": pin.get("y_percent"),
                "drawer_summary": pin.get("drawer_summary"),
            }
        )
        for thread_ref in pin.get("thread_refs") or []:
            if thread_ref and thread_ref not in job.thread_refs:
                job.thread_refs.append(thread_ref)

    for drawing_code, job in jobs.items():
        drawing_spec = DRAWING_SPECS_BY_CODE[drawing_code]
        job.prompt_text = build_drawing_prompt(
            blueprint=blueprint,
            drawing_spec=drawing_spec,
            pin_refs=job.pin_refs,
        )

    return sorted(jobs.values(), key=lambda item: item.drawing_code)


def collect_document_jobs(
    blueprint: dict[str, Any],
    *,
    document_root: Path = GENERATED_DOCUMENT_ROOT,
) -> list[DocumentJob]:
    document_library_rows = blueprint.get("document_library", [])
    document_library: dict[str, dict[str, Any]] = {}
    for item in document_library_rows:
        if not isinstance(item, dict):
            continue
        document_ref = str(item.get("document_ref") or item.get("filename") or "").strip()
        if not document_ref:
            continue
        payload = dict(item)
        payload["document_ref"] = document_ref
        document_library[document_ref] = payload
    if not document_library:
        raise BlueprintMediaError("Missing document_library in editorial blueprint.")

    jobs: dict[str, DocumentJob] = {}

    def register_document_requests(
        *,
        requests: list[Any],
        task_family: str,
        thread_key: str,
        activity_key: str | None,
        activity_title: str | None,
        comment_key: str | None,
        scope: str,
        thread_text: str,
        thread_role: str | None,
    ) -> None:
        for item in requests:
            request = normalize_document_request(item)
            if request is None:
                continue
            document_ref = request["document_ref"]
            document_data = document_library.get(document_ref)
            if document_data is None:
                raise BlueprintMediaError(f'Missing document library entry "{document_ref}".')
            job = jobs.get(document_ref)
            if job is None:
                output_path = document_root / document_ref
                job = DocumentJob(
                    document_ref=document_ref,
                    title=str(document_data.get("title") or document_ref),
                    document_type=str(document_data.get("document_type") or "documento di cantiere"),
                    folder=list(document_data.get("folder") or []),
                    created_at=str(document_data.get("created_at") or "") or None,
                    phase_targets=[str(value) for value in document_data.get("phase_targets") or []],
                    activity_targets=[str(value) for value in document_data.get("activity_targets") or []],
                    lines=[str(value) for value in document_data.get("lines") or []],
                    output_path=output_path,
                )
                jobs[document_ref] = job
            post_summary_it = str(
                request.get("post_summary_it")
                or build_document_usage_summary(
                    document_data=document_data,
                    task_family=task_family,
                    activity_title=activity_title,
                    thread_text=thread_text,
                    thread_role=thread_role,
                )
            ).strip()
            job.usages.append(
                DocumentUsage(
                    task_family=task_family,
                    thread_key=thread_key,
                    placement=str(request.get("placement") or "post"),
                    scope=scope,
                    activity_key=activity_key,
                    activity_title=activity_title,
                    comment_key=comment_key,
                    post_summary_it=post_summary_it or None,
                )
            )

    for task in blueprint.get("tasks", []):
        task_family = str(task.get("task_family") or "")
        task_thread = task.get("task_thread") or {}
        register_document_requests(
            requests=list((task_thread.get("root_post") or {}).get("document_refs") or []),
            task_family=task_family,
            thread_key=str(task_thread.get("thread_key") or ""),
            activity_key=None,
            activity_title=None,
            comment_key=None,
            scope="task_thread_root_post",
            thread_text=str((task_thread.get("root_post") or {}).get("text") or ""),
            thread_role=str(task_thread.get("thread_role") or ""),
        )
        for activity in task.get("activities", []):
            activity_key = str(activity.get("activity_key") or "")
            activity_title = str(activity.get("activity_title") or "")
            for thread in activity.get("threads", []):
                thread_key = str(thread.get("thread_key") or "")
                thread_role = str(thread.get("thread_role") or "")
                root_post = thread.get("root_post") or {}
                register_document_requests(
                    requests=list(root_post.get("document_refs") or []),
                    task_family=task_family,
                    thread_key=thread_key,
                    activity_key=activity_key,
                    activity_title=activity_title,
                    comment_key=None,
                    scope="thread_root_post",
                    thread_text=str(root_post.get("text") or ""),
                    thread_role=thread_role,
                )
                for index, comment in enumerate(thread.get("comment_script", []), start=1):
                    comment_key = str(comment.get("comment_key") or f"{thread_key}-comment-{index}")
                    register_document_requests(
                        requests=list(comment.get("document_refs") or []),
                        task_family=task_family,
                        thread_key=thread_key,
                        activity_key=activity_key,
                        activity_title=activity_title,
                        comment_key=comment_key,
                        scope="thread_comment",
                        thread_text=str(comment.get("text") or root_post.get("text") or ""),
                        thread_role=thread_role,
                    )

    return sorted(jobs.values(), key=lambda item: item.document_ref)


def collect_audio_jobs(
    blueprint: dict[str, Any],
    *,
    attachment_root: Path = GENERATED_ATTACHMENT_ROOT,
) -> list[AudioJob]:
    audio_library = blueprint.get("audio_script_library", {})
    jobs: dict[str, AudioJob] = {}

    def register_request(
        *,
        request: dict[str, Any],
        task_family: str,
        thread_key: str,
        activity_key: str | None,
        comment_key: str | None,
        scope: str,
    ) -> None:
        audio_ref = request.get("audio_ref")
        if not audio_ref:
            return
        audio_data = audio_library.get(audio_ref)
        if audio_data is None:
            raise BlueprintMediaError(f'Missing audio library entry "{audio_ref}".')
        transcript = (
            request.get("transcript_draft")
            or audio_data.get("script_it")
            or audio_data.get("script")
            or ""
        ).strip()
        speaker_code = request.get("speaker_code") or audio_data.get("speaker_code") or ""
        language = request.get("language") or audio_data.get("language") or "it"
        tone = request.get("tone") or audio_data.get("tone") or ""
        voice_name = choose_voice(speaker_code=speaker_code, tone=tone)
        job = jobs.get(audio_ref)
        if job is None:
            output_path = attachment_root / f"{audio_ref}.wav"
            job = AudioJob(
                audio_ref=audio_ref,
                speaker_code=speaker_code,
                language=language,
                tone=tone,
                recording_context=audio_data.get("recording_context", ""),
                transcript=transcript,
                voice_name=voice_name,
                prompt_text=build_tts_prompt(audio_data=audio_data, transcript=transcript, voice_name=voice_name),
                output_path=output_path,
            )
            jobs[audio_ref] = job
        job.usages.append(
            MediaUsage(
                task_family=task_family,
                thread_key=thread_key,
                activity_key=activity_key,
                comment_key=comment_key,
                placement=request.get("placement", "post"),
                scope=scope,
                slot=request.get("slot", "default"),
                brief=request.get("tone"),
            )
        )

    for task in blueprint.get("tasks", []):
        task_family = task["task_family"]
        task_thread = task["task_thread"]
        for request in task_thread.get("root_post", {}).get("audio_requests", []):
            register_request(
                request=request,
                task_family=task_family,
                thread_key=task_thread["thread_key"],
                activity_key=None,
                comment_key=None,
                scope="task_thread_root_post",
            )
        for activity in task.get("activities", []):
            activity_key = activity["activity_key"]
            for thread in activity.get("threads", []):
                for request in thread.get("root_post", {}).get("audio_requests", []):
                    register_request(
                        request=request,
                        task_family=task_family,
                        thread_key=thread["thread_key"],
                        activity_key=activity_key,
                        comment_key=None,
                        scope="thread_root_post",
                    )
                for index, comment in enumerate(thread.get("comment_script", []), start=1):
                    comment_key = comment.get("comment_key") or f'{thread["thread_key"]}-comment-{index}'
                    for request in comment.get("audio_requests", []):
                        register_request(
                            request=request,
                            task_family=task_family,
                            thread_key=thread["thread_key"],
                            activity_key=activity_key,
                            comment_key=comment_key,
                            scope="thread_comment",
                        )
    return sorted(jobs.values(), key=lambda item: item.audio_ref)


def existing_output_for_stem(stem: str, *, root: Path = GENERATED_ATTACHMENT_ROOT) -> Path | None:
    matches = sorted(root.glob(f"{stem}.*"))
    return matches[0] if matches else None


def remove_existing_outputs(stem: str, *, root: Path = GENERATED_ATTACHMENT_ROOT) -> None:
    for path in root.glob(f"{stem}.*"):
        path.unlink(missing_ok=True)


def _post_json(
    *,
    api_key: str,
    model: str,
    payload: dict[str, Any],
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    retry_attempts: int = DEFAULT_RETRY_ATTEMPTS,
) -> dict[str, Any]:
    url = f"{GEMINI_API_ROOT}/{model}:generateContent"
    last_error: Exception | None = None
    for attempt in range(1, retry_attempts + 1):
        try:
            response = requests.post(
                url,
                params={"key": api_key},
                json=payload,
                timeout=timeout_seconds,
            )
            if response.status_code in {429, 500, 502, 503, 504} and attempt < retry_attempts:
                time.sleep(min(10, attempt * 2))
                continue
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            last_error = exc
            if attempt >= retry_attempts:
                break
            time.sleep(min(10, attempt * 2))
    raise BlueprintMediaError(f"Gemini request failed for model {model}: {last_error}") from last_error


def _first_inline_part(response_payload: dict[str, Any]) -> tuple[bytes, str]:
    candidates = response_payload.get("candidates") or []
    for candidate in candidates:
        content = candidate.get("content") or {}
        for part in content.get("parts") or []:
            inline_data = part.get("inlineData") or part.get("inline_data")
            if inline_data and inline_data.get("data"):
                return base64.b64decode(inline_data["data"]), inline_data.get("mimeType") or inline_data.get("mime_type") or ""
    raise BlueprintMediaError("Gemini response did not include inline media data.")


def generate_image_bytes(
    *,
    api_key: str,
    model: str,
    prompt_text: str,
    aspect_ratio: str,
) -> tuple[bytes, str]:
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt_text,
                    }
                ]
            }
        ],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {
                "aspectRatio": aspect_ratio,
            },
        },
    }
    if model.startswith("gemini-3"):
        payload["generationConfig"]["imageConfig"]["imageSize"] = "2K"
    response_payload = _post_json(api_key=api_key, model=model, payload=payload)
    return _first_inline_part(response_payload)


def generate_audio_bytes(
    *,
    api_key: str,
    model: str,
    prompt_text: str,
    voice_name: str,
) -> tuple[bytes, str]:
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt_text,
                    }
                ]
            }
        ],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {
                        "voiceName": voice_name,
                    }
                }
            },
        },
    }
    response_payload = _post_json(api_key=api_key, model=model, payload=payload)
    return _first_inline_part(response_payload)


def _ensure_wav_container(pcm_bytes: bytes, *, output_path: Path) -> None:
    with io.BytesIO() as buffer:
        with wave.open(buffer, "wb") as wave_file:
            wave_file.setnchannels(1)
            wave_file.setsampwidth(2)
            wave_file.setframerate(24000)
            wave_file.writeframes(pcm_bytes)
        output_path.write_bytes(buffer.getvalue())


def _image_output_path(base_path: Path, *, mime_type: str) -> Path:
    suffix = IMAGE_EXTENSION_BY_MIME.get(mime_type.lower(), mimetypes.guess_extension(mime_type) or ".png")
    return base_path.with_suffix(suffix)


def _audio_output_path(base_path: Path, *, mime_type: str, payload: bytes) -> tuple[Path, bool]:
    lower_mime = mime_type.lower()
    if payload.startswith(b"RIFF") and payload[8:12] == b"WAVE":
        return base_path.with_suffix(".wav"), True
    if payload.startswith(b"ID3") or payload[:2] == b"\xff\xfb":
        return base_path.with_suffix(".mp3"), True
    if payload.startswith(b"OggS"):
        return base_path.with_suffix(".ogg"), True
    if payload.startswith(b"\x1aE\xdf\xa3"):
        return base_path.with_suffix(".webm"), True
    suffix = AUDIO_EXTENSION_BY_MIME.get(lower_mime)
    if suffix:
        return base_path.with_suffix(suffix), suffix == ".wav"
    return base_path.with_suffix(".wav"), False


def materialize_image_job(
    *,
    job: ImageJob,
    api_key: str,
    model: str,
    overwrite: bool = False,
) -> ImageJob:
    existing = existing_output_for_stem(job.asset_stem)
    if existing and not overwrite:
        job.status = "skipped_existing"
        job.output_path = existing
        job.output_relative_path = normalize_relative_path(existing)
        job.output_size = existing.stat().st_size
        job.output_sha256 = sha256_bytes(existing.read_bytes())
        job.output_mime_type = mimetypes.guess_type(existing.name)[0] or "image/png"
        return job

    remove_existing_outputs(job.asset_stem)
    payload, mime_type = generate_image_bytes(
        api_key=api_key,
        model=model,
        prompt_text=job.prompt_text,
        aspect_ratio=job.aspect_ratio,
    )
    output_path = _image_output_path(job.output_path, mime_type=mime_type or "image/png")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(payload)
    job.status = "generated"
    job.output_path = output_path
    job.output_relative_path = normalize_relative_path(output_path)
    job.output_size = output_path.stat().st_size
    job.output_sha256 = sha256_bytes(payload)
    job.output_mime_type = mime_type or "image/png"
    return job


def materialize_drawing_job(
    *,
    job: DrawingJob,
    api_key: str,
    model: str,
    overwrite: bool = False,
) -> DrawingJob:
    existing = existing_output_for_stem(job.drawing_stem, root=GENERATED_DRAWING_ROOT)
    if existing and not overwrite:
        job.status = "skipped_existing"
        job.output_path = existing
        job.output_relative_path = normalize_relative_path(existing)
        job.output_size = existing.stat().st_size
        job.output_sha256 = sha256_bytes(existing.read_bytes())
        job.output_mime_type = mimetypes.guess_type(existing.name)[0] or "image/png"
        return job

    remove_existing_outputs(job.drawing_stem, root=GENERATED_DRAWING_ROOT)
    payload, mime_type = generate_image_bytes(
        api_key=api_key,
        model=model,
        prompt_text=job.prompt_text,
        aspect_ratio=job.aspect_ratio,
    )
    output_path = _image_output_path(job.output_path, mime_type=mime_type or "image/png")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(payload)
    job.status = "generated"
    job.output_path = output_path
    job.output_relative_path = normalize_relative_path(output_path)
    job.output_size = output_path.stat().st_size
    job.output_sha256 = sha256_bytes(payload)
    job.output_mime_type = mime_type or "image/png"
    return job


def materialize_document_job(
    *,
    job: DocumentJob,
    overwrite: bool = False,
) -> DocumentJob:
    stem = Path(job.document_ref).stem
    existing = existing_output_for_stem(stem, root=GENERATED_DOCUMENT_ROOT)
    if existing and not overwrite:
        job.status = "skipped_existing"
        job.output_path = existing
        job.output_relative_path = normalize_relative_path(existing)
        job.output_size = existing.stat().st_size
        job.output_sha256 = sha256_bytes(existing.read_bytes())
        job.output_mime_type = mimetypes.guess_type(existing.name)[0] or "application/pdf"
        return job

    remove_existing_outputs(stem, root=GENERATED_DOCUMENT_ROOT)
    payload = build_document_pdf(job)
    output_path = job.output_path.with_suffix(".pdf")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(payload)
    job.status = "generated"
    job.output_path = output_path
    job.output_relative_path = normalize_relative_path(output_path)
    job.output_size = output_path.stat().st_size
    job.output_sha256 = sha256_bytes(payload)
    job.output_mime_type = "application/pdf"
    return job


def materialize_audio_job(
    *,
    job: AudioJob,
    api_key: str,
    model: str,
    overwrite: bool = False,
) -> AudioJob:
    existing = existing_output_for_stem(job.audio_ref)
    if existing and not overwrite:
        job.status = "skipped_existing"
        job.output_path = existing
        job.output_relative_path = normalize_relative_path(existing)
        job.output_size = existing.stat().st_size
        job.output_sha256 = sha256_bytes(existing.read_bytes())
        job.output_mime_type = mimetypes.guess_type(existing.name)[0] or "audio/wav"
        return job

    remove_existing_outputs(job.audio_ref)
    payload, mime_type = generate_audio_bytes(
        api_key=api_key,
        model=model,
        prompt_text=job.prompt_text,
        voice_name=job.voice_name,
    )
    output_path, direct_write = _audio_output_path(job.output_path, mime_type=mime_type or "", payload=payload)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if direct_write:
        output_path.write_bytes(payload)
    else:
        _ensure_wav_container(payload, output_path=output_path)
    final_bytes = output_path.read_bytes()
    job.status = "generated"
    job.output_path = output_path
    job.output_relative_path = normalize_relative_path(output_path)
    job.output_size = output_path.stat().st_size
    job.output_sha256 = sha256_bytes(final_bytes)
    job.output_mime_type = mime_type or "audio/wav"
    return job


def job_to_dict(job: DocumentJob | DrawingJob | ImageJob | AudioJob) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "output_relative_path": job.output_relative_path,
        "output_mime_type": job.output_mime_type,
        "output_sha256": job.output_sha256,
        "output_size": job.output_size,
        "status": job.status,
        "error": job.error,
    }
    if isinstance(job, DocumentJob):
        payload.update(
            {
                "document_ref": job.document_ref,
                "title": job.title,
                "document_type": job.document_type,
                "folder": job.folder,
                "created_at": job.created_at,
                "phase_targets": job.phase_targets,
                "activity_targets": job.activity_targets,
                "lines": job.lines,
                "usages": [
                    {
                        "task_family": usage.task_family,
                        "thread_key": usage.thread_key,
                        "activity_key": usage.activity_key,
                        "activity_title": usage.activity_title,
                        "comment_key": usage.comment_key,
                        "placement": usage.placement,
                        "scope": usage.scope,
                        "post_summary_it": usage.post_summary_it,
                    }
                    for usage in job.usages
                ],
            }
        )
        return payload
    if isinstance(job, DrawingJob):
        payload.update(
            {
                "drawing_code": job.drawing_code,
                "drawing_stem": job.drawing_stem,
                "filename_hint": job.filename_hint,
                "title": job.title,
                "subtitle": job.subtitle,
                "sheet_type": job.sheet_type,
                "subject": job.subject,
                "orientation": job.orientation,
                "aspect_ratio": job.aspect_ratio,
                "sheet_goal": job.sheet_goal,
                "thread_refs": job.thread_refs,
                "pins": job.pin_refs,
                "prompt_text": job.prompt_text,
            }
        )
        return payload
    payload["usages"] = [
        {
            "task_family": usage.task_family,
            "thread_key": usage.thread_key,
            "activity_key": usage.activity_key,
            "comment_key": usage.comment_key,
            "placement": usage.placement,
            "scope": usage.scope,
            "slot": usage.slot,
            "brief": usage.brief,
        }
        for usage in job.usages
    ]
    if isinstance(job, ImageJob):
        payload.update(
            {
                "asset_stem": job.asset_stem,
                "prompt_ref": job.prompt_ref,
                "subject": job.subject,
                "orientation": job.orientation,
                "aspect_ratio": job.aspect_ratio,
                "shot_goal": job.shot_goal,
                "prompt_text": job.prompt_text,
            }
        )
    else:
        payload.update(
            {
                "audio_ref": job.audio_ref,
                "speaker_code": job.speaker_code,
                "language": job.language,
                "tone": job.tone,
                "recording_context": job.recording_context,
                "voice_name": job.voice_name,
                "transcript": job.transcript,
                "prompt_text": job.prompt_text,
            }
        )
    return payload


def build_manifest(
    *,
    blueprint_path: Path,
    document_jobs: list[DocumentJob],
    drawing_model: str,
    image_model: str,
    tts_model: str,
    drawing_jobs: list[DrawingJob],
    image_jobs: list[ImageJob],
    audio_jobs: list[AudioJob],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "blueprint_relative_path": normalize_relative_path(blueprint_path),
        "document_root": normalize_relative_path(GENERATED_DOCUMENT_ROOT),
        "drawing_root": normalize_relative_path(GENERATED_DRAWING_ROOT),
        "attachment_root": normalize_relative_path(GENERATED_ATTACHMENT_ROOT),
        "drawing_model": drawing_model,
        "image_model": image_model,
        "tts_model": tts_model,
        "stats": {
            "document_jobs": len(document_jobs),
            "drawing_jobs": len(drawing_jobs),
            "image_jobs": len(image_jobs),
            "audio_jobs": len(audio_jobs),
            "generated_documents": sum(1 for job in document_jobs if job.status == "generated"),
            "generated_drawings": sum(1 for job in drawing_jobs if job.status == "generated"),
            "generated_images": sum(1 for job in image_jobs if job.status == "generated"),
            "generated_audio": sum(1 for job in audio_jobs if job.status == "generated"),
            "skipped_documents": sum(1 for job in document_jobs if job.status == "skipped_existing"),
            "skipped_drawings": sum(1 for job in drawing_jobs if job.status == "skipped_existing"),
            "skipped_images": sum(1 for job in image_jobs if job.status == "skipped_existing"),
            "skipped_audio": sum(1 for job in audio_jobs if job.status == "skipped_existing"),
            "errored_documents": sum(1 for job in document_jobs if job.status == "error"),
            "errored_drawings": sum(1 for job in drawing_jobs if job.status == "error"),
            "errored_images": sum(1 for job in image_jobs if job.status == "error"),
            "errored_audio": sum(1 for job in audio_jobs if job.status == "error"),
        },
        "documents": [job_to_dict(job) for job in document_jobs],
        "drawings": [job_to_dict(job) for job in drawing_jobs],
        "images": [job_to_dict(job) for job in image_jobs],
        "audio": [job_to_dict(job) for job in audio_jobs],
    }


def write_manifest(*, manifest: dict[str, Any], manifest_path: Path = GENERATED_MEDIA_MANIFEST_PATH) -> Path:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=True, indent=2), encoding="utf-8")
    return manifest_path


def require_gemini_api_key() -> str:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise BlueprintMediaError("GEMINI_API_KEY is not configured.")
    return api_key
