"""Карточка ссылки (ТЗ): заголовок и картинка Open Graph, чтобы показать ссылку без встраивания.

Сервер ходит по адресу, который ввёл человек, поэтому главное здесь — не превратить его в прокси во
внутреннюю сеть (SSRF). Что для этого сделано:

* только http/https, без логина и пароля в адресе, без пробелов и управляющих символов;
* имя хоста разрешается в адреса, и ВСЕ они должны быть публичными (не loopback, не частные, не
  link-local, не метаданные облака, не IPv4-в-IPv6);
* соединение идёт на уже проверенный IP, а не на имя: подменить ответ DNS между проверкой и
  соединением нельзя (при этом SNI и заголовок Host остаются настоящими);
* каждое перенаправление проверяется заново, их не больше трёх;
* ограничены время и размер ответа, а картинка перекодируется Pillow, а не отдаётся как есть.

Только стандартная библиотека: чем меньше зависимостей у кода, что ходит в чужую сеть, тем лучше.
"""

import http.client
import ipaddress
import socket
import ssl
import urllib.parse
from dataclasses import dataclass
from html.parser import HTMLParser

from app.media import MediaError

MAX_URL_LEN = 2000
MAX_REDIRECTS = 3
TIMEOUT_SEC = 6.0
MAX_HTML_BYTES = 512 * 1024
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_TITLE_LEN = 500
USER_AGENT = "Mozilla/5.0 (compatible; BrassSpyglass/1.0; link preview)"
REDIRECTS = {301, 302, 303, 307, 308}
INTERNAL = "Адрес ведёт во внутреннюю сеть, такие ссылки не открываются"


class LinkError(MediaError):
    """Ссылка не принята или не открылась. Текст показывается человеку."""


class UnsafeUrl(LinkError):
    pass


class FetchError(LinkError):
    pass


def parse_url(url: str) -> urllib.parse.SplitResult:
    """Проверяет адрес по форме, без обращения в сеть."""
    url = url.strip()
    if not url or len(url) > MAX_URL_LEN:
        raise UnsafeUrl("Некорректный адрес ссылки")
    if any(ch.isspace() or ord(ch) < 32 for ch in url):
        raise UnsafeUrl("В адресе не должно быть пробелов")
    try:
        parts = urllib.parse.urlsplit(url)
        _ = parts.port  # неверный порт — ValueError
    except ValueError as exc:
        raise UnsafeUrl("Некорректный адрес ссылки") from exc
    if parts.scheme not in ("http", "https"):
        raise UnsafeUrl("Ссылка должна начинаться с http:// или https://")
    if not parts.hostname:
        raise UnsafeUrl("В ссылке нет адреса сайта")
    if parts.username or parts.password:
        raise UnsafeUrl("Ссылки с логином и паролем не принимаются")
    host = parts.hostname.lower()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise UnsafeUrl(INTERNAL)
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        return parts  # имя сайта; публичность его адресов проверит resolve_public перед соединением
    if not is_public_ip(str(literal)):
        raise UnsafeUrl(INTERNAL)
    return parts


def is_public_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    # is_global пропускает, например, многоадресные адреса; нам нужны только обычные публичные хосты
    return ip.is_global and not (ip.is_multicast or ip.is_reserved or ip.is_unspecified)


