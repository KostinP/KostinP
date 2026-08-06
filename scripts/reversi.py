#!/usr/bin/env python3
"""Reversi-via-GitHub-Issues engine.

Two entry points:
  render  - regenerate the README game section from the current state (no move applied)
  apply   - parse a move out of $ISSUE_TITLE, validate it, apply it, update state + README

State lives in game/state.json. README sections are rewritten in place between
HTML comment markers. All game logic is pure stdlib so it needs no dependencies
on the GitHub Actions runner.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "game" / "state.json"
README_PATH = ROOT / "README.md"

OWNER = "KostinP"
REPO = "KostinP"
MOVE_LABEL = "reversi-move"

COLS = "ABCDEFGH"
DIRECTIONS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]

PIECE = {"B": "⚫", "W": "⚪"}  # ⚫ ⚪
NAME = {"B": "чёрные", "W": "белые"}  # чёрные, белые

MARKERS = ["BOARD", "MOVES", "LEADERBOARD"]


def opponent(color: str) -> str:
    return "W" if color == "B" else "B"


def initial_board():
    board = [[None] * 8 for _ in range(8)]
    board[3][3] = "W"  # D4
    board[3][4] = "B"  # E4
    board[4][3] = "B"  # D5
    board[4][4] = "W"  # E5
    return board


def cell_to_rc(cell: str):
    cell = cell.strip().upper()
    if not re.fullmatch(r"[A-H][1-8]", cell):
        return None
    col = COLS.index(cell[0])
    row = int(cell[1]) - 1
    return row, col


def rc_to_cell(r: int, c: int) -> str:
    return f"{COLS[c]}{r + 1}"


def flips_for(board, color, r, c):
    if board[r][c] is not None:
        return []
    found = []
    for dr, dc in DIRECTIONS:
        line = []
        rr, cc = r + dr, c + dc
        while 0 <= rr < 8 and 0 <= cc < 8 and board[rr][cc] == opponent(color):
            line.append((rr, cc))
            rr, cc = rr + dr, cc + dc
        if line and 0 <= rr < 8 and 0 <= cc < 8 and board[rr][cc] == color:
            found.extend(line)
    return found


def legal_moves(board, color):
    moves = {}
    for r in range(8):
        for c in range(8):
            f = flips_for(board, color, r, c)
            if f:
                moves[(r, c)] = f
    return moves


def apply_at(board, color, r, c, flips):
    board[r][c] = color
    for rr, cc in flips:
        board[rr][cc] = color


def score(board):
    b = sum(row.count("B") for row in board)
    w = sum(row.count("W") for row in board)
    return b, w


def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {
        "board": initial_board(),
        "turn": "B",
        "status": "in_progress",
        "game_number": 1,
        "history": [],
        "leaderboard": {},
    }


def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def issue_url(cell: str) -> str:
    title = urllib.parse.quote_plus(f"Move: {cell}")
    body = urllib.parse.quote_plus(
        "Automatically opened from the README board. Please do not edit the title."
    )
    return (
        f"https://github.com/{OWNER}/{REPO}/issues/new"
        f"?title={title}&labels={MOVE_LABEL}&body={body}"
    )


def render_board(state) -> str:
    board = state["board"]
    b, w = score(board)
    lines = []

    if state["status"] == "finished":
        winner = "Ничья (ничья)"
        if b > w:
            winner = f"{PIECE['B']} чёрные"
        elif w > b:
            winner = f"{PIECE['W']} белые"
        lines.append(f"**Игра #{state['game_number']} завершена.** Счёт: {PIECE['B']} {b} : {w} {PIECE['W']}. Победили: {winner}.")
        legal = {}
    else:
        turn = state["turn"]
        lines.append(
            f"**Ходят {PIECE[turn]} {NAME[turn]}.** Счёт: {PIECE['B']} {b} : {w} {PIECE['W']}. "
            f"Нажмите на зелёную клетку, чтобы сходить."
        )
        legal = legal_moves(board, turn)

    lines.append("")
    header = "|   | " + " | ".join(COLS) + " |"
    sep = "|---|" + "|".join(["---"] * 8) + "|"
    lines.append(header)
    lines.append(sep)
    for r in range(8):
        row_cells = []
        for c in range(8):
            piece = board[r][c]
            if piece:
                row_cells.append(PIECE[piece])
            elif (r, c) in legal:
                cell = rc_to_cell(r, c)
                row_cells.append(f"[\U0001f7e9]({issue_url(cell)})")
            else:
                row_cells.append("▫️")
        lines.append(f"| **{r + 1}** | " + " | ".join(row_cells) + " |")

    return "\n".join(lines)


def render_moves(state) -> str:
    history = state["history"][-5:][::-1]
    if not history:
        return "_Ходов пока не было — сделайте первый!_"
    lines = ["| Дата (UTC) | Ход | Игрок |", "|---|---|---|"]
    for m in history:
        dt = datetime.fromisoformat(m["date"]).strftime("%d.%m.%y %H:%M")
        lines.append(f"| {dt} | {PIECE[m['color']]} {m['cell']} | @{m['user']} |")
    return "\n".join(lines)


def render_leaderboard(state) -> str:
    board_lb = sorted(state["leaderboard"].items(), key=lambda kv: kv[1], reverse=True)[:10]
    if not board_lb:
        return "_Пока пусто._"
    lines = ["| # | Игрок | Ходов |", "|---|---|---|"]
    for i, (user, count) in enumerate(board_lb, start=1):
        lines.append(f"| {i} | @{user} | {count} |")
    return "\n".join(lines)


RENDERERS = {"BOARD": render_board, "MOVES": render_moves, "LEADERBOARD": render_leaderboard}


def rewrite_readme(state):
    text = README_PATH.read_text(encoding="utf-8")
    for marker in MARKERS:
        start = f"<!-- REVERSI:{marker}:START -->"
        end = f"<!-- REVERSI:{marker}:END -->"
        pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
        if not pattern.search(text):
            raise SystemExit(f"Markers {start} .. {end} not found in README.md")
        replacement = f"{start}\n{RENDERERS[marker](state)}\n{end}"
        text = pattern.sub(lambda _m, r=replacement: r, text)
    README_PATH.write_text(text, encoding="utf-8")


def set_output(name: str, value: str):
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        print(f"[output] {name} = {value!r}")
        return
    with open(path, "a", encoding="utf-8") as fh:
        if "\n" in value:
            delim = "REVERSI_EOF"
            fh.write(f"{name}<<{delim}\n{value}\n{delim}\n")
        else:
            fh.write(f"{name}={value}\n")


def cmd_render(_args):
    is_new = not STATE_PATH.exists()
    state = load_state()
    if is_new:
        save_state(state)
    rewrite_readme(state)
    print("README regenerated from current state.")


def cmd_apply(_args):
    state = load_state()
    title = os.environ.get("ISSUE_TITLE", "")
    user = os.environ.get("ISSUE_USER", "unknown")

    def reject(message: str):
        set_output("valid", "false")
        set_output("message", message)

    if state["status"] == "finished":
        reject(
            f"Игра #{state['game_number']} уже завершена. "
            "Следите за README — новая игра скоро начнётся."
        )
        return

    match = re.search(r"Move:\s*([A-Ha-h][1-8])", title)
    if not match:
        reject(
            "Не удалось распознать ход из заголовка issue. "
            "Ожидался формат `Move: E2`. "
            "Сделайте ход через ссылки на доске в README, не вручную."
        )
        return

    cell = match.group(1).upper()
    rc = cell_to_rc(cell)
    board = state["board"]
    turn = state["turn"]
    legal = legal_moves(board, turn)

    if rc not in legal:
        legal_list = ", ".join(sorted(rc_to_cell(r, c) for r, c in legal)) or "нет ходов"
        reject(
            f"`{cell}` — недопустимый ход для {PIECE[turn]} {NAME[turn]} "
            f"(клетка занята или не окружает соперника). "
            f"Доступные ходы: {legal_list}. Вернитесь на доску в README и кликните по зелёной клетке."
        )
        return

    r, c = rc
    apply_at(board, turn, r, c, legal[rc])
    state["history"].append(
        {
            "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "cell": cell,
            "color": turn,
            "user": user,
        }
    )
    state["leaderboard"][user] = state["leaderboard"].get(user, 0) + 1

    nxt = opponent(turn)
    skip_note = ""
    if legal_moves(board, nxt):
        state["turn"] = nxt
    elif legal_moves(board, turn):
        state["turn"] = turn
        skip_note = f" У {NAME[nxt]} нет ходов, ход передаётся обратно."
    else:
        state["status"] = "finished"

    save_state(state)
    rewrite_readme(state)

    b, w = score(board)
    if state["status"] == "finished":
        result = (
            f"Готово! Игра #{state['game_number']} завершена со счётом "
            f"{PIECE['B']} {b} : {w} {PIECE['W']}. Смотрите README."
        )
    else:
        result = (
            f"Ход `{cell}` принят за {PIECE[turn]} {NAME[turn]} (@{user}). "
            f"Счёт: {PIECE['B']} {b} : {w} {PIECE['W']}.{skip_note}"
        )
    set_output("valid", "true")
    set_output("message", result)
    set_output("commit_message", f"Reversi: {cell} by @{user}")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "render":
        cmd_render(sys.argv[2:])
    elif cmd == "apply":
        cmd_apply(sys.argv[2:])
    else:
        print("usage: reversi.py [render|apply]", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
