"""Per-media outcomes, bounded image calls and checkpointed audio segments."""

from datetime import timedelta
from contextlib import contextmanager
import hashlib
import io
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
import wave
from threading import Lock
from weakref import WeakValueDictionary

from django.conf import settings
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import F
import httpx

from .checkpoints import ProviderCheckpoint, run_step
from .intelligence_calls import specialist
from .intelligence_contracts import ImageDescription
from .models import DocumentAIUsage, DocumentAudit, DocumentJob, DocumentStepAttempt
from .renderer import image_data
from .provider import DocumentProviderError
from .source_reading import add_parts, authorized_local_file, set_reading_state


_media_locks = WeakValueDictionary()
_media_lock_guard = Lock()


@contextmanager
def media_singleflight(job_id, media_hash):
    # Only one worker owns a job lease. Its parallel lanes must share a single
    # analysis/checkpoint for duplicate bytes; unused locks are reclaimed.
    key = (str(job_id), media_hash)
    with _media_lock_guard:
        lock = _media_locks.get(key)
        if lock is None:
            lock = _media_locks[key] = Lock()
    with lock:
        yield


def analyze_image(job, item):
    try:
        with authorized_local_file(job, item) as (path, sha):
            image = image_data(ContentFile(path.read_bytes()), max_pixels=(1800, 1800))
    except (OSError, ValueError):
        set_reading_state(item, "unreadable", "image_source_unavailable_or_changed")
        return
    if not image:
        set_reading_state(item, "unreadable", "image_cannot_be_decoded")
        return
    with media_singleflight(job.pk, sha):
        key = f"document-media-v3:image:{job.revision.elaborato.project_id}:{sha}"
        description = cache.get(key)
        if description is None:
            result = specialist(
                job=job,
                key=f"media:image:{sha}",
                stage="document_media",
                schema=ImageDescription,
                effort="medium",
                images=[("image", image)],
                data={"image_sha256": sha},
                instructions=(
                    "Descrivi soltanto ciò che è realmente visibile nell'immagine. "
                    "Non hai contesto esterno. Riporta limiti visivi; non dedurre date, "
                    "persone, misure, conformità o completamento tecnico. Se è un documento "
                    "o tavola, is_document=true e trascrivi le parti leggibili senza inventarle."
                ),
            )
            description = result.model_dump()
            cache.set(key, description, int(timedelta(days=30).total_seconds()))
        value = {**description, "model": "gpt-6-luna", "human_verified": False, "media_sha256": sha}
        context = item.payload.get("data", {})
        text = json.dumps({"visual_analysis": value, "context": context}, ensure_ascii=False)
        add_parts(item, text, method="machine_visual_analysis")
        type(item).objects.filter(pk=item.pk).update(reading={"visual_analysis": value})


def transcription_reservation(raw):
    """Conservative quota planning for one decoded segment, never an API cap.

    FFmpeg supplies PCM WAV. Reserve from its real duration rather than zero;
    successful usage releases this reservation in the same ledger transaction.
    The allowance deliberately exceeds ordinary speech token rates and includes
    room for output. Actual provider usage remains the accounting authority.
    """
    try:
        with wave.open(io.BytesIO(raw), "rb") as audio:
            seconds = audio.getnframes() / audio.getframerate()
    except (wave.Error, EOFError, ZeroDivisionError) as exc:
        raise DocumentProviderError("Segmento audio non valido: trascrizione non avviata.") from exc
    if not math.isfinite(seconds) or seconds <= 0:
        raise DocumentProviderError("Segmento audio vuoto: trascrizione non avviata.")
    return math.ceil(seconds * 256) + 4096


