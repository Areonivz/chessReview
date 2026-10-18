import logging
import os
import threading
import time
from io import StringIO
from typing import Literal, TypedDict

import chess
import chess.engine
import chess.pgn

from app.engine import (
    ENGINE_TIMEOUT_SECONDS,
    EngineAnalysisTimeoutError,
    EngineUnavailableError,
    PositionAnalysis,
    analyze_position,
    open_configured_engine,
)

MAX_PGN_BYTES = 1_000_000
MAX_GAME_PLIES = 500
GAME_ANALYSIS_LIMIT_SECONDS = 0.1
GAME_ANALYSIS_BUDGET_SECONDS = 30.0
INACCURACY_THRESHOLD_CP = int(os.getenv("INACCURACY_THRESHOLD_CP", "100"))
MISTAKE_THRESHOLD_CP = int(os.getenv("MISTAKE_THRESHOLD_CP", "300"))
BLUNDER_THRESHOLD_CP = int(os.getenv("BLUNDER_THRESHOLD_CP", "500"))
CONTINUATION_LENGTH = 5

if not (0 < INACCURACY_THRESHOLD_CP < MISTAKE_THRESHOLD_CP < BLUNDER_THRESHOLD_CP):
    raise ValueError(
        "Evaluation thresholds must be positive and ordered from inaccuracy to blunder."
    )


class InvalidPgnError(ValueError):
    pass


class ParsedMove(TypedDict):
    ply: int
    move_number: int
    color: Literal["white", "black"]
    san: str
    uci: str
    fen: str


class ParsedGame(TypedDict):
    headers: dict[str, str]
    initial_fen: str
    moves: list[ParsedMove]


class Evaluation(TypedDict):
    kind: Literal["centipawns", "mate", "terminal"]
    value: int
    perspective: Literal["white", "black"]
    terminal_reason: str | None


class ReviewFinding(TypedDict):
    ply: int
    move_number: int
    color: Literal["white", "black"]
    played_move_san: str
    played_move_uci: str
    evaluation_before: Evaluation
    evaluation_after: Evaluation
    evaluation_change_cp: int | None
    label: Literal["inaccuracy", "mistake", "blunder", "mate_swing", "terminal"]
    best_move_uci: str | None
    best_move_san: str | None
    continuation_san: list[str]


class AnalysisSummary(TypedDict):
    limit_per_position_seconds: float
    budget_seconds: float
    engine_timeout_seconds: float
    max_game_plies: int
    analyzed_plies: int
    thresholds_cp: dict[str, int]


class GameReview(TypedDict):
    headers: dict[str, str]
    initial_fen: str
    moves: list[ParsedMove]
    findings: list[ReviewFinding]
    analysis: AnalysisSummary
    complete: bool
    partial_error: str | None


