"""Drop cached model replies that nothing asks for any more.

While the prompts were being developed, superseded requests piled up in `data/llm_cache/`.
Run the whole pipeline once with `PRAMANA_CACHE_TRACE=trace.tsv` set, then:

    python scripts/prune_cache.py trace.tsv [--namespaces ingest-pages questions-generate ...]

Only the namespaces that appear in the trace (or those named) are pruned; the rest are left
alone, so tracing one stage never deletes another stage's replies.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

CACHE = Path(__file__).resolve().parent.parent / "data" / "llm_cache"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("trace")
    parser.add_argument("--namespaces", nargs="*")
    parser.add_argument("--delete", nargs="*", default=[], help="namespaces to remove entirely (development probes)")
    args = parser.parse_args()
    used: dict[str, set[str]] = {}
    for line in Path(args.trace).read_text().splitlines():
        namespace, key = line.split("\t")
        used.setdefault(namespace, set()).add(key)
    for namespace in args.delete:
        (CACHE / f"{namespace}.jsonl").unlink(missing_ok=True)
        print(f"{namespace}: deleted")
    for namespace in sorted(args.namespaces or used):
        path = CACHE / f"{namespace}.jsonl"
        if not path.exists():
            continue
        rows = {}
        for line in path.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                rows[row["key"]] = row          # the last reply for a key wins
        kept = [row for key, row in rows.items() if key in used.get(namespace, set())]
        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in kept))
        print(f"{namespace}: kept {len(kept)} of {len(rows)}")


if __name__ == "__main__":
    main()
