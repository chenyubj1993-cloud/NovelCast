import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from novelcast.pronunciation import enabled_for
from novelcast.tts_providers import build_provider


def _cfg(**tts):
    return {"tts": tts}


def test_pronunciation_only_for_local_25():
    assert enabled_for(_cfg(provider="indextts2", model_version="2.5")) is True
    assert enabled_for(_cfg(provider="edge", model_version="2.5")) is False
    assert enabled_for(_cfg(provider="openai", model_version="2.5")) is False
    assert enabled_for(_cfg(provider="indextts2", model_version="2")) is False


def test_edge_rate_follows_duration_factor():
    p = build_provider(_cfg(provider="edge", duration_factor=0.9))
    assert p.rate == "+11%"
    p = build_provider(_cfg(provider="edge", duration_factor=1.0))
    assert p.rate == "+0%"


def test_cloud_speed_follows_duration_factor():
    p = build_provider(_cfg(provider="openai", duration_factor=0.8, cloud_api_key="test-key"))
    assert abs(p.speed - 1.25) < 1e-6
