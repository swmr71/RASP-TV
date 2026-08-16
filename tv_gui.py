import signal
from datetime import datetime
import json
import subprocess
import threading
import time
import tkinter as tk
import urllib.request

import intercom_client
import intercom_server
import local_notify
from on_screen_keyboard import OnScreenKeyboard


# WMO天気コードを日本語と絵文字に変換
def get_weather_text(code):
  if code == 0:
    return "晴れ ☀️"
  elif code in [1, 2, 3]:
    return "くもり ☁️"
  elif code in [45, 48]:
    return "霧 🌫️"
  elif code in [51, 53, 55, 61, 63, 65, 80, 81, 82]:
    return "雨 ☔"
  elif code in [71, 73, 75, 85, 86]:
    return "雪 ❄️"
  elif code in [95, 96, 99]:
    return "雷雨 ⚡"
  return "不明"


class TvMenuApp:

  def __init__(self, root):
    self.root = root
    self.root.title("TV Remote GUI")
    self.root.attributes("-fullscreen", True)
    self.root.config(cursor="none")
    self.root.configure(bg="#1e1e2e")

    self.last_event_time = 0
    self.debounce_interval = 0.3

    # リモコン(CEC)・キーボードの入力を今どこに配送するか。
    # メニュー以外（オンスクリーンキーボード等）を開いている間はそちらに切り替える。
    self.input_target = self

    # --- 1. ヘッダーエリア（時計＆天気） ---
    header_frame = tk.Frame(root, bg="#11111b")
    header_frame.pack(fill="x", side="top", ipady=12)

    # 時計表示（左側）
    self.clock_label = tk.Label(
        header_frame,
        text="",
        font=("Helvetica", 20, "bold"),
        fg="#cdd6f4",
        bg="#11111b",
    )
    self.clock_label.pack(side="left", padx=35)

    # 天気表示（右側）
    self.weather_label = tk.Label(
        header_frame,
        text="天気取得中...",
        font=("Helvetica", 20),
        fg="#a6adc8",
        bg="#11111b",
    )
    self.weather_label.pack(side="right", padx=35)

    # --- 2. メインメニューエリア ---
    self.items = ["メディア再生", "YouTube", "インターホン", "システム設定", "アプリ終了"]
    self.current_idx = 0
    self.buttons = []

    title = tk.Label(
        root,
        text="Raspberry Pi TV",
        font=("Helvetica", 32, "bold"),
        fg="#cdd6f4",
        bg="#1e1e2e",
    )
    title.pack(pady=30)

    frame = tk.Frame(root, bg="#1e1e2e")
    frame.pack(expand=True)

    for item in self.items:
      btn = tk.Label(
          frame,
          text=item,
          font=("Helvetica", 22),
          width=18,
          height=2,
          bg="#313244",
          fg="#cdd6f4",
          relief="flat",
      )
      btn.pack(pady=10)
      self.buttons.append(btn)

    self.update_selection()

    # キーバインド（実際の処理は input_target に委譲。ダイアログを開いている
    # 間はそちらに切り替わる）
    self.root.bind("<Up>", lambda e: self.input_target.on_up())
    self.root.bind("<Down>", lambda e: self.input_target.on_down())
    self.root.bind("<Left>", lambda e: self.input_target.on_left())
    self.root.bind("<Right>", lambda e: self.input_target.on_right())
    self.root.bind("<Return>", lambda e: self.input_target.on_select())
    self.root.bind("<Escape>", lambda e: self.input_target.on_cancel())
    self.root.protocol("WM_DELETE_WINDOW", self.shutdown)

    # 時計と天気の自動更新を呼び出し
    self.update_clock()
    self.fetch_weather_async()

    # インターホン受信サーバー（他端末のブラウザ／自分自身から待ち受け）
    self._intercom_overlay = None
    self.intercom_server_thread = intercom_server.start_server_thread(
        port=5005
    )
    intercom_server.add_local_listener(self.handle_incoming_intercom)

    # CEC監視スレッド（HDMI 1対応）
    self.cec_process = None
    self.cec_thread = threading.Thread(
        target=self.listen_cec_events, daemon=True
    )
    self.cec_thread.start()

  def update_clock(self):
    """時計を毎秒更新"""
    now = datetime.now().strftime("%Y/%m/%d  %H:%M:%S")
    self.clock_label.config(text=now)
    # 1秒（1000ミリ秒）後に再呼び出し
    self.root.after(1000, self.update_clock)

  def fetch_weather_async(self):
    """天気をバックグラウンドで取得（UIフリーズ防止）"""

    def task():
      try:
        # Open-Meteo API（登録不要・APIキー不要）
        # ※緯度・経度（lat, lon）は必要に応じて変更してください（デフォルトは京都）
        lat, lon = 35.0116, 135.7681
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true&timezone=Asia%2FTokyo"

        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as res:
          data = json.loads(res.read().decode())
          current = data.get("current_weather", {})
          temp = round(current.get("temperature", 0))
          code = current.get("weathercode", -1)
          weather_text = get_weather_text(code)

          display_text = f"{weather_text}  {temp}℃"
          # 安全にGUIスレッドへ書き反映
          self.root.after(
              0, lambda: self.weather_label.config(text=display_text)
          )
      except Exception:
        self.root.after(
            0,
            lambda: self.weather_label.config(
                text="天気取得失敗", fg="#f38ba8"
            ),
        )

    threading.Thread(target=task, daemon=True).start()
    # 30分（1800000ミリ秒）ごとに天気を自動更新
    self.root.after(1800000, self.fetch_weather_async)

  def update_selection(self):
    for i, btn in enumerate(self.buttons):
      if i == self.current_idx:
        btn.config(bg="#89b4fa", fg="#11111b")
      else:
        btn.config(bg="#313244", fg="#cdd6f4")

  def navigate(self, direction):
    self.current_idx = (self.current_idx + direction) % len(self.items)
    self.update_selection()

  def select_item(self):
    selected = self.items[self.current_idx]
    if selected == "アプリ終了":
      self.shutdown()
    elif selected == "インターホン":
      self.open_intercom_keyboard()
    else:
      pass

  # --- input_target インターフェース（メインメニューがアクティブなとき） ---

  def on_up(self):
    self.navigate(-1)

  def on_down(self):
    self.navigate(1)

  def on_left(self):
    pass

  def on_right(self):
    pass

  def on_select(self):
    self.select_item()

  def on_cancel(self):
    self.shutdown()

  def open_intercom_keyboard(self):
    keyboard = OnScreenKeyboard(
        self.root,
        title="インターホン メッセージ入力",
        on_submit=self.send_intercom_message,
        on_close=self.release_input_target,
    )
    self.input_target = keyboard

  def release_input_target(self):
    self.input_target = self

  def send_intercom_message(self, message, volume=1.0):
    self.show_toast(f"送信中: {message} (音量{round(volume * 100)}%)")

    def task():
      results = intercom_client.send_message(message, volume=volume)
      ok_count = sum(1 for _, _, ok, _ in results if ok)
      total = len(results)
      if total == 0:
        text = "送信先が設定されていません (intercom_config.json)"
      elif ok_count == total:
        text = f"送信しました ({ok_count}/{total})"
      else:
        text = f"一部送信に失敗 ({ok_count}/{total})"
      self.root.after(0, lambda: self.show_toast(text))

    threading.Thread(target=task, daemon=True).start()

  def handle_incoming_intercom(self, message, volume=1.0):
    """intercom_serverが別スレッドでメッセージを受信したときのコールバック。"""
    self.root.after(0, lambda: self.show_intercom_overlay(message, volume))

  def show_intercom_overlay(self, message, volume=1.0):
    local_notify.play_chime(volume)
    threading.Timer(0.7, lambda: local_notify.speak(message, volume)).start()

    if self._intercom_overlay is not None:
      self._intercom_overlay.destroy()

    overlay = tk.Frame(self.root, bg="#11111b")
    overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
    overlay.lift()
    tk.Label(
        overlay, text="🔔", font=("Helvetica", 72), bg="#11111b",
        fg="#cdd6f4",
    ).pack(pady=(160, 20))
    tk.Label(
        overlay, text=message, font=("Helvetica", 36, "bold"),
        fg="#f9e2af", bg="#11111b", wraplength=900, justify="center",
    ).pack(padx=40)
    self._intercom_overlay = overlay

    duration_ms = max(8000, len(message) * 400)
    self.root.after(duration_ms, self.close_intercom_overlay)

  def close_intercom_overlay(self):
    if self._intercom_overlay is not None:
      self._intercom_overlay.destroy()
      self._intercom_overlay = None

  def show_toast(self, text, duration_ms=2500):
    if getattr(self, "_toast_label", None) is not None:
      self._toast_label.destroy()
    self._toast_label = tk.Label(
        self.root, text=text, font=("Helvetica", 16),
        fg="#11111b", bg="#a6e3a1", padx=16, pady=8,
    )
    self._toast_label.place(relx=0.5, rely=0.95, anchor="s")
    self.root.after(duration_ms, self._toast_label.destroy)

  def listen_cec_events(self):
    try:
      self.cec_process = subprocess.Popen(
          ["cec-client", "/dev/cec1"],
          stdout=subprocess.PIPE,
          stderr=subprocess.DEVNULL,
          text=True,
          bufsize=1,
      )
    except (FileNotFoundError, OSError):
      # cec-clientが無い環境（開発機など）ではCEC監視をスキップする
      return

    try:
      for line in self.cec_process.stdout:
        line_lower = line.lower()
        if "key pressed:" in line_lower:
          now = time.time()
          if now - self.last_event_time < self.debounce_interval:
            continue
          self.last_event_time = now

          if "left" in line_lower:
            self.root.after(0, lambda: self.input_target.on_left())
          elif "right" in line_lower:
            self.root.after(0, lambda: self.input_target.on_right())
          elif "up" in line_lower:
            self.root.after(0, lambda: self.input_target.on_up())
          elif "down" in line_lower:
            self.root.after(0, lambda: self.input_target.on_down())
          elif "select" in line_lower or "enter" in line_lower:
            self.root.after(0, lambda: self.input_target.on_select())
          elif "exit" in line_lower or "back" in line_lower:
            self.root.after(0, lambda: self.input_target.on_cancel())
    except Exception:
      pass

  def shutdown(self):
    if self.cec_process is not None and self.cec_process.poll() is None:
      try:
        self.cec_process.terminate()
      except Exception:
        pass
    self.root.destroy()


if __name__ == "__main__":
  root = tk.Tk()
  app = TvMenuApp(root)

  # Ctrl+C (SIGINT) を受け取ったら安全にGUIを終了させる設定を追加
  signal.signal(signal.SIGINT, lambda *args: app.shutdown())

  root.mainloop()