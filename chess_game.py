"""
IconChess - pygame GUI

Requirements:  pip install pygame python-chess
Controls:      click or drag pieces | U = undo | F = flip board | R = restart
               Esc = cancel promotion | mouse wheel = scroll the move list

Stockfish:     install Stockfish (https://stockfishchess.org/download/) and the game finds it
               automatically if it is on your PATH, in a common install folder, or next to this
               script. Otherwise point to it explicitly:
                   python chess_game.py /path/to/stockfish
               or set the STOCKFISH_PATH environment variable.

All pieces are drawn in code (no image files or special fonts needed).
"""
import os
import queue
import random
import shutil
import sys
import threading
import time

import pygame
import chess
import chess.engine

# -------------------- LAYOUT --------------------
WIDTH, HEIGHT = 1060, 740
BOARD_SIZE = 640
SQ = BOARD_SIZE // 8
BOARD_X, BOARD_Y = 62, 50
FRAME = 32
FPS = 60
PIECE_PX = SQ - 4

FRAME_RECT = pygame.Rect(BOARD_X - FRAME, BOARD_Y - FRAME, BOARD_SIZE + 2 * FRAME, BOARD_SIZE + 2 * FRAME)
PANEL_RECT = pygame.Rect(762, 18, 276, 704)
PANEL_PAD = 18
INNER_X = PANEL_RECT.x + PANEL_PAD
INNER_W = PANEL_RECT.w - 2 * PANEL_PAD

TOP_CARD = pygame.Rect(INNER_X, 80, INNER_W, 76)
STATUS_RECT = pygame.Rect(INNER_X, 164, INNER_W, 44)
MOVES_RECT = pygame.Rect(INNER_X, 216, INNER_W, 172)
SET_RECT = pygame.Rect(INNER_X, 396, INNER_W, 108)
SEG_RECT = pygame.Rect(INNER_X + 6, 404, INNER_W - 12, 28)
BROWSE_RECT = pygame.Rect(INNER_X + 50, 474, 140, 26)
LEVEL_RECTS = [pygame.Rect(INNER_X + 6 + i * 29, 460, 25, 28) for i in range(8)]
BOTTOM_CARD = pygame.Rect(INNER_X, 512, INNER_W, 76)
UNDO_RECT = pygame.Rect(INNER_X, 598, 72, 32)
FLIP_RECT = pygame.Rect(INNER_X + 84, 598, 72, 32)
RESTART_RECT = pygame.Rect(INNER_X + 168, 598, 72, 32)
RESIGN_RECT = pygame.Rect(INNER_X, 638, 114, 32)
DRAW_RECT = pygame.Rect(INNER_X + 126, 638, 114, 32)

# -------------------- PALETTE (walnut, brass and felt) --------------------
BG_TOP = (10, 17, 33)
BG_BOT = (20, 33, 62)
LIGHT = (236, 232, 220)
DARK = (104, 130, 170)
BOARD_EDGE = (46, 64, 102)
BRASS = (212, 175, 90)          # gold accent
BRASS_DARK = (150, 120, 60)
BRASS_LIGHT = (236, 205, 130)
PANEL_BG = (19, 29, 52)
PANEL_EDGE = (40, 56, 92)
CARD = (27, 40, 70)
CARD_EDGE = (48, 66, 106)
TEXT = (236, 240, 248)
MUTED = (140, 154, 182)
COORD = (205, 176, 120)
RED = (240, 118, 104)
NAVY_INK = (12, 20, 40)
BTN = (36, 52, 88)
BTN_HOVER = (52, 72, 118)

PIECE_VALUE = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}
START_COUNT = {chess.PAWN: 8, chess.KNIGHT: 2, chess.BISHOP: 2, chess.ROOK: 2, chess.QUEEN: 1}

# (name, Stockfish "Skill Level" 0-20, seconds per move, search depth limit)
LEVELS = [
    ("Beginner", 0, 0.05, 1),
    ("Casual", 2, 0.10, 2),
    ("Easy", 5, 0.15, 4),
    ("Club", 8, 0.25, 6),
    ("Strong", 11, 0.40, 9),
    ("Expert", 15, 0.60, None),
    ("Master", 18, 0.80, None),
    ("Maximum", 20, 1.20, None),
]
DEFAULT_LEVEL = 3
MIN_DRAW_PLY = 20        # the computer won't accept a draw offer before this many half-moves
DRAW_ACCEPT_CP = 30      # ...and only accepts if it isn't better by more than this (centipawns)
ANIM_SECONDS = 0.40      # how long a piece takes to slide to its square
AI_MIN_DELAY = 0.90      # the computer waits at least this long before moving


def app_dirs():
    """Folders searched for the logo and Stockfish: next to the .exe, the bundle, the script, the cwd."""
    dirs = []
    if getattr(sys, "frozen", False):
        dirs.append(os.path.dirname(sys.executable))
        if getattr(sys, "_MEIPASS", None):
            dirs.append(sys._MEIPASS)
    dirs.append(os.path.dirname(os.path.abspath(__file__)))
    dirs.append(os.getcwd())
    return list(dict.fromkeys(dirs))


def _is_executable(path):
    return bool(path) and os.path.isfile(path) and (os.access(path, os.X_OK) or path.lower().endswith(".exe"))


CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".iconchess_stockfish")
_SKIP_EXT = (".zip", ".tar", ".gz", ".7z", ".py", ".txt", ".md", ".png", ".ico", ".spec", ".log")


def saved_path():
    try:
        with open(CONFIG_FILE, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return None


def save_path(path):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
            fh.write(path)
    except OSError:
        pass


def _scan_tree(root, depth=3, limit=4000):
    """Find a file named stockfish* in root or up to `depth` folders below it."""
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root):
        if dirpath[len(root):].count(os.sep) >= depth:
            dirnames[:] = []
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", "build", ".git", "node_modules")]
        for name in sorted(filenames):
            seen += 1
            if seen > limit:
                return None
            low = name.lower()
            if low.startswith("stockfish") and not low.endswith(_SKIP_EXT):
                full = os.path.join(dirpath, name)
                if _is_executable(full):
                    return full
    return None


