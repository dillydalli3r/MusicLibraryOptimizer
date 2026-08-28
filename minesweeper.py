import random
import tkinter as tk
from tkinter import messagebox


class Minesweeper:

    def __init__(self, root, width=9, height=9, mines=10):
        self.root = root
        self.root.title("Minesweeper")
        self.root.resizable(False, False)

        self.width = width
        self.height = height
        self.mines = mines

        self.board = []
        self.mine_locations = set()
        self.game_over = False
        self.first_click = True
        self.flags_left = mines
        self.tiles_revealed = 0

        self.create_widgets()
        self.new_game()

    def create_widgets(self):
        # Top frame for status/restart
        self.top_frame = tk.Frame(self.root, bg="#c0c0c0", bd=3, relief="raised")
        self.top_frame.pack(fill="x", padx=5, pady=5)

        self.mine_label = tk.Label(
            self.top_frame,
            text=f"💣 {self.flags_left:03d}",
            font=("Consolas", 14, "bold"),
            bg="black",
            fg="red",
            padx=5,
            pady=2,
        )
        self.mine_label.pack(side="left", padx=10, pady=5)

        self.reset_button = tk.Button(
            self.top_frame,
            text="😊",
            font=("Arial", 14),
            command=self.new_game,
            relief="raised",
            width=3,
        )
        self.reset_button.pack(side="left", expand=True, padx=5, pady=5)

        # Board frame
        self.board_frame = tk.Frame(self.root, bg="#7b7b7b", bd=3, relief="sunken")
        self.board_frame.pack(padx=5, pady=5)

        self.buttons = {}
        for r in range(self.height):
            for c in range(self.width):
                btn = tk.Button(
                    self.board_frame,
                    font=("Arial", 11, "bold"),
                    width=2,
                    height=1,
                    relief="raised",
                    bg="#bdbdbd",
                    bd=1,
                )
                btn.grid(row=r, column=c, sticky="nsew")
                btn.bind("<Button-1>", lambda e, row=r, col=c: self.left_click(row, col))
                btn.bind("<Button-3>", lambda e, row=r, col=c: self.right_click(row, col))
                self.buttons[(r, c)] = btn

        # Configure grid weight so cells expand nicely if needed
        for r in range(self.height):
            self.board_frame.rowconfigure(r, weight=1)
        for c in range(self.width):
            self.board_frame.columnconfigure(c, weight=1)

    def new_game(self):
        self.game_over = False
        self.first_click = True
        self.flags_left = self.mines
        self.tiles_revealed = 0
        self.mine_locations = set()
        self.mine_label.config(text=f"💣 {self.flags_left:03d}")
        self.reset_button.config(text="😊")

        # Initialize empty board representation
        self.board = [[0 for _ in range(self.width)] for _ in range(self.height)]

        for r in range(self.height):
            for c in range(self.width):
                btn = self.buttons[(r, c)]
                btn.config(
                    text="",
                    state="normal",
                    relief="raised",
                    bg="#bdbdbd",
                    fg="black",
                )

    def place_mines(self, safe_r, safe_c):
        self.mine_locations = set()
        candidates = [
            (r, c)
            for r in range(self.height)
            for c in range(self.width)
            if (r, c) != (safe_r, safe_c)
        ]
        self.mine_locations = set(
            random.sample(candidates, min(self.mines, len(candidates)))
        )

        # Calculate neighbor counts
        for r in range(self.height):
            for c in range(self.width):
                if (r, c) in self.mine_locations:
                    self.board[r][c] = -1
                else:
                    count = 0
                    for dr in (-1, 0, 1):
                        for dc in (-1, 0, 1):
                            if dr == 0 and dc == 0:
                                continue
                            nr, nc = r + dr, c + dc
                            if (
                                0 <= nr < self.height
                                and 0 <= nc < self.width
                                and (nr, nc) in self.mine_locations
                            ):
                                count += 1
                    self.board[r][c] = count

    def left_click(self, r, c):
        if self.game_over:
            return
        btn = self.buttons[(r, c)]
        if btn["relief"] == "sunken" or btn["text"] == "🚩":
            return

        if self.first_click:
            self.place_mines(r, c)
            self.first_click = False

        if (r, c) in self.mine_locations:
            # Hit a mine!
            self.game_over = True
            self.reveal_all_mines(hit=(r, c))
            self.reset_button.config(text="💀")
            return

        self.reveal(r, c)
        self.check_win()

    def reveal(self, r, c):
        if not (0 <= r < self.height and 0 <= c < self.width):
            return
        btn = self.buttons[(r, c)]
        if btn["relief"] == "sunken" or btn["text"] == "🚩":
            return

        btn.config(relief="sunken", bg="#e0e0e0")
        self.tiles_revealed += 1

        val = self.board[r][c]
        if val > 0:
            colors = {
                1: "blue",
                2: "green",
                3: "red",
                4: "darkblue",
                5: "brown",
                6: "cyan",
                7: "black",
                8: "gray",
            }
            btn.config(text=str(val), fg=colors.get(val, "black"))
        elif val == 0:
            # Flood fill empty cells
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    self.reveal(r + dr, c + dc)

    def right_click(self, r, c):
        if self.game_over:
            return
        btn = self.buttons[(r, c)]
        if btn["relief"] == "sunken":
            return

        if btn["text"] == "🚩":
            btn.config(text="")
            self.flags_left += 1
        else:
            if self.flags_left > 0:
                btn.config(text="🚩")
                self.flags_left -= 1
        self.mine_label.config(text=f"💣 {self.flags_left:03d}")

    def reveal_all_mines(self, hit=None):
        for r in range(self.height):
            for c in range(self.width):
                btn = self.buttons[(r, c)]
                if (r, c) in self.mine_locations:
                    btn.config(
                        text="💣",
                        bg="red" if (r, c) == hit else "#bdbdbd",
                        relief="sunken",
                    )
                elif btn["text"] == "🚩":
                    btn.config(text="❌")  # Incorrect flag

    def check_win(self):
        total_cells = self.width * self.height
        if self.tiles_revealed == total_cells - self.mines:
            self.game_over = True
            self.reset_button.config(text="😎")
            for (r, c) in self.mine_locations:
                self.buttons[(r, c)].config(text="🚩")
            messagebox.showinfo(
                "Minesweeper", "Congratulations! You won the game!"
            )


if __name__ == "__main__":
    root = tk.Tk()
    app = Minesweeper(root, width=9, height=9, mines=10)
    root.mainloop()