def resolve_public(host: str, port: int) -> str:
    """IP, на который можно идти. Если хоть один адрес хоста не публичный — отказ."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise FetchError("Не удалось найти такой сайт") from exc
    addresses = sorted({str(info[4][0]) for info in infos}, key=lambda a: (":" in a, a))
    if not addresses or not all(is_public_ip(a) for a in addresses):
        raise UnsafeUrl(INTERNAL)
    return addresses[0]


def _connect(scheme: str, host: str, ip: str, port: int) -> http.client.HTTPConnection:
    """Соединение с проверенным IP; имя хоста остаётся для SNI, проверки сертификата и Host."""
    if scheme == "https":
        context = ssl.create_default_context()

        class Pinned(http.client.HTTPSConnection):
            def connect(self) -> None:
                sock = socket.create_connection((ip, self.port), self.timeout)
                self.sock = context.wrap_socket(sock, server_hostname=self.host)

        return Pinned(host, port, timeout=TIMEOUT_SEC)

    class PinnedPlain(http.client.HTTPConnection):
        def connect(self) -> None:
            self.sock = socket.create_connection((ip, self.port), self.timeout)

    return PinnedPlain(host, port, timeout=TIMEOUT_SEC)


@dataclass(frozen=True, slots=True)
class Fetched:
    url: str  # адрес после перенаправлений
    content_type: str
    body: bytes
    charset: str | None


def fetch(url: str, *, max_bytes: int, accept: str, must_fit: bool = False) -> Fetched:
    """GET с проверкой каждого шага. `must_fit`: превышение размера — ошибка, иначе берём начало."""
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        parts = parse_url(current)
        host = parts.hostname or ""
        port = parts.port or (443 if parts.scheme == "https" else 80)
        ip = resolve_public(host, port)
        connection = _connect(parts.scheme, host, ip, port)
        try:
            target = urllib.parse.urlunsplit(("", "", parts.path or "/", parts.query, ""))
            connection.request(
                "GET",
                target,
                headers={"User-Agent": USER_AGENT, "Accept": accept, "Accept-Encoding": "identity"},
            )
            response = connection.getresponse()
            if response.status in REDIRECTS:
                location = response.getheader("Location")
                if not location:
                    raise FetchError("Сайт перенаправил без адреса")
                current = urllib.parse.urljoin(current, location)
                continue
            if response.status != 200:
                raise FetchError(f"Сайт ответил кодом {response.status}")
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                if must_fit:
                    raise FetchError("Ответ слишком большой")
                body = body[:max_bytes]
            content_type = (
                (response.getheader("Content-Type") or "").split(";", 1)[0].strip().lower()
            )
            charset = response.headers.get_content_charset()
            return Fetched(current, content_type, body, charset)
        except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
            raise FetchError(f"Не удалось открыть ссылку: {exc.__class__.__name__}") from exc
        finally:
            connection.close()
    raise FetchError("Слишком много перенаправлений")


class _Meta(HTMLParser):
    """Заголовок и картинка из разметки: Open Graph, затем Twitter Card, затем <title>."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self._title: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            data = {k.lower(): v for k, v in attrs if v is not None}
            key = (data.get("property") or data.get("name") or "").lower()
            if key and data.get("content"):
                self.meta.setdefault(key, data["content"])

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title.append(data)

    @property
    def title(self) -> str | None:
        for key in ("og:title", "twitter:title"):
            if self.meta.get(key):
                return self.meta[key]
        text = " ".join("".join(self._title).split())
        return text or None

    @property
    def image(self) -> str | None:
        for key in ("og:image", "og:image:url", "twitter:image", "twitter:image:src"):
            if self.meta.get(key):
                return self.meta[key]
        return None


@dataclass(frozen=True, slots=True)
class LinkCard:
    title: str | None
    image: bytes | None


def parse_card(page: Fetched) -> tuple[str | None, str | None]:
    """(заголовок, адрес картинки) из страницы."""
    parser = _Meta()
    try:
        parser.feed(page.body.decode(page.charset or "utf-8", errors="replace"))
    except (LookupError, ValueError):
        parser.feed(page.body.decode("utf-8", errors="replace"))
    title = " ".join((parser.title or "").split())[:MAX_TITLE_LEN] or None
    image = parser.image
    return title, urllib.parse.urljoin(page.url, image) if image else None


def fetch_card(url: str) -> LinkCard:
    """Заголовок и картинка по ссылке. Нет картинки или заголовка — не ошибка, карточка беднее."""
    page = fetch(url, max_bytes=MAX_HTML_BYTES, accept="text/html,application/xhtml+xml,image/*")
    if page.content_type.startswith("image/"):
        return LinkCard(None, page.body if len(page.body) < MAX_IMAGE_BYTES else None)
    if page.content_type not in ("text/html", "application/xhtml+xml"):
        return LinkCard(None, None)
    title, image_url = parse_card(page)
    image: bytes | None = None
    if image_url:
        try:
            shot = fetch(image_url, max_bytes=MAX_IMAGE_BYTES, accept="image/*", must_fit=True)
            if shot.content_type.startswith("image/"):
                image = shot.body
        except LinkError:
            image = None  # картинка не открылась — оставляем только заголовок
    return LinkCard(title, image)
