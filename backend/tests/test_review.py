import asyncio
import threading
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Generator

import chess
import chess.engine
import httpx
import pytest

from app import engine, review
from app.main import app

SAMPLE_PGN = (
    '[Event "Test Event"]\n'
    '[White "White Player"]\n'
    '[Black "Black Player"]\n'
    '[Result "*"]\n'
    "\n"
    "1. e4 e5 *\n"
)
DEMO_PGN_PATH = Path(__file__).resolve().parents[2] / "frontend" / "public" / "demo.pgn"


class FakeEngine:
    timeout = 5.0

    def __init__(self, fail_on_call: int | None = None) -> None:
        self.calls = 0
        self.fail_on_call = fail_on_call

    def analyse(
        self,
        board: chess.Board,
        limit: chess.engine.Limit,
    ) -> chess.engine.InfoDict:
        assert limit.time is not None
        self.calls += 1
        if self.calls == self.fail_on_call:
            raise TimeoutError

        move_count = len(board.move_stack)
        candidate = {
            0: "e2e4",
            1: "e7e5",
            2: "g1f3",
            3: "b8c6",
        }.get(move_count, "e2e4")
        score = {0: 100, 1: 100, 2: 300}.get(move_count, 300)
        return {
            "score": chess.engine.PovScore(chess.engine.Cp(score), chess.WHITE),
            "pv": [chess.Move.from_uci(candidate)],
        }


@contextmanager
def fake_engine_context(
    fake: FakeEngine,
    timeout_seconds: float = 1.0,
) -> Generator[FakeEngine, None, None]:
    assert timeout_seconds > 0
    yield fake


def post_game(
    pgn: str | bytes,
) -> httpx.Response:
    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            return await client.post(
                "/games/analyze",
                files={"file": ("game.pgn", pgn, "application/x-chess-pgn")},
            )

    return asyncio.run(request())


def test_parse_single_game_replays_legal_mainline() -> None:
    parsed = review.parse_single_game(SAMPLE_PGN)

    assert parsed["headers"]["white"] == "White Player"
    assert [move["san"] for move in parsed["moves"]] == ["e4", "e5"]
    assert [move["uci"] for move in parsed["moves"]] == ["e2e4", "e7e5"]
    assert parsed["moves"][0]["color"] == "white"
    assert parsed["moves"][1]["move_number"] == 1
    assert chess.Board(parsed["moves"][1]["fen"]).piece_at(chess.E5) == chess.Piece(
        chess.PAWN, chess.BLACK
    )


@pytest.mark.parametrize(
    ("pgn", "message"),
    [
        ("", "does not contain a PGN game"),
        ("not a PGN game", "no moves"),
        ('[Event "Empty"]\n\n*', "contains no moves"),
        ('[Event "Broken"]\n\n1. e5 *', "malformed or contains an illegal move"),
        (
            '[Event "One"]\n\n1. e4 *\n\n[Event "Two"]\n\n1. d4 *',
            "exactly one PGN game",
        ),
        (
            '[Event "Chess960"]\n[Variant "Chess960"]\n\n1. e4 *',
            "Only standard chess",
        ),
    ],
)
def test_rejects_invalid_or_unsupported_pgn(pgn: str, message: str) -> None:
    with pytest.raises(review.InvalidPgnError, match=message):
        review.parse_single_game(pgn)


def test_rejects_games_over_ply_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(review, "MAX_GAME_PLIES", 2)

    with pytest.raises(review.InvalidPgnError, match="limit of 2 plies"):
        review.parse_single_game('[Event "Long"]\n\n1. e4 e5 2. Nf3 *')


