"""Карточка ссылки: разбор Open Graph и, главное, защита от обращения во внутреннюю сеть (SSRF)."""

import http.client
import http.server
import socket
import threading
from collections.abc import Iterator
from io import BytesIO

import pytest
from PIL import Image

from app import linkpreview as lp

PUBLIC_IP = "93.184.216.34"


def png(size: tuple[int, int] = (40, 30)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, (200, 150, 40)).save(buffer, format="PNG")
    return buffer.getvalue()


# --- адрес по форме ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "ftp://example.com/file",
        "javascript:alert(1)",
        "file:///etc/passwd",
        "//example.com/x",
        "http://",
        "http://user:secret@example.com/",
        "http://example.com:99999/",
        "http://exa mple.com/",
        "http://example.com/\r\nHost: evil",
        "http://example.com/\tx",
        "https://" + "a" * 2100,
    ],
)
def test_malformed_or_dangerous_urls_are_refused_before_any_network(url):
    with pytest.raises(lp.UnsafeUrl):
        lp.parse_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://127.0.0.1:8000/api/files/1",
        "http://localhost/",
        "http://LOCALHOST:8765/",
        "http://app.localhost/",
        "http://printer.local/",
        "http://vault.internal/",
        "http://10.0.0.5/",
        "http://192.168.0.1/",
        "http://172.16.5.4/",
        "http://169.254.169.254/latest/meta-data/",
        "http://100.64.0.1/",
        "http://0.0.0.0/",
        "http://[::1]/",
        "http://[fe80::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://[::ffff:10.0.0.1]/",
    ],
)
def test_internal_addresses_are_refused_even_as_literals(url):
    with pytest.raises(lp.UnsafeUrl):
        lp.parse_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/a?b=1",
        "http://8.8.8.8/",
        "https://[2606:4700:4700::1111]/",
        "HTTP://EXAMPLE.COM",
    ],
)
def test_ordinary_public_urls_are_accepted(url):
    assert lp.parse_url(url).hostname


@pytest.mark.parametrize("address", ["8.8.8.8", "1.1.1.1", PUBLIC_IP, "2606:4700:4700::1111"])
def test_public_ips_pass(address):
    assert lp.is_public_ip(address)


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.1.2.3", "172.31.0.1", "192.168.1.1", "169.254.169.254", "100.64.0.1", "0.0.0.0",
     "224.0.0.1", "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1", "::ffff:192.168.0.1"],
)  # fmt: skip
def test_non_public_ips_are_refused(address):
    assert not lp.is_public_ip(address)


# --- разрешение имени ----------------------------------------------------------------------------


def _dns(monkeypatch, answers: dict[str, list[str]]) -> None:
    real = socket.getaddrinfo

    def fake(host, port, *args, **kwargs):
        if host in answers:
            return [
                (
                    socket.AF_INET6 if ":" in a else socket.AF_INET,
                    socket.SOCK_STREAM,
                    6,
                    "",
                    (a, port),
                )
                for a in answers[host]
            ]
        if str(host).endswith(".test"):
            raise socket.gaierror("нет такого имени")
        return real(host, port, *args, **kwargs)  # локальные соединения самого теста

    monkeypatch.setattr(lp.socket, "getaddrinfo", fake)


def test_a_name_with_any_internal_address_is_refused(monkeypatch):
    _dns(monkeypatch, {"rebind.test": [PUBLIC_IP, "10.0.0.5"], "inner.test": ["192.168.0.9"]})
    for host in ("rebind.test", "inner.test"):
        with pytest.raises(lp.UnsafeUrl):
            lp.resolve_public(host, 80)


def test_a_public_name_resolves_preferring_ipv4(monkeypatch):
    _dns(monkeypatch, {"site.test": ["2606:4700:4700::1111", PUBLIC_IP]})
    assert lp.resolve_public("site.test", 443) == PUBLIC_IP


def test_unknown_name_is_a_readable_error(monkeypatch):
    _dns(monkeypatch, {})
    with pytest.raises(lp.FetchError, match="найти"):
        lp.resolve_public("nowhere.test", 80)


# --- сам запрос: локальный сервер подставляется вместо «публичного» адреса -------------------------


class Site(http.server.BaseHTTPRequestHandler):
    routes: dict[str, tuple[int, dict[str, str], bytes]] = {}
    seen: list[tuple[str, str | None]] = []

    def do_GET(self) -> None:
        Site.seen.append((self.path, self.headers.get("Host")))
        status, headers, body = Site.routes.get(self.path, (404, {}, b""))
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args) -> None:  # тишина в выводе тестов
        pass


@pytest.fixture
def server() -> Iterator[int]:
    Site.routes, Site.seen = {}, []
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1]
    httpd.shutdown()


@pytest.fixture
def site(monkeypatch, server) -> Iterator[type[Site]]:
    """«Публичные» имена ведут на локальный сервер; внутренние адреса по-прежнему настоящие."""
    _dns(
        monkeypatch,
        {"good.test": [PUBLIC_IP], "inner.test": ["10.0.0.5"], "meta.test": ["169.254.169.254"]},
    )
    connected: list[tuple[str, str, int]] = []

    def connect(scheme, host, ip, target_port):
        connected.append((host, ip, target_port))
        return http.client.HTTPConnection("127.0.0.1", server, timeout=3)

    monkeypatch.setattr(lp, "_connect", connect)
    Site.connected = connected  # type: ignore[attr-defined]
    return Site


