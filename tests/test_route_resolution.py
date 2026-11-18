"""Routing precedence + single-route-per-command (architecture fix: router consolidation)."""
from types import SimpleNamespace

from core.hybrid_router import HybridRouter
from core.orchestrator import FlexieOrchestrator


class _Router:
    def __init__(self, table):
        self.table, self.calls = table, 0

    def route(self, text):
        self.calls += 1
        return self.table.get(text, ("conversational", 0.3))


def _orch(router, learned=None):
    o = FlexieOrchestrator.__new__(FlexieOrchestrator)
    o.router = router
    o._route_cache = {}
    o._route_cache_max = 64
    o.logger = __import__("logging").getLogger("t")
    o.adaptive_router = SimpleNamespace(get_cached_route=lambda c: learned)
    return o


def test_deterministic_route_beats_learned_route():
    o = _orch(_Router({"open notepad": ("app_op", 0.95)}), learned="wrong_intent")
    intent, conf, auth = o._resolve_route("open notepad")
    assert intent == "app_op" and conf == 0.95 and not auth


def test_learned_route_used_only_when_router_unsure_and_never_full_confidence():
    o = _orch(_Router({}), learned="weather")
    intent, conf, _ = o._resolve_route("whats it like outside")
    assert intent == "weather" and conf <= 0.85


def test_router_runs_once_per_command_thanks_to_cache():
    r = _Router({"play jazz": ("play_youtube", 0.9)})
    o = _orch(r)
    o._resolve_route("play jazz")
    o._resolve_route("play jazz")
    assert r.calls == 1


def test_classify_reuses_precomputed_route():
    r = _Router({})
    h = HybridRouter(r)
    h.classify("play jazz music please", routed=("play_youtube", 0.95))
    assert r.calls == 0


def test_phrase_with_and_is_not_split_when_route_is_confident():
    h = HybridRouter(_Router({}))
    assert h.classify("search for rock and roll music", routed=("search", 0.95)) == "simple"
    assert h.classify("search for rock then play it", routed=("search", 0.95)) == "complex"
