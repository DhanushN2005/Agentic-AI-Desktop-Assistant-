"""Single write/forget path for user facts across every memory store.

Facts used to be written to five stores by ad-hoc code in the handlers, while
"forget" only reached two of them — a "forgotten" fact could resurface from the
others. All remember/forget operations on user facts go through this facade so
the stores cannot drift apart. Stores are resolved lazily and each is optional.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from core.memory_manager import MemoryCategory

logger = logging.getLogger("Flexie.MemoryFacade")


@dataclass
class ForgetReport:
    removed: dict[str, int] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.removed.values())


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

        mm = self._store("memory_manager")
        if mm:
            _try("memory_manager", lambda: mm.remember(
                key, value, category=category, importance=importance, source=source,
                tags=tags or ["user_explicit"]))
        ms = self._store("memory_system")
        if ms:
            _try("memory_system", lambda: ms.set_preference(f"fact_{int(time.time())}", raw_fact))
        aw = self._store("awareness")
        if aw:
            _try("awareness", lambda: aw.learn_fact(raw_fact, "user_told"))
        me = self._store("memory")
        if me and hasattr(me, "store"):
            _try("memory", lambda: me.store(key, value, cat="user"))
        if index_vector:
            vs = self._brain_vectors()
            if vs:
                _try("vector_store", lambda: vs.add_episode(
                    f"fact_{int(time.time() * 1000)}", raw_fact, {"source": source}))
        return written

    def forget(self, target: str) -> ForgetReport:
        """Delete everything matching ``target`` from EVERY store; report what was removed."""
        report = ForgetReport()
        target = (target or "").strip()
        if not target:
            return report

        def _run(name, fn):
            try:
                n = fn() or 0
                if n:
                    report.removed[name] = int(n)
            except Exception as e:
                report.errors[name] = str(e)
                logger.warning("[MEMORY] forget in %s failed: %s", name, e)

        mm = self._store("memory_manager")
        if mm:
            _run("memory_manager", lambda: mm.forget_matching(target))
        ms = self._store("memory_system")
        if ms and hasattr(ms, "forget_matching"):
            _run("memory_system", lambda: ms.forget_matching(target))
        aw = self._store("awareness")
        if aw and hasattr(aw, "forget_fact"):
            _run("awareness", lambda: aw.forget_fact(target))
        me = self._store("memory")
        if me and hasattr(me, "forget_matching"):
            _run("memory", lambda: me.forget_matching(target))
        elif me and hasattr(me, "forget"):
            def _exact():
                existed = hasattr(me, "recall") and me.recall(target) is not None
                me.forget(target)
                return 1 if existed else 0
            _run("memory", _exact)
        vs = self._brain_vectors()
        if vs and hasattr(vs, "forget_matching"):
            _run("vector_store", lambda: vs.forget_matching(target))
        return report
