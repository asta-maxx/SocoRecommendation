"""ENG-02 item 5: GET /health is 200 when both databases can be read, 503 otherwise. SD-28."""

from __future__ import annotations

import pytest
from fastapi import Response

from reco.api import health as health_api
from reco.config import Settings


def _pings(monkeypatch: pytest.MonkeyPatch, platform: bool, engine: bool) -> None:
    async def platform_ping(settings):
        return platform

    async def engine_ping(settings):
        return engine

    monkeypatch.setattr(health_api.platform_conn, "ping", platform_ping)
    monkeypatch.setattr(health_api.store_conn, "ping", engine_ping)


async def test_both_databases_readable_is_200(monkeypatch: pytest.MonkeyPatch) -> None:
    _pings(monkeypatch, platform=True, engine=True)
    response = Response()

    body = await health_api.health(response, Settings())

    assert response.status_code == 200
    assert body["status"] == "ok"
    assert body["mongo"] == {"app": True, "ml": True}


@pytest.mark.parametrize(
    "platform,engine", [(False, True), (True, False), (False, False)]
)
async def test_either_database_down_is_503(
    monkeypatch: pytest.MonkeyPatch, platform: bool, engine: bool
) -> None:
    _pings(monkeypatch, platform=platform, engine=engine)
    response = Response()

    body = await health_api.health(response, Settings())

    assert response.status_code == 503
    assert body["status"] == "unavailable"
    assert body["mongo"] == {"app": platform, "ml": engine}


async def test_health_names_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    _pings(monkeypatch, platform=True, engine=True)

    body = await health_api.health(Response(), Settings(engine_env="test"))

    assert body["environment"] == "test"
