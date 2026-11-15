"""IndexTTS-2.5 冒烟：验证发音标注 <字|拼音>、duration_factor 变速、显存占用。"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "third_party", "index-tts"))

import soundfile as sf

from modules.tts_providers import IndexTTS2Provider

OUT = os.path.join(ROOT, "output", "_verify_tts25")
os.makedirs(OUT, exist_ok=True)

ref = os.path.join(ROOT, "third_party", "index-tts", "examples", "voice_01.wav")
if not os.path.exists(ref):
    cands = []
    refs_dir = os.path.join(ROOT, "output", "_refs")
    if os.path.isdir(refs_dir):
        cands = [os.path.join(refs_dir, f) for f in os.listdir(refs_dir)
                 if f.lower().endswith((".wav", ".mp3"))]
    ref = cands[0] if cands else None
print("reference:", ref)

CASES = [
    ("plain", "他行走在路上，重庆的夜很安静。", 1.0),
    ("char_annotated", "他<行|XING2>走在路上，<重|CHONG2><庆|QING4>的夜很安静。", 1.0),
    ("word_annotated", "他<行|XING2>走在路上，<重庆|CHONG2 QING4>的夜很安静。", 1.0),
    ("fast_0.8", "他<行|XING2>走在路上，<重|CHONG2><庆|QING4>的夜很安静。", 0.8),
    ("slow_1.25", "他<行|XING2>走在路上，<重|CHONG2><庆|QING4>的夜很安静。", 1.25),
]

provider = IndexTTS2Provider(
    model_dir=os.path.join(ROOT, "models", "IndexTTS-2.5"),
    use_fp16=True,
    version="2.5",
    duration_factor=1.0,
    lang="zh",
)

for tag, text, factor in CASES:
    provider.duration_factor = factor
    out = os.path.join(OUT, f"{tag}.wav")
    t0 = time.time()
    provider.synthesize(text, ref, out)
    dt = time.time() - t0
    info = sf.info(out)
    print(f"{tag:14s} dur={info.duration:6.2f}s wall={dt:6.2f}s rtf={dt/info.duration:4.2f} "
          f"sr={info.samplerate} factor={factor}")

print("OK")
