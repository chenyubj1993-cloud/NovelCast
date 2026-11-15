"""本地假 TTS 服务：实现 OpenAI 兼容的 POST /v1/audio/speech，返回 0.6 秒正弦波。

仅用于离线端到端测试云端 TTS 路径，不产生真实语音。
"""
import json
import math
import struct
from http.server import BaseHTTPRequestHandler, HTTPServer

SR = 24000


def make_wav(seconds=0.6, freq=220.0):
    n = int(SR * seconds)
    frames = bytearray()
    for i in range(n):
        v = int(0.15 * 32767 * math.sin(2 * math.pi * freq * i / SR))
        frames += struct.pack("<h", v)
    data = bytes(frames)
    header = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt "
    header += struct.pack("<IHHIIHH", 16, 1, 1, SR, SR * 2, 2, 16)
    header += b"data" + struct.pack("<I", len(data))
    return header + data


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            payload = json.loads(body)
        except ValueError:
            payload = {}
        audio = make_wav()
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(audio)))
        self.end_headers()
        self.wfile.write(audio)
        print("POST", self.path, payload.get("voice"), payload.get("input", "")[:12], flush=True)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print("fake tts on http://127.0.0.1:18080/v1", flush=True)
    HTTPServer(("127.0.0.1", 18080), Handler).serve_forever()
