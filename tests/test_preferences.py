"""Long-term preference memory (the Mem0 idea, local): learn, update, ignore, retrieve, forget."""
import types

import pytest

from core.preferences import PreferenceStore, extract_llm, extract_rules, is_candidate, is_statement


@pytest.fixture
def store(tmp_path):
    return PreferenceStore(str(tmp_path / "prefs.db"))


def texts(store):
    return sorted(p["text"] for p in store.all())


# --------------------------------------------------------------------------- what is (and is not) a preference
@pytest.mark.parametrize("phrase,fact", [
    ("I prefer short answers", "Prefers short answers"),
    ("call me Sam", "Name is Sam"),
    ("my name is Dhanush N", "Name is Dhanush N"),
    ("I live in Chennai", "Lives in Chennai"),
    ("I'm a software engineer", "Is a software engineer"),
    ("I hate long explanations", "Dislikes long explanations"),
    ("I always use VS Code for coding", "Always use VS Code for coding"),
    ("my favourite colour is blue", "Favourite colour is blue"),
    ("from now on keep answers brief", "Standing instruction: keep answers brief"),
    ("please always reply in Hindi", "Standing instruction: reply in hindi"),
    ("stop calling me sir", "Does not want: calling me sir"),
    ("remember that I prefer dark mode", "Prefers dark mode"),
])
def test_clear_statements_become_short_facts(phrase, fact):
    assert is_candidate(phrase)
    assert [f["text"] for f in extract_rules(phrase)] == [fact]


@pytest.mark.parametrize("phrase", [
    "what do I like", "open chrome", "I want you to open chrome", "I am tired", "I'm hungry right now", "I prefer short answers today",
    "my password is hunter2", "I have diabetes and prefer sugar free", "play some music", "I love you flexie", "how do I use vs code",
    "I use my laptop daily", "my api key is sk-abcdefghijklmnop",
])
def test_questions_commands_temporary_sensitive_and_secret_text_are_never_learned(phrase, store):
    assert is_statement(phrase) is False
    assert store.learn(phrase) == [] and store.all() == []


def test_health_is_kept_only_when_the_user_explicitly_says_remember(store):
    assert store.learn("I have diabetes and I prefer sugar free") == []
    assert is_candidate("remember that I prefer sugar free desserts")


def test_secrets_never_reach_the_database_even_when_forced(store):
    assert store.apply("Password is hunter2 and api key sk-live-abcdefghijklmnop").op == "NONE"
    assert store.all() == []


# --------------------------------------------------------------------------- ADD / UPDATE / NONE
def test_new_facts_are_added_repeats_are_ignored_and_changes_replace_the_old_one(store):
    assert store.learn("I prefer short answers")[0].op == "ADD"
    assert store.learn("I prefer short answers") == []                          # already known
    assert texts(store) == ["Prefers short answers"]
    changed = store.learn("I hate long explanations")                           # same topic (answer length): replaces
    assert changed[0].op == "UPDATE" and changed[0].previous == "Prefers short answers"
    assert texts(store) == ["Dislikes long explanations"]
    store.learn("call me Sam")
    store.learn("call me Alex")
    assert [t for t in texts(store) if t.startswith("Name")] == ["Name is Alex"]


def test_unrelated_facts_live_side_by_side(store):
    for phrase in ("I live in Chennai", "I'm a software engineer", "I like jazz music", "I like rock music", "I always use VS Code"):
        store.learn(phrase)
    assert len(store.all()) == 5                                                # two music tastes are both kept; nothing replaced
    assert store.learn("I live in Mumbai")[0].op == "UPDATE"
    assert "Lives in Mumbai" in texts(store) and "Lives in Chennai" not in texts(store)


def test_the_store_is_bounded(store, monkeypatch):
    monkeypatch.setattr("core.preferences.MAX_FACTS", 5)
    for word in ("apples", "bicycles", "chess", "drones", "espresso", "falcons", "guitars", "hiking", "origami"):
        store.apply(f"Likes {word}")
    assert len(store.all()) == 5


