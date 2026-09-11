import urllib.request
import json


class IPLookupEngine:
    """IP address lookup — free API, no key needed."""

    def lookup(self, ip: str = None) -> str:
        try:
            if ip:
                url = f"http://ip-api.com/json/{ip}"
            else:
                url = "http://ip-api.com/json/"
            req = urllib.request.Request(url, headers={"User-Agent": "Flexie/2.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                if data.get("status") == "success":
                    parts = []
                    if data.get("query"):
                        parts.append(f"IP: {data['query']}")
                    if data.get("country"):
                        parts.append(f"Country: {data['country']}")
                    if data.get("regionName"):
                        parts.append(f"Region: {data['regionName']}")
                    if data.get("city"):
                        parts.append(f"City: {data['city']}")
                    if data.get("isp"):
                        parts.append(f"ISP: {data['isp']}")
                    if data.get("org"):
                        parts.append(f"Org: {data['org']}")
                    if data.get("as"):
                        parts.append(f"AS: {data['as']}")
                    return ". ".join(parts)
                return f"Could not look up IP: {data.get('message', 'unknown error')}"
        except Exception as e:
            return f"IP lookup failed: {e}"

    def get_public_ip(self) -> str:
        try:
            req = urllib.request.Request("https://api.ipify.org?format=json", headers={"User-Agent": "Flexie/2.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                return f"Your public IP: {data.get('ip', 'unknown')}"
        except Exception:
            return "Could not determine public IP."
