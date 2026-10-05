"""Extract brand signals from a company website (URL or uploaded HTML).

Only lightweight, deterministic parsing happens here (colors, fonts, logo, texts);
the AI turns the compact result into a brand style guide (see agents/brand.py).
"""
from __future__ import annotations

import ipaddress
import re
import socket
from collections import Counter
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

MAX_HTML_BYTES = 2_000_000
MAX_CSS_FILES = 4
MAX_TEXT_CHARS = 6000

_HEX = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
_RGB = re.compile(r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})")
_FONT = re.compile(r"font-family\s*:\s*([^;}{]+)", re.I)
_GENERIC_FONTS = {"sans-serif", "serif", "monospace", "inherit", "initial", "system-ui", "cursive", "-apple-system",
                  "blinkmacsystemfont", "arial", "helvetica", "helvetica neue", "segoe ui", "roboto", "var(--font)"}


class BrandImportError(Exception):
    pass


@dataclass
class SiteSignals:
    url: str | None = None
    title: str | None = None
    description: str | None = None
    theme_color: str | None = None
    colors: list[str] = field(default_factory=list)
    fonts: list[str] = field(default_factory=list)
    logo_url: str | None = None
    og_image: str | None = None
    headings: list[str] = field(default_factory=list)
    text: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _norm_hex(value: str) -> str:
    value = value.lower()
    if len(value) == 4:
        value = "#" + "".join(ch * 2 for ch in value[1:])
    return value


def _is_neutral(hex_color: str) -> bool:
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return max(r, g, b) - min(r, g, b) < 18 and (max(r, g, b) > 235 or max(r, g, b) < 40)


def extract_colors(css_text: str, limit: int = 6) -> list[str]:
    counter: Counter[str] = Counter()
    for match in _HEX.findall(css_text):
        counter[_norm_hex(match)] += 1
    for r, g, b in _RGB.findall(css_text):
        if max(int(r), int(g), int(b)) <= 255:
            counter[f"#{int(r):02x}{int(g):02x}{int(b):02x}"] += 1
    brand = [c for c, _ in counter.most_common() if not _is_neutral(c)]
    neutrals = [c for c, _ in counter.most_common() if _is_neutral(c)]
    return (brand + neutrals[:1])[:limit]


def extract_fonts(css_text: str, limit: int = 4) -> list[str]:
    counter: Counter[str] = Counter()
    for decl in _FONT.findall(css_text):
        first = decl.split(",")[0].strip().strip("'\"").strip()
        if first and first.lower() not in _GENERIC_FONTS and len(first) < 40:
            counter[first] += 1
    return [f for f, _ in counter.most_common(limit)]


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.meta: dict[str, str] = {}
        self.styles: list[str] = []
        self.css_links: list[str] = []
        self.icons: list[str] = []
        self.logo_imgs: list[str] = []
        self.headings: list[str] = []
        self.text_parts: list[str] = []
        self._stack: list[str] = []
        self._in_style = False
        self._skip = 0
        self._heading: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if a.get("style"):
            self.styles.append(a["style"])
        if tag == "meta":
            key = (a.get("name") or a.get("property") or "").lower()
            if key:
                self.meta[key] = a.get("content", "")
        elif tag == "link":
            rel = a.get("rel", "").lower()
            if "stylesheet" in rel and a.get("href"):
                self.css_links.append(a["href"])
            if "icon" in rel and a.get("href"):
                self.icons.append(a["href"])
        elif tag == "img":
            blob = " ".join([a.get("src", ""), a.get("alt", ""), a.get("class", ""), a.get("id", "")]).lower()
            if "logo" in blob and a.get("src"):
                self.logo_imgs.append(a["src"])
        elif tag == "style":
            self._in_style = True
        elif tag in ("script", "noscript", "svg", "template"):
            self._skip += 1
        elif tag in ("h1", "h2", "h3"):
            self._heading = []
        elif tag == "title":
            self._stack.append("title")

    def handle_endtag(self, tag: str) -> None:
        if tag == "style":
            self._in_style = False
        elif tag in ("script", "noscript", "svg", "template") and self._skip:
            self._skip -= 1
        elif tag in ("h1", "h2", "h3") and self._heading is not None:
            text = " ".join("".join(self._heading).split())
            if text and len(self.headings) < 25:
                self.headings.append(text[:150])
            self._heading = None
        elif tag == "title" and self._stack:
            self._stack.pop()

    def handle_data(self, data: str) -> None:
        if self._in_style:
            self.styles.append(data)
            return
        if self._skip:
            return
        if self._stack and self._stack[-1] == "title":
            self.title += data
            return
        if self._heading is not None:
            self._heading.append(data)
        cleaned = " ".join(data.split())
        if len(cleaned) > 2:
            self.text_parts.append(cleaned)


