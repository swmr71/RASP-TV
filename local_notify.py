"""tv_gui.py自身の画面・スピーカーでのチャイム再生とTTS読み上げ。

ブラウザ側(Web Speech API)と違い、Pi本体のTkinter画面ではOSコマンドを使う。
チャイムはPython側でWAVを生成して aplay（ALSA）で再生し、読み上げは
espeak-ng（無ければespeak）を使う。どちらも入っていない環境では黙って
何もしない（画面表示は別途行われるため無音でも機能自体は伝わる）。
"""

import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import wave

_CHIME_PATH = os.path.join(tempfile.gettempdir(), "rasptv_chime.wav")


def _generate_chime_wav(volume):
  framerate = 44100
  frames = bytearray()
  for freq in (880, 660):
    n_samples = int(framerate * 0.3)
    for i in range(n_samples):
      t = i / framerate
      envelope = min(1.0, (n_samples - i) / (n_samples * 0.3))
      sample = math.sin(2 * math.pi * freq * t) * envelope * 0.5 * volume
      frames += struct.pack("<h", int(sample * 32767))
    frames += b"\x00\x00" * int(framerate * 0.05)
  with wave.open(_CHIME_PATH, "w") as wf:
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(framerate)
    wf.writeframes(bytes(frames))
  return _CHIME_PATH


def play_chime(volume=1.0):
  volume = max(0.0, min(1.0, volume))

  def _run():
    try:
      if sys.platform.startswith("win"):
        if volume <= 0:
          return
        import winsound
        winsound.Beep(880, 250)
        winsound.Beep(660, 250)
        return
      path = _generate_chime_wav(volume)
      if shutil.which("aplay"):
        subprocess.run(
            ["aplay", "-q", path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception:
      pass

  threading.Thread(target=_run, daemon=True).start()


def speak(text, volume=1.0):
  volume = max(0.0, min(1.0, volume))
  amplitude = int(volume * 100)  # espeakの-aは0〜200、100が標準音量

  def _run():
    try:
      for cmd in ("espeak-ng", "espeak"):
        if shutil.which(cmd):
          subprocess.run(
              [cmd, "-v", "ja", "-a", str(amplitude), text],
              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
          )
          return
    except Exception:
      pass

  threading.Thread(target=_run, daemon=True).start()
