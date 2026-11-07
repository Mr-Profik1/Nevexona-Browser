from urllib.parse import urlsplit, parse_qs

from nevex.urlutil import resolve_input, search_url, display_url, SEARCH_ENGINES


def test_default_search_is_yandex():
    u = resolve_input("hello world")
    assert urlsplit(u).netloc == "yandex.ru"
    assert parse_qs(urlsplit(u).query)["text"] == ["hello world"]


def test_other_engines():
    assert urlsplit(search_url("x", "duckduckgo")).netloc == "duckduckgo.com"
    assert urlsplit(search_url("x", "nonsense")).netloc == "yandex.ru"
    assert set(SEARCH_ENGINES) >= {"yandex", "duckduckgo", "google", "bing"}


def test_domains_and_urls():
    assert resolve_input("example.com") == "https://example.com"
    assert resolve_input("example.com/a?b=1") == "https://example.com/a?b=1"
    assert resolve_input("https://example.com/x y".replace(" ", "%20")) == "https://example.com/x%20y"
    assert resolve_input("яндекс.рф") == "https://яндекс.рф"
    assert resolve_input("http://a.b") == "http://a.b"


def test_local_hosts():
    assert resolve_input("localhost:8080") == "http://localhost:8080"
    assert resolve_input("192.168.1.1/admin") == "http://192.168.1.1/admin"
    assert resolve_input("[::1]:3000") == "http://[::1]:3000"


def test_dangerous_schemes_become_searches():
    for bad in ("javascript:alert(1)", "data:text/html,<b>x</b>", "ftp://x.y/z", "vbscript:x"):
        assert urlsplit(resolve_input(bad)).netloc == "yandex.ru", bad


def test_text_with_dots_but_spaces_is_search():
    assert urlsplit(resolve_input("what is python.org")).netloc == "yandex.ru"


def test_number_is_search():
    assert urlsplit(resolve_input("1.5")).netloc == "yandex.ru"


def test_empty_and_special():
    assert resolve_input("   ") == ""
    assert resolve_input("nevex:start") == "nevex:start"
    assert resolve_input("about:blank") == "about:blank"


def test_file_path(tmp_path):
    f = tmp_path / "a.html"
    f.write_text("x")
    assert resolve_input(str(f)).startswith("file:///")


def test_display_url():
    assert display_url("about:blank") == ""
    assert display_url("nevex:start") == ""
    assert display_url(None) == ""
    assert display_url("https://a.b/") == "https://a.b/"