def find_stockfish():
    """Look for a Stockfish binary: argument, env var, saved choice, app folders, PATH, common spots."""
    candidates = []
    if len(sys.argv) > 1:
        candidates.append(sys.argv[1])
    candidates.append(os.environ.get("STOCKFISH_PATH"))
    candidates.append(saved_path())
    for d in app_dirs():
        candidates += [os.path.join(d, "stockfish"), os.path.join(d, "stockfish.exe")]
    candidates.append(shutil.which("stockfish"))
    candidates += ["/usr/games/stockfish", "/usr/bin/stockfish", "/usr/local/bin/stockfish",
                   "/opt/homebrew/bin/stockfish"]
    for c in candidates:
        if _is_executable(c):
            return c
    # downloaded builds have long names and often sit in nested folders
    home = os.path.expanduser("~")
    for d in app_dirs():
        if d in (home, os.path.dirname(home)) or len(d) <= 3:
            continue  # don't crawl the whole user folder or a drive root
        found = _scan_tree(d)
        if found:
            return found
    return None


def start_engine(path=None):
    """Returns (engine, note). note is None on success, else (headline, detail) for the panel."""
    path = path or find_stockfish()
    if not path:
        print("Stockfish not found. Put it next to the game, or click 'Locate Stockfish' in the panel.")
        return None, ("Stockfish not found", "Download it, then locate the .exe")
    try:
        engine = chess.engine.SimpleEngine.popen_uci(path)
        save_path(path)
        print(f"Using Stockfish at {path}")
        return engine, None
    except Exception as exc:
        detail = (str(exc) or type(exc).__name__).replace("\n", " ")
        print(f"Could not start Stockfish at {path}: {exc}")
        return None, ("Stockfish will not start", "Try the plain x86-64 build. " + detail[:60])


pygame.init()


def load_logo_raw():
    """iconchess_logo.png next to this script (or in the working folder)."""
    for folder in app_dirs():
        path = os.path.join(folder, "iconchess_logo.png")
        if os.path.isfile(path):
            try:
                return pygame.image.load(path)
            except Exception as exc:
                print(f"Could not load {path}: {exc}")
    print("iconchess_logo.png not found next to the script: using the default window icon.")
    return None


LOGO_RAW = load_logo_raw()
if LOGO_RAW is not None:
    pygame.display.set_icon(pygame.transform.smoothscale(LOGO_RAW, (64, 64)))  # before set_mode
pygame.display.set_caption("IconChess")
screen = pygame.display.set_mode((WIDTH, HEIGHT))
LOGO_UI = pygame.transform.smoothscale(LOGO_RAW.convert_alpha(), (48, 48)) if LOGO_RAW is not None else None
clock = pygame.time.Clock()

_font_cache = {}


def F(size, bold=False, serif=False):
    key = (size, bold, serif)
    if key not in _font_cache:
        if serif:
            names = "georgia,palatinolinotype,bookantiqua,dejavuserif,liberationserif,serif"
        else:
            names = "inter,segoeui,sfprodisplay,helveticaneue,helvetica,arial,liberationsans,dejavusans,freesans"
        _font_cache[key] = pygame.font.SysFont(names, size, bold=bold)
    return _font_cache[key]


def blit_text(text, font, color, **anchor):
    image = font.render(text, True, color)
    rect = image.get_rect(**anchor)
    screen.blit(image, rect)
    return rect


def fit_font(text, max_w, sizes=(22, 20, 18, 16, 14), bold=True):
    for s in sizes:
        f = F(s, bold)
        if f.size(text)[0] <= max_w:
            return f
    return F(sizes[-1], bold)


