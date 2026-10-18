"""Convert decoded email alternatives into safe, readable plain text."""

import re
from html.parser import HTMLParser
from unicodedata import category
from urllib.parse import parse_qsl, urlparse


_BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "div", "footer", "h1", "h2", "h3",
    "h4", "h5", "h6", "header", "main", "nav", "p", "pre", "section", "table", "tr",
}
_PARAGRAPH_TAGS = {
    "article", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6", "p", "section",
}
_IGNORED_TAGS = {"head", "script", "style", "template"}
_TRACKING_QUERY_KEYS = {
    "clickid", "mc_cid", "mc_eid", "redirect", "redirect_url", "tracking_id", "trk",
}
_INVISIBLE_CHARACTERS = str.maketrans("", "", (
    "\u00ad\u034f\u061c\u115f\u1160\u17b4\u17b5\u180e"
    "\u200b\u200c\u200d\u200e\u200f\u202a\u202b\u202c\u202d\u202e"
    "\u2060\u2061\u2062\u2063\u2064\u2066\u2067\u2068\u2069\ufeff"
))


def _is_tracking_url(value: str) -> bool:
    if len(value) > 140:
        return True
    query_keys = {key.lower() for key, _ in parse_qsl(urlparse(value).query)}
    return any(key.startswith("utm_") or key in _TRACKING_QUERY_KEYS for key in query_keys)


class _ReadableHTMLParser(HTMLParser):
    def __init__(self, *, compact_tracking_links: bool) -> None:
        super().__init__(convert_charrefs=True)
        self.compact_tracking_links = compact_tracking_links
        self.parts: list[str] = []
        self.ignored_depth = 0
        self.links: list[tuple[str, int]] = []

    def _newlines(self, count: int = 1) -> None:
        if not self.parts:
            return
        recent = "".join(self.parts[-3:])
        existing = len(recent) - len(recent.rstrip("\n"))
        if existing < count:
            self.parts.append("\n" * (count - existing))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self.ignored_depth:
            if tag in _IGNORED_TAGS:
                self.ignored_depth += 1
            return
        if tag in _IGNORED_TAGS:
            self.ignored_depth = 1
            return
        if tag in _PARAGRAPH_TAGS:
            self._newlines(2)
        elif tag in _BLOCK_TAGS or tag == "br":
            self._newlines()
        if tag == "li":
            self._newlines()
            self.parts.append("• ")
        elif tag in {"td", "th"} and self.parts and not self.parts[-1].endswith("\n"):
            self.parts.append(" | ")
        elif tag == "a":
            href = dict(attrs).get("href") or ""
            self.links.append((href.strip(), len(self.parts)))
        elif tag == "img":
            alt = (dict(attrs).get("alt") or "").strip()
            if alt:
                self.parts.append(alt)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.ignored_depth:
            if tag in _IGNORED_TAGS:
                self.ignored_depth -= 1
            return
        if tag == "a" and self.links:
            href, start = self.links.pop()
            parsed = urlparse(href)
            if parsed.scheme in {"http", "https", "mailto"}:
                target = href.removeprefix("mailto:")
                label = "".join(self.parts[start:]).strip()
                if not label:
                    self.parts.append(target)
                elif target not in label and not (
                    self.compact_tracking_links and _is_tracking_url(href)
                ):
                    self.parts.append(f" ({target})")
        if tag in _PARAGRAPH_TAGS:
            self._newlines(2)
        elif tag in _BLOCK_TAGS or tag in {"li", "ul", "ol"}:
            self._newlines()

    def handle_data(self, data: str) -> None:
        if not self.ignored_depth:
            self.parts.append(data)


def _normalize_text(value: str, *, remove_invisible: bool) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    if remove_invisible:
        value = value.translate(_INVISIBLE_CHARACTERS)
    lines = [
        re.sub(r"[ \t\f\v]+", " ", "".join(
            character
            for character in line.replace("\xa0", " ")
            if not remove_invisible
            or character == "\t"
            or not category(character).startswith("C")
        )).strip()
        for line in value.split("\n")
    ]
    output: list[str] = []
    for line in lines:
        if line or (output and output[-1]):
            output.append(line)
    return "\n".join(output).strip()


def _convert_html(value: str, *, compact_tracking_links: bool, remove_invisible: bool) -> str:
    parser = _ReadableHTMLParser(compact_tracking_links=compact_tracking_links)
    parser.feed(value)
    parser.close()
    return _normalize_text("".join(parser.parts), remove_invisible=remove_invisible)


def html_to_readable_text(value: str) -> str:
    """Return visible HTML content as plain text without rendering active markup."""
    return _convert_html(value, compact_tracking_links=True, remove_invisible=True)


def legacy_html_to_readable_text(value: str) -> str:
    """Reproduce the previous output so an exact, safe repair can recognize it."""
    return _convert_html(value, compact_tracking_links=False, remove_invisible=False)


def readable_email_body(body_text: str, body_html: str | None) -> str:
    """Prefer the decoded text/plain MIME part, then convert the HTML alternative."""
    plain_text = _normalize_text(body_text, remove_invisible=True)
    if plain_text:
        return plain_text
    return html_to_readable_text(body_html) if body_html else ""
