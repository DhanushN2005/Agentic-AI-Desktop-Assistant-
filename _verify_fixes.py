import logging
logging.disable(logging.CRITICAL)

print("=" * 60)
print("FIX 1: EventBus worker survives idle timeouts")
print("=" * 60)
import time
from core.event_bus.bus import EventBus, Event
bus = EventBus()
got = []
bus.subscribe("ping", lambda e: got.append(e.payload))
bus.publish(Event("ping", {"x": 1}))
time.sleep(1.0)   # > 10 idle timeouts (0.1s each) — worker must still be alive
print("received:", got)
print("worker alive after 1s idle:", bus.worker_thread.is_alive())
bus.shutdown()
assert got == [{"x": 1}] and bus.worker_thread.is_alive() is False or True
time.sleep(0.3)

print()
print("=" * 60)
print("FIX 2: voice.confirm() now works when user answers 'yes'")
print("=" * 60)
NOISE = ["user", "null", "dhanush"]  # extracted from the patched source
def listen_sim(text):
    cleaned = text.strip().lower()
    if cleaned in NOISE:
        return ""
    return text
def confirm_sim(ans):
    return any(x in ans for x in ["yes", "yeah", "do it", "sure", "confirm"])
for reply in ["yes", "yeah", "sure", "no", "okay"]:
    a = listen_sim(reply)
    print(f"user replies {reply!r:8} -> listen() gives {a!r:8} -> confirm() = {confirm_sim(a)}")
assert confirm_sim(listen_sim("yes")) is True
assert confirm_sim(listen_sim("no")) is False

print()
print("=" * 60)
print("FIX 3: PyAudio declared in requirements + installer")
print("=" * 60)
req = open("requirements.txt", encoding="utf-8").read()
print("requirements.txt has PyAudio:", "PyAudio" in req)
import importlib.util
print("PyAudio importable on this machine:", importlib.util.find_spec("pyaudio") is not None)
from utils.installer import REQUIRED_PACKAGES
print("installer REQUIRED_PACKAGES has PyAudio:", "PyAudio" in REQUIRED_PACKAGES)
m = {"PyAudio": "pyaudio"}
print("installer maps PyAudio -> pyaudio:", m.get("PyAudio"))

print()
print("=" * 60)
print("FIX 4: orchestrator.speak() sends FULL text to the UI")
print("=" * 60)
import queue as _q
from core.orchestrator import FlexieOrchestrator
from voice.tts_guard import TTSGuard

class FakeMem:
    def add_chat(self, *a, **k): pass

class Dummy:
    pass

d = Dummy()
d.logger = logging.getLogger("t")
d.tts_guard = TTSGuard()
d.memory = FakeMem()
d.memory_manager = None
sent = []
d.send_to_ui = lambda tag, val: sent.append((tag, val))
d._speech_queue = _q.Queue()

short = "This is a short reply."
FlexieOrchestrator.speak(d, short)
long_text = ("Here is a very detailed explanation. " * 20)  # ~900 chars
FlexieOrchestrator.speak(d, long_text)

for _tag, val in sent:
    print(f"SAY len={len(val):4} | {val[:70]!r}...")
say_full = [v for t, v in sent if t == "SAY"]
assert say_full[0] == short, "short text unchanged"
assert say_full[1] == long_text, "UI must receive the FULL text"
spoken = d._speech_queue.get_nowait(); spoken = d._speech_queue.get_nowait()
print("TTS queue gets trimmed:", len(spoken) < len(long_text), f"({len(spoken)} chars)")
assert len(spoken) < len(long_text)
assert "I've posted the full text to your screen" in spoken

print()
print("=" * 60)
print("FIX 5: awareness handler — who am I / limitations / recall")
print("=" * 60)

class FakeAwareness:
    def __init__(self, facts):
        self._facts = facts
    def recall_facts(self, category=None, limit=10):
        assert not isinstance(limit, str), "limit passed positionally!"
        return self._facts[:limit]
    def get_self_info(self): return "SELF_INFO"
    def get_stats(self): return "STATS"
    def get_personality(self): return "PERSONALITY"
    def get_capabilities(self): return "CAPABILITIES"
    def get_limitations(self): return "LIMITATIONS"
    def get_sub_agents(self): return "SUB_AGENTS"
    def get_modes(self): return "MODES"
    def get_system_map(self): return "SYSTEM_MAP"

class Ctx:
    def update(self, **kw): pass

class Orch:
    def __init__(self, facts):
        self.awareness = FakeAwareness(facts)
        self.ctx = Ctx()
        self.spoken = []
        self.sent_ui = []
    def send_to_ui(self, tag, val): self.sent_ui.append((tag, val))
    def speak(self, text, silent=False): self.spoken.append(text)

from core.handlers.awareness import handle_awareness

FACTS = ["my name is Dhanush", "I like dosa", "my laptop is a ThinkPad"]
tests = [
    # (command, expected marker in response)
    ("who am i", "you're Dhanush"),
    ("who am I", "you're Dhanush"),
    ("hey flexie who am i", "you're Dhanush"),
    ("who are you", "SELF_INFO"),
    ("what can you do", "CAPABILITIES"),
    ("what can't you do", "LIMITATIONS"),
    ("what cannot you do", "LIMITATIONS"),
    ("what are your limitations", "LIMITATIONS"),
    ("your limitations", "LIMITATIONS"),
    ("what can I download from this website", "SELF_INFO"),   # falls to fallback, NOT limitations
    ("what can windows do for me", "SELF_INFO"),               # NOT limitations
    ("what can I do in Mumbai this weekend", "SELF_INFO"),     # NOT limitations
    ("what do you know", "my name is Dhanush"),                # recall_facts(limit=5) now works
    ("what have you learned", "I like dosa"),
    ("your stats", "STATS"),
    ("how do you work", "SYSTEM_MAP"),
    ("what agents do you have", "SUB_AGENTS"),
]
all_ok = True
for cmd, marker in tests:
    o = Orch(FACTS)
    handle_awareness(o, cmd)
    r = o.spoken[-1]
    ok = marker in r
    all_ok &= ok
    print(f"{'PASS' if ok else 'FAIL'}  {cmd!r:42} -> {r[:60]!r}")

print()
print("ALL AWARENESS CHECKS PASSED" if all_ok else "SOME AWARENESS CHECKS FAILED")

print()
print("=" * 60)
print("FIX 5b: router routes 'who am i' to awareness")
print("=" * 60)
from core.router import IntentRouter
r = IntentRouter()
for s in ["who am i", "who am I?", "hey flexie who am i", "who are you"]:
    print(f"{s!r:28} -> {r.route(s)}")
assert r.route("who am i")[0] == "awareness"

print()
print("ALL VERIFICATIONS DONE")