def html(body: str, charset: str = "utf-8") -> tuple[int, dict[str, str], bytes]:
    return 200, {"Content-Type": f"text/html; charset={charset}"}, body.encode(charset)


def test_card_takes_open_graph_title_and_image(site):
    site.routes["/film"] = html(
        '<html><head><title>запасной</title><meta property="og:title" content="Кривое зеркало · трейлер">'
        '<meta property="og:image" content="/cover.png"></head></html>'
    )
    site.routes["/cover.png"] = (200, {"Content-Type": "image/png"}, png())
    card = lp.fetch_card("http://good.test/film")
    assert card.title == "Кривое зеркало · трейлер"
    assert card.image is not None and Image.open(BytesIO(card.image)).size == (40, 30)


def test_fetch_connects_to_the_checked_ip_not_to_the_name(site):
    site.routes["/"] = html("<title>x</title>")
    lp.fetch_card("http://good.test/")
    assert site.connected[0] == ("good.test", PUBLIC_IP, 80)


def test_pinned_connection_reaches_the_given_ip_and_keeps_the_site_name_in_host(server):
    Site.routes["/"] = html("<title>x</title>")
    connection = lp._connect("http", "good.test", "127.0.0.1", server)
    connection.request("GET", "/")
    assert connection.getresponse().status == 200
    assert Site.seen == [("/", f"good.test:{server}")]  # идём на IP, а заголовок Host — настоящий
    connection.close()


def test_title_tag_is_the_fallback_and_whitespace_is_collapsed(site):
    site.routes["/"] = html("<html><head><title>\n  Два   зеркала \n</title></head></html>")
    assert lp.fetch_card("http://good.test/").title == "Два зеркала"


def test_page_in_a_legacy_encoding_is_decoded(site):
    site.routes["/"] = html("<title>Битва при кривом зеркале</title>", charset="windows-1251")
    assert lp.fetch_card("http://good.test/").title == "Битва при кривом зеркале"


def test_a_direct_image_link_becomes_the_picture(site):
    site.routes["/p.png"] = (200, {"Content-Type": "image/png"}, png())
    card = lp.fetch_card("http://good.test/p.png")
    assert card.title is None and card.image is not None


def test_redirects_are_followed_within_the_limit(site):
    site.routes["/a"] = (302, {"Location": "/b"}, b"")
    site.routes["/b"] = (301, {"Location": "http://good.test/c"}, b"")
    site.routes["/c"] = html("<title>дошли</title>")
    assert lp.fetch_card("http://good.test/a").title == "дошли"


def test_too_many_redirects_fail(site):
    for i in range(6):
        site.routes[f"/{i}"] = (302, {"Location": f"/{i + 1}"}, b"")
    with pytest.raises(lp.FetchError, match="перенаправлений"):
        lp.fetch_card("http://good.test/0")


@pytest.mark.parametrize(
    "target",
    [
        "http://inner.test/secret",
        "http://meta.test/latest/meta-data/",
        "http://127.0.0.1:8000/",
        "http://[::1]/",
    ],
)
def test_a_redirect_into_the_internal_network_is_refused_and_never_connected(site, target):
    site.routes["/go"] = (302, {"Location": target}, b"")
    with pytest.raises(lp.UnsafeUrl):
        lp.fetch_card("http://good.test/go")
    assert [c[0] for c in site.connected] == ["good.test"]  # к внутреннему адресу не подключались


def test_non_200_is_a_readable_error(site):
    with pytest.raises(lp.FetchError, match="404"):
        lp.fetch_card("http://good.test/missing")


def test_unreachable_cover_keeps_the_title(site):
    site.routes["/"] = html(
        '<meta property="og:title" content="Есть заголовок"><meta property="og:image" content="http://inner.test/c.png">'
    )
    card = lp.fetch_card("http://good.test/")
    assert card.title == "Есть заголовок" and card.image is None


def test_oversized_cover_is_dropped_but_the_card_stays(site):
    site.routes["/"] = html(
        '<meta property="og:title" content="Большая"><meta property="og:image" content="/big.png">'
    )
    site.routes["/big.png"] = (200, {"Content-Type": "image/png"}, b"0" * (lp.MAX_IMAGE_BYTES + 1))
    card = lp.fetch_card("http://good.test/")
    assert card.title == "Большая" and card.image is None


def test_huge_html_is_truncated_not_rejected(site):
    site.routes["/"] = html(
        '<meta property="og:title" content="Начало">' + "x" * (lp.MAX_HTML_BYTES * 2)
    )
    assert lp.fetch_card("http://good.test/").title == "Начало"


def test_non_html_non_image_gives_an_empty_card(site):
    site.routes["/f.zip"] = (200, {"Content-Type": "application/zip"}, b"PK")
    card = lp.fetch_card("http://good.test/f.zip")
    assert card.title is None and card.image is None
