from backend.services.finnhub_news import FinnhubNewsService


def test_finnhub_status_does_not_expose_api_key():
    service = FinnhubNewsService()
    status = service.status()
    assert "api_key" not in status
    assert "token" not in status


def test_finnhub_disabled_fallback_is_safe(monkeypatch):
    service = FinnhubNewsService()
    monkeypatch.setattr(type(service), "enabled", property(lambda self: False))
    items = service.latest()
    assert items
    assert "not configured" in items[0].event.lower()


def test_finnhub_general_feed_is_shared_across_market_filters(monkeypatch):
    service = FinnhubNewsService()
    monkeypatch.setattr(type(service), "enabled", property(lambda self: True))
    calls = {"count": 0}

    def fake_fetch():
        calls["count"] += 1
        return [
            {
                "headline": "Federal Reserve and Treasury yields move markets",
                "summary": "Nasdaq, S&P 500 and gold traders watch the dollar.",
                "datetime": 1_700_000_000,
                "source": "Test",
                "url": "https://example.com/news",
            }
        ]

    monkeypatch.setattr(service, "_fetch_general_news", fake_fetch)
    assert service.latest(symbol="NQ")
    assert service.latest(symbol="ES")
    assert service.latest(symbol="GC")
    assert calls["count"] == 1


def test_finnhub_failure_backoff_avoids_repeated_timeout(monkeypatch):
    service = FinnhubNewsService()
    monkeypatch.setattr(type(service), "enabled", property(lambda self: True))
    calls = {"count": 0}

    def fail_fetch():
        calls["count"] += 1
        raise RuntimeError("provider timeout")

    monkeypatch.setattr(service, "_fetch_general_news", fail_fetch)
    first = service.latest(symbol="NQ")
    second = service.latest(symbol="ES")
    assert first and second
    assert calls["count"] == 1
