import os
from contextlib import contextmanager
from typing import Generator, Literal, TypedDict

import chess
import chess.engine

ANALYSIS_LIMIT_SECONDS = 1.0
ENGINE_TIMEOUT_SECONDS = 5.0


class EngineAnalysis(TypedDict):
    best_move: str
    score_cp: int | None
    mate_in: int | None
    score_perspective: Literal["white"]
    analysis_limit_seconds: float


class PositionAnalysis(TypedDict):
    score: chess.engine.PovScore
    pv: list[chess.Move]


class EngineUnavailableError(RuntimeError):
    pass


class EngineAnalysisTimeoutError(RuntimeError):
    pass


@contextmanager
def open_configured_engine(
    timeout_seconds: float = ENGINE_TIMEOUT_SECONDS,
) -> Generator[chess.engine.SimpleEngine, None, None]:
    engine_path = os.getenv("STOCKFISH_PATH")
    if not engine_path:
        raise EngineUnavailableError(
            "Stockfish is not configured. Set STOCKFISH_PATH to the local "
            "Stockfish executable and restart the backend."
        )

    try:
        with chess.engine.SimpleEngine.popen_uci(
            engine_path,
            timeout=timeout_seconds,
        ) as engine:
            yield engine
    except TimeoutError as error:
        raise EngineAnalysisTimeoutError(
            "Stockfish did not respond within "
            f"{timeout_seconds:g} seconds."
        ) from error
    except (OSError, chess.engine.EngineError) as error:
        raise EngineUnavailableError(
            "Stockfish could not be started or failed during analysis. "
            "Check STOCKFISH_PATH and that the engine binary can run."
        ) from error


def analyze_position(
    engine: chess.engine.SimpleEngine,
    board: chess.Board,
    limit_seconds: float,
) -> PositionAnalysis:
    try:
        info = engine.analyse(board, chess.engine.Limit(time=limit_seconds))
    except TimeoutError as error:
        raise EngineAnalysisTimeoutError(
            f"Stockfish did not respond within {engine.timeout:g} seconds."
        ) from error
    except (OSError, chess.engine.EngineError) as error:
        raise EngineUnavailableError(
            "Stockfish could not be started or failed during analysis. "
            "Check STOCKFISH_PATH and that the engine binary can run."
        ) from error

    score = info.get("score")
    principal_variation = info.get("pv")
    if score is None or not principal_variation:
        raise EngineUnavailableError(
            "Stockfish did not return an evaluation and candidate move."
        )

    return {"score": score, "pv": principal_variation}


def analyze_start_position() -> EngineAnalysis:
    board = chess.Board()
    with open_configured_engine() as engine:
        position = analyze_position(
            engine,
            board,
            ANALYSIS_LIMIT_SECONDS,
        )

    white_score = position["score"].pov(chess.WHITE)
    return {
        "best_move": position["pv"][0].uci(),
        "score_cp": white_score.score(),
        "mate_in": white_score.mate(),
        "score_perspective": "white",
        "analysis_limit_seconds": ANALYSIS_LIMIT_SECONDS,
    }
