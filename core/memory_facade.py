"""Single write/forget path for user facts across every memory store.

Facts used to be written to five stores by ad-hoc code in the handlers, while
"forget" only reached two of them — a "forgotten" fact could resurface from the
others. All remember/forget operations on user facts go through this facade so
the stores cannot drift apart. Stores are resolved lazily and each is optional.

``scrub`` (re-exported from ``core.memory_manager``) masks passwords, PINs, OTPs, API
keys and tokens; every store path in this package applies it before writing.
"""
from __future__ import annotations

import hashlib
import itertools
import logging
import time
from dataclasses import dataclass, field

from core.memory_manager import MemoryCategory, contains_secret, scrub

__all__ = ["ForgetReport", "MemoryFacade", "contains_secret", "scrub"]

logger = logging.getLogger("Flexie.MemoryFacade")


@dataclass
class ForgetReport:
    removed: dict[str, int] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    # Per-table counts ("memory_system.conversations": 2) for stores that report them.
    detail: dict[str, int] = field(default_factory=dict)
    # Stores that could not be searched at all (missing, unavailable or failed).
    unreachable: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(self.removed.values())

    def summary(self) -> str:
        parts = [f"{n} in {name}" for name, n in self.removed.items()]
        text = "removed " + ", ".join(parts) if parts else "nothing matched"
        if self.unreachable:
            text += "; could not reach: " + ", ".join(self.unreachable)
        return text


_COUNTER = itertools.count()


def unique_key(prefix: str, text: str) -> str:
    """``prefix_<time_ns>_<hash>_<n>``: unique even for identical texts in the same tick.

    The process-wide counter matters on Windows, where the clock can return the same
    ``time_ns`` for consecutive calls.
    """
    digest = hashlib.sha1((text or "").encode("utf-8", "replace")).hexdigest()[:6]
    return f"{prefix}_{time.time_ns()}_{digest}_{next(_COUNTER)}"


class MemoryFacade:
    def __init__(self, orch):
        self.orch = orch

    def _store(self, name: str):
        return getattr(self.orch, name, None)

    def _brain_vectors(self):
        return getattr(getattr(self.orch, "brain", None), "vector_store", None)

    def remember_fact(
        self,
        key: str,
        value: str,
        raw_fact: str | None = None,
        category: MemoryCategory = MemoryCategory.FACTS,
        importance: float = 0.85,
        tags: list[str] | None = None,
        index_vector: bool = False,
        source: str = "user",
    ) -> list[str]:
        """Write a fact to every store. Returns the names of stores written."""
        raw_fact = raw_fact or value
        written: list[str] = []

        def _try(name, fn):
            try:
                fn()
                written.append(name)
            except Exception as e:
                logger.warning("[MEMORY] write to %s failed: %s", name, e)

        # Redact once up front; each store also scrubs defensively.
        secret = contains_secret(raw_fact) or contains_secret(value) or contains_secret(key)
        key, value, raw_fact = scrub(key), scrub(value), scrub(raw_fact)

        mm = self._store("memory_manager")
        if mm:
            _try("memory_manager", lambda: mm.remember(
                key, value, category=category, importance=importance, source=source,
                tags=tags or ["user_explicit"]))
        ms = self._store("memory_system")
        if ms:
            _try("memory_system", lambda: ms.set_preference(unique_key("fact", raw_fact), raw_fact))
        aw = self._store("awareness")
        if aw:
            _try("awareness", lambda: aw.learn_fact(raw_fact, "user_told"))
        me = self._store("memory")
        if me and hasattr(me, "store"):
            _try("memory", lambda: me.store(key, value, cat="user"))
        if index_vector and not secret:   # flagged text never reaches the vector store
            vs = self._brain_vectors()
            if vs:
                _try("vector_store", lambda: vs.add_episode(
                    unique_key("fact", raw_fact), raw_fact, {"source": source}))
        return written

    def forget(self, target: str) -> ForgetReport:
        """Delete everything matching ``target`` from EVERY store; report what was removed.

        The report lists counts per store, per-table detail where available and the
        stores that could not be reached. Both wiki copies are rewritten synchronously.
        """
        report = ForgetReport()
        target = (target or "").strip()
        if not target:
            return report

        def _run(name, fn):
            try:
                res = fn()
                if isinstance(res, dict):
                    for table, n in res.items():
                        if n:
                            report.detail[f"{name}.{table}"] = int(n)
                    n = sum(int(v) for v in res.values())
                else:
                    n = int(res or 0)
                if n:
                    report.removed[name] = n
            except Exception as e:
                report.errors[name] = str(e)
                report.unreachable.append(name)
                logger.warning("[MEMORY] forget in %s failed: %s", name, e)

        def _missing(name):
            report.unreachable.append(name)

        mm = self._store("memory_manager")
        if mm:
            _run("memory_manager", lambda: mm.forget_matching(target))
        else:
            _missing("memory_manager")

        ms = self._store("memory_system")
        if ms and hasattr(ms, "forget_everywhere"):
            _run("memory_system", lambda: ms.forget_everywhere(target))
        elif ms and hasattr(ms, "forget_matching"):
            _run("memory_system", lambda: ms.forget_matching(target))
        else:
            _missing("memory_system")

        aw = self._store("awareness")
        if aw and hasattr(aw, "forget_everywhere"):
            _run("awareness", lambda: aw.forget_everywhere(target))
        elif aw and hasattr(aw, "forget_fact"):
            _run("awareness", lambda: aw.forget_fact(target))
        else:
            _missing("awareness")

        me = self._store("memory")
        if me and hasattr(me, "forget_everywhere"):
            _run("memory", lambda: me.forget_everywhere(target))
        elif me and hasattr(me, "forget_matching"):
            _run("memory", lambda: me.forget_matching(target))
        elif me and hasattr(me, "forget"):
            def _exact():
                existed = hasattr(me, "recall") and me.recall(target) is not None
                me.forget(target)
                return 1 if existed else 0
            _run("memory", _exact)
        else:
            _missing("memory")

        pr = self._store("preferences")
        if pr and hasattr(pr, "forget_matching"):
            _run("preferences", lambda: pr.forget_matching(target))

        ctx = self._store("ctx") or self._store("context_memory")
        if ctx and hasattr(ctx, "forget_matching"):
            _run("context", lambda: ctx.forget_matching(target))

        gm = next((g for g in (self._store("long_term"), self._store("global_memory"),
                               getattr(self._store("controller"), "long_term", None))
                   if g is not None and hasattr(g, "forget_matching")), None)
        if gm:
            _run("global_profile", lambda: gm.forget_matching(target))

        vs = self._brain_vectors()
        if vs and hasattr(vs, "forget_matching"):
            if getattr(vs, "collection", None) is None and not getattr(vs, "_pending", None):
                _missing("vector_store")   # no Chroma collection: nothing could be searched
            else:
                _run("vector_store", lambda: vs.forget_matching(target))
        else:
            _missing("vector_store")

        # Rewrite BOTH wiki copies now (not debounced) so a forgotten fact is not
        # readable from data/MEMORY.md or workspace/MEMORY.md for another few seconds.
        if mm and hasattr(mm, "sync_markdown_wiki"):
            try:
                mm.sync_markdown_wiki(force=True)
            except Exception as e:  # noqa: BLE001
                report.errors["wiki"] = str(e)
                report.unreachable.append("wiki")
                logger.warning("[MEMORY] wiki rewrite after forget failed: %s", e)
        return report
