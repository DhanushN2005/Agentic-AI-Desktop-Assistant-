import pytest

from core.router import IntentRouter


@pytest.fixture(scope="module")
def router():
    return IntentRouter()


@pytest.mark.parametrize(
    "command,expected",
    [
        ("open chrome", "app_op"),
        ("open vscode", "app_op"),
        ("close chrome", "app_op"),
        ("set volume to 50", "media"),
        ("increase brightness", "media"),
        ("play some music", "play_youtube"),
        ("play a song", "play_youtube"),
        ("shutdown pc", "power"),
        ("lock screen", "power"),
        ("what is photosynthesis", "search"),
        ("search for quantum computing", "research"),
        ("google search cats", "research"),
        ("hello", "social"),
        ("calculate 5 plus 5", "calc"),
        ("what is 12 times 12", "calc"),
        ("check battery", "status"),
        ("remember that my name is Dhanush", "memory_system"),
        ("translate good morning to Spanish", "translate"),
        ("convert 100 dollars to rupees", "convert"),
        ("convert 5 kilometers to miles", "convert"),
        ("delete file report.txt", "file_delete"),
        ("rename file a.txt to b.txt", "file_rename"),
        ("create a folder called work", "file_op"),
        ("build a website", "dev_build"),
        ("create an app", "dev_build"),
        ("analyze my screen", "vision_analyze"),
        ("take a screenshot", "vision_capture"),
        ("new tab", "browser_tabs"),
        ("skip the ad", "youtube"),
        ("check gmail", "gmail"),
        ("search my files for notes", "knowledge_search"),
        ("remind me to buy milk", "remind_me"),
        ("remind me in 10 minutes to drink water", "remind_me"),
        ("set a reminder for 5pm to call mom", "remind_me"),
        ("list reminders", "list_reminders"),
        ("show reminders", "list_reminders"),
        ("start dictation", "dictation_mode"),
        ("good morning flexie", "daily_briefing"),
        ("unknown gibberish xyz", "conversational"),
    ],
)
def test_route_known_intents(router, command, expected):
    intent, confidence = router.route(command)
    assert intent == expected, f"{command!r} routed to {intent!r}, expected {expected!r}"
    assert 0.0 <= confidence <= 1.0


def test_route_empty(router):
    intent, confidence = router.route("")
    assert intent == "conversational"
    assert confidence == 0.0


def test_route_priority_beats_confidence(router):
    # "shutdown pc" must hit power (priority 4), not app_op (priority 8).
    intent, _ = router.route("shutdown pc")
    assert intent == "power"


def test_route_smoke_performance():
    router = IntentRouter()
    commands = [
        "open chrome",
        "set volume to 50",
        "play some music",
        "what is photosynthesis",
        "shutdown pc",
        "delete file report.txt",
        "build a website",
    ]
    # 2000 routes to smoke-check the hot path has no exceptions or hangs.
    for _ in range(2000):
        for c in commands:
            router.route(c)
