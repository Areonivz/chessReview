"use client";

import Link from "next/link";
import { ChangeEvent, FormEvent, useEffect, useMemo, useState } from "react";
import {
  evaluationLabel,
  GameMove,
  GameReview,
  isGameReview,
  ReviewFinding,
} from "@/lib/review";

const MAX_PGN_BYTES = 1_000_000;
const configuredBackendUrl =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
const BACKEND_URL = (
  configuredBackendUrl.startsWith("http://") ||
  configuredBackendUrl.startsWith("https://")
    ? configuredBackendUrl
    : `https://${configuredBackendUrl}`
).replace(/\/+$/, "");
const DEMO_PGN_URL = "/demo.pgn";

const PIECES: Record<string, string> = {
  K: "♔",
  Q: "♕",
  R: "♖",
  B: "♗",
  N: "♘",
  P: "♙",
  k: "♚",
  q: "♛",
  r: "♜",
  b: "♝",
  n: "♞",
  p: "♟",
};

const LABELS: Record<ReviewFinding["label"], string> = {
  inaccuracy: "Inaccuracy",
  mistake: "Mistake",
  blunder: "Blunder",
  mate_swing: "Mate opportunity",
  terminal: "Game over",
};

type BackendStatus = "checking" | "online" | "offline";

function formatChange(change: number | null): string {
  if (change === null) {
    return "Mate or terminal evaluation changed";
  }
  return `${(change / 100).toFixed(2)} pawn${Math.abs(change) === 100 ? "" : "s"}`;
}

