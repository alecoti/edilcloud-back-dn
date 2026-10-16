"""Stable workflow failures shared by persistence and provider adapters."""


class IncompleteDocumentOutput(RuntimeError):
    """A terminal, billed response exceeded its output allowance.

    This is known output loss, not an ambiguous network result. Its original
    assignment must not be purchased again; a writer may create smaller child
    assignments while retaining the incomplete parent's usage and provenance.
    """
