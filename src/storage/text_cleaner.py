import re
from cleantext import clean

_ZERO_WIDTH_RE = re.compile(r'[\u2000-\u200D\uFEFF]')


def clean_text(text: str) -> str:
    text = clean(text,
        fix_unicode=True,
        no_line_breaks=False,
        to_ascii=False,
    )
    text = _ZERO_WIDTH_RE.sub("", text)
    return text


def clean_chunks(chunks: list[dict], text_key: str = "text") -> list[dict]:
    for chunk in chunks:
        chunk[text_key] = clean_text(chunk[text_key])
    return chunks
