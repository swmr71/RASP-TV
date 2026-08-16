"""リモコン（矢印キー＋決定）だけで操作できるソフトウェアキーボード。

かな入力とABC/記号入力を切り替えられる、TV向けのシンプルなオンスクリーン
キーボード。PC用の物理キーボードで直接文字を打つことも可能（開発機での
動作確認用）。
"""

import tkinter as tk

KANA_ROWS = [
    list("あいうえお"),
    list("かきくけこ"),
    list("さしすせそ"),
    list("たちつてと"),
    list("なにぬねの"),
    list("はひふへほ"),
    list("まみむめも"),
    list("やゆよ"),
    list("らりるれろ"),
    list("わをん"),
    list("がぎぐげござじずぜぞ"),
    list("だぢづでどばびぶべぼぱぴぷぺぽ"),
    list("ゃゅょっー、。"),
]

ALPHA_ROWS = [
    list("1234567890"),
    list("qwertyuiop"),
    list("asdfghjkl"),
    list("zxcvbnm"),
    list("-_@.,!?/:()"),
]

BG = "#1e1e2e"
BG_PANEL = "#11111b"
BG_KEY = "#313244"
FG_KEY = "#cdd6f4"
BG_FOCUS = "#89b4fa"
FG_FOCUS = "#11111b"
BG_ACCENT = "#a6e3a1"


