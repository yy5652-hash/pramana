"""Print the simulation summary compactly (used while tuning; reads results/simulation.json)."""
import json
from .common import RESULTS

d = json.loads((RESULTS / "simulation.json").read_text())
for kind, block in d["learners"].items():
    print(kind)
    for policy, s in block["summary"].items():
        print(f"  {policy:10s} gain {s['gain']:+.3f}  probe error {s['probe_error_first_session']:.3f} -> {s['probe_error_last_session']:.3f} (no model {s['probe_error_without_model']:.3f})  "
              f"weak5 {s['weakest5_last_session']:.2f}  spearman {s['spearman_last_session']:.2f}  repeats {s['exact_repeat_rate']:.3f}")
    profiles = sorted({c["profile"] for c in block["cells"].values()})
    for profile in profiles:
        row = "  ".join(f"{p[:3]} {block['cells'][f'{profile}|{p}']['gain']['mean']:+.3f}" for p in ("adaptive", "sequential", "random"))
        print(f"    {profile:26s} {row}")
