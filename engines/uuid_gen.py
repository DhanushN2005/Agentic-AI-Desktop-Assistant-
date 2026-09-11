import uuid
import time


class UUIDEngine:
    """UUID generator — no API needed."""

    def generate_v4(self) -> str:
        return f"UUID v4: {uuid.uuid4()}"

    def generate_v1(self) -> str:
        return f"UUID v1: {uuid.uuid1()}"

    def generate_batch(self, count: int = 5) -> str:
        if count > 50:
            count = 50
        uuids = [str(uuid.uuid4()) for _ in range(count)]
        return "Generated UUIDs:\n" + "\n".join(f"  {i+1}. {u}" for i, u in enumerate(uuids))

    def generate_namespace(self, namespace: str, name: str) -> str:
        ns = uuid.uuid5(uuid.NAMESPACE_DNS, namespace)
        return f"UUID v5 (namespace={namespace}, name={name}): {uuid.uuid5(ns, name)}"

    def is_valid(self, text: str) -> str:
        try:
            u = uuid.UUID(text)
            return f"Valid UUID: {u} (version {u.version}, variant {u.variant})"
        except ValueError:
            return f"Invalid UUID: '{text}'"

    def timestamp(self, text: str) -> str:
        try:
            u = uuid.UUID(text)
            if u.version == 1:
                ts = u.time
                # UUID v1 timestamp is 100-nanosecond intervals since 1582-10-15
                timestamp = (ts - 0x01b21dd213814000) / 1e7
                import datetime
                dt = datetime.datetime.fromtimestamp(timestamp)
                return f"UUID v1 timestamp: {dt.strftime('%Y-%m-%d %H:%M:%S')}"
            return "Timestamp only available for UUID v1."
        except ValueError:
            return "Invalid UUID."
