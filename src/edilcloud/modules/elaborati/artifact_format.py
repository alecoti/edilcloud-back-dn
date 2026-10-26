"""Bump when rendering changes invalidate unconfirmed draft/publication PDFs.

Frozen publications keep their stored bytes and PDF hash across format changes.
The value is shared with Rust's rendering::FORMAT_VERSION.
"""

PDF_FORMAT_VERSION = "elaborati-pdf-v2-chronology"
