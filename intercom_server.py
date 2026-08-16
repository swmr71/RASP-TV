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

_local_listeners = []
_local_listeners_lock = threading.Lock()


def add_local_listener(callback):
  """このサーバー自身のプロセス内(tv_gui.pyなど)にメッセージ着信を通知する。"""
  with _local_listeners_lock:
    _local_listeners.append(callback)


def remove_local_listener(callback):
  with _local_listeners_lock:
    if callback in _local_listeners:
      _local_listeners.remove(callback)


def _notify_local_listeners(message, volume):
  with _local_listeners_lock:
    listeners = list(_local_listeners)
  for callback in listeners:
    try:
      callback(message, volume)
    except Exception:
      pass

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
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: 18px;
  }
  #idle .label { font-size: 22px; color: #45475a; }
  #sendForm {
    display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
    justify-content: center;
  }
  #volumeWrap {
    display: flex; align-items: center; gap: 8px;
    font-size: 14px; color: #a6adc8;
  }
  #volumeInput { width: 140px; }
  #sendInput {
    font-size: 20px; padding: 12px 16px;
    background: #313244; color: #cdd6f4;
    border: none; border-radius: 8px; width: 320px;
  }
  #sendBtn {
    font-size: 20px; padding: 12px 24px;
    background: #89b4fa; color: #11111b;
    border: none; border-radius: 8px; cursor: pointer;
  }
  #sendStatus {
    font-size: 14px; color: #a6e3a1; min-height: 18px;
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
  <div id="idle">
    <div class="label">インターホン待機中</div>
    <form id="sendForm">
      <input id="sendInput" type="text" placeholder="メッセージを入力して送信" autocomplete="off">
      <div id="volumeWrap">
        <span>音量</span>
        <input id="volumeInput" type="range" min="0" max="100" value="100">
        <span id="volumeLabel">100%</span>
      </div>
      <button id="sendBtn" type="submit">送信</button>
    </form>
    <div id="sendStatus"></div>
  </div>
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

function playChime(volume) {
  if (!audioCtx) return;
  const peak = Math.max(0.0001, 0.4 * volume);
  const now = audioCtx.currentTime;
  [880, 660].forEach((freq, i) => {
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = 'sine';
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(0.0001, now + i * 0.35);
    gain.gain.exponentialRampToValueAtTime(peak, now + i * 0.35 + 0.05);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + i * 0.35 + 0.6);
    osc.connect(gain).connect(audioCtx.destination);
    osc.start(now + i * 0.35);
    osc.stop(now + i * 0.35 + 0.65);
  });
}

function speak(text, volume) {
  if (!('speechSynthesis' in window)) return;
  window.speechSynthesis.cancel();
  const utter = new SpeechSynthesisUtterance(text);
  utter.lang = 'ja-JP';
  utter.rate = 1.0;
  utter.volume = Math.max(0, Math.min(1, volume));
  window.speechSynthesis.speak(utter);
}

function showMessage(text, volume) {
  messageEl.textContent = text;
  overlayEl.classList.add('show');
  playChime(volume);
  setTimeout(() => speak(text, volume), 700);
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
      const volume = typeof data.volume === 'number' ? data.volume : 1.0;
      if (data.message) showMessage(data.message, volume);
    } catch (e) { /* ignore malformed payloads */ }
  };
}

const sendForm = document.getElementById('sendForm');
const sendInput = document.getElementById('sendInput');
const sendStatus = document.getElementById('sendStatus');
const volumeInput = document.getElementById('volumeInput');
const volumeLabel = document.getElementById('volumeLabel');
volumeInput.addEventListener('input', () => {
  volumeLabel.textContent = `${volumeInput.value}%`;
});
sendForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const message = sendInput.value.trim();
  if (!message) return;
  const volume = Number(volumeInput.value) / 100;
  sendStatus.textContent = '送信中...';
  try {
    const res = await fetch('/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, volume }),
    });
    const data = await res.json();
    sendStatus.textContent = data.ok ? `送信しました (${data.delivered}件)` : '送信に失敗しました';
  } catch (e) {
    sendStatus.textContent = '送信に失敗しました';
  }
  sendInput.value = '';
  setTimeout(() => { sendStatus.textContent = ''; }, 3000);
});

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
  try:
    volume = float(data.get("volume", 1.0))
  except (TypeError, ValueError):
    volume = 1.0
  volume = max(0.0, min(1.0, volume))
  delivered = _broadcast(message, volume)
  return jsonify({"ok": True, "delivered": delivered})


@app.route("/health")
def health():
  with _clients_lock:
    count = len(_clients)
  return jsonify({"ok": True, "clients": count})


def _broadcast(message, volume=1.0):
  payload = json.dumps({"message": message, "volume": volume})
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
  _notify_local_listeners(message, volume)
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