class _DiscardPgnLog(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        del record
        return False


_PGN_PARSE_LOCK = threading.Lock()


def parse_single_game(pgn_text: str) -> ParsedGame:
    parser_logger = logging.getLogger("chess.pgn")
    discard_filter = _DiscardPgnLog()

    with _PGN_PARSE_LOCK:
        parser_logger.addFilter(discard_filter)
        try:
            stream = StringIO(pgn_text)
            game = chess.pgn.read_game(stream)
            second_game = chess.pgn.read_game(stream) if game is not None else None
        finally:
            parser_logger.removeFilter(discard_filter)

    if game is None:
        raise InvalidPgnError("The uploaded file does not contain a PGN game.")
    if game.errors:
        raise InvalidPgnError("The PGN is malformed or contains an illegal move.")
    if second_game is not None:
        raise InvalidPgnError("Upload exactly one PGN game per file.")

    variant = game.headers.get("Variant", "Standard").strip().casefold()
    if variant != "standard":
        raise InvalidPgnError("Only standard chess PGN games are supported.")

    try:
        board = game.board()
    except ValueError as error:
        raise InvalidPgnError(
            "The PGN contains an invalid starting position."
        ) from error

    if board.chess960 or not board.is_valid():
        raise InvalidPgnError("The PGN contains an invalid starting position.")

    moves: list[ParsedMove] = []
    for ply, move in enumerate(game.mainline_moves(), start=1):
        if ply > MAX_GAME_PLIES:
            raise InvalidPgnError(
                f"The game exceeds the limit of {MAX_GAME_PLIES} plies."
            )
        if not board.is_legal(move):
            raise InvalidPgnError("The PGN is malformed or contains an illegal move.")

        color: Literal["white", "black"] = "white" if board.turn else "black"
        move_number = board.fullmove_number
        san = board.san(move)
        board.push(move)
        if not board.is_valid():
            raise InvalidPgnError("The PGN reaches an invalid chess position.")

        moves.append(
            {
                "ply": ply,
                "move_number": move_number,
                "color": color,
                "san": san,
                "uci": move.uci(),
                "fen": board.fen(),
            }
        )

    if not moves:
        raise InvalidPgnError("The PGN game contains no moves.")

    headers = game.headers
    return {
        "headers": {
            "white": headers.get("White", "Unknown"),
            "black": headers.get("Black", "Unknown"),
            "event": headers.get("Event", "Unknown"),
            "date": headers.get("Date", "Unknown"),
            "result": headers.get("Result", "*"),
        },
        "initial_fen": game.board().fen(),
        "moves": moves,
    }


def _evaluation(
    score: chess.engine.PovScore,
    perspective: chess.Color,
) -> Evaluation:
    relative_score = score.pov(perspective)
    side: Literal["white", "black"] = "white" if perspective else "black"
    mate = relative_score.mate()
    if mate is not None:
        return {
            "kind": "mate",
            "value": mate,
            "perspective": side,
            "terminal_reason": None,
        }

    centipawns = relative_score.score()
    if centipawns is None:
        raise EngineUnavailableError(
            "Stockfish returned an unsupported evaluation score."
        )
    return {
        "kind": "centipawns",
        "value": centipawns,
        "perspective": side,
        "terminal_reason": None,
    }


def _terminal_evaluation(
    board: chess.Board,
    perspective: chess.Color,
) -> Evaluation | None:
    outcome = board.outcome(claim_draw=False)
    if outcome is None:
        return None

    if outcome.winner is None:
        value = 0
    else:
        value = 1 if outcome.winner == perspective else -1

    return {
        "kind": "terminal",
        "value": value,
        "perspective": "white" if perspective else "black",
        "terminal_reason": outcome.termination.name.lower(),
    }


def _finding_label(
    before: Evaluation,
    after: Evaluation,
) -> tuple[
    int | None,
    Literal["inaccuracy", "mistake", "blunder", "mate_swing", "terminal"] | None,
]:
    if after["kind"] == "terminal":
        return None, "terminal"
    if before["kind"] == "mate" or after["kind"] == "mate":
        if before == after:
            return None, None
        return None, "mate_swing"
    if before["kind"] != "centipawns" or after["kind"] != "centipawns":
        return None, None

    evaluation_change = before["value"] - after["value"]
    if evaluation_change >= BLUNDER_THRESHOLD_CP:
        return evaluation_change, "blunder"
    if evaluation_change >= MISTAKE_THRESHOLD_CP:
        return evaluation_change, "mistake"
    if evaluation_change >= INACCURACY_THRESHOLD_CP:
        return evaluation_change, "inaccuracy"
    return evaluation_change, None


def _continuation_san(
    board: chess.Board,
    principal_variation: list[chess.Move],
) -> list[str]:
    continuation: list[str] = []
    line_board = board.copy()
    for move in principal_variation[:CONTINUATION_LENGTH]:
        if not line_board.is_legal(move):
            break
        continuation.append(line_board.san(move))
        line_board.push(move)
    return continuation


def _summary(
    analyzed_plies: int,
) -> AnalysisSummary:
    return {
        "limit_per_position_seconds": GAME_ANALYSIS_LIMIT_SECONDS,
        "budget_seconds": GAME_ANALYSIS_BUDGET_SECONDS,
        "engine_timeout_seconds": ENGINE_TIMEOUT_SECONDS,
        "max_game_plies": MAX_GAME_PLIES,
        "analyzed_plies": analyzed_plies,
        "thresholds_cp": {
            "inaccuracy": INACCURACY_THRESHOLD_CP,
            "mistake": MISTAKE_THRESHOLD_CP,
            "blunder": BLUNDER_THRESHOLD_CP,
        },
    }


def analyze_game(pgn_text: str) -> GameReview:
    parsed_game = parse_single_game(pgn_text)
    board = chess.Board(parsed_game["initial_fen"])
    findings: list[ReviewFinding] = []
    analyzed_plies = 0
    partial_error: str | None = None
    deadline = time.monotonic() + GAME_ANALYSIS_BUDGET_SECONDS

    def analyze_current_position(
        engine: chess.engine.SimpleEngine,
    ) -> PositionAnalysis:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise EngineAnalysisTimeoutError(
                "Analysis reached its "
                f"{GAME_ANALYSIS_BUDGET_SECONDS:g}-second engine time budget."
            )
        engine.timeout = min(ENGINE_TIMEOUT_SECONDS, remaining)
        return analyze_position(
            engine,
            board,
            min(GAME_ANALYSIS_LIMIT_SECONDS, remaining),
        )

    with open_configured_engine(
        timeout_seconds=min(ENGINE_TIMEOUT_SECONDS, GAME_ANALYSIS_BUDGET_SECONDS)
    ) as engine:
        current_position = analyze_current_position(engine)
        before_score = current_position["score"]

        for move_data in parsed_game["moves"]:
            mover = board.turn
            move = chess.Move.from_uci(move_data["uci"])
            before_evaluation = _evaluation(before_score, mover)
            best_move = current_position["pv"][0] if current_position["pv"] else None
            best_move_san = None
            if best_move is not None and board.is_legal(best_move):
                best_move_san = board.san(best_move)
            continuation = _continuation_san(board, current_position["pv"])
            board.push(move)

            after_evaluation = _terminal_evaluation(board, mover)
            next_position: PositionAnalysis | None = None
            if after_evaluation is None:
                try:
                    next_position = analyze_current_position(engine)
                    score = next_position.get("score")
                    pv = next_position.get("pv")
                    if score is None or not pv:
                        raise EngineUnavailableError(
                            "Stockfish did not return an evaluation and candidate move."
                        )
                    after_evaluation = _evaluation(score, mover)
                except (EngineAnalysisTimeoutError, EngineUnavailableError) as error:
                    if analyzed_plies == 0:
                        raise
                    partial_error = str(error)
                    break
            else:
                next_position = None

            change, label = _finding_label(
                before_evaluation,
                after_evaluation,
            )
            if label is not None:
                findings.append(
                    {
                        "ply": move_data["ply"],
                        "move_number": move_data["move_number"],
                        "color": move_data["color"],
                        "played_move_san": move_data["san"],
                        "played_move_uci": move_data["uci"],
                        "evaluation_before": before_evaluation,
                        "evaluation_after": after_evaluation,
                        "evaluation_change_cp": change,
                        "label": label,
                        "best_move_uci": best_move.uci() if best_move else None,
                        "best_move_san": best_move_san,
                        "continuation_san": continuation,
                    }
                )

            analyzed_plies += 1
            if next_position is None:
                break
            before_score = next_position["score"]
            current_position = {
                "score": before_score,
                "pv": next_position["pv"],
            }

    return {
        **parsed_game,
        "findings": findings,
        "analysis": _summary(analyzed_plies),
        "complete": partial_error is None,
        "partial_error": partial_error,
    }
