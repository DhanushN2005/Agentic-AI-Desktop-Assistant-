import urllib.request
import json


class ColorInfoEngine:
    """Color information lookup — free API, no key needed."""

    def lookup(self, color: str) -> str:
        try:
            url = f"https://www.thecolorapi.com/id?name={color.replace(' ', '%20')}"
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
        except Exception:
            return f"Could not look up color '{color}'."

    def from_hex(self, hex_code: str) -> str:
        try:
            url = f"https://www.thecolorapi.com/id?hex={hex_code.replace('#', '')}"
            req = urllib.request.Request(url, headers={"User-Agent": "Flexie/2.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                name = data.get("name", {}).get("value", "Unknown")
                rgb = data.get("rgb", {})
                return f"Hex {hex_code}: {name}. RGB: {rgb.get('r', 0)}, {rgb.get('g', 0)}, {rgb.get('b', 0)}"
        except Exception:
            return f"Could not look up hex '{hex_code}'."

    def random_color(self) -> str:
        try:
            import random
            r = random.randint(0, 255)
            g = random.randint(0, 255)
            b = random.randint(0, 255)
            hex_val = f"#{r:02x}{g:02x}{b:02x}"
            return self.from_hex(hex_val)
        except Exception:
            return "Could not generate random color."

    def complementary(self, hex_code: str) -> str:
        try:
            hex_val = hex_code.replace('#', '')
            r = int(hex_val[0:2], 16)
            g = int(hex_val[2:4], 16)
            b = int(hex_val[4:6], 16)
            comp_r = 255 - r
            comp_g = 255 - g
            comp_b = 255 - b
            comp_hex = f"#{comp_r:02x}{comp_g:02x}{comp_b:02x}"
            return f"Complementary color: {comp_hex} (RGB: {comp_r}, {comp_g}, {comp_b})"
        except Exception:
            return "Invalid hex code."