function PositionBoard({
  fen,
  lastMove,
  description,
}: {
  fen: string;
  lastMove: GameMove | null;
  description: string;
}) {
  const [placement, activeColor] = fen.split(" ");
  const ranks = placement.split("/");
  const highlightedSquares = new Set(
    lastMove
      ? [lastMove.uci.slice(0, 2), lastMove.uci.slice(2, 4)]
      : [],
  );
  const squares: { piece: string | null; name: string }[] = [];

  for (let row = 0; row < 8; row += 1) {
    let file = 0;
    for (const symbol of ranks[row] ?? "") {
      if (/^[1-8]$/.test(symbol)) {
        const emptySquares = Number(symbol);
        for (let empty = 0; empty < emptySquares; empty += 1) {
          squares.push({
            piece: null,
            name: `${String.fromCharCode(97 + file)}${8 - row}`,
          });
          file += 1;
        }
        continue;
      }
      const squareName = `${String.fromCharCode(97 + file)}${8 - row}`;
      squares.push({ piece: symbol, name: squareName });
      file += 1;
    }

    while (file < 8) {
      squares.push({
        piece: null,
        name: `${String.fromCharCode(97 + file)}${8 - row}`,
      });
      file += 1;
    }
  }

  return (
    <div
      role="img"
      aria-label={`${description}. ${activeColor === "b" ? "Black" : "White"} to move.`}
      className="grid grid-cols-8 overflow-hidden rounded-xl border-4 border-[#26352f] shadow-2xl"
    >
      {squares.map((square, index) => {
        const row = Math.floor(index / 8);
        const column = index % 8;
        const isDark = (row + column) % 2 === 1;
        const isHighlighted = highlightedSquares.has(square.name);
        const isPieceWhite = square.piece === square.piece?.toUpperCase();
        return (
          <div
            key={square.name}
            className={`relative flex aspect-square items-center justify-center ${
              isDark ? "bg-[#76917e]" : "bg-[#e8e7d7]"
            } ${isHighlighted ? "after:absolute after:inset-0 after:bg-amber-300/40" : ""}`}
          >
            {column === 0 && (
              <span
                aria-hidden="true"
                className={`absolute left-1 top-0.5 z-10 text-[9px] font-bold sm:text-xs ${
                  isDark ? "text-[#f4f1e5]" : "text-[#63776a]"
                }`}
              >
                {8 - row}
              </span>
            )}
            {row === 7 && (
              <span
                aria-hidden="true"
                className={`absolute bottom-0.5 right-1 z-10 text-[9px] font-bold sm:text-xs ${
                  isDark ? "text-[#f4f1e5]" : "text-[#63776a]"
                }`}
              >
                {String.fromCharCode(97 + column)}
              </span>
            )}
            {square.piece && (
              <span
                aria-hidden="true"
                className={`relative z-10 select-none text-[clamp(1.45rem,8vw,3.4rem)] leading-none ${
                  isPieceWhite
                    ? "text-[#fffdf2] drop-shadow-[0_1px_1px_#1b2921]"
                    : "text-[#23332a] drop-shadow-[0_1px_1px_#f0efdf]"
                }`}
              >
                {PIECES[square.piece]}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

function MoveList({
  moves,
  selectedPly,
  onSelect,
}: {
  moves: GameMove[];
  selectedPly: number;
  onSelect: (ply: number) => void;
}) {
  const moveNumbers = [...new Set(moves.map((move) => move.move_number))];

  return (
    <div className="max-h-[24rem] overflow-y-auto rounded-lg border border-[#26352f]">
      <div className="grid grid-cols-[2.5rem_1fr_1fr] text-sm">
        <div className="sticky top-0 bg-[#26352f] px-3 py-2 text-xs uppercase tracking-widest text-[#b7c8ba]">
          #
        </div>
        <div className="sticky top-0 bg-[#26352f] px-3 py-2 text-xs uppercase tracking-widest text-[#b7c8ba]">
          White
        </div>
        <div className="sticky top-0 bg-[#26352f] px-3 py-2 text-xs uppercase tracking-widest text-[#b7c8ba]">
          Black
        </div>
        {moveNumbers.map((moveNumber) => {
          const white = moves.find(
            (move) => move.move_number === moveNumber && move.color === "white",
          );
          const black = moves.find(
            (move) => move.move_number === moveNumber && move.color === "black",
          );

          return (
            <MoveRow
              key={moveNumber}
              moveNumber={moveNumber}
              white={white}
              black={black}
              selectedPly={selectedPly}
              onSelect={onSelect}
            />
          );
        })}
      </div>
    </div>
  );
}

function MoveRow({
  moveNumber,
  white,
  black,
  selectedPly,
  onSelect,
}: {
  moveNumber: number;
  white?: GameMove;
  black?: GameMove;
  selectedPly: number;
  onSelect: (ply: number) => void;
}) {
  return (
    <>
      <div className="border-t border-[#26352f] px-3 py-2 font-mono text-xs text-[#93a49a]">
        {moveNumber}
      </div>
      {[white, black].map((move, index) => (
        <div
          key={index === 0 ? "white" : "black"}
          className="border-t border-[#26352f]"
        >
          {move ? (
            <button
              type="button"
              onClick={() => onSelect(move.ply)}
              aria-pressed={selectedPly === move.ply}
              aria-label={`Go to move ${move.move_number}${move.color === "black" ? " black" : ""}, ${move.san}`}
              className={`w-full px-3 py-2 text-left font-mono transition-colors hover:bg-[#26352f] focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-emerald-300 ${
                selectedPly === move.ply
                  ? "bg-emerald-300/15 font-bold text-emerald-200"
                  : "text-[#e5e7df]"
              }`}
            >
              {move.san}
            </button>
          ) : (
            <span className="block px-3 py-2 text-[#708278]">—</span>
          )}
        </div>
      ))}
    </>
  );
}

function FindingCard({
  finding,
  selected,
  onSelect,
}: {
  finding: ReviewFinding;
  selected: boolean;
  onSelect: () => void;
}) {
  const change = finding.evaluation_change_cp;
  const changeText =
    change === null
      ? finding.label === "terminal"
        ? (finding.evaluation_after.terminal_reason ?? "Game ended").replace(
            /^./,
            (letter) => letter.toUpperCase(),
          )
        : formatChange(change)
      : `${change > 0 ? "+" : ""}${formatChange(change)}`;

  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={`w-full rounded-xl border p-4 text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-300 ${
        selected
          ? "border-emerald-300/70 bg-emerald-300/10"
          : "border-[#34443d] bg-[#18241f] hover:border-[#6a8575]"
      }`}
    >
      <span className="flex flex-wrap items-center justify-between gap-3">
        <span
          className={`rounded-full px-2.5 py-1 text-xs font-bold uppercase tracking-wider ${
            finding.label === "blunder"
              ? "bg-rose-400/15 text-rose-300"
              : finding.label === "mistake"
                ? "bg-amber-300/15 text-amber-200"
                : "bg-sky-300/15 text-sky-200"
          }`}
        >
          {LABELS[finding.label]}
        </span>
        <span className="font-mono text-sm text-[#c3cec5]">
          {finding.move_number}.{finding.color === "black" ? ".." : ""}{" "}
          {finding.played_move_san}
        </span>
      </span>
      <span className="mt-3 block text-sm text-[#d5dbd4]">
        Evaluation: {evaluationLabel(finding.evaluation_before)} →{" "}
        {evaluationLabel(finding.evaluation_after)}
        <span className="ml-2 text-[#aebdb1]">({changeText})</span>
      </span>
      {finding.best_move_san && (
        <span className="mt-2 block text-sm text-[#aebdb1]">
          Engine candidate:{" "}
          <span className="font-mono text-emerald-200">
            {finding.best_move_san}
          </span>
          {finding.continuation_san.length > 1 && (
            <span> · {finding.continuation_san.join(" ")}</span>
          )}
        </span>
      )}
      {finding.label === "mate_swing" && (
        <span className="mt-2 block text-xs text-[#aebdb1]">
          The engine’s mate evaluation changed. This is not a centipawn loss.
        </span>
      )}
    </button>
  );
}

function UploadError({ message }: { message: string }) {
  return (
    <div
      role="alert"
      className="mt-5 rounded-lg border border-rose-300/30 bg-rose-400/10 px-4 py-3 text-sm text-rose-100"
    >
      {message}
    </div>
  );
}

export function ReviewExperience() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [review, setReview] = useState<GameReview | null>(null);
  const [selectedPly, setSelectedPly] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [backendStatus, setBackendStatus] = useState<BackendStatus>("checking");

  useEffect(() => {
    const controller = new AbortController();
    async function checkBackend() {
      try {
        const response = await fetch(`${BACKEND_URL}/health`, {
          signal: controller.signal,
        });
        setBackendStatus(response.ok ? "online" : "offline");
      } catch {
        if (!controller.signal.aborted) {
          setBackendStatus("offline");
        }
      }
    }

    void checkBackend();
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!isAnalyzing) {
      return;
    }
    const startedAt = Date.now();
    const timer = window.setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [isAnalyzing]);

  const movesByPly = useMemo(() => {
    return new Map(review?.moves.map((move) => [move.ply, move]) ?? []);
  }, [review]);
  const selectedMove = movesByPly.get(selectedPly) ?? null;
  const boardFen = selectedMove?.fen ?? review?.initial_fen;
  const previousMove =
    selectedPly > 0 ? (movesByPly.get(selectedPly) ?? null) : null;
  const sideToMove = boardFen?.split(" ")[1] === "b" ? "Black" : "White";
  const selectedFinding = review?.findings.find(
    (finding) => finding.ply === selectedPly,
  );
  const analyzedThroughPly = review?.moves[review.analysis.analyzed_plies - 1]?.ply ?? 0;
  const backendStatusText = {
    checking: "Checking API",
    online: "API ready",
    offline: "API offline",
  }[backendStatus];

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    event.currentTarget.value = "";
    setError(null);
    setReview(null);
    setSelectedPly(0);
    setSelectedFile(file);

    if (!file) {
      return;
    }
    if (!file.name.toLowerCase().endsWith(".pgn")) {
      setError("Choose a PGN file with a .pgn extension.");
      setSelectedFile(null);
    } else if (file.size > MAX_PGN_BYTES) {
      setError("This file is too large. PGN files must be 1 MB or smaller.");
      setSelectedFile(null);
    } else if (file.size === 0) {
      setError("The selected file is empty. Choose a PGN containing one game.");
      setSelectedFile(null);
    }
  }

  async function analyzeFile(file: File, isDemo = false) {
    if (isAnalyzing) {
      return;
    }

    setError(null);
    setReview(null);
    setSelectedFile(null);
    setSelectedPly(0);
    setElapsedSeconds(0);
    setIsAnalyzing(true);
    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await fetch(`${BACKEND_URL}/games/analyze`, {
        method: "POST",
        body: formData,
      });
      let payload: unknown;
      try {
        payload = await response.json();
      } catch {
        throw new Error(`The API returned an unreadable response (${response.status}).`);
      }

      if (!response.ok) {
        const detail =
          typeof payload === "object" &&
          payload !== null &&
          "detail" in payload &&
          typeof payload.detail === "string"
            ? payload.detail
            : `The API could not analyse this game (HTTP ${response.status}).`;
        throw new Error(detail);
      }
      if (!isGameReview(payload)) {
        throw new Error("The API returned an unexpected game review.");
      }

      setReview(payload);
      const demoFinding = isDemo
        ? payload.findings.find((finding) => finding.label === "terminal")
        : undefined;
      setSelectedPly(demoFinding?.ply ?? payload.moves[0]?.ply ?? 0);
    } catch (caughtError) {
      setError(
        caughtError instanceof TypeError
          ? "Could not reach the review API. Start the backend and try again."
          : caughtError instanceof Error
            ? caughtError.message
            : "The game could not be analysed. Check the API and try again.",
      );
    } finally {
      setIsAnalyzing(false);
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selectedFile) {
      await analyzeFile(selectedFile);
    }
  }

  async function handleDemo() {
    try {
      const response = await fetch(DEMO_PGN_URL);
      if (!response.ok) {
        throw new Error("The guided demo game could not be loaded. Try again.");
      }
      const demoFile = new File(
        [await response.text()],
        "demo.pgn",
        { type: "application/x-chess-pgn" },
      );
      await analyzeFile(demoFile, true);
    } catch (caughtError) {
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : "The guided demo game could not be loaded. Try again.",
      );
    }
  }

  function moveToPly(ply: number) {
    if (review) {
      setSelectedPly(Math.max(0, Math.min(ply, review.moves.length)));
    }
  }

  return (
    <main className="min-h-screen bg-[#101914] px-4 pb-16 pt-5 text-[#f0f1e9] sm:px-8 sm:pt-8">
      <div className="mx-auto max-w-7xl">
        <header className="flex flex-wrap items-center justify-between gap-4 border-b border-[#2b3932] pb-5">
          <Link href="/" className="inline-flex items-center gap-3 rounded focus-visible:outline-2 focus-visible:outline-emerald-300">
            <span
              aria-hidden="true"
              className="grid h-10 w-10 place-items-center rounded-xl bg-emerald-300 text-xl text-[#142019]"
            >
              ♞
            </span>
            <span>
              <span className="block text-sm font-bold tracking-[0.18em]">
                CHESS REVIEW
              </span>
              <span className="mt-0.5 block text-xs text-[#9eada2]">
                One game, clearly reviewed
              </span>
            </span>
          </Link>
          <div
            aria-live="polite"
            className="inline-flex items-center gap-2 rounded-full border border-[#34443d] bg-[#18241f] px-3 py-1.5 text-xs text-[#cbd4cc]"
          >
            <span
              aria-hidden="true"
              className={`h-2 w-2 rounded-full ${
                backendStatus === "online"
                  ? "bg-emerald-300"
                  : backendStatus === "offline"
                    ? "bg-rose-300"
                    : "animate-pulse bg-amber-200"
              }`}
            />
            {backendStatusText}
          </div>
        </header>

        <section className="py-9 sm:py-12">
          <div className="max-w-3xl">
            <p className="text-xs font-bold uppercase tracking-[0.24em] text-emerald-300">
              Game review · PGN
            </p>
            <h1 className="mt-3 text-3xl font-semibold tracking-tight sm:text-5xl">
              Find the moments worth a second look.
            </h1>
            <p className="mt-4 max-w-2xl text-base leading-7 text-[#b3beb5]">
              Review a single game with Stockfish-supported prompts. Evaluations
              describe positions and moves—not why a player chose them.
            </p>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-[#aab7ad]">
              New here? Try the guided checkmate demo to see a review moment
              without preparing a PGN.
            </p>
          </div>

          <form
            onSubmit={handleSubmit}
            className="mt-8 rounded-2xl border border-[#34443d] bg-[#18241f] p-4 shadow-lg sm:flex sm:items-center sm:justify-between sm:gap-6 sm:p-5"
          >
            <div className="min-w-0">
              <label
                htmlFor="pgn-file"
                className="block text-sm font-semibold text-[#e8ece5]"
              >
                Upload one PGN game
              </label>
              <p id="pgn-help" className="mt-1 text-xs leading-5 text-[#9eada2]">
                .pgn file · maximum 1 MB · standard chess
              </p>
              <input
                id="pgn-file"
                type="file"
                accept=".pgn,application/x-chess-pgn"
                aria-describedby="pgn-help"
                onChange={handleFileChange}
                disabled={isAnalyzing}
                className="mt-3 block w-full max-w-lg cursor-pointer text-sm text-[#cbd4cc] file:mr-3 file:cursor-pointer file:rounded-lg file:border-0 file:bg-[#2a3a32] file:px-4 file:py-2 file:text-sm file:font-semibold file:text-emerald-100 hover:file:bg-[#34473c] focus-visible:outline-2 focus-visible:outline-emerald-300"
              />
              {selectedFile && (
                <p className="mt-2 truncate text-xs text-[#9eada2]">
                  Selected: {selectedFile.name}
                </p>
              )}
            </div>
            <div className="mt-4 flex w-full flex-col gap-2 sm:mt-0 sm:w-auto sm:flex-row">
              <button
                type="submit"
                disabled={!selectedFile || isAnalyzing}
                className="inline-flex min-h-11 w-full items-center justify-center rounded-lg bg-emerald-300 px-5 py-2.5 text-sm font-bold text-[#142019] transition-colors hover:bg-emerald-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-200 disabled:cursor-not-allowed disabled:bg-[#43544a] disabled:text-[#a9b3aa] sm:w-auto"
              >
                {isAnalyzing ? "Analysing…" : "Analyse game"}
              </button>
              <button
                type="button"
                onClick={() => void handleDemo()}
                disabled={isAnalyzing}
                className="inline-flex min-h-11 w-full items-center justify-center rounded-lg border border-[#6a8575] px-5 py-2.5 text-sm font-semibold text-emerald-100 transition-colors hover:bg-[#26352f] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-300 disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto"
              >
                {isAnalyzing ? "Loading demo…" : "Try checkmate demo"}
              </button>
            </div>
          </form>

          {error && <UploadError message={error} />}
          {isAnalyzing && (
            <div
              role="status"
              aria-live="polite"
              className="mt-5 flex items-center gap-3 rounded-lg border border-emerald-300/20 bg-emerald-300/5 px-4 py-3 text-sm text-[#d3ddd4]"
            >
              <span
                aria-hidden="true"
                className="h-4 w-4 animate-spin rounded-full border-2 border-emerald-300/30 border-t-emerald-300"
              />
              Analysing with Stockfish… {elapsedSeconds}s elapsed. This may
              take up to 30 seconds.
            </div>
          )}
        </section>

        {review && (
          <section
            aria-labelledby="review-title"
            className="space-y-6"
          >
            {!review.complete && (
              <div
                role="status"
                className="rounded-xl border border-amber-300/30 bg-amber-300/10 px-4 py-3 text-sm text-amber-100"
              >
                <strong>Partial engine analysis.</strong>{" "}
                {review.analysis.analyzed_plies} of {review.moves.length} plies
                were analysed. {review.partial_error}
              </div>
            )}

            <div className="flex flex-wrap items-end justify-between gap-4">
              <div>
                <p className="text-xs font-bold uppercase tracking-[0.2em] text-emerald-300">
                  Review ready
                </p>
                <h2
                  id="review-title"
                  className="mt-2 text-2xl font-semibold sm:text-3xl"
                >
                  {review.headers.white}{" "}
                  <span className="text-[#87978c]">vs</span>{" "}
                  {review.headers.black}
                </h2>
                <p className="mt-2 text-sm text-[#aab7ad]">
                  {review.headers.event} · {review.headers.date} ·{" "}
                  {review.headers.result}
                </p>
              </div>
              <p className="rounded-full border border-[#34443d] bg-[#18241f] px-3 py-1.5 text-xs text-[#c2cec4]">
                {review.analysis.analyzed_plies} / {review.moves.length} plies
                analysed
              </p>
            </div>

            <div className="grid gap-6 lg:grid-cols-[minmax(0,1.15fr)_minmax(20rem,0.85fr)]">
              <section className="rounded-2xl border border-[#34443d] bg-[#18241f] p-4 sm:p-6">
                <div className="mx-auto w-full max-w-[42rem]">
                  {boardFen && (
                    <PositionBoard
                      fen={boardFen}
                      lastMove={previousMove}
                      description={
                        selectedMove
                          ? `Position after ${selectedMove.move_number}${selectedMove.color === "black" ? "..." : "."} ${selectedMove.san}`
                          : "Starting position"
                      }
                    />
                  )}
                  <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                    <div aria-live="polite" className="min-h-10">
                      <p className="text-sm font-semibold text-[#edf0e9]">
                        {selectedMove
                          ? `Move ${selectedMove.move_number}${selectedMove.color === "black" ? "..." : "."} ${selectedMove.san}`
                          : "Starting position"}
                      </p>
                      <p className="mt-1 text-xs text-[#9eada2]">
                        {sideToMove} to move
                      </p>
                    </div>
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={() => moveToPly(selectedPly - 1)}
                        disabled={selectedPly === 0}
                        aria-label="Previous move"
                        className="min-h-10 min-w-10 rounded-lg border border-[#43544a] text-lg text-[#e3e9e1] hover:bg-[#26352f] focus-visible:outline-2 focus-visible:outline-emerald-300 disabled:cursor-not-allowed disabled:opacity-40"
                      >
                        ←
                      </button>
                      <button
                        type="button"
                        onClick={() => moveToPly(selectedPly + 1)}
                        disabled={selectedPly >= review.moves.length}
                        aria-label="Next move"
                        className="min-h-10 min-w-10 rounded-lg border border-[#43544a] text-lg text-[#e3e9e1] hover:bg-[#26352f] focus-visible:outline-2 focus-visible:outline-emerald-300 disabled:cursor-not-allowed disabled:opacity-40"
                      >
                        →
                      </button>
                    </div>
                  </div>
                </div>

                <div className="mt-6">
                  <h3 className="mb-3 text-xs font-bold uppercase tracking-[0.18em] text-[#aebdb1]">
                    Moves
                  </h3>
                  <MoveList
                    moves={review.moves}
                    selectedPly={selectedPly}
                    onSelect={moveToPly}
                  />
                </div>
              </section>

              <section className="space-y-4">
                {selectedFinding && (
                  <div className="rounded-2xl border border-emerald-300/25 bg-[#1c2c24] p-5">
                    <p className="text-xs font-bold uppercase tracking-[0.18em] text-emerald-300">
                      Selected moment
                    </p>
                    <p className="mt-2 text-lg font-semibold">
                      {LABELS[selectedFinding.label]} on{" "}
                      {selectedFinding.played_move_san}
                    </p>
                    <p className="mt-2 text-sm leading-6 text-[#c3cec5]">
                      {selectedFinding.label === "terminal" &&
                      selectedFinding.evaluation_after.terminal_reason ===
                        "checkmate" ? (
                        <>
                          {selectedFinding.played_move_san} ends the game by
                          checkmate. This finding comes from the recorded legal
                          position; earlier engine evaluations are approximate.
                        </>
                      ) : (
                        <>
                          The evaluation changed by{" "}
                          <strong>
                            {formatChange(selectedFinding.evaluation_change_cp)}
                          </strong>{" "}
                          from {selectedFinding.color}&apos;s perspective. This
                          is an approximate engine-based signal, not an
                          explanation of intent.
                        </>
                      )}
                    </p>
                  </div>
                )}

                <div className="rounded-2xl border border-[#34443d] bg-[#18241f] p-4 sm:p-5">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <h3 className="text-lg font-semibold">Review moments</h3>
                      <p className="mt-1 text-xs text-[#9eada2]">
                        Approximate thresholds · engine limit{" "}
                        {review.analysis.limit_per_position_seconds}s per
                        position
                      </p>
                    </div>
                    <span className="rounded-full bg-[#293a31] px-2.5 py-1 text-xs text-[#d1dad2]">
                      {review.findings.length}
                    </span>
                  </div>

                  {review.findings.length > 0 ? (
                    <div className="mt-4 space-y-3">
                      {review.findings.map((finding) => (
                        <FindingCard
                          key={finding.ply}
                          finding={finding}
                          selected={selectedPly === finding.ply}
                          onSelect={() => moveToPly(finding.ply)}
                        />
                      ))}
                    </div>
                  ) : (
                    <div className="mt-4 rounded-xl border border-dashed border-[#43544a] px-4 py-6 text-center">
                      <p className="text-sm font-semibold text-[#e4e9e1]">
                        No review moments crossed the configured thresholds.
                      </p>
                      <p className="mx-auto mt-2 max-w-sm text-xs leading-5 text-[#9eada2]">
                        That does not mean every move was perfect. Engine
                        evaluations are approximate, and this review highlights
                        only larger changes.
                      </p>
                    </div>
                  )}
                </div>

                <details className="rounded-xl border border-[#34443d] bg-[#18241f] px-4 py-3 text-xs text-[#aebbb0]">
                  <summary className="cursor-pointer font-semibold text-[#dce4dc] focus-visible:outline-2 focus-visible:outline-emerald-300">
                    Analysis details
                  </summary>
                  <p className="mt-3 leading-5">
                    Analysed {review.analysis.analyzed_plies} plies at{" "}
                    {review.analysis.limit_per_position_seconds} seconds per
                    position, with a {review.analysis.budget_seconds}-second
                    game budget. Approximate thresholds: inaccuracy{" "}
                    {review.analysis.thresholds_cp.inaccuracy} cp, mistake{" "}
                    {review.analysis.thresholds_cp.mistake} cp, blunder{" "}
                    {review.analysis.thresholds_cp.blunder} cp.
                    {!review.complete &&
                      ` Analysis ended after ply ${analyzedThroughPly}.`}
                  </p>
                </details>
              </section>
            </div>
          </section>
        )}
      </div>
    </main>
  );
}