def test_malformed_moves_do_not_write_pgn_details_to_logs(
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sensitive_pgn = '[Event "Private Event"]\n[White "Private White"]\n\n1. e5 *\n'

    with pytest.raises(review.InvalidPgnError):
        review.parse_single_game(sensitive_pgn)

    captured = capsys.readouterr()
    output = caplog.text + captured.out + captured.err
    assert "Private Event" not in output
    assert "Private White" not in output
    assert "illegal san" not in output


def test_analysis_compares_evaluations_from_each_movers_perspective(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeEngine()
    monkeypatch.setattr(
        review,
        "open_configured_engine",
        lambda **kwargs: fake_engine_context(fake, **kwargs),
    )

    result = review.analyze_game(SAMPLE_PGN)

    black_finding = next(
        finding for finding in result["findings"] if finding["color"] == "black"
    )
    assert black_finding["played_move_san"] == "e5"
    assert black_finding["evaluation_before"] == {
        "kind": "centipawns",
        "value": -100,
        "perspective": "black",
        "terminal_reason": None,
    }
    assert black_finding["evaluation_after"]["value"] == -300
    assert black_finding["evaluation_change_cp"] == 200
    assert black_finding["label"] == "inaccuracy"
    assert black_finding["best_move_uci"] == "e7e5"
    assert black_finding["continuation_san"] == ["e5"]
    assert result["analysis"]["analyzed_plies"] == 2
    assert result["complete"] is True


def test_mate_evaluations_are_not_converted_to_centipawns() -> None:
    score = chess.engine.PovScore(chess.engine.Mate(3), chess.WHITE)

    black_view = review._evaluation(score, chess.BLACK)

    assert black_view == {
        "kind": "mate",
        "value": -3,
        "perspective": "black",
        "terminal_reason": None,
    }
    change, label = review._finding_label(
        {
            "kind": "centipawns",
            "value": 0,
            "perspective": "black",
            "terminal_reason": None,
        },
        black_view,
    )
    assert change is None
    assert label == "mate_swing"


@pytest.mark.parametrize(
    ("change", "expected_label"),
    [
        (100, "inaccuracy"),
        (300, "mistake"),
        (500, "blunder"),
    ],
)
def test_quality_labels_use_named_centipawn_thresholds(
    change: int,
    expected_label: str,
) -> None:
    before: review.Evaluation = {
        "kind": "centipawns",
        "value": change,
        "perspective": "white",
        "terminal_reason": None,
    }
    after: review.Evaluation = {
        "kind": "centipawns",
        "value": 0,
        "perspective": "white",
        "terminal_reason": None,
    }

    actual_change, label = review._finding_label(before, after)

    assert actual_change == change
    assert label == expected_label


def test_checkmate_position_is_reported_without_engine_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeEngine()
    monkeypatch.setattr(
        review,
        "open_configured_engine",
        lambda **kwargs: fake_engine_context(fake, **kwargs),
    )
    pgn = '[Event "Mate"]\n\n1. f3 e5 2. g4 Qh4# 0-1'

    result = review.analyze_game(pgn)

    final_finding = result["findings"][-1]
    assert final_finding["played_move_san"] == "Qh4#"
    assert final_finding["label"] == "terminal"
    assert final_finding["evaluation_after"]["kind"] == "terminal"
    assert final_finding["evaluation_after"]["terminal_reason"] == "checkmate"
    assert fake.calls == 4
    assert result["complete"] is True


def test_guided_demo_always_contains_a_checkmate_review_moment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeEngine()
    monkeypatch.setattr(
        review,
        "open_configured_engine",
        lambda **kwargs: fake_engine_context(fake, **kwargs),
    )

    result = review.analyze_game(DEMO_PGN_PATH.read_text(encoding="utf-8"))

    terminal_finding = next(
        finding for finding in result["findings"] if finding["label"] == "terminal"
    )
    assert terminal_finding["played_move_san"] == "Qh2#"
    assert terminal_finding["evaluation_after"]["terminal_reason"] == "checkmate"
    assert terminal_finding["ply"] == len(result["moves"])


def test_stalemate_is_reported_as_terminal_draw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeEngine()
    monkeypatch.setattr(
        review,
        "open_configured_engine",
        lambda **kwargs: fake_engine_context(fake, **kwargs),
    )
    pgn = (
        '[Event "Stalemate"]\n'
        '[SetUp "1"]\n'
        '[FEN "7k/8/5K2/6Q1/8/8/8/8 w - - 0 1"]\n'
        "\n"
        "1. Qg6 *"
    )

    result = review.analyze_game(pgn)

    finding = result["findings"][0]
    assert finding["label"] == "terminal"
    assert finding["evaluation_after"]["kind"] == "terminal"
    assert finding["evaluation_after"]["value"] == 0
    assert finding["evaluation_after"]["terminal_reason"] == "stalemate"
    assert result["complete"] is True


def test_engine_timeout_returns_explicit_partial_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeEngine(fail_on_call=3)
    monkeypatch.setattr(
        review,
        "open_configured_engine",
        lambda **kwargs: fake_engine_context(fake, **kwargs),
    )

    result = review.analyze_game(SAMPLE_PGN)

    assert result["complete"] is False
    assert result["partial_error"] == "Stockfish did not respond within 5 seconds."
    assert result["analysis"]["analyzed_plies"] == 1
    assert len(result["moves"]) == 2


def test_game_budget_returns_partial_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeEngine()
    clock_values = iter([0.0, 0.0, 0.0, 0.2])
    monkeypatch.setattr(
        review,
        "time",
        SimpleNamespace(monotonic=lambda: next(clock_values)),
    )
    monkeypatch.setattr(review, "GAME_ANALYSIS_BUDGET_SECONDS", 0.1)
    monkeypatch.setattr(
        review,
        "open_configured_engine",
        lambda **kwargs: fake_engine_context(fake, **kwargs),
    )

    result = review.analyze_game(SAMPLE_PGN)

    assert result["complete"] is False
    assert result["partial_error"] == (
        "Analysis reached its 0.1-second engine time budget."
    )
    assert result["analysis"]["analyzed_plies"] == 1
    assert len(result["moves"]) == 2


def test_engine_crash_returns_explicit_partial_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CrashedEngine(FakeEngine):
        def analyse(
            self,
            board: chess.Board,
            limit: chess.engine.Limit,
        ) -> chess.engine.InfoDict:
            assert limit.time is not None
            if self.calls == 2:
                self.calls += 1
                raise OSError("engine process exited")
            return super().analyse(board, limit)

    fake = CrashedEngine()
    monkeypatch.setattr(
        review,
        "open_configured_engine",
        lambda **kwargs: fake_engine_context(fake, **kwargs),
    )

    result = review.analyze_game(SAMPLE_PGN)

    assert result["complete"] is False
    assert result["partial_error"] == (
        "Stockfish could not be started or failed during analysis. "
        "Check STOCKFISH_PATH and that the engine binary can run."
    )
    assert result["analysis"]["analyzed_plies"] == 1


def test_upload_rejects_oversized_file() -> None:
    response = post_game(b"x" * (review.MAX_PGN_BYTES + 1))

    assert response.status_code == 413
    assert "bytes or smaller" in response.json()["detail"]


def test_upload_rejects_non_utf8_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("STOCKFISH_PATH", raising=False)

    response = post_game(b"\xff\xfe")

    assert response.status_code == 422
    assert "valid UTF-8" in response.json()["detail"]


def test_upload_returns_clear_error_for_malformed_pgn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("STOCKFISH_PATH", raising=False)

    response = post_game('[Event "Bad"]\n\n1. e5 *')

    assert response.status_code == 422
    assert "malformed or contains an illegal move" in response.json()["detail"]


def test_upload_rejects_multiple_games_before_engine_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("STOCKFISH_PATH", raising=False)
    pgn = '[Event "One"]\n\n1. e4 *\n\n[Event "Two"]\n\n1. d4 *'

    response = post_game(pgn)

    assert response.status_code == 422
    assert "exactly one PGN game" in response.json()["detail"]


def test_upload_reports_missing_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("STOCKFISH_PATH", raising=False)

    response = post_game(SAMPLE_PGN)

    assert response.status_code == 503
    assert "Set STOCKFISH_PATH" in response.json()["detail"]


def test_upload_reports_busy_engine_slots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STOCKFISH_PATH", "configured-stockfish")
    slots = threading.BoundedSemaphore(1)
    assert slots.acquire(blocking=False)
    monkeypatch.setattr(engine, "_ENGINE_SLOTS", slots)

    response = post_game(SAMPLE_PGN)

    slots.release()
    assert response.status_code == 503
    assert "analysis slots are busy" in response.json()["detail"]


def test_upload_reports_engine_timeout_before_any_move(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeEngine(fail_on_call=1)
    monkeypatch.setattr(
        review,
        "open_configured_engine",
        lambda **kwargs: fake_engine_context(fake, **kwargs),
    )

    response = post_game(SAMPLE_PGN)

    assert response.status_code == 504
    assert "did not respond within 5 seconds" in response.json()["detail"]


def test_upload_returns_structured_analysis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeEngine()
    monkeypatch.setattr(
        review,
        "open_configured_engine",
        lambda **kwargs: fake_engine_context(fake, **kwargs),
    )

    response = post_game(SAMPLE_PGN)

    assert response.status_code == 200
    payload = response.json()
    assert payload["headers"]["white"] == "White Player"
    assert [move["san"] for move in payload["moves"]] == ["e4", "e5"]
    assert payload["findings"][0]["evaluation_change_cp"] == 200
    assert payload["analysis"]["limit_per_position_seconds"] == 0.1
