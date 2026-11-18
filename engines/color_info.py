import colorsys
import json
import logging
import re
import urllib.parse
import urllib.request


class ColorInfoEngine:
    """Color information lookup — free API, no key needed."""

    def lookup(self, color: str) -> str:
        try:
            url = f"https://www.thecolorapi.com/id?name={urllib.parse.quote(color, safe='')}"
            req = urllib.request.Request(url, headers={"User-Agent": "Flexie/2.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                name = data.get("name", {}).get("value", color)
                hex_val = data.get("hex", {}).get("value", "")
                rgb = data.get("rgb", {})
                hsl = data.get("hsl", {})
                cmyk = data.get("cmyk", {})
                parts = [f"Color: {name}"]
                if hex_val:
                    parts.append(f"Hex: {hex_val}")
                if rgb:
                    parts.append(f"RGB: {rgb.get('r', 0)}, {rgb.get('g', 0)}, {rgb.get('b', 0)}")
                if hsl:
                    parts.append(f"HSL: {hsl.get('h', 0)}°, {hsl.get('s', 0)}%, {hsl.get('l', 0)}%")
                if cmyk:
                    parts.append(f"CMYK: {cmyk.get('c', 0)}, {cmyk.get('m', 0)}, {cmyk.get('y', 0)}, {cmyk.get('k', 0)}")
                return ". ".join(parts)
        except Exception as _e:
            logging.debug("[engines/color_info.py:29] Swallowed exception: %s: %s", type(_e).__name__, _e)
            return f"Could not look up color '{color}'."

    def from_hex(self, hex_code: str) -> str:
        try:
            url = f"https://www.thecolorapi.com/id?hex={urllib.parse.quote(hex_code.replace('#', ''), safe='')}"
            req = urllib.request.Request(url, headers={"User-Agent": "Flexie/2.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                name = data.get("name", {}).get("value", "Unknown")
                rgb = data.get("rgb", {})
                return f"Hex {hex_code}: {name}. RGB: {rgb.get('r', 0)}, {rgb.get('g', 0)}, {rgb.get('b', 0)}"
        except Exception as _e:
            logging.debug("[engines/color_info.py:41] Swallowed exception: %s: %s", type(_e).__name__, _e)
            return f"Could not look up hex '{hex_code}'."

    def random_color(self) -> str:
        try:
            import random
            r = random.randint(0, 255)
            g = random.randint(0, 255)
            b = random.randint(0, 255)
            hex_val = f"#{r:02x}{g:02x}{b:02x}"
            return self.from_hex(hex_val)
        except Exception as _e:
            logging.debug("[engines/color_info.py:52] Swallowed exception: %s: %s", type(_e).__name__, _e)
            return "Could not generate random color."

    def complementary(self, hex_code: str) -> str:
        """Complement = hue rotated by 180 degrees (not the RGB inverse)."""
        hex_val = (hex_code or "").strip().lstrip("#")
        if not re.fullmatch(r"[0-9a-fA-F]{6}", hex_val):
            return "Invalid hex code."
        r, g, b = (int(hex_val[i:i + 2], 16) for i in (0, 2, 4))
        h, light, sat = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        cr, cg, cb = colorsys.hls_to_rgb((h + 0.5) % 1.0, light, sat)
        comp_r, comp_g, comp_b = (int(round(v * 255)) for v in (cr, cg, cb))
        comp_hex = f"#{comp_r:02x}{comp_g:02x}{comp_b:02x}"
        return f"Complementary color: {comp_hex} (RGB: {comp_r}, {comp_g}, {comp_b})"
