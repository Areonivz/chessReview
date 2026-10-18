import os
from typing import Literal

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.engine import (
    EngineAnalysisTimeoutError,
    EngineUnavailableError,
    analyze_start_position,
)
from app.review import (
    MAX_PGN_BYTES,
    GameReview,
    InvalidPgnError,
    analyze_game,
)


class HealthResponse(BaseModel):
    status: Literal["ok"]


class EngineSmokeResponse(BaseModel):
    best_move: str
    score_cp: int | None
    mate_in: int | None
    score_perspective: Literal["white"]
    analysis_limit_seconds: float


class GameHeaders(BaseModel):
    white: str
    black: str
    event: str
    date: str
    result: str


class GameMove(BaseModel):
    ply: int
    move_number: int
    color: Literal["white", "black"]
    san: str
    uci: str
    fen: str


class EvaluationResponse(BaseModel):
    kind: Literal["centipawns", "mate", "terminal"]
    value: int
    perspective: Literal["white", "black"]
    terminal_reason: str | None


class ReviewFindingResponse(BaseModel):
    ply: int
    move_number: int
    color: Literal["white", "black"]
    played_move_san: str
    played_move_uci: str
    evaluation_before: EvaluationResponse
    evaluation_after: EvaluationResponse
    evaluation_change_cp: int | None
    label: Literal["inaccuracy", "mistake", "blunder", "mate_swing", "terminal"]
    best_move_uci: str | None
    best_move_san: str | None
    continuation_san: list[str]


class AnalysisSummaryResponse(BaseModel):
    limit_per_position_seconds: float
    budget_seconds: float
    engine_timeout_seconds: float
    max_game_plies: int
    analyzed_plies: int
    thresholds_cp: dict[str, int]


class GameReviewResponse(BaseModel):
    headers: GameHeaders
    initial_fen: str
    moves: list[GameMove]
    findings: list[ReviewFindingResponse]
    analysis: AnalysisSummaryResponse
    complete: bool
    partial_error: str | None


app = FastAPI(title="Chess Review API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")],
    allow_methods=["GET", "POST"],
    allow_headers=[],
)


@app.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post("/engine/smoke", response_model=EngineSmokeResponse)
def engine_smoke_check() -> EngineSmokeResponse:
    try:
        result = analyze_start_position()
    except EngineAnalysisTimeoutError as error:
        raise HTTPException(status_code=504, detail=str(error)) from error
    except EngineUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    return EngineSmokeResponse(**result)


@app.post("/games/analyze", response_model=GameReviewResponse)
async def analyze_uploaded_game(
    file: UploadFile = File(...),
) -> GameReviewResponse:
    try:
        uploaded_pgn = await file.read(MAX_PGN_BYTES + 1)
    finally:
        await file.close()

    if len(uploaded_pgn) > MAX_PGN_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"PGN files must be {MAX_PGN_BYTES} bytes or smaller.",
        )

    try:
        pgn_text = uploaded_pgn.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise HTTPException(
            status_code=422,
            detail="The PGN must be valid UTF-8 text.",
        ) from error

    try:
        result: GameReview = await run_in_threadpool(analyze_game, pgn_text)
    except InvalidPgnError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except EngineAnalysisTimeoutError as error:
        raise HTTPException(status_code=504, detail=str(error)) from error
    except EngineUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    return GameReviewResponse(**result)
