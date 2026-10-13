"""Authenticated file delivery with bounded single-range streaming and validators.

Call only after authorization. Conditional requests must never bypass access checks.
"""
import os
import re

from django.http import FileResponse, HttpResponse, StreamingHttpResponse
from django.utils.http import http_date, parse_http_date_safe


def inline_file_response(file_field, *, filename, content_type, request=None):
    file_field.open("rb")
    try:
        stat = os.fstat(file_field.fileno())
        size, modified = stat.st_size, stat.st_mtime
        etag = f'"{stat.st_mtime_ns:x}-{size:x}"'
    except (OSError, AttributeError):
        size, modified, etag = file_field.size, None, None
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=0, must-revalidate",
               "Vary": "Authorization, Cookie"}
    if etag:
        headers["ETag"] = etag
    if modified is not None:
        headers["Last-Modified"] = http_date(modified)
    incoming = request.headers if request is not None else {}
    none_match = incoming.get("If-None-Match")
    since = parse_http_date_safe(incoming.get("If-Modified-Since", ""))
    unchanged = (etag and none_match and any(value.strip().removeprefix("W/") in {etag, "*"} for value in none_match.split(",")))
    if unchanged or (not none_match and since is not None and modified is not None and int(modified) <= since):
        file_field.close()
        return HttpResponse(status=304, headers=headers)

    raw_range = incoming.get("Range", "")
    if_range = incoming.get("If-Range")
    if if_range:
        date = parse_http_date_safe(if_range)
        if if_range != etag and not (date is not None and modified is not None and int(modified) <= date):
            raw_range = ""
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", raw_range.strip())
    if match and any(match.groups()):
        first, last = match.groups()
        if first:
            start = int(first)
            end = min(int(last), size - 1) if last else size - 1
        else:
            start, end = max(0, size - int(last)), size - 1
        if size == 0 or start > end or start >= size or (not first and int(last) == 0):
            file_field.close()
            return HttpResponse(status=416, headers={**headers, "Content-Range": f"bytes */{size}"})
        length = end - start + 1
        file_field.seek(start)

        def chunks():
            remaining = length
            try:
                while remaining:
                    data = file_field.read(min(65536, remaining))
                    if not data:
                        break
                    remaining -= len(data)
                    yield data
            finally:
                file_field.close()

        response = StreamingHttpResponse(chunks(), status=206, content_type=content_type,
            headers={**headers, "Content-Length": str(length), "Content-Range": f"bytes {start}-{end}/{size}"})
        response._resource_closers.append(file_field.close)
        from django.utils.http import content_disposition_header
        disposition = content_disposition_header(False, filename)
        if disposition:
            response["Content-Disposition"] = disposition
        return response
    response = FileResponse(file_field, content_type=content_type, filename=filename or "", as_attachment=False, headers=headers)
    return response
