import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from novelcast.config_manager import ConfigManager
from novelcast.local_tts import concat_segments, synthesize_lines
from novelcast.tts_providers import build_provider

cfg = ConfigManager("config/settings.json")
cast = json.load(open(r"output\全职高手_有声书\cast.json", encoding="utf-8"))
script = json.load(open(r"output\全职高手_有声书\002_第0002章 C区47号_script.json", encoding="utf-8"))
lines = script["lines"][:4]

provider = build_provider(cfg)
print("provider", provider.version, "alpha", provider.emo_alpha, "df", provider.duration_factor)
units = []
done = synthesize_lines(
    lines, r"output\_verify_p1", cast=cast, config=cfg, verbose=True, restart=True, units_out=units
)
paths = [done[i] for i in sorted(done)]
chars = [units[i]["character"] for i in sorted(done)]
stats = {}
out = r"output\_verify_p1\verify.wav"
concat_segments(paths, out, characters=chars, stats=stats)
print("stats", {k: round(v, 2) if isinstance(v, float) else v for k, v in stats.items()})
for l, u in zip(lines, units):
    print(" ", l["character"], "/", l["emotion"], "/", u["character"])
