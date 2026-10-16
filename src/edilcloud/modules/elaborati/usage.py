"""Document-wide provider consumption, independent of revision and job success."""

from django.db.models import Count, Q, Sum

from .models import DocumentAIUsage, DocumentAudit


def document_token_usage(document_id):
    usage = DocumentAIUsage.objects.filter(job__revision__elaborato_id=document_id)
    # Read supplementary metrics first: during a live call they can lag the
    # total, but cannot run ahead of a provider response committed afterwards.
    audits = list(
        DocumentAudit.objects.filter(
            revision__elaborato_id=document_id,
            action__in=("ai.response", "ai.stream_interrupted", "ai.transcription"),
        ).values("action", "detail")
    )
    totals = usage.aggregate(
        input_tokens=Sum("input_tokens"),
        output_tokens=Sum("output_tokens"),
        total_tokens=Sum("total_tokens"),
        requests_count=Count("pk"),
        detailed_requests=Count("pk", filter=~Q(stage="document_transcription")),
    )
    detailed_requests = totals.pop("detailed_requests")
    result = {key: value or 0 for key, value in totals.items()}
    result.update(reasoning_tokens=0, cached_input_tokens=0, audio_seconds=0.0)
    interrupted = set()
    unidentified = 0
    detail_counts = {"reasoning_tokens": 0, "cached_input_tokens": 0}
    for audit in audits:
        detail = audit["detail"]
        if audit["action"] == "ai.response":
            # Both are subsets of the recorded input/output, never added again.
            for key in detail_counts:
                if detail.get(key) is not None:
                    result[key] += max(0, int(detail[key]))
                    detail_counts[key] += 1
        elif audit["action"] == "ai.transcription":
            if (detail.get("usage") or {}).get("type") == "duration":
                result["audio_seconds"] += max(
                    0.0, float(detail["usage"].get("seconds", detail.get("duration_seconds")) or 0)
                )
        elif detail.get("usage_unknown"):
            if detail.get("response_id"):
                interrupted.add(detail["response_id"])
            else:
                unidentified += 1
    if interrupted:
        interrupted.difference_update(
            usage.filter(response_id__in=interrupted).values_list("response_id", flat=True)
        )
    result["unknown_requests"] = len(interrupted) + unidentified
    for key, recorded in detail_counts.items():
        # Older documents may lack this breakdown: unknown is not zero.
        if recorded < detailed_requests:
            result[key] = None
    result["audio_seconds"] = round(result["audio_seconds"], 2)
    return result
