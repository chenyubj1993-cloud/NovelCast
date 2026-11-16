import sys
import time
import wave
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from novelcast import local_tts


def _cfg(**tts):
    return SimpleNamespace(config={"tts": tts})


def test_max_segment_chars_auto_and_explicit():
    assert local_tts.resolve_max_segment_chars(_cfg(provider="indextts2"), provider=SimpleNamespace(name="indextts2")) == 40
    assert local_tts.resolve_max_segment_chars(_cfg(provider="edge"), provider=SimpleNamespace(name="edge")) == 120
    assert local_tts.resolve_max_segment_chars(_cfg(max_segment_chars=90), provider=SimpleNamespace(name="edge")) == 90


class FakeCloud:
    name = "openai"
    kind = "cloud"
    version = ""
    model_dir = ""
    duration_factor = 1.0
    lang = "zh"
    emotion_mode = "text"
    emo_alpha = 0.55

    def __init__(self, delay):
        self.delay = delay
        self.calls = 0
        self.lock = __import__("threading").Lock()

    def synthesize(self, text, voice, path, emotion=None):
        time.sleep(self.delay)
        with self.lock:
            self.calls += 1
        with wave.open(str(path), "wb") as fh:
            fh.setnchannels(1)
            fh.setsampwidth(2)
            fh.setframerate(24000)
            fh.writeframes(b"\x00\x00" * 2400)


def test_cloud_synthesis_runs_in_parallel(tmp_path):
    provider = FakeCloud(delay=0.2)
    lines = [
        {"text": f"第{i}句。", "character": "旁白", "emotion": "neutral"}
        for i in range(4)
    ]
    start = time.time()
    done = local_tts.synthesize_lines(
        lines,
        str(tmp_path),
        cast={"voices": {"旁白": "nova"}},
        provider=provider,
        config=_cfg(cloud_concurrency=4),
        verbose=False,
        restart=True,
    )
    elapsed = time.time() - start
    assert len(done) == 4
    assert provider.calls == 4
    # 串行需要 ~0.8s；4 路并发应明显更快
    assert elapsed < 0.7
    assert (tmp_path / "segments.json").exists()


def test_indextts_stays_serial(tmp_path):
    provider = FakeCloud(delay=0.05)
    provider.name = "indextts2"
    provider.kind = "local"
    lines = [{"text": f"第{i}句。", "character": "旁白", "emotion": ""} for i in range(2)]
    local_tts.synthesize_lines(
        lines,
        str(tmp_path),
        cast={"voices": {"旁白": "冰糖"}},
        provider=provider,
        config=_cfg(cloud_concurrency=8),
        verbose=False,
        restart=True,
    )
    assert provider.calls == 2
