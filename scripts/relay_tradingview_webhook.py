#!/usr/bin/env python3
"""
TradingView Webhook 中转脚本（可选）

TradingView 告警无法携带自定义请求头，本脚本接收 TV 的 POST，对 body 做 HMAC-SHA256 签名后转发到本系统。
运行后得到一个「中转 URL」，把该 URL 填到 TradingView 告警的 Webhook URL 即可。

使用方式：
  1. 设置环境变量（必填）：
     - TV_WEBHOOK_SECRET：与 .env 中一致
     - RELAY_TARGET_URL：本系统 Webhook 地址（默认 http://localhost:8000/webhook/tradingview）
  2. 启动：python scripts/relay_tradingview_webhook.py
  3. 本地得到：http://localhost:9000/webhook
  4. 用 ngrok 暴露：ngrok http 9000 → 得到 https://xxx.ngrok.io
  5. 在 TradingView 告警的 Webhook URL 填：https://xxx.ngrok.io/webhook

仅使用 Python 标准库，无需安装额外依赖。
"""
import base64
import hmac
import hashlib
import json
import os
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler

RELAY_PORT = int(os.environ.get("RELAY_PORT", "9000"))
RELAY_TARGET_URL = os.environ.get(
    "RELAY_TARGET_URL",
    "http://localhost:8000/webhook/tradingview",
)
TV_SECRET = (os.environ.get("TV_WEBHOOK_SECRET") or "").encode("utf-8")
SIGNATURE_HEADER = "X-TradingView-Signature"


def compute_signature(body: bytes, secret: bytes) -> str:
    return base64.b64encode(
        hmac.new(secret, body, hashlib.sha256).digest()
    ).decode("utf-8")


class RelayHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/")
        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        if path == "/webhook" or path == "":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"TradingView webhook relay. Use POST from TradingView alert."
            )
            return
        self.send_response(404)
        self.end_headers()
        self.wfile.write(b"Not Found")

    def do_POST(self):
        if self.path.rstrip("/") != "/webhook":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        if not TV_SECRET:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {"error": "TV_WEBHOOK_SECRET not set"}
                ).encode("utf-8")
            )
            return
        sig = compute_signature(body, TV_SECRET)
        req = urllib.request.Request(
            RELAY_TARGET_URL,
            data=body,
            method="POST",
            headers={
                "Content-Type": self.headers.get("Content-Type", "application/json"),
                SIGNATURE_HEADER: sig,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                self.send_response(resp.status)
                for k, v in resp.headers.items():
                    if k.lower() != "transfer-encoding":
                        self.send_header(k, v)
                self.end_headers()
                self.wfile.write(resp.read())
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(e.read() if e.fp else b"{}")
        except Exception as e:
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps({"error": "Relay forward failed", "detail": str(e)}).encode("utf-8")
            )

    def log_message(self, format, *args):
        print(f"[relay] {args[0]}")


def main():
    if not TV_SECRET:
        print("ERROR: Set TV_WEBHOOK_SECRET in environment (same as .env)")
        raise SystemExit(1)
    print(f"Relay target: {RELAY_TARGET_URL}")
    print(f"Local URL:    http://localhost:{RELAY_PORT}/webhook")
    print("Expose with:  ngrok http", RELAY_PORT)
    print("Then in TradingView Webhook URL use: https://<ngrok-host>/webhook")
    server = HTTPServer(("", RELAY_PORT), RelayHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
