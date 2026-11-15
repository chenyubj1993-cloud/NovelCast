# -*- coding: utf-8 -*-
"""IndexTTS-2 冒烟测试：加载模型并用参考音合成一句。"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, ".vendor"))
sys.path.insert(0, os.path.join(ROOT, "third_party", "index-tts"))

import torch

print("torch", torch.__version__, "cuda", torch.cuda.is_available())
if torch.cuda.is_available():
    print("gpu", torch.cuda.get_device_name(0), torch.cuda.get_device_capability(0))

from indextts.infer_v2 import IndexTTS2
import indextts.infer_v2 as _iv
import soundfile as _sf


def _save_wav(path, wav, sampling_rate, **kwargs):
    arr = wav.detach().cpu().float().numpy()
    if arr.ndim == 2 and arr.shape[0] == 1:
        arr = arr[0]
    elif arr.ndim == 2:
        arr = arr.T
    _sf.write(path, arr, sampling_rate, subtype="PCM_16")


_iv.save_pcm_wav = _save_wav

MODEL_DIR = os.path.join(ROOT, "models", "IndexTTS-2")
CFG = os.path.join(MODEL_DIR, "config.yaml")
REF = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "output", "_ref_yunxi.mp3")
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "output", "_tts_smoke.wav")

t0 = time.time()
tts = IndexTTS2(cfg_path=CFG, model_dir=MODEL_DIR, use_fp16=True)
print("model loaded in %.1fs" % (time.time() - t0))

t1 = time.time()
tts.infer(
    spk_audio_prompt=REF,
    text="你好，我是叶秋。这只是一个测试。",
    output_path=OUT,
    verbose=True,
)
print("inferred in %.1fs -> %s" % (time.time() - t1, OUT))
print("size", os.path.getsize(OUT))
