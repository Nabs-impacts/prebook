import html
import re

TAG_PATTERN = re.compile(r"<[^>]*>")
CONTROL_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MULTI_NEWLINE_PATTERN = re.compile(r"\n{3,}")
MULTI_SPACE_PATTERN = re.compile(r"[ \t]{2,}")


def sanitize_text(value: str, max_length: int, *, collapse_whitespace: bool = False) -> str:
    cleaned = value
    previous = ""
    while cleaned != previous:
        previous = cleaned
        cleaned = TAG_PATTERN.sub("", cleaned)
    cleaned = CONTROL_PATTERN.sub("", cleaned)
    cleaned = html.escape(cleaned, quote=False)
    if collapse_whitespace:
        cleaned = " ".join(cleaned.split())
    else:
        cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
        cleaned = MULTI_NEWLINE_PATTERN.sub("\n\n", cleaned)
        cleaned = MULTI_SPACE_PATTERN.sub(" ", cleaned)
        cleaned = "\n".join(line.strip() for line in cleaned.split("\n"))
        cleaned = cleaned.strip()
    return cleaned[:max_length].strip()