def parse_html(html: str, base_url: str | None = None, extra_css: str = "") -> tuple[SiteSignals, list[str]]:
    parser = _Parser()
    parser.feed(html)
    css = "\n".join(parser.styles) + "\n" + extra_css
    meta = parser.meta

    def absolute(value: str | None) -> str | None:
        if not value:
            return None
        return urljoin(base_url, value) if base_url else value

    theme = meta.get("theme-color")
    colors = extract_colors(css)
    if theme and _HEX.fullmatch(theme.strip()):
        theme = _norm_hex(theme.strip())
        colors = [theme] + [c for c in colors if c != theme]
    text = " ".join(parser.text_parts)
    return SiteSignals(
        url=base_url,
        title=" ".join(parser.title.split())[:200] or meta.get("og:title"),
        description=(meta.get("description") or meta.get("og:description") or "")[:500] or None,
        theme_color=theme,
        colors=colors[:6],
        fonts=extract_fonts(css),
        logo_url=absolute(parser.logo_imgs[0] if parser.logo_imgs else (parser.icons[-1] if parser.icons else None)),
        og_image=absolute(meta.get("og:image")),
        headings=parser.headings,
        text=text[:MAX_TEXT_CHARS],
    ), parser.css_links


def _assert_public_host(url: str) -> None:
    """Block requests to localhost / private networks (SSRF protection)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise BrandImportError("Нужна ссылка вида https://сайт.ру")
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise BrandImportError(f"Сайт {parsed.hostname} не найден") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise BrandImportError("Ссылка ведёт во внутреннюю сеть — такие адреса запрещены")


def _get(client: httpx.Client, url: str, limit: int) -> httpx.Response:
    _assert_public_host(url)
    response = client.get(url)
    for _ in range(5):  # follow redirects manually to re-check every hop
        if response.status_code not in (301, 302, 303, 307, 308) or "location" not in response.headers:
            break
        url = urljoin(url, response.headers["location"])
        _assert_public_host(url)
        response = client.get(url)
    if len(response.content) > limit:
        raise BrandImportError("Страница слишком большая")
    return response


def fetch_site(url: str, *, transport: httpx.BaseTransport | None = None) -> SiteSignals:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    headers = {"User-Agent": "Mozilla/5.0 (compatible; VKregerBrandBot/1.0)", "Accept-Language": "ru,en;q=0.8"}
    try:
        with httpx.Client(timeout=15, follow_redirects=False, headers=headers, transport=transport) as client:
            response = _get(client, url, MAX_HTML_BYTES)
            if response.status_code >= 400:
                raise BrandImportError(f"Сайт ответил ошибкой HTTP {response.status_code}")
            final_url = str(response.url)
            html = response.text
            _, css_links = parse_html(html, final_url)
            css_parts = []
            for href in css_links[:MAX_CSS_FILES]:
                try:
                    css_resp = _get(client, urljoin(final_url, href), 800_000)
                    if css_resp.status_code < 400:
                        css_parts.append(css_resp.text)
                except (httpx.HTTPError, BrandImportError):
                    continue
    except httpx.HTTPError as exc:
        raise BrandImportError(f"Не удалось открыть сайт: {type(exc).__name__}") from exc
    signals, _ = parse_html(html, final_url, "\n".join(css_parts))
    return signals


def signals_from_upload(content: bytes) -> SiteSignals:
    if len(content) > MAX_HTML_BYTES:
        raise BrandImportError("Файл слишком большой (максимум 2 МБ)")
    for encoding in ("utf-8", "cp1251", "latin-1"):
        try:
            html = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    signals, _ = parse_html(html)
    if not (signals.text or signals.colors):
        raise BrandImportError("В файле не нашлось текста или стилей — это точно HTML-страница?")
    return signals
