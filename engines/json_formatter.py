import json
import logging

_TYPE_ORDER = ["object", "array", "string", "number", "boolean", "null"]


class JSONFormatterEngine:
    """JSON formatting and validation — no API needed."""

    @staticmethod
    def _err(e) -> str:
        if isinstance(e, RecursionError):
            return "Invalid or too deeply nested JSON."
        return f"Invalid JSON: {e}"

    def format_json(self, text: str, indent: int = 2) -> str:
        try:
            data = json.loads(text)
            formatted = json.dumps(data, indent=indent, ensure_ascii=False)
            return formatted
        except (json.JSONDecodeError, RecursionError) as e:
            logging.debug("[engines/json_formatter.py:12] Swallowed exception: %s: %s", type(e).__name__, e)
            return self._err(e)

    def minify_json(self, text: str) -> str:
        try:
            data = json.loads(text)
            return json.dumps(data, separators=(',', ':'), ensure_ascii=False)
        except (json.JSONDecodeError, RecursionError) as e:
            logging.debug("[engines/json_formatter.py:19] Swallowed exception: %s: %s", type(e).__name__, e)
            return self._err(e)

    def validate_json(self, text: str) -> str:
        try:
            data = json.loads(text)
            keys = self._count_keys(data)
            types = self._detect_types(data)
            return f"Valid JSON. Keys: {keys}. Types: {types}"
        except (json.JSONDecodeError, RecursionError) as e:
            logging.debug("[engines/json_formatter.py:28] Swallowed exception: %s: %s", type(e).__name__, e)
            if isinstance(e, RecursionError):
                return "Invalid or too deeply nested JSON."
            return f"Invalid JSON at position {e.pos}: {e.msg}"

    def json_info(self, text: str) -> str:
        try:
            data = json.loads(text)
            info = []
            if isinstance(data, dict):
                info.append(f"Object with {len(data)} keys: {', '.join(list(data.keys())[:10])}")
            elif isinstance(data, list):
                info.append(f"Array with {len(data)} elements")
                if data:
                    info.append(f"First element type: {type(data[0]).__name__}")
            else:
                info.append(f"Value: {type(data).__name__}")
            info.append(f"Size: {len(text.encode('utf-8'))} bytes")
            return ". ".join(info)
        except (json.JSONDecodeError, RecursionError) as e:
            logging.debug("[engines/json_formatter.py:45] Swallowed exception: %s: %s", type(e).__name__, e)
            return self._err(e)

    def extract_keys(self, text: str) -> str:
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return "Keys: " + ", ".join(data.keys())
            return "Not a JSON object."
        except (json.JSONDecodeError, RecursionError) as _e:
            logging.debug("[engines/json_formatter.py:54] Swallowed exception: %s: %s", type(_e).__name__, _e)
            return self._err(_e)

    def flatten_json(self, text: str) -> str:
        try:
            data = json.loads(text)
            flat = self._flatten(data)
            return json.dumps(flat, indent=2, ensure_ascii=False)
        except (json.JSONDecodeError, RecursionError) as e:
            logging.debug("[engines/json_formatter.py:62] Swallowed exception: %s: %s", type(e).__name__, e)
            return self._err(e)

    def _count_keys(self, obj, count=0):
        if isinstance(obj, dict):
            count += len(obj)
            for v in obj.values():
                count = self._count_keys(v, count)
        elif isinstance(obj, list):
            for item in obj:
                count = self._count_keys(item, count)
        return count

    def _detect_types(self, obj):
        types = set()
        if isinstance(obj, dict):
            types.add("object")
            for v in obj.values():
                types.update(self._detect_types(v).split(", "))
        elif isinstance(obj, list):
            types.add("array")
            for item in obj:
                types.update(self._detect_types(item).split(", "))
        elif isinstance(obj, bool):
            types.add("boolean")
        elif isinstance(obj, (int, float)):
            types.add("number")
        elif isinstance(obj, str):
            types.add("string")
        elif obj is None:
            types.add("null")
        return ", ".join(t for t in _TYPE_ORDER if t in types)

    def _flatten(self, obj, prefix=""):
        items = {}
        if isinstance(obj, dict):
            for k, v in obj.items():
                key = f"{prefix}.{k}" if prefix else k
                if isinstance(v, (dict, list)) and v:
                    items.update(self._flatten(v, key))
                else:
                    items[key] = v
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                key = f"{prefix}[{i}]"
                if isinstance(v, (dict, list)) and v:
                    items.update(self._flatten(v, key))
                else:
                    items[key] = v
        else:
            items[prefix] = obj
        return items
