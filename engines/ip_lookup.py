import ipaddress
import json
import logging
import re
import socket
import urllib.parse
import urllib.request

_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$", re.IGNORECASE)


class IPLookupEngine:
    """IP address lookup — free API, no key needed."""

    # ip-api.com free tier is HTTP only; HTTPS is tried first and the plain
    # endpoint is only a fallback.
    ENDPOINTS = ("https://ipwho.is/{q}", "http://ip-api.com/json/{q}")

    @staticmethod
    def validate_ip(ip: str):
        """Return a normalised IP string or None (octets must be 0-255)."""
        try:
            return str(ipaddress.ip_address((ip or "").strip()))
        except ValueError:
            return None

    @staticmethod
    def resolve_domain(name: str):
        if not _DOMAIN_RE.match(name or ""):
            return None
        try:
            return socket.gethostbyname(name)
        except OSError:
            return None

    def _fetch(self, url: str) -> dict:
        req = urllib.request.Request(url, headers={"User-Agent": "Flexie/2.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())

    def lookup(self, ip: str = None) -> str:
        target = ""
        if ip:
            valid = self.validate_ip(ip)
            if valid is None:
                valid = self.resolve_domain(ip)
            if valid is None:
                return f"'{ip}' is not a valid IP address or domain."
            target = urllib.parse.quote(valid, safe=":")
        data = None
        last_err = None
        for tmpl in self.ENDPOINTS:
            try:
                data = self._fetch(tmpl.format(q=target))
                if not isinstance(data, dict):
                    data = None
                    continue
                ok = data.get("status") == "success" or data.get("success") is True
                if ok:
                    break
                last_err = data.get("message", "unknown error")
                data = None
            except Exception as e:
                logging.debug("[engines/ip_lookup.py] %s: %s", type(e).__name__, e)
                last_err = str(e)
                data = None
        if not data:
            return f"Could not look up IP: {last_err or 'unknown error'}"
        conn = data.get("connection") if isinstance(data.get("connection"), dict) else {}
        fields = [
            ("IP", data.get("query") or data.get("ip")),
            ("Country", data.get("country")),
            ("Region", data.get("regionName") or data.get("region")),
            ("City", data.get("city")),
            ("ISP", data.get("isp") or conn.get("isp")),
            ("Org", data.get("org") or conn.get("org")),
            ("AS", data.get("as") or conn.get("asn")),
        ]
        return ". ".join(f"{k}: {v}" for k, v in fields if v)

    def get_public_ip(self) -> str:
        try:
            req = urllib.request.Request("https://api.ipify.org?format=json", headers={"User-Agent": "Flexie/2.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                return f"Your public IP: {data.get('ip', 'unknown')}"
        except Exception as _e:
            logging.debug("[engines/ip_lookup.py] %s: %s", type(_e).__name__, _e)
            return "Could not determine public IP."
