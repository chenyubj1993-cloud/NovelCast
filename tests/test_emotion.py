import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from novelcast import tts_providers as tp


def _provider(mode="text"):
    p = tp.IndexTTS2Provider(version="2.5", duration_factor=0.9, emotion_mode=mode)
    captured = {}

    class Fake:
        def infer(self, **kwargs):
            captured.update(kwargs)

    p._tts = Fake()
    p._emo_ok = True
    return p, captured


def test_text_emotion_and_speed():
    p, captured = _provider("text")
    p.synthesize("测试", "ref.wav", "out.wav", emotion="angry")
    assert captured["use_emo_text"] is True
    assert captured["emo_text"].startswith("有些不悦")
    assert abs(captured["duration_factor"] - 0.855) < 1e-6, captured["duration_factor"]


def test_vector_emotion():
    p, captured = _provider("vector")
    p.synthesize("测试", "ref.wav", "out.wav", emotion="surprise")
    assert captured["emo_vector"] == [0, 0, 0, 0, 0, 0, 1, 0]
    assert "use_emo_text" not in captured


def test_neutral_untouched():
    p, captured = _provider("text")
    p.synthesize("测试", "ref.wav", "out.wav", emotion="neutral")
    assert "use_emo_text" not in captured
    assert abs(captured["duration_factor"] - 0.9) < 1e-6


if __name__ == "__main__":
    test_text_emotion_and_speed()
    test_vector_emotion()
    test_neutral_untouched()
    print("emotion tests passed")
