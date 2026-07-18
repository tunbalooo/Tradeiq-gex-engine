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
