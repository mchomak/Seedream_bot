# localization.py
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


_LANG_RE = re.compile(r"^[a-z]{2}([_-][A-Z]{2})?$")


class _SafeFormatDict(dict):
    """Не падаем на отсутствующих плейсхолдерах: оставляем {name} как есть."""
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def normalize_lang(lang: Optional[str], default: str = "ru") -> str:
    if not lang:
        return default
    lang = lang.replace("_", "-")
    # Telegram часто отдаёт "en", "ru", иногда "en-US"
    if "-" in lang:
        base = lang.split("-", 1)[0].lower()
        region = lang.split("-", 1)[1].upper()
        return f"{base}-{region}"
    return lang.lower()


def _is_lang_code(s: str) -> bool:
    return bool(_LANG_RE.match(s))


@dataclass(frozen=True)
class LocalizerConfig:
    path: str | Path
    default_lang: str = "ru"
    # цепочка fallback: сначала exact ("en-US"), потом base ("en"), потом default ("ru")
    enable_base_fallback: bool = True
    strict_keys: bool = False  # если True: отсутствующий key -> KeyError


class Localizer:
    """
    Загружает локализацию из CSV/JSON в память при старте.
    Поддерживаемые форматы:
      CSV: key, ru, en, ... (как в Google Sheets)
      JSON:
        A) lang-first: {"ru": {"btn_start": "..."}, "en": {...}}
        B) key-first:  {"btn_start": {"ru": "...", "en": "..."}, ...}
        C) rows: [{"key":"btn_start","ru":"...","en":"..."}, ...]
    """

    def __init__(self, config: LocalizerConfig):
        self.config = config
        self.default_lang = normalize_lang(config.default_lang, "ru")
        self._data: Dict[str, Dict[str, Any]] = {}
        self._all_keys: set[str] = set()

    # ---------- public API ----------

    def load(self) -> "Localizer":
        path = Path(self.config.path)
        if not path.exists():
            raise FileNotFoundError(f"Localization file not found: {path}")

        if path.suffix.lower() == ".csv":
            rows = self._load_csv_rows(path)
            self._ingest_rows(rows)
        elif path.suffix.lower() == ".json":
            obj = json.loads(path.read_text(encoding="utf-8"))
            self._ingest_json(obj)
        else:
            raise ValueError("Unsupported localization format. Use .csv or .json")

        self._finalize()
        return self

    def available_languages(self) -> list[str]:
        return sorted(self._data.keys())

    def has_key(self, key: str) -> bool:
        return key in self._all_keys

    def get_raw(self, key: str, lang: Optional[str] = None) -> Any:
        """Вернуть значение без форматирования (может быть str/dict/list)."""
        lang = self._resolve_lang(lang)
        value = self._try_get(key, lang)
        if value is not None:
            return value

        # fallback chain
        for fb in self._fallback_chain(lang):
            value = self._try_get(key, fb)
            if value is not None:
                return value

        if self.config.strict_keys:
            raise KeyError(f"Missing localization key: {key}")
        return None

    def t(self, key: str, lang: Optional[str] = None, **fmt: Any) -> str:
        """
        Вернуть локализованную строку и безопасно применить .format().
        Если ключ не найден — вернём сам key (или KeyError при strict_keys=True).
        """
        raw = self.get_raw(key, lang=lang)

        if raw is None:
            return key

        if not isinstance(raw, str):
            # Если кто-то случайно положил объект — преобразуем в JSON-строку
            return json.dumps(raw, ensure_ascii=False)

        if fmt:
            return raw.format_map(_SafeFormatDict(fmt))
        return raw

    def group(self, prefix: str, lang: Optional[str] = None) -> Dict[str, str]:
        """
        Вернуть группу ключей вида:
           prefix.item -> {"item": "text", ...}
        Например prefix="help_items" для help_items.start, help_items.help ...
        """
        lang = self._resolve_lang(lang)
        out: Dict[str, str] = {}

        candidates = [lang] + list(self._fallback_chain(lang))
        for lg in candidates:
            for k, v in self._data.get(lg, {}).items():
                if not isinstance(v, str):
                    continue
                if k.startswith(prefix + "."):
                    short = k[len(prefix) + 1 :]
                    if short not in out:
                        out[short] = v
        return out

    # ---------- internal loading ----------

    def _load_csv_rows(self, path: Path) -> list[dict[str, str]]:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                raise ValueError("CSV has no header row.")
            if "key" not in reader.fieldnames:
                raise ValueError("CSV must contain 'key' column.")
            rows = []
            for row in reader:
                # normalize: strip keys and values
                cleaned = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
                if cleaned.get("key"):
                    rows.append(cleaned)
            return rows

    def _ingest_json(self, obj: Any) -> None:
        # C) rows
        if isinstance(obj, list):
            rows = []
            for item in obj:
                if not isinstance(item, dict) or "key" not in item:
                    raise ValueError("JSON rows format must be a list of objects with 'key'.")
                rows.append({str(k): ("" if v is None else str(v)) for k, v in item.items()})
            self._ingest_rows(rows)
            return

        if not isinstance(obj, dict):
            raise ValueError("JSON must be object or array.")

        # A) lang-first: {"ru": {...}, "en": {...}}
        if obj and all(isinstance(v, dict) for v in obj.values()) and all(_is_lang_code(str(k)) for k in obj.keys()):
            for lang, mapping in obj.items():
                lang_n = normalize_lang(str(lang), self.default_lang)
                self._data.setdefault(lang_n, {})
                for key, val in mapping.items():
                    self._data[lang_n][str(key)] = val
            return

        # B) key-first: {"btn_start": {"ru": "...", "en": "..."}, ...}
        if obj and all(isinstance(v, dict) for v in obj.values()):
            for key, per_lang in obj.items():
                for lang, val in per_lang.items():
                    lang_n = normalize_lang(str(lang), self.default_lang)
                    self._data.setdefault(lang_n, {})
                    self._data[lang_n][str(key)] = val
            return

        raise ValueError("Unsupported JSON structure for localization.")

    def _ingest_rows(self, rows: Iterable[dict[str, str]]) -> None:
        # rows: {"key": "...", "ru": "...", "en": "...", ...}
        for row in rows:
            key = str(row.get("key", "")).strip()
            if not key:
                continue

            for col, val in row.items():
                if col == "key":
                    continue
                if not col:
                    continue
                lang = normalize_lang(col, self.default_lang)
                self._data.setdefault(lang, {})
                # пустые ячейки пропускаем, чтобы работал fallback
                if isinstance(val, str) and val.strip() == "":
                    continue
                self._data[lang][key] = val

    def _finalize(self) -> None:
        # compute all keys
        keys = set()
        for mapping in self._data.values():
            keys.update(mapping.keys())
        self._all_keys = keys

        # ensure default language exists
        if self.default_lang not in self._data:
            self._data[self.default_lang] = {}

    def _resolve_lang(self, lang: Optional[str]) -> str:
        lang = normalize_lang(lang, self.default_lang)
        # если языка нет вообще — сразу уходим на default
        if lang not in self._data and self.config.enable_base_fallback:
            base = lang.split("-", 1)[0]
            if base in self._data:
                return base
        if lang not in self._data:
            return self.default_lang
        return lang

    def _fallback_chain(self, lang: str) -> Iterable[str]:
        # exact -> base -> default
        if self.config.enable_base_fallback and "-" in lang:
            base = lang.split("-", 1)[0]
            if base != lang:
                yield base
        if self.default_lang != lang:
            yield self.default_lang

    def _try_get(self, key: str, lang: str) -> Any:
        return self._data.get(lang, {}).get(key)
