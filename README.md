# IconChess

A modern chess game for desktop, built with Python, pygame and python-chess.
Play a friend on one screen, or play against Stockfish at 8 difficulty levels.

## Features
- Navy and gold interface with hand-drawn pieces (no image files needed for the pieces)
- Click-to-move and drag-and-drop, with smooth sliding animations
- Legal move hints, last-move and check highlights, pawn promotion, castling and en passant
- Move list in standard notation, captured pieces and material count
- Play vs Stockfish (8 levels) or two players on one computer
- Resign, offer a draw, undo, flip the board

## Run from source
```
pip install -r requirements.txt
python chess_game.py
```

## Stockfish (computer opponent)
Stockfish is a separate program and is not included in this repository.

1. Download it from https://stockfishchess.org/download/ and unzip it.
2. Start the game and click **Locate Stockfish** to pick the `.exe` (it is remembered afterwards),
   or put the Stockfish file next to `chess_game.py`.
3. You can also run `python chess_game.py /path/to/stockfish` or set the `STOCKFISH_PATH` environment variable.

Without Stockfish the two-player mode still works.

## Controls
| Key | Action |
| --- | --- |
| U | Undo |
| F | Flip board |
| R | Restart |
| Esc | Cancel promotion / close a prompt |

## Build a Windows exe
```
pip install pyinstaller
python -m PyInstaller --onefile --windowed --name IconChess --icon iconchess.ico --add-data "iconchess_logo.png;." chess_game.py
```
The result is `dist/IconChess.exe`. Keep Stockfish next to it, or use **Locate Stockfish** in the game.

## Credits
- Chess rules: [python-chess](https://github.com/niklasf/python-chess)
- Engine: [Stockfish](https://stockfishchess.org/) (GPL, not bundled)