# --------------------------------------------------------------------------- bringing the right ones back
def test_standing_preferences_always_apply_and_others_only_when_relevant(store):
    for phrase in ("I prefer short answers", "call me Sam", "I like jazz music", "I always use VS Code for coding", "I live in Chennai"):
        store.learn(phrase)
    general = store.prompt_block("what is the capital of france")
    assert "Prefers short answers" in general and "Name is Sam" in general
    assert "jazz" not in general and "VS Code" not in general                    # unrelated: stays out of the prompt
    assert "jazz" in store.prompt_block("recommend some jazz to play")
    assert "VS Code" in store.prompt_block("how do I set up vs code for python")
    assert "do not recite" in general.lower() and "\n" not in store.relevant("x")[0]


def test_nothing_learned_means_nothing_added_to_the_prompt(store):
    assert store.prompt_block("hello there") == ""


# --------------------------------------------------------------------------- forgetting
def test_forget_by_meaning_by_text_and_everything(store):
    for phrase in ("I prefer short answers", "call me Sam", "I like jazz music"):
        store.learn(phrase)
    assert store.forget_matching("that I prefer short answers") == 1               # said the way a person says it
    assert store.forget_matching("jazz") == 1
    assert texts(store) == ["Name is Sam"]
    assert store.forget_matching("something else entirely") == 0
    pid = store.all()[0]["id"]
    assert store.delete(pid) is True and store.delete(pid) is False
    store.learn("call me Sam")
    assert store.clear() == 1 and store.all() == []


def test_the_shared_forget_path_reaches_the_preference_store(store):
    from core.memory_facade import MemoryFacade
    store.learn("I prefer short answers")
    orch = types.SimpleNamespace(preferences=store)
    report = MemoryFacade(orch).forget("short answers")
    assert report.removed.get("preferences") == 1 and store.all() == []


# --------------------------------------------------------------------------- the model fallback is careful
def test_model_fallback_only_accepts_clean_short_facts():
    brain = types.SimpleNamespace(ask=lambda p, **k: '```json\n{"facts": ["Prefers metric units", "The user likes tea", "password is abc123", ""]}\n```')
    assert [f["text"] for f in extract_llm(brain, "I like things in km and celsius")] == ["Prefers metric units"]
    broken = types.SimpleNamespace(ask=lambda p, **k: (_ for _ in ()).throw(RuntimeError("no provider")))
    assert extract_llm(broken, "I prefer metric") == []
    assert extract_llm(types.SimpleNamespace(ask=lambda p, **k: "not json at all"), "x") == []


def test_the_model_is_used_only_for_unusual_phrasing_with_a_strong_signal(store):
    calls = []
    brain = types.SimpleNamespace(ask=lambda p, **k: calls.append(p) or '{"facts": ["Prefers metric units"]}')
    store.learn("I prefer short answers", brain=brain, allow_llm=True)                 # rules handle it: no model call
    assert calls == []
    store.learn("I'm a bit tired", brain=brain, allow_llm=True)                          # weak signal: no model call
    assert calls == []
    store.learn("my favourite is jazz", brain=brain, allow_llm=True)                       # strong signal the rules cannot parse
    assert len(calls) == 1 and "Prefers metric units" in [p["text"] for p in store.all()]


# --------------------------------------------------------------------------- wired into Flexie
def make_orch(store, learn=True):
    from core.orchestrator import FlexieOrchestrator
    said = []
    orch = types.SimpleNamespace(preferences=store, speak=lambda t, **k: said.append(t), logger=types.SimpleNamespace(warning=lambda *a, **k: None))
    orch.learn_now = lambda c: FlexieOrchestrator._try_preference_statement(orch, c)
    return orch, said


def test_a_preference_statement_is_learned_confirmed_once_and_not_routed(store):
    orch, said = make_orch(store)
    assert orch.learn_now("I prefer short answers") is True
    assert said == ["Got it. I'll remember: prefers short answers."]
    assert orch.learn_now("I prefer short answers") is True and said[-1] == "I already have that noted."
    assert orch.learn_now("I hate long explanations") is True and said[-1].startswith("Updated.")
    assert orch.learn_now("open chrome") is False and orch.learn_now("what are my preferences") is False       # ordinary commands pass through
    assert orch.learn_now("I love you flexie") is False


