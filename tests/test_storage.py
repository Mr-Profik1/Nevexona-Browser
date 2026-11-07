import json
import os
import stat

from nevex import storage


def test_settings_defaults_and_persistence(tmp_path):
    p = str(tmp_path / "s.json")
    s = storage.Settings(p)
    assert s.get("search_engine") == "yandex"
    assert s.get("ai_enabled") is False
    assert s.get("reduced_memory") is False
    s.set("search_engine", "duckduckgo")
    s.set("ai_enabled", True)
    s.save()
    s2 = storage.Settings(p)
    assert s2.get("search_engine") == "duckduckgo"
    assert s2.get("ai_enabled") is True


def test_settings_validation(tmp_path):
    s = storage.Settings(str(tmp_path / "s.json"))
    import pytest
    with pytest.raises(KeyError):
        s.set("nope", 1)
    with pytest.raises(TypeError):
        s.set("ai_enabled", "yes")


def test_settings_ignores_bad_types_and_corrupt_file(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"ai_enabled": "yes", "search_engine": "bing", "junk": 1}))
    s = storage.Settings(str(p))
    assert s.get("ai_enabled") is False
    assert s.get("search_engine") == "bing"
    p.write_text("{not json")
    s = storage.Settings(str(p))
    assert s.get("search_engine") == "yandex"
    assert os.path.exists(str(p) + ".bad")


def test_api_key_store_permissions_and_env(tmp_path, monkeypatch):
    monkeypatch.delenv("NEVEX_AI_API_KEY", raising=False)
    k = storage.ApiKeyStore(str(tmp_path / "k.json"))
    assert k.get() == ""
    k.set("  sk-test  ")
    assert k.get() == "sk-test"
    assert stat.S_IMODE(os.stat(k.path).st_mode) == 0o600
    monkeypatch.setenv("NEVEX_AI_API_KEY", "from-env")
    assert k.get() == "from-env"
    monkeypatch.delenv("NEVEX_AI_API_KEY")
    k.set("")
    assert k.get() == ""
    assert not os.path.exists(k.path)


def test_bookmarks(tmp_path):
    p = str(tmp_path / "b.json")
    b = storage.Bookmarks(p)
    assert b.add("https://a.example/", "A") is True
    assert b.add("https://a.example/", "dup") is False
    assert b.contains("https://a.example/")
    b.add("https://b.example/", "Bee")
    assert [i["url"] for i in storage.Bookmarks(p).all()] == ["https://b.example/", "https://a.example/"]
    assert [i["title"] for i in b.search("bee")] == ["Bee"]
    assert b.toggle("https://b.example/") is False
    assert b.toggle("https://c.example/", "C") is True
    assert not storage.Bookmarks(p).contains("https://b.example/")
    assert b.remove("https://nope/") is False


def test_history(tmp_path):
    h = storage.History(str(tmp_path / "h.db"), max_rows=3)
    h.add("https://a/", "A")
    h.add("https://b/", "")
    h.add("https://a/", "A2")
    rows = h.recent()
    assert {r["url"] for r in rows} == {"https://a/", "https://b/"}
    assert [r for r in rows if r["url"] == "https://a/"][0]["title"] == "A2"
    assert h.recent("b")[0]["url"] == "https://b/"
    assert h.recent("100%") == []
    h.delete("https://a/")
    assert [r["url"] for r in h.recent()] == ["https://b/"]
    h.clear()
    assert h.recent() == []
    h.close()


def test_history_prunes(tmp_path):
    h = storage.History(str(tmp_path / "h.db"), max_rows=50)
    for i in range(200):
        h.add("https://x/%d" % i, "t")
    assert len(h.recent(limit=1000)) == 50


def test_history_persists(tmp_path):
    p = str(tmp_path / "h.db")
    h = storage.History(p)
    h.add("https://a/", "A")
    h.close()
    assert storage.History(p).recent()[0]["url"] == "https://a/"


def test_session(tmp_path):
    s = storage.SessionStore(str(tmp_path / "s.json"))
    assert s.load() == ([], 0)
    s.save([{"url": "https://a/", "title": "A"}, {"url": "nevex:start", "title": ""}], 1)
    tabs, active = s.load()
    assert [t["url"] for t in tabs] == ["https://a/", "nevex:start"] and active == 1
    s.save([{"url": "https://a/", "title": "A"}], 5)
    assert s.load()[1] == 0
