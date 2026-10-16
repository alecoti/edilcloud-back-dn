"""Persist only provider-authored public summaries, never raw reasoning tokens."""

from copy import deepcopy
import logging
import time
import uuid

from django.utils import timezone
from django.db import DatabaseError

from .models import DocumentJob

logger = logging.getLogger(__name__)


class ReasoningProgress:
    def __init__(self, job, stage):
        self.job = job
        job.refresh_from_db(fields=("thinking",))
        self.entries = deepcopy(job.thinking)
        self.entry = {"id": str(uuid.uuid4()), "stage": stage, "status": "in_progress", "parts": []}
        self.entries.append(self.entry)
        self.parts = {}
        self.last_write = 0.0
        self.flush(force=True)

    def summary(self, output_index, summary_index, text, *, append=False, complete=False):
        key = (output_index, summary_index)
        previous = self.parts.get(key, {"text": "", "complete": False})
        self.parts[key] = {
            "text": previous["text"] + text if append else text,
            "complete": complete or previous["complete"],
        }
        self.entry["parts"] = [self.parts[key] for key in sorted(self.parts)]
        self.flush(force=complete)

    def finish(self, status):
        self.entry["status"] = (
            "completed"
            if status == "completed" and any(p["text"] for p in self.entry["parts"])
            else "unavailable"
            if status == "completed"
            else "interrupted"
        )
        self.flush(force=True)

    def flush(self, *, force=False):
        now = time.monotonic()
        if not force and now - self.last_write < 1:
            return
        try:
            DocumentJob.objects.filter(
                pk=self.job.pk, state="running", lease_token=self.job.lease_token
            ).update(
                thinking=self.entries,
                updated_at=timezone.now(),
            )
        except DatabaseError:
            # Progress is optional telemetry, never a reason to discard a paid
            # response or skip its usage ledger. Do not log provider text.
            logger.warning("Reasoning summary progress unavailable job_id=%s", self.job.pk)
        self.last_write = now