def test_learning_can_be_switched_off(store):
    from utils.config import Config
    orch, said = make_orch(store)
    saved = Config.LEARN_PREFERENCES
    Config.LEARN_PREFERENCES = False
    try:
        assert orch.learn_now("I prefer short answers") is False and store.all() == []
    finally:
        Config.LEARN_PREFERENCES = saved


def test_the_conversation_prompt_includes_what_was_learned_and_is_wired_to_the_ui():
    import inspect

    from core import orchestrator
    from core.handlers import dispatcher
    src = inspect.getsource(dispatcher.handle_conversational)
    assert "prefs.prompt_block(c)" in src and "LEARN_PREFERENCES" in src
    osrc = inspect.getsource(orchestrator.FlexieOrchestrator)
    assert "_try_preference_statement(c, silent)" in osrc and '"GET_PREFS"' in osrc and "DELETE_PREF:" in osrc and '"CLEAR_PREFS"' in osrc


def test_the_toggle_is_a_live_setting_and_a_known_env_key():
    from core import settings_service as ss
    from utils.config import _is_allowed_env_key
    spec = next(b for b in ss.BEHAVIOR if b["env"] == "FLEXIE_LEARN_PREFERENCES")
    assert spec["live"] and spec["type"] == "bool" and _is_allowed_env_key("FLEXIE_LEARN_PREFERENCES")


def test_flexie_can_say_what_it_has_learned(store):
    from core.self_model import SelfModel, classify
    for phrase in ("what are my preferences", "what have you learned about me", "show my preferences"):
        assert classify(phrase) == "prefs", phrase
    sm = SelfModel.__new__(SelfModel)
    sm.orch = types.SimpleNamespace(preferences=store)
    assert "haven't learned" in sm._a_prefs()
    store.learn("I prefer short answers")
    store.learn("call me Sam")
    text = sm._a_prefs()
    assert "2 things" in text and "Prefers short answers" in text and "Name is Sam" in text and "Settings" in text


def test_the_dashboard_has_a_memory_section_with_delete():
    import pathlib
    page = (pathlib.Path(__file__).resolve().parents[1] / "interface" / "web_ui_v2.html").read_text(encoding="utf-8")
    for needle in ('data-s="memory"', 'id="s-memory"', "tag === 'PREFS'", "DELETE_PREF:", "CLEAR_PREFS", "GET_PREFS", "What Flexie remembers"):
        assert needle in page, needle
    assert ".innerHTML" not in page                                             # preference text is shown as text, never parsed


def test_no_new_dependency_and_no_telemetry():
    import pathlib
    reqs = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in pathlib.Path(__file__).resolve().parents[1].glob("requirements*.txt")).lower()
    assert "mem0" not in reqs and "posthog" not in reqs
    src = (pathlib.Path(__file__).resolve().parents[1] / "core" / "preferences.py").read_text(encoding="utf-8")
    assert "import mem0" not in src and "posthog" not in src.lower().replace("posthog)", "")


def test_a_learned_preference_really_reaches_the_models_system_prompt(store):
    from unittest.mock import MagicMock

    from core.handlers.dispatcher import handle_conversational
    store.learn("I prefer short answers")
    store.learn("call me Sam")
    store.learn("I like jazz music")
    seen = {}
    orch = MagicMock()
    orch.preferences = store
    orch.current_mode = "professional"
    orch.router.route.return_value = ("conversational", 0.0)
    orch.brain.ask_stream = lambda prompt, **k: seen.update(k) or iter(["Paris."])
    handle_conversational(orch, "what is the capital of france")
    system_text = str(seen.get("system_override", ""))
    assert system_text, "the conversational model call never happened"
    assert "Prefers short answers" in system_text and "Name is Sam" in system_text and "jazz" not in system_text