def transcribe_segment(job, raw, filename):
    checkpoint = ProviderCheckpoint(
        job, stage="document_transcription", model="gpt-4o-transcribe", effort="none"
    )
    payload = checkpoint.restore()
    if payload is None:
        if not settings.OPENAI_API_KEY:
            raise DocumentProviderError("Trascrizione audio non configurata.")
        checkpoint.sent(reservation=transcription_reservation(raw))
        try:
            response = httpx.post(
                settings.OPENAI_API_BASE_URL.rstrip("/") + "/audio/transcriptions",
                headers={"Authorization": "Bearer " + settings.OPENAI_API_KEY},
                data={"model": "gpt-4o-transcribe"},
                files={"file": (filename, raw, "audio/wav")},
                timeout=httpx.Timeout(180, connect=15),
                follow_redirects=False,
            )
            if response.status_code >= 400:
                if response.status_code in {400, 401, 403, 413, 422, 429}:
                    checkpoint.rejected(f"HTTP_{response.status_code}")
                raise DocumentProviderError(
                    "Il servizio di trascrizione non ha completato la richiesta."
                )
            result = response.json()
            text = result.get("text")
            identifier = "audio:" + (
                response.headers.get("x-request-id") or str(checkpoint.attempt.pk)
            )
            payload = {
                "id": identifier,
                "status": "completed",
                "usage": result.get("usage") or {},
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps({"text": text}),
                            }
                        ],
                    }
                ],
            }
            checkpoint.completed(payload)
        finally:
            checkpoint.interrupted()
    usage = payload.get("usage") or {}
    with transaction.atomic():
        record, created = DocumentAIUsage.objects.get_or_create(
            response_id=payload["id"],
            defaults={
                "job": job,
                "workspace": job.revision.elaborato.project.workspace,
                "attempt": checkpoint.attempt,
                "stage": "document_transcription",
                "model": "gpt-4o-transcribe",
                "input_tokens": max(0, int(usage.get("input_tokens", 0))),
                "output_tokens": max(0, int(usage.get("output_tokens", 0))),
                "total_tokens": max(0, int(usage.get("total_tokens", 0))),
            },
        )
        if checkpoint.attempt:
            DocumentStepAttempt.objects.filter(pk=checkpoint.attempt.pk).update(reserved_tokens=0)
        if created:
            DocumentJob.objects.filter(pk=job.pk).update(
                consumed_tokens=F("consumed_tokens") + record.total_tokens
            )
            if record.total_tokens:
                from edilcloud.modules.billing.services import apply_ai_usage_to_billing

                apply_ai_usage_to_billing(
                    workspace=record.workspace,
                    total_tokens=record.total_tokens,
                    reference_id=f"elaborati:{record.pk}",
                )
            DocumentAudit.objects.create(
                revision=job.revision,
                actor=job.requested_by,
                action="ai.transcription",
                detail={"model": record.model, "usage": usage},
            )
    text = json.loads(payload["output"][0]["content"][0]["text"])["text"]
    if not isinstance(text, str) or not text.strip():
        raise DocumentProviderError("Il servizio di trascrizione ha restituito un risultato vuoto.")
    return {"text": text, "human_verified": False, "model": "gpt-4o-transcribe"}


def analyze_audio(job, item):
    executable = shutil.which("ffmpeg")
    if not executable:
        set_reading_state(item, "unreadable", "audio_decoder_unavailable")
        return
    try:
        with (
            authorized_local_file(job, item) as (path, sha),
            tempfile.TemporaryDirectory(prefix="edilcloud-audio-") as directory,
        ):
            command = [
                executable,
                "-v",
                "error",
                "-nostdin",
                "-i",
                str(path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-f",
                "segment",
                "-segment_time",
                "120",
                "-c:a",
                "pcm_s16le",
                str(Path(directory) / "part-%06d.wav"),
            ]
            result = subprocess.run(command, capture_output=True, timeout=600, check=False)
            if result.returncode:
                set_reading_state(item, "unreadable", "audio_decode_failed")
                return
            segments = sorted(Path(directory).glob("part-*.wav"))
            if not segments:
                set_reading_state(item, "unreadable", "audio_has_no_decodable_segments")
                return
            for index, segment in enumerate(segments):
                raw = segment.read_bytes()
                value = run_step(
                    job=job,
                    key=f"audio:{sha}:{index}",
                    kind="document_transcription",
                    data={"sha256": hashlib.sha256(raw).hexdigest(), "model": "gpt-4o-transcribe"},
                    execute=lambda step, data=raw: transcribe_segment(job, data, "segment.wav"),
                )
                add_parts(
                    item,
                    value["text"],
                    section=f"audio:{index}:start:{index * 120}",
                    method="machine_audio_transcription",
                )
            type(item).objects.filter(pk=item.pk).update(
                reading={"audio_segments": len(segments), "media_sha256": sha}
            )
    except (OSError, ValueError, subprocess.TimeoutExpired):
        set_reading_state(item, "unreadable", "audio_not_accessible_or_decodable")


def prepare_source(job, item):
    from .source_reading import extract_local_source

    item.refresh_from_db()
    if item.state in {"read", "excluded", "unreadable"}:
        return
    kind = item.payload.get("data", {}).get("media_kind")
    if kind == "image":
        analyze_image(job, item)
    elif kind == "audio":
        analyze_audio(job, item)
    else:
        extract_local_source(job, item)
