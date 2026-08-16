"""インターホン機能の送信側ヘルパー。

intercom_config.json に登録された宛先（自分自身も含めてよい）に
メッセージをPOSTする。
"""

import json
import os
import urllib.request

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "intercom_config.json")

DEFAULT_CONFIG = {
    "targets": [
        {"name": "自分自身（テスト用）", "url": "http://127.0.0.1:5005"},
    ]
}


def load_config():
  if not os.path.exists(CONFIG_PATH):
    save_config(DEFAULT_CONFIG)
    return dict(DEFAULT_CONFIG)
  try:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
      return json.load(f)
  except (json.JSONDecodeError, OSError):
    return dict(DEFAULT_CONFIG)


def save_config(config):
  with open(CONFIG_PATH, "w", encoding="utf-8") as f:
    json.dump(config, f, ensure_ascii=False, indent=2)


def send_message(message, targets=None, timeout=3):
  """設定済みの宛先すべてにメッセージを送信する。

  戻り値: [(name, url, success: bool, error: str|None), ...]
  """
  if targets is None:
    targets = load_config().get("targets", [])

  results = []
  body = json.dumps({"message": message}).encode("utf-8")
  for target in targets:
    name = target.get("name", target.get("url", "?"))
    url = target.get("url", "").rstrip("/") + "/send"
    try:
      req = urllib.request.Request(
          url,
          data=body,
          headers={"Content-Type": "application/json"},
          method="POST",
      )
      with urllib.request.urlopen(req, timeout=timeout) as res:
        res.read()
      results.append((name, url, True, None))
    except Exception as exc:
      results.append((name, url, False, str(exc)))
  return results