# -------------------- PIECE ARTWORK --------------------
def add_shading(surf, k):
    """Soft highlight on the left and shadow on the right, clipped to the piece shape."""
    w, h = surf.get_size()
    mask = pygame.mask.from_surface(surf, 200)
    msurf = mask.to_surface(setcolor=(255, 255, 255, 255), unsetcolor=(0, 0, 0, 0))
    hi = pygame.Surface((w, h), pygame.SRCALPHA)
    lo = pygame.Surface((w, h), pygame.SRCALPHA)
    for x in range(int(18 * k), int(46 * k)):
        t = 1 - abs(x - 32 * k) / (14 * k)
        if t > 0:
            pygame.draw.line(hi, (255, 255, 255, int(95 * t)), (x, 0), (x, h))
    for x in range(int(60 * k), int(84 * k)):
        t = (x - 60 * k) / (24 * k)
        pygame.draw.line(lo, (0, 0, 0, int(70 * t)), (x, 0), (x, h))
    hi.blit(msurf, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    lo.blit(msurf, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    surf.blit(lo, (0, 0))
    surf.blit(hi, (0, 0))


def build_piece(piece_type, white):
    """Draw a Staunton-style piece on a 100x100 design grid, supersampled 5x."""
    S = PIECE_PX * 5
    k = S / 100.0
    surf = pygame.Surface((S, S), pygame.SRCALPHA)

    fill = (252, 250, 244) if white else (30, 52, 102)
    outline = (20, 34, 68) if white else (7, 13, 32)
    detail = (20, 34, 68) if white else (222, 186, 100)
    lw = max(2, int(2.4 * k))

    def pts(points):
        return [(x * k, y * k) for x, y in points]

    def poly(points):
        p = pts(points)
        pygame.draw.polygon(surf, fill, p)
        pygame.draw.lines(surf, outline, True, p, lw)
        for qx, qy in p:
            pygame.draw.circle(surf, outline, (int(qx), int(qy)), lw // 2)

    def circ(cx, cy, r):
        c = (int(cx * k), int(cy * k))
        rr = int(r * k)
        pygame.draw.circle(surf, fill, c, rr)
        pygame.draw.circle(surf, outline, c, rr, lw)

    def ell(x, y, w, h):
        rect = pygame.Rect(int(x * k), int(y * k), int(w * k), int(h * k))
        pygame.draw.ellipse(surf, fill, rect)
        pygame.draw.ellipse(surf, outline, rect, lw)

    def line(a, b, width=1.6):
        pygame.draw.line(surf, detail, (a[0] * k, a[1] * k), (b[0] * k, b[1] * k), max(1, int(width * k)))

    def dot(cx, cy, r):
        pygame.draw.circle(surf, detail, (int(cx * k), int(cy * k)), max(1, int(r * k)))

    def plinth():
        poly([(73, 80), (79, 86), (76, 92), (24, 92), (21, 86), (27, 80)])
        line((22, 86), (78, 86), 1.0)

    # contact shadow
    pygame.draw.ellipse(surf, (0, 0, 0, 70),
                        pygame.Rect(int(14 * k), int(85 * k), int(72 * k), int(12 * k)))

    if piece_type == chess.PAWN:
        poly([(54, 46), (57, 52), (62, 66), (68, 80), (32, 80), (38, 66), (43, 52), (46, 46)])
        ell(37, 42, 26, 9)
        circ(50, 31, 12)
        plinth()

    elif piece_type == chess.ROOK:
        poly([(64, 38), (65, 62), (70, 80), (30, 80), (35, 62), (36, 38)])
        poly([(28, 16), (38, 16), (38, 22), (45, 22), (45, 16), (55, 16), (55, 22),
              (62, 22), (62, 16), (72, 16), (72, 34), (66, 38), (34, 38), (28, 34)])
        poly([(32, 58), (68, 58), (68, 65), (32, 65)])
        plinth()

    elif piece_type == chess.BISHOP:
        poly([(56, 52), (60, 66), (68, 80), (32, 80), (40, 66), (44, 52)])
        ell(32, 54, 36, 9)
        circ(50, 16, 5)
        ell(37, 22, 26, 34)
        line((55, 31), (46, 42), 2.0)
        plinth()

    elif piece_type == chess.KNIGHT:
        poly([(72, 80), (71, 58), (66, 38), (58, 24), (50, 15), (46, 23), (36, 30),
              (24, 43), (19, 51), (23, 58), (31, 57), (40, 50), (46, 46), (36, 62), (28, 80)])
        line((57, 29), (64, 50), 1.6)
        line((51, 27), (57, 44), 1.4)
        dot(38, 37, 2.6)
        dot(23, 51, 1.6)
        plinth()

    elif piece_type == chess.QUEEN:
        poly([(66, 58), (72, 80), (28, 80), (34, 58)])
        poly([(25, 24), (32, 44), (38, 20), (44, 42), (50, 15), (56, 42), (62, 20),
              (68, 44), (75, 24), (66, 62), (34, 62)])
        ell(31, 58, 38, 9)
        for cx, cy in [(25, 22), (38, 17), (50, 12), (62, 17), (75, 22)]:
            circ(cx, cy, 4.5)
        plinth()

    elif piece_type == chess.KING:
        poly([(66, 52), (72, 80), (28, 80), (34, 52)])
        ell(33, 30, 34, 30)
        ell(30, 56, 40, 9)
        poly([(46, 6), (54, 6), (54, 12), (61, 12), (61, 19), (54, 19), (54, 32),
              (46, 32), (46, 19), (39, 19), (39, 12), (46, 12)])
        plinth()

    add_shading(surf, k)
    small = pygame.transform.smoothscale(surf, (PIECE_PX, PIECE_PX))
    return small.convert_alpha()


PIECES = {}
MINI = {}
for _color in (chess.WHITE, chess.BLACK):
    for _pt in range(1, 7):
        PIECES[(_color, _pt)] = build_piece(_pt, _color == chess.WHITE)
        MINI[(_color, _pt)] = pygame.transform.smoothscale(PIECES[(_color, _pt)], (24, 24)).convert_alpha()


# -------------------- STATIC SURFACES --------------------
def build_board_surface():
    surf = pygame.Surface((BOARD_SIZE, BOARD_SIZE))
    for row in range(8):
        for col in range(8):
            color = LIGHT if (row + col) % 2 == 0 else DARK
            surf.fill(color, pygame.Rect(col * SQ, row * SQ, SQ, SQ))
    return surf


def build_static_bg():
    bg = pygame.Surface((WIDTH, HEIGHT))
    for y in range(HEIGHT):
        t = y / (HEIGHT - 1)
        pygame.draw.line(bg, tuple(int(BG_TOP[i] + (BG_BOT[i] - BG_TOP[i]) * t) for i in range(3)),
                         (0, y), (WIDTH, y))

    board_rect = pygame.Rect(BOARD_X, BOARD_Y, BOARD_SIZE, BOARD_SIZE)

    # soft shadows under the board and the panel
    shadow = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    for target in (board_rect, PANEL_RECT):
        for i in range(14, 0, -1):
            rect = target.move(0, 8).inflate(i * 2, i * 2)
            pygame.draw.rect(shadow, (0, 0, 0, int(6 + (14 - i) * 5)), rect, border_radius=10 + i)
    bg.blit(shadow, (0, 0))

    bg.blit(build_board_surface(), board_rect.topleft)
    pygame.draw.rect(bg, BOARD_EDGE, board_rect.inflate(2, 2), 1)

    # side panel with logo and wordmark
    pygame.draw.rect(bg, PANEL_BG, PANEL_RECT, border_radius=18)
    pygame.draw.rect(bg, PANEL_EDGE, PANEL_RECT, 1, border_radius=18)
    text_x = INNER_X
    if LOGO_UI is not None:
        bg.blit(LOGO_UI, (INNER_X, 26))
        text_x = INNER_X + 60
    word = F(30, True).render("IconChess", True, TEXT)
    bg.blit(word, word.get_rect(midleft=(text_x, 50)))
    pygame.draw.line(bg, BRASS, (text_x, 68), (text_x + 44, 68), 3)
    return bg


def make_overlay(color):
    s = pygame.Surface((SQ, SQ), pygame.SRCALPHA)
    s.fill(color)
    return s


def make_check_overlay():
    s = pygame.Surface((SQ, SQ), pygame.SRCALPHA)
    start = int(SQ * 0.72)
    for r in range(start, 0, -1):
        t = 1 - r / start
        pygame.draw.circle(s, (225, 45, 45, int(40 + 190 * t ** 0.8)), (SQ // 2, SQ // 2), r)
    return s


def make_dot():
    s = pygame.Surface((SQ, SQ), pygame.SRCALPHA)
    pygame.draw.circle(s, (30, 30, 30, 95), (SQ // 2, SQ // 2), 11)
    return s


def make_ring():
    s = pygame.Surface((SQ, SQ), pygame.SRCALPHA)
    pygame.draw.circle(s, (30, 30, 30, 95), (SQ // 2, SQ // 2), SQ // 2 - 4, 7)
    return s


STATIC_BG = build_static_bg()
OV_LAST = make_overlay((246, 206, 84, 100))
OV_SEL = make_overlay((255, 226, 110, 150))
OV_CHECK = make_check_overlay()
OV_DOT = make_dot()
OV_RING = make_ring()


def button(rect, label, mouse, enabled=True):
    hover = enabled and rect.collidepoint(mouse)
    pygame.draw.rect(screen, BTN_HOVER if hover else BTN, rect, border_radius=12)
    if hover:
        pygame.draw.rect(screen, BRASS, rect, 1, border_radius=12)
    blit_text(label, F(15, True), TEXT if enabled else (92, 105, 132), center=rect.center)


# -------------------- GAME --------------------
class Game:
    def __init__(self, engine=None):
        self.engine = engine
        self.engine_note = None
        self.engine_lock = threading.Lock()
        self.results = queue.Queue()
        self.gen = 0
        self.thinking = False
        self.mode = "two"          # "two", "white" or "black" (the side you play against the computer)
        self.human = None          # chess.WHITE / chess.BLACK, or None for two players
        self.level = DEFAULT_LEVEL
        self.anim = None
        self.pending_move = None
        self.ai_started = 0.0
        self.promo_animate = True
        self.result = None         # (text, kind) once someone resigns or a draw is agreed
        self.dialog = None         # "resign" or "draw" confirmation shown over the board
        self.toast = None          # (text, expiry) short message shown in the status box
        self.draw_pending = False  # waiting for the computer to answer a draw offer
        self.declined_ply = -1
        self.draw_results = queue.Queue()
        self.board = chess.Board()
        self.selected = None
        self.targets = []
        self.last_move = None
        self.promo = None  # (from_square, to_square) while choosing a promotion piece
        self.flipped = False
        self.dragging = False
        self.drag_origin = (0, 0)
        self.drag_pos = (0, 0)
        self.scroll = 0
        self._san_key = None
        self._san_cache = []

    # ---- coordinate helpers ----
    def square_rect(self, sq):
        file, rank = chess.square_file(sq), chess.square_rank(sq)
        col, row = (7 - file, rank) if self.flipped else (file, 7 - rank)
        return pygame.Rect(BOARD_X + col * SQ, BOARD_Y + row * SQ, SQ, SQ)

    def pos_to_square(self, pos):
        x, y = pos
        if not (BOARD_X <= x < BOARD_X + BOARD_SIZE and BOARD_Y <= y < BOARD_Y + BOARD_SIZE):
            return None
        col, row = (x - BOARD_X) // SQ, (y - BOARD_Y) // SQ
        if self.flipped:
            return chess.square(7 - col, row)
        return chess.square(col, 7 - row)

    # ---- state changes ----
    def clear_selection(self):
        self.selected = None
        self.targets = []
        self.dragging = False

    def bump_gen(self):
        """Invalidate any computer move that is still being calculated."""
        self.gen += 1
        self.thinking = False
        self.pending_move = None
        self.draw_pending = False
        self.toast = None

    def reset(self):
        self.bump_gen()
        self.anim = None
        self.result = None
        self.dialog = None
        self.declined_ply = -1
        self.board = chess.Board()
        self.clear_selection()
        self.last_move = None
        self.promo = None
        self.scroll = 0

    def set_mode(self, mode):
        self.mode = mode
        self.human = {"two": None, "white": chess.WHITE, "black": chess.BLACK}[mode]
        self.reset()
        self.flipped = mode == "black"

    def is_over(self):
        return self.result is not None or self.board.is_game_over()

    def undo(self):
        if self.result is not None:  # undo takes back a resignation or agreed draw
            self.result = None
            self.bump_gen()
            return
        # against the computer, undo takes back your move and its reply
        if self.human is None or self.board.turn != self.human:
            n = 1
        else:
            n = 2
        if len(self.board.move_stack) < n:
            return
        for _ in range(n):
            self.board.pop()
        self.bump_gen()
        self.anim = None
        self.last_move = self.board.peek() if self.board.move_stack else None
        self.clear_selection()
        self.promo = None
        self.scroll = 0

    def begin_anim(self, move):
        b = self.board
        items = [(b.piece_at(move.from_square), move.from_square, move.to_square)]
        captured = None
        if b.is_en_passant(move):
            csq = chess.square(chess.square_file(move.to_square), chess.square_rank(move.from_square))
            captured = (b.piece_at(csq), csq)
        elif b.is_capture(move):
            captured = (b.piece_at(move.to_square), move.to_square)
        if captured and captured[0] is None:
            captured = None
        if b.is_castling(move):
            rank = chess.square_rank(move.from_square)
            if b.is_kingside_castling(move):
                rook_from, rook_to = chess.square(7, rank), chess.square(5, rank)
            else:
                rook_from, rook_to = chess.square(0, rank), chess.square(3, rank)
            items.append((b.piece_at(rook_from), rook_from, rook_to))
        self.anim = {"items": items, "captured": captured, "start": time.monotonic()}

    def anim_state(self):
        """Returns (animation, eased progress) while a piece is sliding, else None."""
        if not self.anim:
            return None
        t = (time.monotonic() - self.anim["start"]) / ANIM_SECONDS
        if t >= 1:
            self.anim = None
            return None
        return self.anim, t * t * (3 - 2 * t)

    def push(self, move, animate=False):
        if move in self.board.legal_moves:
            if animate:
                self.begin_anim(move)
            else:
                self.anim = None
            self.board.push(move)
            self.last_move = move
        self.clear_selection()
        self.promo = None
        self.scroll = 0

    def targets_from(self, sq):
        return list({m.to_square for m in self.board.legal_moves if m.from_square == sq})

    def try_move(self, from_sq, to_sq, animate=True):
        candidates = [m for m in self.board.legal_moves
                      if m.from_square == from_sq and m.to_square == to_sq]
        if not candidates:
            return
        if any(m.promotion for m in candidates):
            self.promo = (from_sq, to_sq)
            self.promo_animate = animate
            self.dragging = False
        else:
            self.push(candidates[0], animate=animate)

    # ---- input ----
    def mouse_down(self, pos):
        sq = self.pos_to_square(pos)
        if sq is None:
            self.clear_selection()
            return
        if not self.human_can_move():
            return
        if self.selected is not None and sq in self.targets:
            self.try_move(self.selected, sq)
            return
        piece = self.board.piece_at(sq)
        if piece and piece.color == self.board.turn:
            self.selected = sq
            self.targets = self.targets_from(sq)
            self.dragging = True
            self.drag_origin = pos
            self.drag_pos = pos
        else:
            self.clear_selection()

    def mouse_up(self, pos):
        if not self.dragging:
            return
        self.dragging = False
        sq = self.pos_to_square(pos)
        if sq is not None and self.selected is not None and sq != self.selected and sq in self.targets:
            self.try_move(self.selected, sq, animate=False)  # a dropped piece is already in place

    def scroll_moves(self, dy):
        self.scroll += dy

    def promo_layout(self):
        panel = pygame.Rect(0, 0, 420, 200)
        panel.center = (BOARD_X + BOARD_SIZE // 2, BOARD_Y + BOARD_SIZE // 2)
        rects = []
        for i, pt in enumerate((chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT)):
            rects.append((pygame.Rect(panel.x + 16 + i * 100, panel.y + 68, 88, 112), pt))
        return panel, rects

    def promo_click(self, pos):
        _, rects = self.promo_layout()
        for rect, pt in rects:
            if rect.collidepoint(pos):
                f, t = self.promo
                self.push(chess.Move(f, t, promotion=pt), animate=self.promo_animate)
                return
        self.promo = None
        self.clear_selection()

    def human_can_move(self):
        if self.is_over() or self.draw_pending:
            return False
        return self.human is None or self.board.turn == self.human

    # ---- computer player ----
    def ai_turn(self):
        return (self.engine is not None and self.human is not None and
                not self.is_over() and self.board.turn != self.human and
                self.promo is None)

    def start_ai(self):
        self.thinking = True
        self.pending_move = None
        self.ai_started = time.monotonic()
        _, skill, secs, depth = LEVELS[self.level]
        threading.Thread(target=self._ai_worker,
                         args=(self.gen, self.board.copy(), skill, secs, depth),
                         daemon=True).start()

    def _ai_worker(self, gen, board, skill, secs, depth):
        try:
            with self.engine_lock:
                try:
                    self.engine.configure({"Skill Level": skill})
                except Exception:
                    pass  # engine without a Skill Level option
                result = self.engine.play(board, chess.engine.Limit(time=secs, depth=depth))
            self.results.put((gen, result.move, None))
        except Exception as exc:
            self.results.put((gen, None, str(exc)))

    def poll_ai(self):
        while True:
            try:
                gen, move, err = self.results.get_nowait()
            except queue.Empty:
                break
            if gen != self.gen:
                continue  # stale result from before an undo, restart or mode change
            if err:
                print(f"Stockfish stopped: {err}")
                self.engine = None
                self.engine_note = ("Stockfish stopped", err[:60])
                self.set_mode("two")
                return
            if move is None:
                self.thinking = False
            else:
                self.pending_move = move

        # hold the move back so the computer doesn't answer instantly
        if (self.pending_move is not None and self.anim_state() is None and
                time.monotonic() - self.ai_started >= AI_MIN_DELAY):
            move, self.pending_move = self.pending_move, None
            self.thinking = False
            if self.ai_turn() and move in self.board.legal_moves:
                self.push(move, animate=True)

    def show_toast(self, text, secs=3.0):
        self.toast = (text, time.monotonic() + secs)

    def request_resign(self):
        if not self.is_over():
            self.dialog = "resign"

    def request_draw(self):
        if self.is_over() or not self.human_can_move():
            return
        ply = len(self.board.move_stack)
        if ply == self.declined_ply:
            self.show_toast("Make a move before offering again")
            return
        if self.human is None:
            self.dialog = "draw"
        elif ply < MIN_DRAW_PLY:
            self.declined_ply = ply
            self.show_toast("Computer: too early for a draw")
        else:
            self.draw_pending = True
            self.show_toast("Draw offered, waiting for reply", 30)
            threading.Thread(target=self._draw_worker, args=(self.gen, self.board.copy()),
                             daemon=True).start()

    def _draw_worker(self, gen, board):
        try:
            with self.engine_lock:
                info = self.engine.analyse(board, chess.engine.Limit(time=0.4))
            cp = info["score"].pov(not self.human).score(mate_score=10000)
            self.draw_results.put((gen, cp is not None and cp <= DRAW_ACCEPT_CP, None))
        except Exception as exc:
            self.draw_results.put((gen, False, str(exc)))

    def poll_draw(self):
        while True:
            try:
                gen, accept, err = self.draw_results.get_nowait()
            except queue.Empty:
                return
            if gen != self.gen:
                continue
            self.draw_pending = False
            if err:
                self.show_toast("Computer could not answer the offer")
            elif accept:
                self.agree_draw()
            else:
                self.declined_ply = len(self.board.move_stack)
                self.show_toast("Computer declines the draw")

    def agree_draw(self):
        self.result = ("Draw by agreement", "draw")
        self.toast = None
        self.bump_gen()
        self.clear_selection()

    def confirm_resign(self):
        loser = self.human if self.human is not None else self.board.turn
        if self.human is None:
            text = f"{'White' if loser else 'Black'} resigns: {'Black' if loser else 'White'} wins"
        else:
            text = "You resigned: computer wins"
        self.result = (text, "mate")
        self.bump_gen()
        self.clear_selection()
        self.promo = None

    def dialog_layout(self):
        panel = pygame.Rect(0, 0, 420, 170)
        panel.center = (BOARD_X + BOARD_SIZE // 2, BOARD_Y + BOARD_SIZE // 2)
        yes = pygame.Rect(panel.x + 30, panel.bottom - 66, 170, 44)
        no = pygame.Rect(panel.right - 200, panel.bottom - 66, 170, 44)
        return panel, yes, no

    def dialog_answer(self, yes):
        kind, self.dialog = self.dialog, None
        if kind == "resign":
            if yes:
                self.confirm_resign()
        elif kind == "draw":
            if yes:
                self.agree_draw()
            else:
                self.declined_ply = len(self.board.move_stack)
                self.show_toast("Draw offer declined")

    def dialog_click(self, pos):
        panel, yes, no = self.dialog_layout()
        if yes.collidepoint(pos):
            self.dialog_answer(True)
        elif no.collidepoint(pos):
            self.dialog_answer(False)
        elif self.dialog == "resign" and not panel.collidepoint(pos):
            self.dialog_answer(False)

    def update(self, mouse):
        if self.dragging:
            self.drag_pos = mouse
        self.poll_draw()
        self.poll_ai()
        if self.ai_turn() and not self.thinking:
            self.start_ai()

    def locate_stockfish(self):
        """Let the player pick the Stockfish program with a file dialog."""
        try:
            import tkinter
            from tkinter import filedialog
            root = tkinter.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            path = filedialog.askopenfilename(title="Select the Stockfish program",
                                              filetypes=[("All files", "*.*")])
            root.destroy()
        except Exception as exc:
            self.engine_note = ("Could not open file picker", str(exc)[:60])
            return
        if not path:
            return
        engine, note = start_engine(path)
        self.engine, self.engine_note = engine, note
        if engine:
            self.set_mode("white")

    def settings_click(self, pos):
        if self.engine is None and BROWSE_RECT.collidepoint(pos):
            self.locate_stockfish()
            return True
        if SEG_RECT.collidepoint(pos):
            i = min(2, (pos[0] - SEG_RECT.x) // (SEG_RECT.w // 3))
            mode = ("two", "white", "black")[i]
            if mode != "two" and self.engine is None:
                return True
            if mode != self.mode:
                self.set_mode(mode)
            return True
        if self.human is not None:
            for i, rect in enumerate(LEVEL_RECTS):
                if rect.collidepoint(pos):
                    self.level = i
                    return True
        return SET_RECT.collidepoint(pos)

    # ---- status ----
    def status(self):
        if self.result:
            return self.result
        b = self.board
        if b.is_checkmate():
            winner = not b.turn
            if self.human is None:
                who = "White" if winner else "Black"
            else:
                who = "you" if winner == self.human else "the computer"
            return f"Checkmate: {who} wins", "mate"
        if b.is_stalemate():
            return "Draw by stalemate", "draw"
        if b.is_insufficient_material():
            return "Draw: insufficient material", "draw"
        if b.is_fivefold_repetition():
            return "Draw: fivefold repetition", "draw"
        if b.is_seventyfive_moves():
            return "Draw: 75-move rule", "draw"
        if self.toast and time.monotonic() < self.toast[1]:
            return self.toast[0], "draw"
        if self.human is not None:
            mine = b.turn == self.human
            if b.is_check():
                return ("You are in check" if mine else "Computer is in check"), "check"
            return ("Your move" if mine else "Computer is thinking"), "normal"
        side = "White" if b.turn else "Black"
        if b.is_check():
            return f"{side} is in check", "check"
        return f"{side} to move", "normal"

    def san_list(self):
        stack = tuple(self.board.move_stack)
        if stack != self._san_key:
            tmp = chess.Board()
            sans = []
            for mv in stack:
                sans.append(tmp.san(mv))
                tmp.push(mv)
            self._san_cache = sans
            self._san_key = stack
        return self._san_cache

    def missing(self, color):
        out = []
        for pt in (chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT, chess.PAWN):
            n = START_COUNT[pt] - len(self.board.pieces(pt, color))
            out += [pt] * max(0, n)
        return out

    def material(self, color):
        return sum(v * len(self.board.pieces(pt, color)) for pt, v in PIECE_VALUE.items())

    # ---- drawing ----
    def draw(self, mouse):
        screen.blit(STATIC_BG, (0, 0))
        self.draw_board(mouse)
        self.draw_panel(mouse)
        if self.promo:
            self.draw_promotion(mouse)
        if self.dialog:
            self.draw_dialog(mouse)

    def draw_board(self, mouse):
        board = self.board

        # coordinates inside the edge squares
        for i in range(8):
            file = 7 - i if self.flipped else i
            col_color = DARK if (7 + i) % 2 == 0 else LIGHT
            img = F(14, True).render(chr(97 + file), True, col_color)
            screen.blit(img, img.get_rect(bottomright=(BOARD_X + (i + 1) * SQ - 6, BOARD_Y + BOARD_SIZE - 4)))
            label = str(i + 1) if self.flipped else str(8 - i)
            row_color = DARK if i % 2 == 0 else LIGHT
            img = F(14, True).render(label, True, row_color)
            screen.blit(img, img.get_rect(topleft=(BOARD_X + 6, BOARD_Y + i * SQ + 4)))

        drag_visible = (self.dragging and self.selected is not None and
                        abs(self.drag_pos[0] - self.drag_origin[0]) +
                        abs(self.drag_pos[1] - self.drag_origin[1]) > 6)

        # highlights
        for sq in chess.SQUARES:
            rect = self.square_rect(sq)
            if self.last_move and sq in (self.last_move.from_square, self.last_move.to_square):
                screen.blit(OV_LAST, rect.topleft)
            if sq == self.selected:
                screen.blit(OV_SEL, rect.topleft)
        if board.is_check():
            ksq = board.king(board.turn)
            if ksq is not None:
                screen.blit(OV_CHECK, self.square_rect(ksq).topleft)

        # pieces
        anim_state = self.anim_state()
        skip = {to for _, _, to in anim_state[0]["items"]} if anim_state else set()
        for sq in chess.SQUARES:
            piece = board.piece_at(sq)
            if not piece or sq in skip or (drag_visible and sq == self.selected):
                continue
            sprite = PIECES[(piece.color, piece.piece_type)]
            rect = self.square_rect(sq)
            screen.blit(sprite, sprite.get_rect(center=(rect.centerx, rect.centery + 2)))

        # sliding piece(s); a captured piece stays put until the mover arrives
        if anim_state:
            anim, e = anim_state
            if anim["captured"]:
                cpiece, csq = anim["captured"]
                crect = self.square_rect(csq)
                csprite = PIECES[(cpiece.color, cpiece.piece_type)]
                screen.blit(csprite, csprite.get_rect(center=(crect.centerx, crect.centery + 2)))
            for apiece, frm, to in anim["items"]:
                a = self.square_rect(frm).center
                b = self.square_rect(to).center
                cx = a[0] + (b[0] - a[0]) * e
                cy = a[1] + (b[1] - a[1]) * e
                asprite = PIECES[(apiece.color, apiece.piece_type)]
                screen.blit(asprite, asprite.get_rect(center=(int(cx), int(cy) + 2)))

        # legal move markers
        if self.selected is not None and not self.promo:
            sel_piece = board.piece_at(self.selected)
            for t in self.targets:
                capture = board.piece_at(t) is not None or (
                    sel_piece and sel_piece.piece_type == chess.PAWN and
                    chess.square_file(t) != chess.square_file(self.selected))
                screen.blit(OV_RING if capture else OV_DOT, self.square_rect(t).topleft)

        # hover outline
        if not self.promo and not self.dragging:
            hs = self.pos_to_square(mouse)
            if hs is not None and self.human_can_move():
                piece = board.piece_at(hs)
                if hs in self.targets or (piece and piece.color == board.turn):
                    pygame.draw.rect(screen, BRASS_LIGHT, self.square_rect(hs).inflate(-4, -4), 3, border_radius=4)

        # piece being dragged
        if drag_visible:
            piece = board.piece_at(self.selected)
            if piece:
                sprite = PIECES[(piece.color, piece.piece_type)]
                screen.blit(sprite, sprite.get_rect(center=self.drag_pos))

    def draw_panel(self, mouse):
        top_color = chess.WHITE if self.flipped else chess.BLACK
        self.draw_card(TOP_CARD, top_color)
        self.draw_status(STATUS_RECT)
        self.draw_moves(MOVES_RECT)
        self.draw_settings(mouse)
        self.draw_card(BOTTOM_CARD, not top_color)

        button(UNDO_RECT, "Undo", mouse)
        button(FLIP_RECT, "Flip", mouse)
        button(RESTART_RECT, "Restart", mouse)
        button(RESIGN_RECT, "Resign", mouse, enabled=not self.is_over())
        button(DRAW_RECT, "Offer draw", mouse, enabled=self.human_can_move())
        blit_text("U undo    F flip    R restart", F(13), MUTED, center=(PANEL_RECT.centerx, 698))

    def draw_settings(self, mouse):
        pygame.draw.rect(screen, CARD, SET_RECT, border_radius=12)
        pygame.draw.rect(screen, CARD_EDGE, SET_RECT, 1, border_radius=12)
        pygame.draw.rect(screen, BTN, SEG_RECT, border_radius=8)

        seg_w = SEG_RECT.w // 3
        for i, (label, mode) in enumerate((("2 players", "two"), ("Play White", "white"), ("Play Black", "black"))):
            r = pygame.Rect(SEG_RECT.x + i * seg_w, SEG_RECT.y, seg_w, SEG_RECT.h)
            disabled = mode != "two" and self.engine is None
            selected = self.mode == mode
            if selected:
                pygame.draw.rect(screen, BRASS, r, border_radius=8)
            elif r.collidepoint(mouse) and not disabled:
                pygame.draw.rect(screen, BTN_HOVER, r, border_radius=8)
            color = NAVY_INK if selected else (MUTED if disabled else TEXT)
            blit_text(label, F(13, True), color, center=r.center)

        if self.engine is None:
            head, detail = self.engine_note or ("Stockfish not found", "Locate the Stockfish program")
            blit_text(head, F(14, True), RED, center=(SET_RECT.centerx, 446))
            blit_text(detail, fit_font(detail, SET_RECT.w - 16, (12, 11, 10), False), MUTED,
                      center=(SET_RECT.centerx, 463))
            button(BROWSE_RECT, "Locate Stockfish", mouse)
        elif self.human is None:
            blit_text("Pass and play on one screen", F(14), MUTED, center=(SET_RECT.centerx, 464))
        else:
            blit_text(f"Computer level {self.level + 1}: {LEVELS[self.level][0]}", F(15, True), TEXT,
                      center=(SET_RECT.centerx, 447))
            for i, rect in enumerate(LEVEL_RECTS):
                selected = i == self.level
                filled = i < self.level
                if selected:
                    bg = BRASS
                elif filled:
                    bg = (150, 122, 62)
                else:
                    bg = BTN_HOVER if rect.collidepoint(mouse) else BTN
                pygame.draw.rect(screen, bg, rect, border_radius=6)
                pygame.draw.rect(screen, BRASS if rect.collidepoint(mouse) else CARD_EDGE, rect, 1, border_radius=6)
                blit_text(str(i + 1), F(13, True), NAVY_INK if selected else TEXT, center=rect.center)

    def draw_card(self, rect, color):
        active = self.board.turn == color and not self.is_over()
        pygame.draw.rect(screen, CARD, rect, border_radius=12)
        pygame.draw.rect(screen, BRASS if active else CARD_EDGE, rect, 2 if active else 1, border_radius=12)

        cx, cy = rect.x + 24, rect.y + 24
        pygame.draw.circle(screen, (250, 250, 246) if color else (30, 52, 102), (cx, cy), 10)
        pygame.draw.circle(screen, (120, 140, 175), (cx, cy), 10, 2)
        name = "White" if color else "Black"
        if self.human is not None:
            name += " (You)" if color == self.human else " (CPU)"
        blit_text(name, F(20, True), TEXT, midleft=(rect.x + 44, cy))

        # captured pieces and material lead
        x = rect.x + 14
        for pt in self.missing(not color):
            screen.blit(MINI[(not color, pt)], (x, rect.y + 46))
            x += 14
        lead = self.material(color) - self.material(not color)
        if lead > 0:
            blit_text(f"+{lead}", F(18, True), BRASS_LIGHT, midright=(rect.right - 14, cy))

    def draw_status(self, rect):
        text, kind = self.status()
        edge = {"check": RED, "mate": BRASS, "draw": MUTED}.get(kind, CARD_EDGE)
        pygame.draw.rect(screen, CARD, rect, border_radius=12)
        pygame.draw.rect(screen, edge, rect, 2 if kind != "normal" else 1, border_radius=12)
        color = {"check": RED, "mate": BRASS_LIGHT}.get(kind, TEXT)
        if kind in ("normal", "check"):
            cx, cy = rect.x + 24, rect.centery
            pygame.draw.circle(screen, (250, 250, 246) if self.board.turn else (30, 52, 102), (cx, cy), 9)
            pygame.draw.circle(screen, (120, 140, 175), (cx, cy), 9, 2)
            font = fit_font(text, rect.w - 60)
            blit_text(text, font, color, midleft=(rect.x + 44, cy))
        else:
            font = fit_font(text, rect.w - 24)
            blit_text(text, font, color, center=rect.center)

    def draw_moves(self, rect):
        pygame.draw.rect(screen, CARD, rect, border_radius=12)
        pygame.draw.rect(screen, CARD_EDGE, rect, 1, border_radius=12)
        sans = self.san_list()
        if not sans:
            blit_text("Moves will appear here", F(16), MUTED, center=rect.center)
            return

        rows = [(i // 2 + 1, sans[i], sans[i + 1] if i + 1 < len(sans) else "")
                for i in range(0, len(sans), 2)]
        row_h = 26
        visible = (rect.h - 16) // row_h
        max_scroll = max(0, len(rows) - visible)
        self.scroll = max(0, min(self.scroll, max_scroll))
        start = max(0, len(rows) - visible - self.scroll)

        last_ply = len(sans) - 1
        font = F(17)
        col_x = (rect.x + 56, rect.x + 148)
        for idx, (num, white_san, black_san) in enumerate(rows[start:start + visible]):
            row_i = start + idx
            y = rect.y + 8 + idx * row_h
            if row_i % 2 == 0:
                pygame.draw.rect(screen, (33, 48, 82), (rect.x + 6, y, rect.w - 12, row_h), border_radius=6)
            if last_ply // 2 == row_i:
                cell_x = col_x[last_ply % 2] - 8
                pygame.draw.rect(screen, (52, 74, 124), (cell_x, y + 2, 82, row_h - 4), border_radius=6)
            cy = y + row_h // 2
            blit_text(f"{num}.", font, MUTED, midleft=(rect.x + 14, cy))
            blit_text(white_san, font, TEXT, midleft=(col_x[0], cy))
            if black_san:
                blit_text(black_san, font, TEXT, midleft=(col_x[1], cy))

    def draw_dialog(self, mouse):
        shade = pygame.Surface((BOARD_SIZE, BOARD_SIZE), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 150))
        screen.blit(shade, (BOARD_X, BOARD_Y))

        panel, yes, no = self.dialog_layout()
        pygame.draw.rect(screen, PANEL_BG, panel, border_radius=14)
        pygame.draw.rect(screen, BRASS, panel, 2, border_radius=14)

        if self.dialog == "resign":
            if self.human is None:
                who = "White" if self.board.turn else "Black"
                title, sub = f"{who}, resign the game?", f"{who} will lose the game."
            else:
                title, sub = "Resign the game?", "The computer will win."
            labels = ("Resign", "Keep playing")
        else:
            who = "White" if self.board.turn else "Black"
            other = "Black" if self.board.turn else "White"
            title, sub = f"{who} offers a draw", f"{other}, do you accept?"
            labels = ("Accept", "Decline")
        blit_text(title, F(22, True), TEXT, center=(panel.centerx, panel.y + 34))
        blit_text(sub, F(16), MUTED, center=(panel.centerx, panel.y + 66))

        for rect, label, primary in ((yes, labels[0], True), (no, labels[1], False)):
            hover = rect.collidepoint(mouse)
            base = (150, 122, 62) if primary else BTN
            pygame.draw.rect(screen, tuple(min(255, v + 18) for v in base) if hover else base, rect, border_radius=10)
            pygame.draw.rect(screen, BRASS if (hover or primary) else CARD_EDGE, rect, 1, border_radius=10)
            blit_text(label, F(17, True), TEXT, center=rect.center)

    def draw_promotion(self, mouse):
        shade = pygame.Surface((BOARD_SIZE, BOARD_SIZE), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 150))
        screen.blit(shade, (BOARD_X, BOARD_Y))

        panel, rects = self.promo_layout()
        pygame.draw.rect(screen, PANEL_BG, panel, border_radius=14)
        pygame.draw.rect(screen, BRASS, panel, 2, border_radius=14)
        blit_text("Choose a piece to promote to", F(20, True), TEXT, center=(panel.centerx, panel.y + 34))

        names = {chess.QUEEN: "Queen", chess.ROOK: "Rook", chess.BISHOP: "Bishop", chess.KNIGHT: "Knight"}
        for rect, pt in rects:
            hover = rect.collidepoint(mouse)
            pygame.draw.rect(screen, BTN_HOVER if hover else BTN, rect, border_radius=10)
            pygame.draw.rect(screen, BRASS if hover else CARD_EDGE, rect, 2 if hover else 1, border_radius=10)
            sprite = PIECES[(self.board.turn, pt)]
            screen.blit(sprite, sprite.get_rect(center=(rect.centerx, rect.centery - 10)))
            blit_text(names[pt], F(14), TEXT, center=(rect.centerx, rect.bottom - 14))


def main():
    engine, note = start_engine()
    game = Game(engine)
    game.engine_note = note
    if engine:
        game.set_mode("white")
    running = True

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.KEYDOWN:
                if game.dialog:
                    if event.key == pygame.K_ESCAPE:
                        game.dialog_answer(False)
                elif event.key == pygame.K_ESCAPE and game.promo:
                    game.promo = None
                    game.clear_selection()
                elif not game.promo:
                    if event.key == pygame.K_u:
                        game.undo()
                    elif event.key == pygame.K_f:
                        game.flipped = not game.flipped
                    elif event.key == pygame.K_r:
                        game.reset()

            elif event.type == pygame.MOUSEWHEEL:
                game.scroll_moves(event.y)

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if game.dialog:
                    game.dialog_click(event.pos)
                elif game.promo:
                    game.promo_click(event.pos)
                elif UNDO_RECT.collidepoint(event.pos):
                    game.undo()
                elif FLIP_RECT.collidepoint(event.pos):
                    game.flipped = not game.flipped
                elif RESTART_RECT.collidepoint(event.pos):
                    game.reset()
                elif RESIGN_RECT.collidepoint(event.pos):
                    game.request_resign()
                elif DRAW_RECT.collidepoint(event.pos):
                    game.request_draw()
                elif game.settings_click(event.pos):
                    pass
                else:
                    game.mouse_down(event.pos)

            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                game.mouse_up(event.pos)

        mouse = pygame.mouse.get_pos()
        game.update(mouse)
        game.draw(mouse)
        pygame.display.flip()
        clock.tick(FPS)

    if game.engine:
        try:
            game.engine.close()
        except Exception:
            pass
    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()