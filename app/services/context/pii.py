"""Strip email addresses and phone numbers from a typed question before it is sent or logged."""
from __future__ import annotations

import re

EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(\.[\w-]+)+\b")
PHONE = re.compile(r"(?<![\w-])\+?\d[\d ()-]{7,}\d(?![\w-])")


def strip_contact_details(text: str) -> tuple[str, int]:
    count = len(EMAIL.findall(text)) + len(PHONE.findall(text))
    text = EMAIL.sub("[email removed]", text)
    text = PHONE.sub("[number removed]", text)
    return text, count


def has_contact_details(text: str) -> bool:
    return bool(EMAIL.search(text) or PHONE.search(text))
