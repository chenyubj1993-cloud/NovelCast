import math
import os
import sys
import tempfile
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import soundfile as sf

from novelcast.local_tts import concat_segments


def _tone(path, seconds=0.5, amp=0.08, sr=24000):
    n = int(seconds * sr)
    t = np.arange(n) / sr
    y = (amp * np.sin(2 * math.pi * 220 * t)).astype("float32")
    sf.write(path, y, sr, subtype="FLOAT")


def test_silence_by_speaker_and_loudness():
    with tempfile.TemporaryDirectory() as td:
        segs = []
        for i in range(3):
            p = os.path.join(td, f"{i}.wav")
            _tone(p)
            segs.append(p)
        out = os.path.join(td, "out.wav")
        stats = {}
        # 旁白 -> 甲：0.4s；甲 -> 乙：0.15s
        concat_segments(segs, out, characters=["旁白", "甲", "乙"], stats=stats)
        with wave.open(out) as w:
            actual = w.getnframes() / w.getframerate()
        expected = 1.5 + 0.4 + 0.15
        assert abs(actual - expected) < 0.02, (actual, expected)
        assert stats["segments"] == 3
        assert 0 < stats["peak"] <= 0.9501
        # stats 记录实测响度：包含静音后与目标 -18 LUFS 允许小偏差
        assert -19.5 < stats["lufs"] < -16.5, stats["lufs"]
        assert abs(stats["gain_db"]) > 1e-3


if __name__ == "__main__":
    test_silence_by_speaker_and_loudness()
    print("concat tests passed")
