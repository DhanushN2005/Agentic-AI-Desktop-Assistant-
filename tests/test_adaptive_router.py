
from core.adaptive_router import AdaptiveRouter


def test_persists_after_first_success(tmp_path):
    history = tmp_path / "routing_history.json"
    router = AdaptiveRouter(str(history))
    router.record_route("open spotify", "launch_spotify", True)
    assert history.exists()


def test_route_loaded_across_instances(tmp_path):
    history = tmp_path / "routing_history.json"
    router = AdaptiveRouter(str(history))
    for _ in range(3):
        router.record_route("open spotify", "launch_spotify", True)
    reloaded = AdaptiveRouter(str(history))
    assert reloaded.get_cached_route("open spotify") == "launch_spotify"


def test_failed_routes_not_recorded(tmp_path):
    history = tmp_path / "routing_history.json"
    router = AdaptiveRouter(str(history))
    router.record_route("rm -rf", "delete_everything", False)
    assert not history.exists()


def test_fuzzy_match_with_filler_words(tmp_path):
    router = AdaptiveRouter(str(tmp_path / "routing_history.json"))
    for _ in range(3):
        router.record_route("open spotify", "launch_spotify", True)
    assert router.get_cached_route("open spotify please") == "launch_spotify"
    assert router.get_cached_route("please open spotify for me") == "launch_spotify"


def test_fuzzy_match_rejects_different_action(tmp_path):
    router = AdaptiveRouter(str(tmp_path / "routing_history.json"))
    for _ in range(3):
        router.record_route("open spotify", "launch_spotify", True)
    assert router.get_cached_route("play spotify") is None
    assert router.get_cached_route("open") is None


def test_fuzzy_match_picks_closest_route(tmp_path):
    router = AdaptiveRouter(str(tmp_path / "routing_history.json"))
    for _ in range(3):
        router.record_route("open spotify", "launch_spotify", True)
        router.record_route("open vscode", "launch_vscode", True)
    assert router.get_cached_route("open spotify now") == "launch_spotify"
    assert router.get_cached_route("open vscode now") == "launch_vscode"
