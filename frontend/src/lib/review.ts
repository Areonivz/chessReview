export type Evaluation = {
  kind: "centipawns" | "mate" | "terminal";
  value: number;
  perspective: "white" | "black";
  terminal_reason: string | null;
};

export type GameMove = {
  ply: number;
  move_number: number;
  color: "white" | "black";
  san: string;
  uci: string;
  fen: string;
};

export type ReviewFinding = {
  ply: number;
  move_number: number;
  color: "white" | "black";
  played_move_san: string;
  played_move_uci: string;
  evaluation_before: Evaluation;
  evaluation_after: Evaluation;
  evaluation_change_cp: number | null;
  label: "inaccuracy" | "mistake" | "blunder" | "mate_swing" | "terminal";
  best_move_uci: string | null;
  best_move_san: string | null;
  continuation_san: string[];
};

export type GameReview = {
  headers: {
    white: string;
    black: string;
    event: string;
    date: string;
    result: string;
  };
  initial_fen: string;
  moves: GameMove[];
  findings: ReviewFinding[];
  analysis: {
    limit_per_position_seconds: number;
    budget_seconds: number;
    engine_timeout_seconds: number;
    max_game_plies: number;
    analyzed_plies: number;
    thresholds_cp: {
      inaccuracy: number;
      mistake: number;
      blunder: number;
    };
  };
  complete: boolean;
  partial_error: string | null;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isEvaluation(value: unknown): value is Evaluation {
  return (
    isRecord(value) &&
    (value.kind === "centipawns" ||
      value.kind === "mate" ||
      value.kind === "terminal") &&
    typeof value.value === "number" &&
    (value.perspective === "white" || value.perspective === "black") &&
    (value.terminal_reason === null ||
      typeof value.terminal_reason === "string")
  );
}

function isGameMove(value: unknown): value is GameMove {
  return (
    isRecord(value) &&
    typeof value.ply === "number" &&
    typeof value.move_number === "number" &&
    (value.color === "white" || value.color === "black") &&
    typeof value.san === "string" &&
    typeof value.uci === "string" &&
    typeof value.fen === "string"
  );
}

function isFinding(value: unknown): value is ReviewFinding {
  return (
    isRecord(value) &&
    typeof value.ply === "number" &&
    typeof value.move_number === "number" &&
    (value.color === "white" || value.color === "black") &&
    typeof value.played_move_san === "string" &&
    typeof value.played_move_uci === "string" &&
    isEvaluation(value.evaluation_before) &&
    isEvaluation(value.evaluation_after) &&
    (typeof value.evaluation_change_cp === "number" ||
      value.evaluation_change_cp === null) &&
    (value.label === "inaccuracy" ||
      value.label === "mistake" ||
      value.label === "blunder" ||
      value.label === "mate_swing" ||
      value.label === "terminal") &&
    (typeof value.best_move_uci === "string" ||
      value.best_move_uci === null) &&
    (typeof value.best_move_san === "string" ||
      value.best_move_san === null) &&
    Array.isArray(value.continuation_san) &&
    value.continuation_san.every(
      (move): move is string => typeof move === "string",
    )
  );
}

export function isGameReview(value: unknown): value is GameReview {
  if (!isRecord(value) || !isRecord(value.headers) || !isRecord(value.analysis)) {
    return false;
  }

  const headers = value.headers;
  const analysis = value.analysis;
  return (
    ["white", "black", "event", "date", "result"].every(
      (key) => typeof headers[key] === "string",
    ) &&
    typeof value.initial_fen === "string" &&
    Array.isArray(value.moves) &&
    value.moves.every(isGameMove) &&
    Array.isArray(value.findings) &&
    value.findings.every(isFinding) &&
    typeof analysis.limit_per_position_seconds === "number" &&
    typeof analysis.budget_seconds === "number" &&
    typeof analysis.engine_timeout_seconds === "number" &&
    typeof analysis.max_game_plies === "number" &&
    typeof analysis.analyzed_plies === "number" &&
    isRecord(analysis.thresholds_cp) &&
    typeof analysis.thresholds_cp.inaccuracy === "number" &&
    typeof analysis.thresholds_cp.mistake === "number" &&
    typeof analysis.thresholds_cp.blunder === "number" &&
    typeof value.complete === "boolean" &&
    (typeof value.partial_error === "string" ||
      value.partial_error === null)
  );
}

export function evaluationLabel(evaluation: Evaluation): string {
  if (evaluation.kind === "mate") {
    return evaluation.value > 0
      ? `Mate in ${evaluation.value}`
      : `Mated in ${Math.abs(evaluation.value)}`;
  }
  if (evaluation.kind === "terminal") {
    if (evaluation.value === 0) {
      return `Draw${evaluation.terminal_reason ? ` · ${evaluation.terminal_reason}` : ""}`;
    }
    return evaluation.value > 0
      ? `Win${evaluation.terminal_reason ? ` · ${evaluation.terminal_reason}` : ""}`
      : `Loss${evaluation.terminal_reason ? ` · ${evaluation.terminal_reason}` : ""}`;
  }

  const pawns = evaluation.value / 100;
  return `${pawns > 0 ? "+" : ""}${pawns.toFixed(2)}`;
}
