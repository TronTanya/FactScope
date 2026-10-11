"""Безопасная загрузка и извлечение текста публичных веб-страниц."""

from __future__ import annotations

import ipaddress
import re
import socket
import ssl
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_TEXT_CHARS = 50_000
MAX_UPLOAD_BYTES = 1 * 1024 * 1024
CONNECT_TIMEOUT = 8
READ_TIMEOUT = 12
MAX_REDIRECTS = 3
USER_AGENT = "FactScope/1.0 (educational verification tool; +local)"

BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "metadata",
}


class SourceLoadError(Exception):
    """Ошибка загрузки или разбора источника."""


@dataclass
class ExtractedSource:
    """Результат извлечения данных из источника."""

    title: str = ""
    author: str = ""
    publication_date: str = ""
    canonical_url: str = ""
    publisher: str = ""
    main_text: str = ""
    reference_links: list[str] = field(default_factory=list)
    retrieval_time: str = ""
    final_url: str = ""
    input_method: str = "manual"
    warnings: list[str] = field(default_factory=list)

    def display(self, value: str) -> str:
        return value.strip() if value and value.strip() else "Не найдено"


def truncate_text(text: str, limit: int = MAX_TEXT_CHARS) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def read_uploaded_text(raw: bytes, filename: str = "") -> str:
    if len(raw) > MAX_UPLOAD_BYTES:
        raise SourceLoadError("Размер файла превышает 1 МБ.")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceLoadError("Файл должен быть в кодировке UTF-8.") from exc
    text = text.strip()
    if not text:
        raise SourceLoadError("Файл пуст.")
    text, truncated = truncate_text(text)
    if truncated:
        text += "\n\n[Текст обрезан до 50 000 символов]"
    return text


def _normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        raise SourceLoadError("Укажите URL.")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise SourceLoadError("Допускаются только схемы HTTP и HTTPS.")
    if parsed.username is not None or parsed.password is not None:
        raise SourceLoadError("URL не должен содержать учётные данные.")
    if not parsed.hostname:
        raise SourceLoadError("В URL отсутствует имя хоста.")
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path or "/",
            "",
            parsed.query,
            "",
        )
    )


def _hostname_blocked(hostname: str) -> bool:
    host = hostname.lower().rstrip(".")
    if host in BLOCKED_HOSTNAMES:
        return True
    if host.endswith(".localhost") or host.endswith(".local"):
        return True
    return False


def _ip_is_public(ip: ipaddress._BaseAddress) -> bool:
    if ip.version == 4 and ip == ipaddress.IPv4Address("169.254.169.254"):
        return False
    blocked = (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        or getattr(ip, "is_site_local", False)
    )
    return not blocked


def resolve_public_addresses(hostname: str, port: int) -> list[str]:
    if _hostname_blocked(hostname):
        raise SourceLoadError("Адрес относится к локальной или служебной сети.")

    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None

    if literal is not None:
        if not _ip_is_public(literal):
            raise SourceLoadError("Запрещены частные, локальные и служебные адреса.")
        return [str(literal)]

    try:
        infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise SourceLoadError("Не удалось разрешить имя хоста.") from exc

    addresses: list[str] = []
    for info in infos:
        ip_str = info[4][0]
        try:
            ip_obj = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if not _ip_is_public(ip_obj):
            raise SourceLoadError(
                "Имя хоста указывает на частный, локальный или служебный адрес."
            )
        if ip_str not in addresses:
            addresses.append(ip_str)

    if not addresses:
        raise SourceLoadError("Не найден публичный IP-адрес для хоста.")
    return addresses


def validate_url_destination(url: str) -> tuple[str, list[str]]:
    """Проверяет URL и возвращает нормализованный URL и публичные IP."""
    normalized = _normalize_url(url)
    parsed = urlparse(normalized)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    addresses = resolve_public_addresses(parsed.hostname or "", port)
    return normalized, addresses


def _decode_body(body: bytes, content_type: str) -> str:
    charset = "utf-8"
    match = re.search(r"charset=([\w\-]+)", content_type or "", flags=re.I)
    if match:
        charset = match.group(1).strip().strip("\"'")
    for encoding in (charset, "utf-8", "cp1251", "latin-1"):
        try:
            return body.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    raise SourceLoadError("Не удалось декодировать содержимое страницы.")


