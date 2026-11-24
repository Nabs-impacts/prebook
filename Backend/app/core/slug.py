import re
import unicodedata

NON_ALPHANUMERIC_PATTERN = re.compile(r"[^a-z0-9]+")


def slugify(value: str, max_length: int = 200) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    slug = NON_ALPHANUMERIC_PATTERN.sub("-", ascii_value.lower()).strip("-")
    slug = slug[:max_length].strip("-")
    return slug or "ebook"
