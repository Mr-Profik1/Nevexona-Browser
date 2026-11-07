import os

from nevex import fsutil, pages, paths


def test_sanitize_filename():
    assert fsutil.sanitize_filename("../../etc/passwd") == "passwd"
    assert fsutil.sanitize_filename("a/b\\c.txt") == "c.txt"
    assert fsutil.sanitize_filename("") == "download"
    assert fsutil.sanitize_filename("..") == "download"
    assert fsutil.sanitize_filename('we"ird:name?.zip') == "we_ird_name_.zip"
    assert len(fsutil.sanitize_filename("я" * 300 + ".txt").encode()) < 255


def test_unique_path(tmp_path):
    (tmp_path / "f.txt").write_text("x")
    assert fsutil.unique_path(str(tmp_path), "f.txt").endswith("f (1).txt")
    (tmp_path / "f (1).txt").write_text("x")
    assert fsutil.unique_path(str(tmp_path), "f.txt").endswith("f (2).txt")
    assert fsutil.unique_path(str(tmp_path), "new.txt").endswith("new.txt")


def test_profile_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("NEVEX_PROFILE", str(tmp_path / "p"))
    for fn in (paths.config_dir, paths.data_dir, paths.cache_dir):
        assert fn().startswith(str(tmp_path / "p")) and os.path.isdir(fn())


def test_download_dir_override(tmp_path, monkeypatch):
    monkeypatch.setenv("NEVEX_DOWNLOAD_DIR", str(tmp_path / "dl"))
    assert paths.download_dir() == str(tmp_path / "dl") and os.path.isdir(str(tmp_path / "dl"))


def test_start_page_escapes_and_filters():
    bm = [
        {"title": "<script>alert(1)</script>", "url": "https://ok.example/?a=1&b=2"},
        {"title": "bad", "url": "javascript:alert(1)"},
    ]
    h = pages.start_page_html("yandex", bm)
    assert "<script>alert" not in h
    assert "javascript:" not in h
    assert "https://yandex.ru/search/" in h and 'name="text"' in h
    assert "https://ok.example/?a=1&amp;b=2" in h
    assert "Private window" in pages.start_page_html("yandex", [], private=True)


def test_error_page_escapes():
    h = pages.error_page_html('https://x.example/"><img src=x>', "<b>boom</b>", 404)
    assert "<img" not in h and "<b>boom" not in h
    assert "Try again" in h
    assert "Try again" not in pages.error_page_html("file:///x", "m")
