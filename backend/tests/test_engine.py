import asyncio
from typing import Any

import chess
import chess.engine
import httpx
import pytest

from app.main import app


def post_engine_smoke() -> httpx.Response:
    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            return await client.post("/engine/smoke")

    return asyncio.run(request())


def test_engine_smoke_requires_configured_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("STOCKFISH_PATH", raising=False)

    response = post_engine_smoke()

    assert response.status_code == 503
    assert "Set STOCKFISH_PATH" in response.json()["detail"]


def test_engine_smoke_reports_missing_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STOCKFISH_PATH", "missing-stockfish")

    def missing_binary(*args: Any, **kwargs: Any) -> Any:
        raise FileNotFoundError("missing engine executable")

    monkeypatch.setattr(
        chess.engine.SimpleEngine,
        "popen_uci",
        missing_binary,
    )

    response = post_engine_smoke()

    assert response.status_code == 503
    assert "could not be started" in response.json()["detail"]


def test_engine_smoke_reports_engine_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STOCKFISH_PATH", "configured-stockfish")

    class TimedOutEngine:
        timeout = 5.0

        def __enter__(self) -> "TimedOutEngine":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def analyse(
            self,
            board: chess.Board,
            limit: chess.engine.Limit,
        ) -> dict[str, Any]:
            raise TimeoutError

    def launch_engine(*args: Any, **kwargs: Any) -> TimedOutEngine:
        return TimedOutEngine()

    monkeypatch.setattr(
        chess.engine.SimpleEngine,
        "popen_uci",
        launch_engine,
    )

    response = post_engine_smoke()

    assert response.status_code == 504
    assert "did not respond within 5 seconds" in response.json()["detail"]


def test_engine_smoke_returns_score_and_candidate_move(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STOCKFISH_PATH", "configured-stockfish")
    observed: dict[str, Any] = {}

    class AnalysedEngine:
        def __enter__(self) -> "AnalysedEngine":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def analyse(
            self,
            board: chess.Board,
            limit: chess.engine.Limit,
        ) -> chess.engine.InfoDict:
            observed["fen"] = board.fen()
            observed["limit"] = limit.time
            return {
                "score": chess.engine.PovScore(chess.engine.Cp(34), chess.WHITE),
                "pv": [chess.Move.from_uci("e2e4")],
            }

    def launch_engine(*args: Any, **kwargs: Any) -> AnalysedEngine:
        observed["path"] = args[0]
        observed["timeout"] = kwargs["timeout"]
        return AnalysedEngine()

    monkeypatch.setattr(
        chess.engine.SimpleEngine,
        "popen_uci",
        launch_engine,
    )

    response = post_engine_smoke()

    assert response.status_code == 200
    assert response.json() == {
        "best_move": "e2e4",
        "score_cp": 34,
        "mate_in": None,
        "score_perspective": "white",
        "analysis_limit_seconds": 1.0,
    }
    assert observed["fen"] == chess.STARTING_FEN
    assert observed["limit"] == 1.0
    assert observed["timeout"] == 5.0
