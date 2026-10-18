# Chess Review

Chess Review is a local-first web app for reviewing one chess game at a time.
The MVP accepts a single PGN, validates and analyses it with Stockfish, and
shows engine-supported review moments alongside the game. Uploaded games and
player information are never persisted.

## Architecture

- `frontend/`: Next.js App Router, React, TypeScript, and Tailwind CSS.
- `backend/`: FastAPI API with Pydantic response models.
- `python-chess`: PGN parsing, legal move replay, and UCI engine communication
  (used for engine communication and PGN analysis).
- Stockfish: a locally installed engine executable configured with
  `STOCKFISH_PATH`; no engine path or arguments are accepted from API requests.
- No accounts, database, Redis, bulk analysis, Chess.com import, or AI in the
  MVP.

Review findings will be engine-based prompts, not claims about why a player
made a move. Approximate move-quality labels will use named thresholds and show
the underlying evaluation change. Evaluations will be compared from the
original mover's perspective, with mate scores handled separately.

## Prerequisites

- Node.js 20.9 or newer and npm.
- Python 3.11 or newer.
- A locally installed Stockfish executable is optional for running Milestone 0;
  install it to run the Milestone 1 engine smoke check.

## Run locally

In one terminal, start the API:

```powershell
cd backend
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload --env-file .env --port 8000
```

In another terminal, start the frontend:

```powershell
cd frontend
npm install
npm run dev
```

Open <http://localhost:3000>. The page calls `GET http://localhost:8000/health`
and reports whether the API is reachable.

To run backend tests, activate the backend virtual environment and run
`pytest`. From `frontend/`, run `npm run lint`, `npx tsc --noEmit`, or
`npm run build`.

## Configuration

The backend loads `backend/.env` for local configuration. Set `STOCKFISH_PATH`
there to the absolute path of a locally installed Stockfish executable; for
example, `C:\Tools\Stockfish\stockfish.exe`. `FRONTEND_ORIGIN` defaults to
`http://localhost:3000`; change it if the frontend uses a different origin.
The named `INACCURACY_THRESHOLD_CP`, `MISTAKE_THRESHOLD_CP`, and
`BLUNDER_THRESHOLD_CP` values default to `100`, `300`, and `500` centipawns and
must be positive and strictly increasing. These are approximate heuristics;
the report includes the actual evaluation change. The frontend uses
`NEXT_PUBLIC_BACKEND_URL`, which defaults to `http://localhost:8000`; set it in
`frontend/.env.local` when the API runs elsewhere.

## Milestone 1: verify Stockfish

After installing Stockfish, set `STOCKFISH_PATH` in `backend/.env` and start
the API using the command above. In another PowerShell terminal, run this
single check:

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8000/engine/smoke
```

The API launches the configured UCI engine, analyses the standard starting
position for one second, and returns the candidate move, score in centipawns or
mate moves, the score's White perspective, and the analysis limit. No executable
path or engine arguments are accepted by this endpoint. Missing configuration
or an engine that cannot start returns HTTP 503; an engine timeout returns
HTTP 504. Without Stockfish installed, test these failure paths with
`pytest tests/test_engine.py`.

Before distributing a Stockfish binary or deploying it, check its license
obligations and the target host's CPU and memory limits.

## Milestone 2: upload and analyse one PGN

With Stockfish configured and the API running, upload the included sample with
PowerShell:

```powershell
curl.exe -F "file=@backend/sample.pgn" http://localhost:8000/games/analyze
```

The endpoint accepts exactly one standard-chess PGN, validates the mainline
and replays only legal positions. Uploads are limited to 1,000,000 bytes and
500 plies. Each analysed position has a 0.1-second Stockfish search; the
request has a 30-second analysis budget and a 5-second engine communication
timeout. If analysis stops after producing results, the response marks
`complete: false` and explains why; failures before any analysis return HTTP
503 or 504. Invalid, empty, multiple-game, unsupported-variant, and oversized
files return clear 4xx errors.

The response includes PGN headers, SAN/UCI moves and resulting FEN positions,
plus review findings with the played move, best move/continuation when
available, before/after evaluations from that mover's perspective, and
centipawn loss or a separately represented mate/terminal score. Review labels
are approximate threshold heuristics, not explanations of a player's intent.
The API does not write uploaded PGNs or player details to application logs or
save them as project files.

Run the parser, engine-comparison, and upload failure tests with
`pytest tests/test_review.py tests/test_engine.py`.

## Milestone 3: review a game in the browser

Start the API and frontend as described in **Run locally**, then open
<http://localhost:3000>. Choose one `.pgn` file (maximum 1 MB) and select
**Analyse game**. The review shows the game metadata, analysed move count, and
board position. Use the previous/next controls or select a move to navigate;
review moments select their associated move. Expand **Analysis details** to
inspect the analysis settings and result information.

If analysis is partial, the page explains why and retains the available
results. A game with no findings displays an explicit no-review-moments state;
this does not imply that every move was perfect. The included `backend/sample.pgn`
can be used to exercise the upload and review flow.
