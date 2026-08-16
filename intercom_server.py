"""インターホン機能のサーバー側。

受信側は普通のWebブラウザでこのサーバーの "/" を開いて開きっぱなしにしておく。
送信側は "/send" にPOSTするとつながっている全ブラウザにメッセージが配信され、
ブラウザ側でチャイム再生と強制読み上げ（Web Speech API）が行われる。
"""

import json
import threading

from flask import Flask, Response, jsonify, request
from flask_sock import Sock

app = Flask(__name__)
sock = Sock(app)

_clients = set()
_clients_lock = threading.Lock()

RECEIVER_PAGE = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>インターホン受信</title>
<style>
  html, body {
    margin: 0; padding: 0; height: 100%;
    background: #1e1e2e; color: #cdd6f4;
    font-family: "Helvetica Neue", "Hiragino Sans", sans-serif;
    overflow: hidden;
  }
  #status {
    position: fixed; top: 12px; right: 16px;
    font-size: 14px; color: #a6adc8;
  }
  #unlock {
    position: fixed; inset: 0;
    display: flex; align-items: center; justify-content: center;
    background: #1e1e2e; z-index: 10;
  }
  #unlock button {
    font-size: 28px; padding: 24px 48px;
    background: #89b4fa; color: #11111b;
    border: none; border-radius: 12px; cursor: pointer;
  }
  #idle {
    position: fixed; inset: 0;
    display: flex; align-items: center; justify-content: center;
    font-size: 22px; color: #45475a;
  }
  #overlay {
    position: fixed; inset: 0;
    display: none;
    flex-direction: column; align-items: center; justify-content: center;
    background: #11111b;
    text-align: center; padding: 40px; box-sizing: border-box;
  }
  #overlay.show { display: flex; }
  #overlay .icon { font-size: 72px; margin-bottom: 24px; }
  #overlay .message {
    font-size: 48px; font-weight: bold; color: #f9e2af;
    max-width: 90vw; word-break: break-word;
  }
  #overlay .close {
    margin-top: 40px; font-size: 18px; padding: 10px 28px;
    background: #313244; color: #cdd6f4; border: none;
    border-radius: 8px; cursor: pointer;
  }
</style>
</head>
<body>
  <div id="status">接続中...</div>
  <div id="idle">インターホン待機中</div>
  <div id="overlay">
    <div class="icon">🔔</div>
    <div class="message" id="message"></div>
    <button class="close" id="closeBtn">閉じる</button>
  </div>
  <div id="unlock">
    <button id="unlockBtn">タップして待機を開始</button>
  </div>

<script>
const statusEl = document.getElementById('status');
const overlayEl = document.getElementById('overlay');
const messageEl = document.getElementById('message');
const unlockEl = document.getElementById('unlock');
let audioCtx = null;
let hideTimer = null;

function playChime() {
  if (!audioCtx) return;
  const now = audioCtx.currentTime;
  [880, 660].forEach((freq, i) => {
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = 'sine';
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(0.0001, now + i * 0.35);
    gain.gain.exponentialRampToValueAtTime(0.4, now + i * 0.35 + 0.05);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + i * 0.35 + 0.6);
    osc.connect(gain).connect(audioCtx.destination);
    osc.start(now + i * 0.35);
    osc.stop(now + i * 0.35 + 0.65);
  });
}

function speak(text) {
  if (!('speechSynthesis' in window)) return;
  window.speechSynthesis.cancel();
  const utter = new SpeechSynthesisUtterance(text);
  utter.lang = 'ja-JP';
  utter.rate = 1.0;
  window.speechSynthesis.speak(utter);
}

function showMessage(text) {
  messageEl.textContent = text;
  overlayEl.classList.add('show');
  playChime();
  setTimeout(() => speak(text), 700);
  clearTimeout(hideTimer);
  const displaySeconds = Math.max(8, text.length * 0.5);
  hideTimer = setTimeout(hideMessage, displaySeconds * 1000);
}

function hideMessage() {
  overlayEl.classList.remove('show');
  window.speechSynthesis.cancel();
}

document.getElementById('closeBtn').addEventListener('click', hideMessage);

let ws = null;
function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = () => { statusEl.textContent = '待機中'; };
  ws.onclose = () => { statusEl.textContent = '切断（再接続中...）'; setTimeout(connect, 2000); };
  ws.onerror = () => { ws.close(); };
  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.message) showMessage(data.message);
    } catch (e) { /* ignore malformed payloads */ }
  };
}

document.getElementById('unlockBtn').addEventListener('click', () => {
  audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  const utter = new SpeechSynthesisUtterance('');
  window.speechSynthesis.speak(utter);
  unlockEl.style.display = 'none';
  connect();
});
</script>
</body>
</html>
"""


@app.route("/")
def index():
  return Response(RECEIVER_PAGE, mimetype="text/html")


@sock.route("/ws")
def ws_endpoint(conn):
  with _clients_lock:
    _clients.add(conn)
  try:
    while True:
      # 受信側からのデータは使わないが、切断検知のために読み続ける
      if conn.receive() is None:
        break
  except Exception:
    pass
  finally:
    with _clients_lock:
      _clients.discard(conn)


@app.route("/send", methods=["POST"])
def send():
  data = request.get_json(silent=True) or {}
  message = (data.get("message") or "").strip()
  if not message:
    return jsonify({"ok": False, "error": "message is required"}), 400
  delivered = _broadcast(message)
  return jsonify({"ok": True, "delivered": delivered})


@app.route("/health")
def health():
  with _clients_lock:
    count = len(_clients)
  return jsonify({"ok": True, "clients": count})


def _broadcast(message):
  payload = json.dumps({"message": message})
  delivered = 0
  with _clients_lock:
    dead = []
    for conn in _clients:
      try:
        conn.send(payload)
        delivered += 1
      except Exception:
        dead.append(conn)
    for conn in dead:
      _clients.discard(conn)
  return delivered


def run_server(host="0.0.0.0", port=5005):
  app.run(host=host, port=port, threaded=True, use_reloader=False)


def start_server_thread(host="0.0.0.0", port=5005):
  thread = threading.Thread(
      target=run_server, kwargs={"host": host, "port": port}, daemon=True
  )
  thread.start()
  return thread


if __name__ == "__main__":
  run_server()