class OnScreenKeyboard:
  """フルスクリーンのソフトウェアキーボードダイアログ。

  on_submit(text) は「送信」が押されたときに呼ばれる。
  キャンセル時やEscapeでは何も呼ばれずに閉じる。
  """

  def __init__(self, parent, title="メッセージ入力", on_submit=None, on_close=None):
    self.on_submit = on_submit
    self.on_close = on_close
    self.text = ""
    self.mode = "kana"
    self.volume = 1.0
    self.pos = [0, 0]
    self.widgets = []

    self.win = tk.Toplevel(parent)
    self.win.title(title)
    self.win.attributes("-fullscreen", True)
    self.win.configure(bg=BG)
    self.win.grab_set()
    self.win.focus_set()
    # マップ直後はfocus_setが効かないことがあるため、少し遅らせて強制フォーカス
    self.win.after(50, self.win.focus_force)

    tk.Label(
        self.win, text=title, font=("Helvetica", 20, "bold"),
        fg=FG_KEY, bg=BG,
    ).pack(pady=(20, 10))

    self.preview = tk.Label(
        self.win, text="|", font=("Helvetica", 24), fg=BG_ACCENT,
        bg=BG_PANEL, width=40, anchor="w", padx=12,
    )
    self.preview.pack(pady=(0, 6))

    self.volume_label = tk.Label(
        self.win, text="音量: 100%", font=("Helvetica", 14),
        fg=FG_KEY, bg=BG,
    )
    self.volume_label.pack(pady=(0, 14))

    self.grid_frame = tk.Frame(self.win, bg=BG)
    self.grid_frame.pack(expand=True)

    self.win.bind("<Up>", lambda e: self.navigate(-1, 0))
    self.win.bind("<Down>", lambda e: self.navigate(1, 0))
    self.win.bind("<Left>", lambda e: self.navigate(0, -1))
    self.win.bind("<Right>", lambda e: self.navigate(0, 1))
    self.win.bind("<Return>", lambda e: self.activate())
    self.win.bind("<Escape>", lambda e: self.cancel())
    self.win.bind("<BackSpace>", lambda e: self.backspace())
    self.win.bind("<KeyPress>", self.handle_typed_key)

    self.build_grid()

  # --- グリッド構築 ---

  def char_rows(self):
    return KANA_ROWS if self.mode == "kana" else ALPHA_ROWS

  def control_row(self):
    toggle_label = "ABC/記号" if self.mode == "kana" else "かな"
    return [
        {"label": "空白", "action": self.space},
        {"label": "削除", "action": self.backspace},
        {"label": "全消去", "action": self.clear},
        {"label": toggle_label, "action": self.toggle_mode},
        {"label": "音量-", "action": self.volume_down},
        {"label": "音量+", "action": self.volume_up},
        {"label": "送信", "action": self.submit, "accent": True},
        {"label": "キャンセル", "action": self.cancel},
    ]

  def build_grid(self):
    for child in self.grid_frame.winfo_children():
      child.destroy()

    self.grid = []
    for row in self.char_rows():
      self.grid.append(
          [{"label": ch, "action": (lambda c=ch: self.insert_char(c))}
           for ch in row]
      )
    self.grid.append(self.control_row())

    self.pos[0] = min(self.pos[0], len(self.grid) - 1)
    self.pos[1] = min(self.pos[1], len(self.grid[self.pos[0]]) - 1)

    self.widgets = []
    for row_cells in self.grid:
      row_frame = tk.Frame(self.grid_frame, bg=BG)
      row_frame.pack(pady=3)
      row_widgets = []
      for cell in row_cells:
        lbl = tk.Label(
            row_frame, text=cell["label"], font=("Helvetica", 18),
            width=4 if len(cell["label"]) == 1 else 8,
            height=1, bg=BG_KEY, fg=FG_KEY, relief="flat", padx=6, pady=6,
        )
        lbl.pack(side="left", padx=3)
        row_widgets.append(lbl)
      self.widgets.append(row_widgets)

    self.refresh_focus()

  # --- ナビゲーション ---

  def navigate(self, dr, dc):
    row, col = self.pos
    if dc != 0:
      row_len = len(self.grid[row])
      col = (col + dc) % row_len
    else:
      row = max(0, min(len(self.grid) - 1, row + dr))
      col = min(col, len(self.grid[row]) - 1)
    self.pos = [row, col]
    self.refresh_focus()

  def refresh_focus(self):
    for r, row_widgets in enumerate(self.widgets):
      for c, widget in enumerate(row_widgets):
        accent = self.grid[r][c].get("accent")
        if [r, c] == self.pos:
          widget.config(bg=BG_FOCUS, fg=FG_FOCUS)
        elif accent:
          widget.config(bg=BG_ACCENT, fg=BG_PANEL)
        else:
          widget.config(bg=BG_KEY, fg=FG_KEY)

  def activate(self):
    row, col = self.pos
    self.grid[row][col]["action"]()

  # --- input_target インターフェース（親アプリのCEC/キー処理から呼ばれる） ---

  def on_up(self):
    self.navigate(-1, 0)

  def on_down(self):
    self.navigate(1, 0)

  def on_left(self):
    self.navigate(0, -1)

  def on_right(self):
    self.navigate(0, 1)

  def on_select(self):
    self.activate()

  def on_cancel(self):
    self.cancel()

  # --- 文字操作 ---

  def insert_char(self, ch):
    self.text += ch
    self.update_preview()

  def space(self):
    self.text += " "
    self.update_preview()

  def backspace(self):
    self.text = self.text[:-1]
    self.update_preview()

  def clear(self):
    self.text = ""
    self.update_preview()

  def toggle_mode(self):
    self.mode = "alpha" if self.mode == "kana" else "kana"
    self.pos = [0, 0]
    self.build_grid()

  def volume_down(self):
    self.volume = max(0.0, round(self.volume - 0.1, 2))
    self.update_volume_label()

  def volume_up(self):
    self.volume = min(1.0, round(self.volume + 0.1, 2))
    self.update_volume_label()

  def update_volume_label(self):
    self.volume_label.config(text=f"音量: {round(self.volume * 100)}%")

  def update_preview(self):
    self.preview.config(text=(self.text or " ") + "|")

  def handle_typed_key(self, event):
    if event.keysym in (
        "Up", "Down", "Left", "Right", "Return", "Escape", "BackSpace",
    ):
      return
    if event.char and event.char.isprintable():
      self.insert_char(event.char)

  # --- 確定・キャンセル ---

  def submit(self):
    text = self.text.strip()
    volume = self.volume
    self.win.grab_release()
    self.win.destroy()
    if text and self.on_submit:
      self.on_submit(text, volume)
    if self.on_close:
      self.on_close()

  def cancel(self):
    self.win.grab_release()
    self.win.destroy()
    if self.on_close:
      self.on_close()
