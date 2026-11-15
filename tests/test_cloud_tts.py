import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from novelcast import tts_providers as tp
from novelcast.cast_manager import build_cast


def test_cloud_cast_uses_cloud_voices():
    class C:
        config = {
            "tts": {
                "provider": "openai",
                "cloud_voices": {"female": ["nova"], "male": ["onyx"], "unknown": ["alloy"]},
            },
            "main_character_count": 1,
        }

    chars = {
        "旁白": {"name": "旁白", "gender": "unknown", "appearances": 0},
        "张三": {"name": "张三", "gender": "male", "appearances": 10},
        "李四": {"name": "李四", "gender": "female", "appearances": 5},
    }
    roster = {"characters": chars}
    cast = build_cast(roster, C())
    assert cast["narrator"] == "nova"
    assert cast["voices"]["张三"] == "onyx"
    assert cast["voices"]["李四"] == "nova"


def test_openai_provider_payload(tmp_path, monkeypatch):
    import httpx2

    captured = {}

    class Resp:
        content = b"RIFF" + b"0" * 100

        def raise_for_status(self):
            pass

    class Client:
        def __init__(self, *a, **k):
            captured["kw"] = k

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, json=None):
            captured.update(url=url, headers=headers, json=json)
            return Resp()

    monkeypatch.setattr(httpx2, "Client", Client)
    p = tp.OpenAITTSProvider(base_url="https://api.example.com/v1", api_key="k", model="m")
    out = tmp_path / "a.wav"
    p.synthesize("你好", "nova", str(out), emotion="angry")
    assert captured["url"] == "https://api.example.com/v1/audio/speech"
    assert captured["json"]["voice"] == "nova"
    assert captured["json"]["instructions"] == tp.EMOTION_PROMPTS["angry"]
    assert out.read_bytes().startswith(b"RIFF")


if __name__ == "__main__":
    test_cloud_cast_uses_cloud_voices()
    print("cloud tts tests passed")
