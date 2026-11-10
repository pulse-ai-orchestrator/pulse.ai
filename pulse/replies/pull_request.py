"""The `pulse:pull-request` block: the markdown the agent filled for the request body.

The engine does not read the headings. A missing or malformed block is an empty
string, and the caller opens the request from the template instead.
"""

from __future__ import annotations

from pulse.domain.outcome import last_fenced_block

PULL_REQUEST_TAG = "pull-request"
BODY_MAX_CHARS = 20_000


def parse_pull_request(text: str) -> str:
    """Markdown inside the last `pulse:pull-request` block, or empty when it cannot be used.

    The body may not contain another fence: a fence quoted from a file must not
    swallow the agent's block, and a block past the size cap is treated as absent.
    """
    body = last_fenced_block(text or "", PULL_REQUEST_TAG)
    if body is None:
        return ""
    cleaned = body.strip()
    if not cleaned or len(cleaned) > BODY_MAX_CHARS:
        return ""
    return cleaned
