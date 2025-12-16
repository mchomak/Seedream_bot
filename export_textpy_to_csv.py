# tools/export_textpy_to_csv.py
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict

from text import phrases  # ваш text.py


def flatten(d: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else str(k)
        if isinstance(v, dict):
            out.update(flatten(v, key))
        else:
            out[key] = v
    return out


def main() -> None:
    langs = sorted(phrases.keys())  # ["ru", "en", ...]
    flat_by_lang = {lang: flatten(phrases[lang]) for lang in langs}

    # Собираем множество ключей
    keys = set()
    for mapping in flat_by_lang.values():
        keys |= set(mapping.keys())
    keys = sorted(keys)

    out_path = Path("locales/phrases.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["key", *langs])
        for key in keys:
            row = [key]
            for lang in langs:
                val = flat_by_lang[lang].get(key, "")
                row.append("" if val is None else str(val))
            writer.writerow(row)

    print(f"Exported: {out_path}")


if __name__ == "__main__":
    main()