def _fetch_once(url: str, ip: str) -> tuple[int, dict[str, str], bytes, str]:
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"

    context = ssl.create_default_context()
    sock = socket.create_connection((ip, port), timeout=CONNECT_TIMEOUT)
    try:
        if parsed.scheme == "https":
            sock = context.wrap_socket(sock, server_hostname=hostname)
        sock.settimeout(READ_TIMEOUT)

        request_lines = [
            f"GET {path} HTTP/1.1",
            f"Host: {hostname}",
            f"User-Agent: {USER_AGENT}",
            "Accept: text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1",
            "Accept-Language: ru,en;q=0.8",
            "Connection: close",
            "",
            "",
        ]
        sock.sendall("\r\n".join(request_lines).encode("ascii", errors="ignore"))

        raw = b""
        while True:
            chunk = sock.recv(64 * 1024)
            if not chunk:
                break
            raw += chunk
            if len(raw) > MAX_RESPONSE_BYTES + 64 * 1024:
                raise SourceLoadError("Размер ответа превышает 2 МБ.")
    finally:
        try:
            sock.close()
        except OSError:
            pass

    if b"\r\n\r\n" not in raw:
        raise SourceLoadError("Некорректный HTTP-ответ.")
    header_blob, body = raw.split(b"\r\n\r\n", 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise SourceLoadError("Размер ответа превышает 2 МБ.")

    header_text = header_blob.decode("iso-8859-1", errors="replace")
    lines = header_text.split("\r\n")
    status_line = lines[0] if lines else ""
    match = re.match(r"HTTP/\d(?:\.\d)?\s+(\d+)", status_line)
    if not match:
        raise SourceLoadError("Не удалось разобрать статус HTTP.")
    status = int(match.group(1))

    response_headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        response_headers[key.strip().lower()] = value.strip()

    # Простейшая поддержка chunked (без расширения).
    if response_headers.get("transfer-encoding", "").lower() == "chunked":
        body = _decode_chunked(body)

    return status, response_headers, body, url


def _decode_chunked(body: bytes) -> bytes:
    result = bytearray()
    pos = 0
    while pos < len(body):
        idx = body.find(b"\r\n", pos)
        if idx < 0:
            break
        size_text = body[pos:idx].decode("ascii", errors="ignore").split(";")[0]
        try:
            size = int(size_text, 16)
        except ValueError:
            break
        pos = idx + 2
        if size == 0:
            break
        result.extend(body[pos : pos + size])
        pos += size + 2
    return bytes(result)


def fetch_public_url(url: str) -> ExtractedSource:
    """Загружает публичную страницу с проверкой каждого адреса назначения."""
    current, addresses = validate_url_destination(url)
    redirects = 0

    while True:
        last_error: Optional[Exception] = None
        status = 0
        headers: dict[str, str] = {}
        body = b""
        used_url = current

        for ip in addresses:
            try:
                status, headers, body, used_url = _fetch_once(current, ip)
                last_error = None
                break
            except (TimeoutError, socket.timeout, ConnectionError, OSError, ssl.SSLError) as exc:
                last_error = exc
                continue
            except SourceLoadError:
                raise

        if last_error is not None:
            raise SourceLoadError(
                "Не удалось установить безопасное соединение с сервером."
            ) from last_error

        if status in {301, 302, 303, 307, 308}:
            location = headers.get("location")
            if not location:
                raise SourceLoadError("Перенаправление без заголовка Location.")
            redirects += 1
            if redirects > MAX_REDIRECTS:
                raise SourceLoadError("Превышено число перенаправлений (максимум 3).")
            next_url = urljoin(current, location)
            current, addresses = validate_url_destination(next_url)
            continue

        if status >= 400:
            raise SourceLoadError(f"Сервер вернул код ошибки HTTP {status}.")

        content_type = headers.get("content-type", "")
        if content_type and not any(
            part in content_type.lower()
            for part in ("text/html", "application/xhtml", "text/plain")
        ):
            raise SourceLoadError(
                "Неподдерживаемый тип содержимого. Ожидается HTML или текст."
            )

        html = _decode_body(body, content_type)
        extracted = extract_from_html(html, base_url=used_url)
        extracted.retrieval_time = datetime.now(timezone.utc).isoformat(timespec="seconds")
        extracted.final_url = used_url
        extracted.input_method = "url"
        if not extracted.main_text.strip():
            extracted.warnings.append("Основной текст не удалось извлечь.")
        return extracted


def _meta_content(soup: BeautifulSoup, attrs: dict) -> str:
    tag = soup.find("meta", attrs=attrs)
    if tag and tag.get("content"):
        return str(tag["content"]).strip()
    return ""


def extract_from_html(html: str, base_url: str = "") -> ExtractedSource:
    """Извлекает метаданные и основной текст из HTML (локально)."""
    if not html or not html.strip():
        result = ExtractedSource()
        result.warnings.append("Пустой HTML.")
        return result

    soup = BeautifulSoup(html, "lxml")

    for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
        tag.decompose()

    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    if not title:
        title = _meta_content(soup, {"property": "og:title"}) or _meta_content(
            soup, {"name": "title"}
        )

    author = (
        _meta_content(soup, {"name": "author"})
        or _meta_content(soup, {"property": "article:author"})
        or _meta_content(soup, {"name": "citation_author"})
    )
    if not author:
        author_tag = soup.find(attrs={"rel": "author"}) or soup.find(
            class_=re.compile(r"author", re.I)
        )
        if author_tag:
            author = author_tag.get_text(" ", strip=True)

    publication_date = (
        _meta_content(soup, {"property": "article:published_time"})
        or _meta_content(soup, {"name": "publish-date"})
        or _meta_content(soup, {"name": "date"})
        or _meta_content(soup, {"name": "citation_publication_date"})
        or _meta_content(soup, {"itemprop": "datePublished"})
    )
    time_tag = soup.find("time")
    if not publication_date and time_tag:
        publication_date = (time_tag.get("datetime") or time_tag.get_text(" ", strip=True)).strip()

    canonical = ""
    link_canonical = soup.find("link", rel=lambda v: v and "canonical" in v)
    if link_canonical and link_canonical.get("href"):
        canonical = urljoin(base_url, str(link_canonical["href"]))
    if not canonical:
        canonical = _meta_content(soup, {"property": "og:url"})

    publisher = (
        _meta_content(soup, {"property": "og:site_name"})
        or _meta_content(soup, {"name": "publisher"})
        or _meta_content(soup, {"name": "application-name"})
    )

    article = soup.find("article") or soup.find("main") or soup.body or soup
    paragraphs = [
        p.get_text(" ", strip=True)
        for p in article.find_all(["p", "li", "h1", "h2", "h3"])
        if p.get_text(strip=True)
    ]
    main_text = "\n\n".join(paragraphs).strip()
    if not main_text:
        main_text = article.get_text("\n", strip=True)

    main_text, truncated = truncate_text(main_text)
    warnings: list[str] = []
    if truncated:
        warnings.append("Текст обрезан до 50 000 символов.")

    reference_links: list[str] = []
    seen: set[str] = set()
    for a in article.find_all("a", href=True):
        href = str(a["href"]).strip()
        if not href or href.startswith("#") or href.lower().startswith("javascript:"):
            continue
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"}:
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        reference_links.append(absolute)
        if len(reference_links) >= 50:
            break

    return ExtractedSource(
        title=title,
        author=author,
        publication_date=publication_date,
        canonical_url=canonical,
        publisher=publisher,
        main_text=main_text,
        reference_links=reference_links,
        warnings=warnings,
        input_method="html",
    )


def source_from_manual_text(
    text: str,
    *,
    title: str = "",
    author: str = "",
    publication_date: str = "",
    canonical_url: str = "",
    publisher: str = "",
    url: str = "",
) -> ExtractedSource:
    cleaned = (text or "").strip()
    if not cleaned:
        raise SourceLoadError("Текст источника пуст.")
    cleaned, truncated = truncate_text(cleaned)
    warnings = ["Текст обрезан до 50 000 символов."] if truncated else []
    return ExtractedSource(
        title=title.strip(),
        author=author.strip(),
        publication_date=publication_date.strip(),
        canonical_url=canonical_url.strip() or url.strip(),
        publisher=publisher.strip(),
        main_text=cleaned,
        reference_links=[],
        retrieval_time="",
        final_url=url.strip(),
        input_method="manual",
        warnings=warnings,
    )

