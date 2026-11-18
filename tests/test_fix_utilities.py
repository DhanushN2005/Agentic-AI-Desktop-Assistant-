"""Regression tests for the everyday-utility engines and handlers.

Everything here is offline and deterministic: HTTP is faked, clocks are frozen,
files go to tmp_path.
"""
import hashlib
import io
import json
import os
import threading
import urllib.error
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from utils import voice_parse as vp

# --------------------------------------------------------------------- helpers


class _Ctx:
    def __init__(self):
        self.pending_action = None
        self.last_response = None
        self.query = None

    def update(self, **kw):
        self.__dict__.update(kw)

    def set_pending_action(self, action, data=None):
        self.pending_action = action

    def clear_pending_action(self):
        self.pending_action = None


class _Orch:
    def __init__(self, **engines):
        self.said = []
        self.ui = []
        self.ctx = _Ctx()
        self.__dict__.update(engines)

    def speak(self, text, *a, **k):
        self.said.append(text)

    def send_to_ui(self, *a, **k):
        self.ui.append(a)

    @property
    def last(self):
        return self.said[-1] if self.said else None


class _Resp:
    def __init__(self, body=b"", status=200, headers=None):
        self._body = body if isinstance(body, bytes) else body.encode()
        self.status = status
        self.status_code = status
        self.headers = headers or {}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_urlopen(routes):
    """routes: list of (substring, body|Exception|(status, body)); first match wins."""
    calls = []

    def _open(req, timeout=None, **kw):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        calls.append(url)
        for key, val in routes:
            if key in url:
                if isinstance(val, Exception):
                    raise val
                if isinstance(val, tuple):
                    status, body = val
                    if status != 200:
                        raise urllib.error.HTTPError(url, status, "err", {}, io.BytesIO(b""))
                    return _Resp(body, status)
                return _Resp(val)
        raise urllib.error.URLError("no route " + url)

    _open.calls = calls
    return _open


class _RequestsResp:
    def __init__(self, payload=None, status=200, content=b"", headers=None, text=""):
        self._payload = payload
        self.status_code = status
        self.content = content
        self.headers = headers or {}
        self.text = text

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    def iter_content(self, n):
        yield self.content


class _FakeSession:
    def __init__(self, responder):
        self.responder = responder
        self.calls = []

    def get(self, url, params=None, timeout=None, **kw):
        self.calls.append((url, params))
        r = self.responder(url, params)
        if isinstance(r, Exception):
            raise r
        return r


# ============================================================ voice_parse ====


def test_voice_parse_numbers():
    assert vp.parse_number("5") == 5
    assert vp.parse_number("1.5") == 1.5
    assert vp.parse_number("five") == 5
    assert vp.parse_number("twenty five") == 25
    assert vp.parse_number("twenty-five") == 25
    assert vp.parse_number("a couple") == 2
    assert vp.parse_number("a dozen") == 12
    assert vp.parse_number("1,000") == 1000
    assert vp.parse_number("") is None
    assert vp.parse_number(None) is None
    assert vp.parse_number("banana") is None


def test_voice_parse_durations():
    assert vp.parse_duration("1.5 hours") == 5400
    assert vp.parse_duration("2 hours 30 minutes") == 9000
    assert vp.parse_duration("1 minute 30 seconds") == 90
    assert vp.parse_duration("an hour") == 3600
    assert vp.parse_duration("a minute") == 60
    assert vp.parse_duration("45 seconds") == 45
    assert vp.parse_duration("half an hour") == 1800
    assert vp.parse_duration("an hour and a half") == 5400
    assert vp.parse_duration("ten minutes") == 600
    assert vp.parse_duration("no duration here") is None
    assert vp.parse_duration("") is None
    assert vp.parse_duration("0 minutes") == 0
    assert vp.parse_duration("99999 hours") == 99999 * 3600  # huge input stays finite


def test_voice_parse_format_duration():
    assert vp.format_duration(60) == "1 minute"
    assert vp.format_duration(30) == "30 seconds"
    assert vp.format_duration(5400) == "1 hour 30 minutes"
    assert vp.format_duration(0) == "0 seconds"
    assert vp.format_duration(-5) == "0 seconds"


NOW = datetime(2025, 3, 10, 14, 0, 0)


@pytest.mark.parametrize("text,expected", [
    ("remind me at 5 pm", datetime(2025, 3, 10, 17, 0)),
    ("at 5pm", datetime(2025, 3, 10, 17, 0)),
    ("at 5:30 pm", datetime(2025, 3, 10, 17, 30)),
    ("at 17:30", datetime(2025, 3, 10, 17, 30)),
    ("7 am", datetime(2025, 3, 11, 7, 0)),            # already past -> tomorrow
    ("at 7", datetime(2025, 3, 11, 7, 0)),
    ("tomorrow at 9", datetime(2025, 3, 11, 9, 0)),
    ("noon", datetime(2025, 3, 11, 12, 0)),            # 12:00 already past at 14:00
    ("midnight", datetime(2025, 3, 11, 0, 0)),
    ("12am", datetime(2025, 3, 11, 0, 0)),
    ("12pm", datetime(2025, 3, 11, 12, 0)),
    ("in 10 minutes", datetime(2025, 3, 10, 14, 10)),
    ("in an hour", datetime(2025, 3, 10, 15, 0)),
    ("in 1.5 hours", datetime(2025, 3, 10, 15, 30)),
    ("in 2 hours 30 minutes", datetime(2025, 3, 10, 16, 30)),
    ("in 45 seconds", datetime(2025, 3, 10, 14, 0, 45)),
    ("in a minute", datetime(2025, 3, 10, 14, 1)),
])
def test_parse_time_cases(text, expected):
    assert vp.parse_time(text, NOW) == expected


def test_parse_time_none_and_errors():
    assert vp.parse_time("hello there", NOW) is None
    assert vp.parse_time("", NOW) is None
    with pytest.raises(vp.TimeParseError):
        vp.parse_time("at 25:00", NOW)
    with pytest.raises(vp.TimeParseError):
        vp.parse_time("at 13 pm", NOW)
    with pytest.raises(vp.TimeParseError):
        vp.parse_time("at 7:75", NOW)


def test_parse_time_midnight_and_month_end_rollover():
    late = datetime(2025, 1, 31, 23, 30)
    assert vp.parse_time("at 1 am", late) == datetime(2025, 2, 1, 1, 0)
    assert vp.parse_time("in 45 minutes", late) == datetime(2025, 2, 1, 0, 15)
    dec = datetime(2025, 12, 31, 23, 59)
    assert vp.parse_time("midnight", dec) == datetime(2026, 1, 1, 0, 0)
    assert vp.parse_time("tomorrow at 9", dec) == datetime(2026, 1, 1, 9, 0)


def test_parse_time_leap_day():
    now = datetime(2024, 2, 28, 20, 0)
    assert vp.parse_time("tomorrow at 9", now) == datetime(2024, 2, 29, 9, 0)
    now2 = datetime(2024, 2, 29, 20, 0)
    assert vp.parse_time("at 8 am", now2) == datetime(2024, 3, 1, 8, 0)
    now3 = datetime(2023, 2, 28, 20, 0)
    assert vp.parse_time("at 8 am", now3) == datetime(2023, 3, 1, 8, 0)


def test_parse_time_dst_wall_clock():
    zi = pytest.importorskip("zoneinfo")
    try:
        tz = zi.ZoneInfo("America/New_York")
    except Exception:
        pytest.skip("tzdata unavailable")
    # the evening before spring-forward (2025-03-09): 'at 9 am' stays 09:00 local
    now = datetime(2025, 3, 8, 22, 0, tzinfo=tz)
    target = vp.parse_time("at 9 am", now)
    assert (target.year, target.month, target.day, target.hour) == (2025, 3, 9, 9)
    # relative durations are absolute elapsed time across the change
    now2 = datetime(2025, 3, 9, 1, 30, tzinfo=tz)
    t2 = vp.parse_time("in 1 hour", now2)
    assert (t2 - now2).total_seconds() == 3600
    assert vp.seconds_until(target, now) > 0


def test_voice_parse_remove_and_extract_time_phrase():
    assert vp.remove_time_phrases("call mom at 5 pm tomorrow") == "call mom"
    assert vp.remove_time_phrases("take pills in 10 minutes") == "take pills"
    assert "5" in vp.extract_time_phrase("call mom at 5 pm")
    assert vp.strip_wake("Hey Flexie, Hash ABC") == "Hash ABC"
    assert vp.is_relative("in 10 minutes") and not vp.is_relative("at 5 pm")


# ============================================================== reminders ====


def _patch_now(monkeypatch, module, now):
    monkeypatch.setattr(module, "_now", lambda: now)


class _Mem:
    def __init__(self):
        self.added = []

    def add_reminder(self, task, minutes):
        self.added.append((task, minutes))

    def list_reminders(self):
        return [t for t, _ in self.added]


def _remind(monkeypatch, cmd, now=NOW):
    from core.handlers import reminders
    _patch_now(monkeypatch, reminders, now)
    started = []
    monkeypatch.setattr(threading.Thread, "start", lambda self: started.append(self))
    o = _Orch(memory=_Mem())
    reminders.handle_remind(o, cmd)
    return o, started


def test_reminder_absolute_time_uses_target_delay(monkeypatch):
    o, _ = _remind(monkeypatch, "remind me to call mom at 5 pm")
    task, minutes = o.memory.added[0]
    assert task == "call mom"
    assert minutes == pytest.approx(180)           # 14:00 -> 17:00, not 5 minutes
    assert "5:00" in o.last or "5 PM" in o.last.upper() or "17:00" in o.last


def test_reminder_absolute_variants(monkeypatch):
    for cmd, mins in [
        ("remind me to stretch at 17:30", 210),
        ("remind me to run tomorrow at 9", 19 * 60),
        ("remind me to eat at noon", 22 * 60),
        ("remind me to sleep at midnight", 10 * 60),
    ]:
        o, _ = _remind(monkeypatch, cmd)
        assert o.memory.added[0][1] == pytest.approx(mins), cmd


def test_reminder_confirmation_text_units(monkeypatch):
    o, _ = _remind(monkeypatch, "remind me in a minute to check the oven")
    assert "1 minute" in o.last and "5 minutes" not in o.last
    assert o.memory.added[0][1] == pytest.approx(1)
    o, _ = _remind(monkeypatch, "remind me in 30 seconds to stir")
    assert "30 seconds" in o.last and "0 minutes" not in o.last
    assert o.memory.added[0][1] == pytest.approx(0.5)


def test_reminder_no_sleeping_thread_and_case_preserved(monkeypatch):
    o, started = _remind(monkeypatch, "Remind me in 10 minutes to Call NASA")
    assert started == []                            # DB poller is the single mechanism
    assert o.memory.added[0][0] == "Call NASA"


def test_reminder_invalid_time_and_missing_task(monkeypatch):
    o, _ = _remind(monkeypatch, "remind me at 25:00 to nap")
    assert "valid time" in o.last and o.memory.added == []
    o, _ = _remind(monkeypatch, "remind me in 5 minutes")
    assert "remind you about" in o.last and o.memory.added == []


def test_reminder_midnight_rollover_month_end(monkeypatch):
    now = datetime(2025, 1, 31, 23, 0)
    o, _ = _remind(monkeypatch, "remind me to wake at 1 am", now)
    assert o.memory.added[0][1] == pytest.approx(120)


def test_reminder_list(monkeypatch):
    from core.handlers import reminders
    o = _Orch(memory=_Mem())
    reminders.handle_remind(o, "list reminders")
    assert "no pending" in o.last.lower()


# ================================================================== alarms ===


class _DummyTimer:
    instances = []

    def __init__(self, interval, fn, *a, **k):
        self.interval, self.fn, self.cancelled, self.daemon = interval, fn, False, False
        _DummyTimer.instances.append(self)

    def start(self):
        pass

    def cancel(self):
        self.cancelled = True


@pytest.fixture
def dummy_timers(monkeypatch):
    _DummyTimer.instances = []
    monkeypatch.setattr(threading, "Timer", _DummyTimer)
    return _DummyTimer.instances


def _alarm_engine(now=NOW):
    from engines.alarm import AlarmEngine
    said = []
    eng = AlarmEngine(speak_callback=said.append)
    eng._now = lambda: now
    return eng, said


def test_alarm_time_grammar(dummy_timers):
    eng, _ = _alarm_engine()
    for txt, delay in [("7 am", 17 * 3600), ("5pm", 3 * 3600), ("noon", 22 * 3600),
                       ("7:15", 17 * 3600 + 15 * 60), ("14:30", 30 * 60), ("19:45", 5 * 3600 + 45 * 60)]:
        dummy_timers.clear()
        msg = eng.set_alarm(txt)
        assert msg.startswith("Alarm set"), (txt, msg)
        assert dummy_timers[0].interval == pytest.approx(delay), txt
    assert "Could not understand" in eng.set_alarm("banana")
    assert "valid time" in eng.set_alarm("25:00")


def test_alarm_ids_monotonic_pop_and_bounded(dummy_timers):
    eng, said = _alarm_engine()
    eng.set_alarm("5pm")
    eng.set_alarm("6pm")
    assert eng.cancel_alarm("alarm_1").startswith("Alarm alarm_1 cancelled")
    eng.set_alarm("7pm")
    assert "alarm_3" in eng._alarms and "alarm_1" not in eng._alarms   # ids never reused
    # fire one: it is popped and recorded once
    dummy_timers[1].fn()
    assert len(eng._alarms) == 1 and said and "Alarm!" in said[0]
    assert len(eng.get_triggered()) == 1
    assert eng.get_triggered() == []                                    # popped
    for _ in range(300):
        eng._record({"triggered": True})
    assert len(eng._active_countdowns) <= 100


def test_alarm_timer_durations_and_ids(dummy_timers):
    eng, _ = _alarm_engine()
    assert "Timer duration must be positive" in eng.set_timer(0)
    assert "Timer duration must be positive" in eng.set_timer(-3)
    assert "1 hour 30 minutes" in eng.set_timer(5400)
    assert dummy_timers[-1].interval == 5400
    eng.set_timer(90)
    eng.cancel_timer("timer_1")
    eng.set_timer(10)
    assert set(eng._timers) == {"timer_2", "timer_3"}


def _alarm_handler(monkeypatch, dummy_timers, cmd, now=NOW):
    from core.handlers import alarm as h
    from engines import alarm as ea
    from engines.alarm import AlarmEngine
    eng = AlarmEngine(speak_callback=lambda t: None)
    eng._now = lambda: now
    monkeypatch.setattr(ea, "datetime", ea.datetime)
    o = _Orch(alarm=eng)
    h.handle_alarm(o, cmd)
    return o, eng


def test_alarm_handler_grammar(monkeypatch, dummy_timers):
    o, eng = _alarm_handler(monkeypatch, dummy_timers, "set a timer for 1.5 hours")
    assert dummy_timers[-1].interval == 5400
    o, eng = _alarm_handler(monkeypatch, dummy_timers, "set a timer for 2 hours 30 minutes")
    assert dummy_timers[-1].interval == 9000
    o, eng = _alarm_handler(monkeypatch, dummy_timers, "timer for 1 minute 30 seconds")
    assert dummy_timers[-1].interval == 90
    o, eng = _alarm_handler(monkeypatch, dummy_timers, "wake me up at 7")
    assert o.last.startswith("Alarm set")
    o, eng = _alarm_handler(monkeypatch, dummy_timers, "set alarm for 5pm")
    assert o.last.startswith("Alarm set") and "5:00" in o.last or "17:00" in o.last
    o, eng = _alarm_handler(monkeypatch, dummy_timers, "set an alarm for 7 am called gym")
    assert "gym" in o.last
    o, eng = _alarm_handler(monkeypatch, dummy_timers, "set alarm for 25:00")
    assert "valid" in o.last
    o, eng = _alarm_handler(monkeypatch, dummy_timers, "set a timer")
    assert o.ctx.pending_action == "waiting_for_timer_duration"


def test_alarm_handler_pending_timer_duration(monkeypatch, dummy_timers):
    from core.handlers import alarm as h
    from engines.alarm import AlarmEngine
    eng = AlarmEngine(speak_callback=lambda t: None)
    o = _Orch(alarm=eng)
    o.ctx.pending_action = "waiting_for_timer_duration"
    h.handle_alarm(o, "30 seconds")
    assert dummy_timers[-1].interval == 30 and o.ctx.pending_action is None


# ============================================================ notification ===


def _notify(monkeypatch, cmd, now=NOW):
    from core.handlers import notification as n
    _patch_now(monkeypatch, n, now)
    timers = []

    class T:
        def __init__(self, interval, fn):
            timers.append(interval)
            self.daemon = False

        def start(self):
            pass

    monkeypatch.setattr(n.threading, "Timer", T)
    o = _Orch()
    n.handle_notification(o, cmd)
    return o, timers


def test_notification_message_keeps_to_and_about(monkeypatch):
    from core.handlers.notification import _extract_notify_message
    assert _extract_notify_message("notify me in 10 minutes to go to the gym") == "go to the gym"
    assert _extract_notify_message("notify me at 5 pm about talk about taxes") == "talk about taxes"
    assert _extract_notify_message("Notify me in 5 minutes to Call NASA") == "Call NASA"
    assert _extract_notify_message("notify me in 5 minutes") is None


def test_notification_month_end_and_validation(monkeypatch):
    now = datetime(2025, 1, 31, 20, 0)
    o, timers = _notify(monkeypatch, "notify me at 9 am to stretch", now)   # would crash on day=32
    assert timers == [13 * 3600]
    o, timers = _notify(monkeypatch, "notify me at 25:00 to stretch")
    assert "valid time" in o.last and timers == []


def test_notification_flag_not_left_dangling(monkeypatch):
    o, timers = _notify(monkeypatch, "notify me in 10 minutes")
    assert timers == []
    assert not getattr(o.ctx, "waiting_for_notify_message", False)
    assert o.ctx.pending_action is None


# ===================================================================== todo ==


@pytest.fixture
def todo(tmp_path, monkeypatch):
    from core.handlers import todo as t
    monkeypatch.setattr(t.Config, "DATA_DIR", str(tmp_path), raising=False)
    o = _Orch()

    def run(cmd):
        t.handle_todo(o, cmd)
        return o.last
    run.items = lambda: t._load()
    run.orch = o
    return run


def test_todo_add_remove_clear_list(todo):
    assert todo("add Milk to my list").startswith("Added Milk")
    todo("add eggs to my todo")
    todo("add bread and butter")
    assert todo.items() == ["Milk", "eggs", "bread", "butter"]       # case preserved
    assert "Removed eggs" in todo("remove eggs from my list")
    assert "eggs" not in todo.items()
    assert "Your list has 3 items" in todo("show my todo list")
    assert "Your list has 3 items" in todo("what's on my list")
    assert "Marked done Milk" in todo("mark milk as done")
    assert "Cleared" in todo("clear my list")
    assert todo.items() == []
    assert "empty" in todo("show my list")
    todo("add a")
    assert "Cleared" in todo("clear the list")


def test_todo_remove_missing_and_help(todo):
    assert "couldn't find" in todo("remove unicorns from my list")
    assert "Say" in todo("hello")


def test_todo_unicode_and_empty(todo):
    todo("add Café au lait to my list")
    assert todo.items() == ["Café au lait"]
    assert "What should I add" in todo("add . to my list") or todo.items() == ["Café au lait"]


# ====================================================================== tip ==


class _TipCalc:
    def calculate(self, bill, pct, split):
        return ("calc", bill, pct, split)

    def tip_from_total(self, total, bill):
        return ("from_total", total, bill)


def _tip(cmd):
    from core.handlers.tip import handle_tip
    o = _Orch(tip_calc=_TipCalc())
    handle_tip(o, cmd)
    return o.last


@pytest.mark.parametrize("cmd,expected", [
    ("tip 20% on $50", ("calc", 50.0, 20.0, 1)),
    ("20% tip on $50", ("calc", 50.0, 20.0, 1)),
    ("split $60 by 3", ("calc", 60.0, 15.0, 3)),
    ("tip 15% on 80 split 4", ("calc", 80.0, 15.0, 4)),
    ("tip on $42.50", ("calc", 42.5, 15.0, 1)),
    ("tip 18 percent on 100", ("calc", 100.0, 18.0, 1)),
    ("calculate tip for bill 75 split 3 ways", ("calc", 75.0, 15.0, 3)),
])
def test_tip_parsing(cmd, expected):
    assert _tip(cmd) == expected


def test_tip_validation_messages():
    assert "bill amount" in _tip("what is the tip")
    assert "more than zero" in _tip("tip 15% on $0")
    assert "between 0 and 100" in _tip("tip 150% on $50")
    assert "whole number" in _tip("split $60 by 2.5")
    assert "whole number" in _tip("split $60 by 0")


def test_tip_engine_outputs():
    from engines.tip_calc import TipCalculatorEngine
    e = TipCalculatorEngine()
    assert "Tip (20%): $10.00" in e.calculate(50, 20, 1)
    assert "Split 3 ways: $23.00 each" in e.calculate(60, 15, 3)
    assert "at least 1" in e.split_bill(10, 0)
    assert "greater than 0" in e.tip_from_total(10, 0)


# ================================================================ converter ==


def _convert(cmd, monkeypatch=None):
    from core.handlers.converter import handle_convert
    o = _Orch()
    handle_convert(o, cmd)
    return o.last


def test_converter_basic_and_negative():
    assert "-40 c is -40.00 f" in _convert("convert -40 c to f")
    assert "100 celsius is 212.00 fahrenheit" in _convert("convert 100 celsius to fahrenheit")
    assert "32 f is 0 c" in _convert("convert 32 f to c")
    assert "degrees celsius is 212" in _convert("convert 100 degrees celsius to fahrenheit")
    assert "absolute zero" in _convert("convert -500 c to f")


def test_converter_plurals_and_weight_vs_currency():
    assert "pounds is" in _convert("convert 10 pounds to kilograms") and "4.54" in _convert("convert 10 pounds to kg")
    assert "approximate" in _convert("convert 10 pounds to dollars") or "not live" in _convert("convert 10 pounds to dollars")
    assert "liters" in _convert("convert 2 gallons to liters") and "7.57" in _convert("convert 2 gallons to liters")
    assert "tons" in _convert("convert 2 tons to kg")


def test_converter_decimal_comma_and_thousands():
    assert "1.5 km is" in _convert("convert 1,5 km to m") and "1,500.00 m" in _convert("convert 1,5 km to m")
    assert "1,500 km" in _convert("convert 1,500 km to m") or "1500 km" in _convert("convert 1,500 km to m")
    assert "1,500,000.00 m" in _convert("convert 1,500 km to m")


def test_converter_data_units_labelled_and_adaptive_rounding():
    r = _convert("convert 1 gb to mb")
    assert "1,024.00 mb" in r and "1 KB = 1024" in r
    r = _convert("convert 1 mg to kg")
    assert "0.00 kg" not in r and "e-06" in r or "1e-06" in r
    assert "0" != r


def test_converter_currency_flagged_and_overridable(tmp_path, monkeypatch):
    r = _convert("convert 100 usd to inr")
    assert "approximate" in r and "not live" in r and "2025" in r
    f = tmp_path / "rates.json"
    f.write_text(json.dumps({"inr": 0.01}))
    monkeypatch.setenv("FLEXIE_CURRENCY_RATES", str(f))
    r = _convert("convert 100 usd to inr")
    assert "10,000.00 inr" in r and "configured" in r


def test_converter_usage_only_when_unparseable():
    assert "Say something like" in _convert("convert something weird")
    assert "Say something like" not in _convert("convert 5 miles to km")
    assert "don't know that pair" in _convert("convert 5 miles to kg")
    assert "too large" in _convert("convert 1" + "0" * 30 + " km to m")


# =================================================================== hash ====


def _hash(cmd):
    from core.handlers.hash_encoder import handle_hash
    from engines.hash_encoder import HashEncoderEngine
    o = _Orch(hash_encoder=HashEncoderEngine())
    handle_hash(o, cmd)
    return o.last


def test_hash_payload_case_and_filler():
    assert "185f8db32271fe25f561a6fc938b2e264306ec304eda518007d1764826381969" in _hash('sha256 "Hello"')
    assert hashlib.md5(b"hello").hexdigest() in _hash("md5 hash of hello")
    assert "Decoded: Hello" in _hash("base64 decode SGVsbG8=")
    assert "SGVsbG8=" in _hash("base64 encode Hello")
    assert hashlib.sha1(b"MiXeD").hexdigest() in _hash("sha1 MiXeD")
    assert "What text" in _hash("sha256")
    assert hashlib.sha256("héllo wörld".encode()).hexdigest() in _hash('sha256 "héllo wörld"')


def test_hash_payload_containing_keywords_does_not_change_op():
    assert hashlib.sha256(b"md5 decode").hexdigest() in _hash('sha256 "md5 decode"')


def test_binary_decode_edge_cases():
    from engines.hash_encoder import HashEncoderEngine
    e = HashEncoderEngine()
    assert e.binary_decode("01001000 01101001") == "Decoded: Hi"
    assert e.binary_decode("0100100001101001") == "Decoded: Hi"
    assert "Invalid" in e.binary_decode("0100 abc")
    assert "Invalid" in e.binary_decode("")
    assert "multiple of 8" in e.binary_decode("010010000110100")
    assert e.binary_decode(e.binary_encode("Hi").split(": ", 1)[1]) == "Decoded: Hi"
    assert "Invalid" in e.base64_decode("!!!")
    assert "Invalid hex" in e.hex_decode("zz")


# ==================================================================== json ===


def _json(cmd):
    from core.handlers.json_fmt import handle_json
    from engines.json_formatter import JSONFormatterEngine
    o = _Orch(json_formatter=JSONFormatterEngine())
    handle_json(o, cmd)
    return o.last


def test_json_handler_uses_original_text():
    out = _json('format json {"Name": "Alice", "ID": 7}')
    assert '"Name": "Alice"' in out and '"ID": 7' in out
    out = _json('validate {"A":"FORMAT"}')
    assert out.startswith("Valid JSON")
    out = _json('minify {"A": "x y", "B": [1, 2]}')
    assert out == '{"A":"x y","B":[1,2]}'
    assert "Invalid JSON" in _json("format {not json}")


def test_json_engine_flatten_info_and_recursion():
    from engines.json_formatter import JSONFormatterEngine
    e = JSONFormatterEngine()
    flat = json.loads(e.flatten_json('{"a": {}, "b": [], "c": {"d": 1}, "e": [1, {"f": 2}]}'))
    assert flat == {"a": {}, "b": [], "c.d": 1, "e[0]": 1, "e[1].f": 2}
    deep = "[" * 5000 + "]" * 5000
    for fn in (e.flatten_json, e.format_json, e.validate_json, e.json_info):
        assert "deeply nested" in fn(deep) or "Invalid" in fn(deep)
    assert e.validate_json('{"a": [null, true, 1, "s"]}').endswith("object, array, string, number, boolean, null")
    assert "Size: 9 bytes" in e.json_info('{"é": 1}')  # bytes, not characters
    assert "Invalid JSON at position" in e.validate_json("{")


# ================================================================= password ==


def _pw(monkeypatch, cmd):
    from core.handlers import password as h
    from engines.password_gen import PasswordEngine
    copied = []
    import sys
    import types
    fake = types.SimpleNamespace(copy=copied.append)
    monkeypatch.setitem(sys.modules, "pyperclip", fake)
    o = _Orch(password_gen=PasswordEngine())
    h.handle_password(o, cmd)
    return o, copied


def test_password_check_uses_original_text(monkeypatch):
    o, _ = _pw(monkeypatch, "check password MyP@ssw0rd!Long")
    assert "Strong" in o.last or "Very Strong" in o.last or "Excellent" in o.last
    o, _ = _pw(monkeypatch, 'check password "Pass Word 123!"')
    assert "score" in o.last
    assert o.ctx.query == "password request"          # typed secret never stored
    o, _ = _pw(monkeypatch, "check password PASSWORD")
    assert "Weak" in o.last or "Very Weak" in o.last


def test_password_generated_never_spoken_or_stored(monkeypatch):
    o, copied = _pw(monkeypatch, "generate a password 20 characters")
    assert copied and len(copied[0]) == 20
    secret = copied[0]
    assert secret not in o.last
    assert all(secret not in str(s) for s in o.said)
    assert secret not in str(o.ctx.last_response) and secret not in str(o.ctx.query)


def test_password_length_validation(monkeypatch):
    for n in (2, 4, 7, 129, 1000):
        o, copied = _pw(monkeypatch, f"generate a password {n} characters")
        assert "between 8 and 128" in o.last and copied == []
    o, copied = _pw(monkeypatch, "generate a password 128 characters")
    assert len(copied[0]) == 128
    o, copied = _pw(monkeypatch, "generate a password 8 chars")
    assert len(copied[0]) == 8


def test_password_engine_validation_and_strength():
    from engines.password_gen import PasswordEngine
    e = PasswordEngine()
    with pytest.raises(ValueError):
        e.generate(2)
    with pytest.raises(ValueError):
        e.generate(129)
    with pytest.raises(ValueError):
        e.generate(True)
    pw = e.generate(8)
    assert len(pw) == 8
    assert e.strength_check("aB3$aB3$aB3$")["score"] == 6
    assert e.strength_check("password")["score"] <= 1
    assert e.strength_check("")["score"] == 0 or e.strength_check("")["level"] == "Very Weak"
    assert e.strength_check("aaaaaaaaaaaaaaaa")["score"] <= 2
    assert e.strength_check("Abc 123 xyz Q")["score"] == 6                 # space counts as a symbol
    with pytest.raises(ValueError):
        e.generate_passphrase(1)


# ==================================================================== QR =====


def test_qr_payload_case_and_engine_failure(tmp_path, monkeypatch):
    from core.handlers.qrcode import handle_qr
    from engines.qrcode_gen import QRCodeEngine
    seen = []

    class Eng:
        def generate(self, data):
            seen.append(data)
            return "Could not generate QR code: boom"
    o = _Orch(qrcode_gen=Eng())
    handle_qr(o, "generate QR for https://Example.com/Path?Q=AbC")
    assert seen == ["https://Example.com/Path?Q=AbC"]
    assert "Could not generate" in o.last              # failure reported honestly
    o = _Orch(qrcode_gen=QRCodeEngine(str(tmp_path)))
    handle_qr(o, "qr code")
    assert "What should the QR code contain" in o.last


def test_qr_engine_filenames_and_local_lib(tmp_path, monkeypatch):
    from engines import qrcode_gen
    e = qrcode_gen.QRCodeEngine(str(tmp_path / "qr"))
    monkeypatch.setattr(qrcode_gen.QRCodeEngine, "_local", staticmethod(lambda d, p: open(p, "wb").write(b"x") and True))
    a = e.generate("hello")
    b = e.generate("hellp")
    assert a.startswith("QR code saved to") and b.startswith("QR code saved to")
    fa = a.split("saved to ")[1]
    assert fa == e._filepath("hello") and e._filepath("hello") != e._filepath("hellp")
    assert os.path.dirname(fa) == str(tmp_path / "qr") and os.path.isfile(fa)
    assert os.path.basename(fa) == "qr_" + hashlib.sha256(b"hello").hexdigest()[:16] + ".png"
    assert "nothing to encode" in e.generate("   ")
    assert "too long" in e.generate("x" * 5000)


def test_qr_remote_fallback_notice_and_bad_response(tmp_path, monkeypatch):
    from engines import qrcode_gen
    e = qrcode_gen.QRCodeEngine(str(tmp_path))
    monkeypatch.setattr(qrcode_gen.QRCodeEngine, "_local", staticmethod(lambda d, p: False))
    monkeypatch.setattr(qrcode_gen.urllib.request, "urlopen", _fake_urlopen([("qrserver", b"\x89PNG\r\n\x1a\nDATA")]))
    r = e.generate("hi there")
    assert "api.qrserver.com" in r and "sent to" in r
    monkeypatch.setattr(qrcode_gen.urllib.request, "urlopen", _fake_urlopen([("qrserver", b"<html>")]))
    assert "Could not generate QR code" in e.generate("other")
    monkeypatch.setattr(qrcode_gen.urllib.request, "urlopen", _fake_urlopen([("qrserver", (500, b""))]))
    assert "Could not generate QR code" in e.generate("third")


# ===================================================================== age ===


def _age_engine(today):
    from engines.age_calc import AgeCalculatorEngine
    return AgeCalculatorEngine(today=today)


def test_age_calendar_correct():
    e = _age_engine(date(2025, 3, 31))
    assert "Age: 0 years, 1 months, 3 days" in e.age("2025-02-28")
    e = _age_engine(date(2025, 3, 1))
    assert "Age: 1 years, 0 months, 0 days" in e.age("2024-03-01")
    e = _age_engine(date(2025, 1, 31))
    assert "0 years, 0 months, 30 days" in e.age("2024-12-31") or "1 months" in e.age("2024-12-31")
    assert "future" in e.age("2030-01-01")
    assert "Invalid date" in e.age("2025-02-30")
    assert "Invalid date" in e.age("not a date")


def test_age_next_birthday_today_tomorrow():
    e = _age_engine(date(2025, 5, 15))
    assert "birthday is today" in e.next_birthday("1990-05-15")
    assert "1 day away" in _age_engine(date(2025, 5, 14)).next_birthday("1990-05-15")
    assert "364 days" in _age_engine(date(2025, 5, 16)).next_birthday("1990-05-15")
    assert "future" in e.next_birthday("2999-01-01")


def test_age_ignores_time_of_day():
    called = {}

    def fake_today():
        called["x"] = 1
        return date(2025, 5, 14)
    e = _age_engine(fake_today)
    assert "1 day away" in e.next_birthday("1990-05-15")


def test_age_feb29():
    e = _age_engine(date(2025, 2, 27))
    r = e.next_birthday("2000-02-29")
    assert "February 28, 2025" in r and "Feb 29" in r and "1 day away" in r
    e = _age_engine(date(2024, 2, 28))
    assert "February 29, 2024" in e.next_birthday("2000-02-29") and "1 day away" in e.next_birthday("2000-02-29")
    e = _age_engine(date(2025, 3, 1))
    assert "Age: 25 years, 0 months, 1 days" in e.age("2000-02-29") or "25 years" in e.age("2000-02-29")
    assert "Age: 24 years, 11 months" in _age_engine(date(2025, 2, 28)).age("2000-02-29")


def test_age_days_between_and_add():
    e = _age_engine(date(2025, 1, 1))
    assert "Days between: 366" in e.days_between("2024-01-01", "2025-01-01")
    assert "Days between: 366" in e.days_between("2025-01-01", "2024-01-01")
    assert "2024-03-01" in e.add_days("2024-02-29", 1)
    assert "2024-02-29" in e.subtract_days("2024-03-01", 1)
    assert "outside the range" in e.add_days("9999-12-31", 5)


def test_age_handler_dates(monkeypatch):
    from core.handlers.age import handle_age
    o = _Orch(age_calc=_age_engine(date(2025, 5, 14)))
    handle_age(o, "next birthday 15/05/1990")
    assert "1 day away" in o.last
    handle_age(o, "age")
    assert "Provide a birthdate" in o.last


# ================================================================ text tools =


def _text(cmd):
    from core.handlers.text_tools import handle_text_tools
    from engines.text_tools import TextToolsEngine
    o = _Orch(text_tools=TextToolsEngine())
    handle_text_tools(o, cmd)
    return o.last


def test_text_tools_quotes_and_case():
    assert _text('uppercase "don\'t stop"') == "DON'T STOP"
    assert _text("uppercase don't stop") == "DON'T STOP"
    assert _text("uppercase 'hello there'") == "HELLO THERE"
    assert _text("title case don't stop") == "Don't Stop"
    assert _text("lowercase It's Fine") == "it's fine"
    assert _text("reverse abc") == "cba"


def test_text_tools_urls_and_numbers_keep_case():
    out = _text("extract urls Visit HTTP://Example.com/AbC and https://x.org/Q.")
    assert "HTTP://Example.com/AbC" in out and "https://x.org/Q" in out and "Q." not in out
    assert _text("extract numbers 3. and 1-2") == "Numbers found: 3, 1, 2"
    assert _text("extract numbers 1,234.5 and 7") == "Numbers found: 1,234.5, 7"
    assert _text("extract numbers none here") == "No numbers found."


def test_text_tools_word_count_and_wrap():
    out = _text("word count Hello world. This is a test.")
    assert "Words: 6" in out and "Sentences: 2" in out
    assert "Words: 0" in _text('word count ""') or "What text" in _text('word count ""')
    from engines.text_tools import TextToolsEngine
    e = TextToolsEngine()
    wrapped = e.wrap("aaaa bbbb cccc dddd", 9)
    assert wrapped == "aaaa bbbb\ncccc dddd" and not wrapped.startswith("\n")
    assert e.wrap("", 10) == ""
    assert e.wrap("x", 0) == "x"
    assert e.extract_numbers("a 5.") == "Numbers found: 5"
    assert e.sentence_case("hello. world") == "Hello. World"
    assert e.sentence_case("") == ""


def test_text_tools_unicode_and_huge():
    assert _text('uppercase "straße café"') == "STRASSE CAFÉ"
    big = "word " * 50000
    from engines.text_tools import TextToolsEngine
    assert "Words: 50000" in TextToolsEngine().word_count(big)


# ================================================================== weather ==


def _weather_engine(responder, clock=None):
    from engines.weather import WeatherEngine
    e = WeatherEngine(clock=clock)
    e._session = _FakeSession(responder)
    e._cache = {}
    e._wx_cache = {}
    return e


def _wx_ok(url, params):
    if "geocoding" in url:
        return _RequestsResp({"results": [{"name": "Paris", "latitude": 48.8, "longitude": 2.3,
                                           "admin1": "Ile-de-France", "country": "France"}]})
    if params.get("current"):
        return _RequestsResp({"current": {"temperature_2m": 12.5, "apparent_temperature": 10.0,
                                          "relative_humidity_2m": 70, "wind_speed_10m": 9, "weather_code": 61}})
    return _RequestsResp({"daily": {"time": ["2025-01-01", "2025-01-02"], "temperature_2m_max": [10, 11],
                                    "temperature_2m_min": [1, 2], "weather_code": [0, 3]}})


def test_weather_city_extraction():
    from core.handlers.weather import extract_city
    assert extract_city("forecast for this week") is None
    assert extract_city("will it rain tomorrow in Paris") == "Paris"
    assert extract_city("what's the temperature in Delhi?") == "Delhi"
    assert extract_city("weather in San Francisco, California") == "San Francisco, California"
    assert extract_city("weather in New York today") == "New York"
    assert extract_city("how is the weather") is None
    assert extract_city("weather for next week") is None


def test_weather_handler_routes_forecast_and_default_city(monkeypatch):
    from core.handlers.weather import handle_weather
    calls = []

    class W:
        def get_current(self, c):
            calls.append(("cur", c))
            return "cur"

        def get_forecast(self, c):
            calls.append(("fc", c))
            return "fc"
    o = _Orch(weather=W())
    handle_weather(o, "forecast for this week")
    handle_weather(o, "weather in Rio de Janeiro")
    assert calls[0][0] == "fc" and calls[0][1]          # default city, not 'this week'
    assert calls[1] == ("cur", "Rio de Janeiro")


def test_weather_http_errors_not_fake_clear_sky():
    for bad in (_RequestsResp({}, status=429), _RequestsResp({}, status=500),
                _RequestsResp(ValueError("bad json")), _RequestsResp(None),
                _RequestsResp({"error": True, "reason": "x"}), ConnectionError("down")):
        e = _weather_engine(lambda u, p, bad=bad: bad)
        r = e.get_current("Paris")
        assert "unavailable" in r and "Clear sky" not in r
    # current block missing -> unavailable, not Clear sky
    e = _weather_engine(lambda u, p: _wx_ok(u, p) if "geocoding" in u else _RequestsResp({"current": {}}))
    assert "unavailable" in e.get_current("Paris")


def test_weather_not_found_vs_geocode_error():
    e = _weather_engine(lambda u, p: _RequestsResp({"results": []}))
    assert "Could not find location: Atlantis" in e.get_current("Atlantis")
    e = _weather_engine(lambda u, p: _RequestsResp({}, status=503))
    assert "unavailable" in e.get_current("Atlantis")
    assert "unavailable" in e.get_forecast("Atlantis")


def test_weather_ttl_cache_and_geocode_forever():
    t = {"now": 0.0}
    e = _weather_engine(_wx_ok, clock=lambda: t["now"])
    r1 = e.get_current("Paris")
    n = len(e._session.calls)
    assert "Slight rain" in r1 and "12.5" in r1
    e.get_current("Paris")
    assert len(e._session.calls) == n                   # fully cached
    t["now"] = 601.0
    e.get_current("Paris")
    assert len(e._session.calls) == n + 1               # only weather re-fetched, geocode kept
    t["now"] = 100000.0
    e.get_current("Paris")
    geo_calls = [c for c in e._session.calls if "geocoding" in c[0]]
    assert len(geo_calls) == 1


def test_weather_forecast_and_region_disambiguation():
    e = _weather_engine(_wx_ok)
    r = e.get_forecast("Paris, France", days=2)
    assert "2025-01-01: Clear sky" in r and "2025-01-02: Overcast" in r
    e = _weather_engine(_wx_ok)
    assert "Forecast" in e.get_forecast("Paris", days=99)      # days clamped, no crash


# ================================================================ dictionary ==


def _dict_orch(monkeypatch, routes):
    from engines import dictionary as d
    monkeypatch.setattr(d.urllib.request, "urlopen", _fake_urlopen(routes))
    return _Orch(dictionary=d.DictionaryEngine())


ENTRY = json.dumps([{
    "word": "happy", "phonetic": "/h/",
    "meanings": [{"partOfSpeech": "adjective",
                  "definitions": [{"definition": "feeling joy", "synonyms": ["glad", "joyful"],
                                   "antonyms": ["sad"]}],
                  "synonyms": ["cheerful", "glad"], "antonyms": ["unhappy"]}]}])


def test_dictionary_word_extraction():
    from core.handlers.dictionary import extract_word
    assert extract_word("what does serendipity mean") == "serendipity"
    assert extract_word("synonym for happy") == "happy"
    assert extract_word("synonyms for happy") == "happy"
    assert extract_word("antonym of hot") == "hot"
    assert extract_word("define Quixotic") == "Quixotic"
    assert extract_word("what's the meaning of ephemeral?") == "ephemeral"
    assert extract_word("how do you spell necessary") == "necessary"


def test_dictionary_handler_and_deterministic_synonyms(monkeypatch):
    from core.handlers.dictionary import handle_dictionary
    o = _dict_orch(monkeypatch, [("/en/happy", ENTRY)])
    handle_dictionary(o, "synonyms for happy")
    first = o.last
    handle_dictionary(o, "synonyms for happy")
    assert first == o.last == "Synonyms for 'happy': cheerful, glad, joyful"
    handle_dictionary(o, "antonym of happy")
    assert o.last == "Antonyms for 'happy': unhappy, sad"
    handle_dictionary(o, "what does happy mean")
    assert "feeling joy" in o.last
    handle_dictionary(o, "synonym")
    assert "What word" in o.last


def test_dictionary_errors_and_quoting(monkeypatch):
    o = _dict_orch(monkeypatch, [("/en/zzzz", (404, b"")), ("/en/boom", (500, b"")), ("AC%2FDC", ENTRY)])
    assert "No definition found" in o.dictionary.define("zzzz")
    assert "Could not look up" in o.dictionary.define("boom")
    assert "happy" in o.dictionary.define("AC/DC")      # '/' encoded, not a path split


# ===================================================================== wiki ==


def test_wiki_quote_sentences_and_html(monkeypatch):
    from engines import wiki
    summary = json.dumps({"title": "AC/DC", "extract": "One. Two. Three. Four.",
                          "content_urls": {"desktop": {"page": "https://w/AC_DC"}}})
    fake = _fake_urlopen([("page/summary/AC%2FDC", summary)])
    monkeypatch.setattr(wiki.urllib.request, "urlopen", fake)
    e = wiki.WikiEngine()
    r = e.search("AC/DC", sentences=2)
    assert r.startswith("AC/DC: One. Two.") and "Three" not in r      # title case kept, sentences honoured
    assert "AC%2FDC" in fake.calls[0]
    # fallback to search, HTML stripped
    search = json.dumps({"query": {"search": [{"title": "Foo", "snippet": "a <span class=\"x\">bar</span> &amp; baz"}]}})
    monkeypatch.setattr(wiki.urllib.request, "urlopen",
                        _fake_urlopen([("page/summary", (404, b"")), ("w/api.php", search)]))
    r = wiki.WikiEngine().search("foo")
    assert "<" not in r and "a bar & baz" in r
    monkeypatch.setattr(wiki.urllib.request, "urlopen",
                        _fake_urlopen([("page/summary", (404, b"")), ("w/api.php", json.dumps({"query": {"search": []}}))]))
    assert "No Wikipedia article" in wiki.WikiEngine().search("qwertyzzz")
    monkeypatch.setattr(wiki.urllib.request, "urlopen", _fake_urlopen([]))
    assert "Could not search" in wiki.WikiEngine().search("x")


def test_wiki_handler_keeps_case():
    from core.handlers.wiki import handle_wiki
    seen = []

    class W:
        def search(self, q):
            seen.append(q)
            return "r"
    o = _Orch(wiki=W())
    handle_wiki(o, "wikipedia AC/DC")
    handle_wiki(o, "who is NASA")
    handle_wiki(o, "tell me about iPhone?")
    assert seen == ["AC/DC", "NASA", "iPhone"]
    handle_wiki(o, "wikipedia")
    assert "What should I look up" in o.last


# ==================================================================== facts ==


def test_facts_category_honest_and_random(monkeypatch):
    from core.handlers.facts import handle_facts
    from engines import facts
    monkeypatch.setattr(facts.urllib.request, "urlopen",
                        _fake_urlopen([("uselessfacts", json.dumps({"text": "Bananas are berries."}))]))
    o = _Orch(facts=facts.FactsEngine())
    handle_facts(o, "tell me a science fact")
    assert "can't filter facts by science" in o.last and "Bananas are berries" in o.last
    handle_facts(o, "tell me a spacecraft fact")           # 'space' is not a whole word here
    assert "can't filter" not in o.last
    handle_facts(o, "random fact")
    assert o.last == "Fun fact: Bananas are berries."
    monkeypatch.setattr(facts.urllib.request, "urlopen", _fake_urlopen([]))
    handle_facts(o, "science fact")
    assert o.last == "Couldn't fetch a fact right now."


# ==================================================================== uuid ===


class _UUID:
    def __init__(self):
        self.calls = []

    def generate_v4(self):
        self.calls.append(("v4",))
        return "v4"

    def generate_v1(self):
        self.calls.append(("v1",))
        return "v1"

    def generate_batch(self, n):
        self.calls.append(("batch", n))
        return "batch"

    def generate_namespace(self, ns, name):
        self.calls.append(("v5", ns, name))
        return "v5"

    def is_valid(self, t):
        return "valid " + t

    def timestamp(self, t):
        return "ts " + t


def _uuid(cmd):
    from core.handlers.uuid import handle_uuid
    u = _UUID()
    o = _Orch(uuid_gen=u)
    handle_uuid(o, cmd)
    return u.calls, o.last


@pytest.mark.parametrize("cmd,call", [
    ("generate uuid", ("v4",)),
    ("generate a uuid", ("v4",)),
    ("generate 5 uuids", ("batch", 5)),
    ("generate uuid v4", ("v4",)),
    ("generate uuid v1", ("v1",)),
    ("generate a version 1 uuid", ("v1",)),
    ("give me 3 guids", ("batch", 3)),
    ("generate two uuids", ("batch", 2)),
    ("generate a batch of uuids", ("batch", 5)),
    ("generate uuid version 5", ("v5", "example.com", "test")),
])
def test_uuid_counts_and_versions(cmd, call):
    assert _uuid(cmd)[0] == [call]


def test_uuid_bounds_and_validation():
    calls, resp = _uuid("generate 0 uuids")
    assert calls == [] and "1 to 100" in resp
    calls, resp = _uuid("generate 500 uuids")
    assert calls == [("batch", 500)] and "at most 100" in resp
    _, resp = _uuid("is 123e4567-e89b-12d3-a456-426614174000 a valid uuid")
    assert resp == "valid 123e4567-e89b-12d3-a456-426614174000"
    _, resp = _uuid("check this uuid")
    assert "Provide a UUID" in resp


def test_uuid_engine():
    from engines.uuid_gen import UUIDEngine
    e = UUIDEngine()
    assert len(e.generate_batch(500).splitlines()) == 101    # header + capped 100
    assert "1 to 100" in e.generate_batch(0)
    assert "version 4" in e.is_valid(e.generate_v4().split(": ")[1])
    assert "Invalid" in e.is_valid("nope")
    assert "UTC" in e.timestamp(e.generate_v1().split(": ")[1].split()[0])


# ============================================================== body metrics ==


def _body(cmd):
    from core.handlers.body_metrics import handle_body_metrics
    from engines.body_metrics import BodyMetricsEngine
    o = _Orch(body_metrics=BodyMetricsEngine())
    handle_body_metrics(o, cmd)
    return o.last


def test_body_units():
    assert "BMI: 22.9" in _body("bmi 70 kg 175 cm")
    assert "BMI: 22.9" in _body("bmi 70 kg 1.75 m")
    assert "BMI: 22.7" in _body("bmi 154 lbs 5 ft 9 in")
    assert "BMI: 22.1" in _body("bmi weight 70 kg height 5ft10")
    assert "BMI: 22.1" in _body("bmi 70kg 5'10")


def test_body_plausibility_and_word_boundaries():
    assert "doesn't look right" in _body("bmi 5000 kg 175 cm")
    assert "doesn't look right" in _body("bmi 70 kg 900 cm")
    r = _body("calories burned she 30 minutes")           # 'she' must not be read as a unit/gender token
    assert "Say" in r
    assert "Say" in _body("bmi")


# =================================================================== news ====


def _news_engine(responder, clock=None):
    from engines.news import NewsEngine
    e = NewsEngine(clock=clock)
    e._session = _FakeSession(lambda u, p: responder(u))
    return e


RSS = (b"<rss><channel>"
       b"<item><title>First story</title><description>d1</description></item>"
       b"<item><title></title></item><item><description>no title</description></item>"
       b"<item><title>Second story</title><description>" + b"x" * 200 + b"</description></item>"
       b"</channel></rss>")


def test_news_none_titles_skipped_and_ttl():
    t = {"now": 0.0}
    e = _news_engine(lambda u: _RequestsResp(content=RSS), clock=lambda: t["now"])
    r = e.get_headlines("tech", 5)
    assert r == "Top tech headlines: 1. First story; 2. Second story."
    assert "None" not in r
    e.get_headlines("tech", 5)
    assert len(e._session.calls) == 1
    t["now"] = 601
    e.get_summary("tech", 2)
    assert len(e._session.calls) == 2
    assert "..." in e.get_summary("tech", 2)


@pytest.mark.parametrize("resp", [_RequestsResp(status=429), _RequestsResp(status=500),
                                  _RequestsResp(content=b""), _RequestsResp(content=b"<rss><broken"),
                                  ConnectionError("x")])
def test_news_failures_have_clear_message_and_are_not_cached(resp):
    e = _news_engine(lambda u: resp)
    assert "couldn't reach the news service" in e.get_headlines()
    assert "couldn't reach the news service" in e.get_summary()
    assert len(e._session.calls) == 2                    # failures are retried, never cached


def test_news_handler_categories():
    from core.handlers.news import handle_news
    got = []

    class N:
        def get_headlines(self, cat, n):
            got.append(("h", cat))
            return "h"

        def get_summary(self, cat, n):
            got.append(("s", cat))
            return "s"
    o = _Orch(news=N())
    handle_news(o, "tech news")
    handle_news(o, "sports news summary")
    assert got == [("h", "tech"), ("s", "sports")]


# ======================================================== summarize / pdf =====


def test_summarize_newest_file_and_missing_downloads(tmp_path, monkeypatch):
    from core.handlers import summarize as s
    assert s.newest_file(str(tmp_path / "nope"), (".txt",)) is None
    old = tmp_path / "old.txt"
    new = tmp_path / "new.txt"
    old.write_text("a")
    new.write_text("b")
    os.utime(old, (1000, 1000))
    os.utime(new, (2000, 2000))
    (tmp_path / "newer.pdf").write_text("p")
    os.utime(tmp_path / "newer.pdf", (3000, 3000))
    assert s.newest_file(str(tmp_path), (".txt",)) == str(new)
    monkeypatch.setattr(s, "downloads_dir", lambda: str(tmp_path / "missing"))

    class S:
        def summarize_file(self, p):
            return p
    o = _Orch(summarizer=S())
    s.handle_summarize(o, "summarize file")
    assert "No text files" in o.last
    monkeypatch.setattr(s, "downloads_dir", lambda: str(tmp_path))
    s.handle_summarize(o, "summarize file")
    assert o.last == str(new)


def test_summarize_path_and_url_case_kept_and_spoken_cap():
    from core.handlers.summarize import SPOKEN_CAP, cap_spoken, handle_summarize
    seen = []

    class S:
        def summarize_file(self, p):
            seen.append(p)
            return "ok"

        def summarize_url(self, u):
            seen.append(u)
            return "y" * 2000
    o = _Orch(summarizer=S())
    handle_summarize(o, r"summarize file C:\Users\Bob\Notes\ToDo.TXT")
    handle_summarize(o, "summarize url https://Example.com/Path?A=B.")
    assert seen == [r"C:\Users\Bob\Notes\ToDo.TXT", "https://Example.com/Path?A=B"]
    assert len(o.last) <= SPOKEN_CAP + 60
    assert cap_spoken("Short.") == "Short."
    long = ("Sentence number one. " * 100)
    spoken = cap_spoken(long)
    assert len(spoken) <= SPOKEN_CAP + 40 and spoken.endswith("screen.")


def test_summarizer_engine_strips_script_and_checks_status(monkeypatch):
    from engines import text_summarizer as ts
    e = ts.TextSummarizerEngine()
    html_doc = ("<html><head><style>.a{color:red}</style><script>var secret=1;</script></head>"
                "<body><p>Hello visible text here.</p><!-- hidden --></body></html>")
    assert e.html_to_text(html_doc) == "Hello visible text here."
    monkeypatch.setattr(ts.requests, "get", lambda *a, **k: _RequestsResp(status=404))
    assert "HTTP 404" in e.summarize_url("https://x.test")
    monkeypatch.setattr(ts.requests, "get", lambda *a, **k: _RequestsResp(
        status=200, headers={"Content-Type": "text/html"}, text=html_doc))
    out = e.summarize_url("https://x.test")
    assert "secret" not in out and "color" not in out and "visible" in out
    monkeypatch.setattr(ts.requests, "get", lambda *a, **k: (_ for _ in ()).throw(ConnectionError("x")))
    assert "Error fetching" in e.summarize_url("https://x.test")
    assert "full http" in e.summarize_url("ftp://x")
    assert e.summarize_file(str(os.path.join("nonexistent_dir_zz", "a.txt"))).startswith("Error reading file")


def test_pdf_handler_default_newest_and_case(tmp_path, monkeypatch):
    from core.handlers import pdf as h
    from core.handlers import summarize as s
    monkeypatch.setattr(h, "downloads_dir", lambda: str(tmp_path / "gone"))
    o = _Orch(pdf_reader=SimpleNamespace(read_pdf=lambda p: p, summarize_pdf=lambda p: "S" + p,
                                         get_info=lambda p: "I" + p))
    h.handle_pdf(o, "read pdf")
    assert "No PDF files found" in o.last
    a = tmp_path / "a.pdf"
    b = tmp_path / "B.PDF"
    a.write_text("x")
    b.write_text("x")
    os.utime(a, (1000, 1000))
    os.utime(b, (2000, 2000))
    monkeypatch.setattr(h, "downloads_dir", lambda: str(tmp_path))
    h.handle_pdf(o, "summarize pdf")
    assert o.last.startswith("S") and o.last.endswith("B.PDF")
    h.handle_pdf(o, f"read {tmp_path}{os.sep}Mixed Case.pdf")
    assert "Mixed Case.pdf" in o.last
    assert s.cap_spoken("x") == "x"


def test_pdf_reader_stops_at_cap_and_real_page_count(tmp_path):
    from engines import pdf_reader as pr
    extracted = []

    class Page:
        def __init__(self, i):
            self.i = i

        def extract_text(self):
            extracted.append(self.i)
            return "word " * 100

    class Reader:
        def __init__(self, path):
            self.pages = [Page(i) for i in range(1000)]
            self.metadata = {}
    e = pr.PDFReaderEngine()
    e._available = True
    f = tmp_path / "big.pdf"
    f.write_bytes(b"%PDF")
    orig = pr.PdfReader
    pr.PdfReader = Reader
    try:
        r = e.read_pdf(str(f))
        assert "of 1000 pages" in r and len(extracted) < 20       # parsing stopped at the cap
        extracted.clear()
        r = e.summarize_pdf(str(f), max_pages=5)
        assert len(extracted) == 5 and "first 5 of 1000 pages" in r
    finally:
        pr.PdfReader = orig
    assert "File not found" in e.read_pdf(str(tmp_path / "none.pdf"))


# ============================================================ quotes / jokes ==


def test_quotes_dead_host_not_used_and_author_parsing(monkeypatch):
    from core.handlers.quotes import handle_quotes
    from engines import quotes
    urls = []
    base = _fake_urlopen([("zenquotes", (500, b""))])

    def spy(req, timeout=None):
        urls.append(req.full_url)
        return base(req, timeout)
    monkeypatch.setattr(quotes.urllib.request, "urlopen", spy)
    o = _Orch(quotes=quotes.QuotesEngine())
    handle_quotes(o, "quote of the day")
    assert "—" in o.last and "the day" not in o.last
    handle_quotes(o, "give me a quote by Albert Einstein")
    assert "Einstein" in o.last
    handle_quotes(o, "quote by Nobody McNoone")
    assert "don't have a quote by Nobody McNoone" in o.last
    handle_quotes(o, "inspirational quote")
    assert "—" in o.last
    assert all("quotable.io" not in u for u in urls)


def test_quotes_live_source(monkeypatch):
    from engines import quotes
    monkeypatch.setattr(quotes.urllib.request, "urlopen",
                        _fake_urlopen([("zenquotes", json.dumps([{"q": "Be.", "a": "Me"}]))]))
    assert quotes.QuotesEngine().get_random() == '"Be." — Me'
    monkeypatch.setattr(quotes.urllib.request, "urlopen", _fake_urlopen([("zenquotes", "not json")]))
    assert "—" in quotes.QuotesEngine().get_random()


def test_jokes_never_none_and_dark_safe_mode(monkeypatch):
    from core.handlers.jokes import handle_jokes
    from engines import jokes
    monkeypatch.setattr(jokes.urllib.request, "urlopen", _fake_urlopen([
        ("icanhazdadjoke", json.dumps({})), ("v2.jokeapi.dev/joke/Any", json.dumps({"type": "twopart", "setup": "S", "delivery": "D"}))]))
    o = _Orch(jokes=jokes.JokesEngine())
    handle_jokes(o, "tell me a joke")
    assert o.last == "S\nD"
    monkeypatch.setattr(jokes.urllib.request, "urlopen", _fake_urlopen([]))
    handle_jokes(o, "tell me a joke")
    assert o.last == "Couldn't fetch a joke right now. Try again later." and "None" not in o.last
    handle_jokes(o, "tell me a programming joke")      # category fetch fails -> fallback, not None
    assert o.last and "None" not in o.last
    handle_jokes(o, "tell me a dark joke")
    assert "safe mode" in o.last
    handle_jokes(o, "tell me a joke about pundits")     # 'pun' is not a whole word
    assert "None" not in o.last


# ================================================================== pomodoro ==


def test_pomodoro_single_loop_and_stop():
    from engines.pomodoro import PomodoroEngine
    p = PomodoroEngine()
    msgs = []
    p.set_callback(msgs.append)
    assert p.start(25, 5) is True
    assert p.start(1, 1) is False                       # second start does not spawn a loop
    assert p.work_duration == 25 * 60                   # ... and does not clobber settings
    assert sum(1 for m in msgs if "Work started" in m) == 1
    t0 = threading.active_count()
    p.stop()
    assert not p._timer.is_alive() and p.status() == "No pomodoro session active."
    assert threading.active_count() <= t0
    assert p.start(1, 1) is True                         # can restart after stop
    p.stop()


def test_pomodoro_cycles_with_event_wait():
    from engines.pomodoro import PomodoroEngine
    p = PomodoroEngine()
    p.work_duration = 0.01
    p.break_duration = 0.01
    done = threading.Event()
    msgs = []

    def cb(m):
        msgs.append(m)
        if "Break over" in m:
            done.set()
    p.set_callback(cb)
    p.start()
    assert done.wait(2)
    p.stop()
    assert p.get_sessions() >= 1
    assert any("Work session complete" in m for m in msgs)


def test_pomodoro_handler_whole_words():
    from core.handlers.pomodoro import handle_pomodoro
    calls = []

    class P:
        work_duration, break_duration = 1500, 300

        def stop(self):
            calls.append("stop")

        def status(self):
            return "status"

        def set_callback(self, cb):
            pass

        def start(self, work_minutes=None, break_minutes=None):
            calls.append(("start", work_minutes, break_minutes))
            return True
    o = _Orch(pomodoro=P())
    handle_pomodoro(o, "start pomodoro this weekend")
    handle_pomodoro(o, "send me a pomodoro")
    assert calls == [("start", None, None), ("start", None, None)]
    handle_pomodoro(o, "start pomodoro 30 min break 10")
    assert calls[-1] == ("start", 30, 10)
    handle_pomodoro(o, "stop pomodoro")
    assert calls[-1] == "stop"
    handle_pomodoro(o, "pomodoro status")
    assert o.last == "status"
    handle_pomodoro(o, "hello")
    assert "Say" in o.last
    P.start = lambda self, **k: False
    handle_pomodoro(o, "start pomodoro")
    assert "already running" in o.last


# ================================================================ ip lookup ===


def test_ip_validation_https_and_domain(monkeypatch):
    from core.handlers.ip_lookup import handle_ip_lookup
    from engines import ip_lookup as ipl
    eng = ipl.IPLookupEngine()
    fake = _fake_urlopen([("ipwho.is/8.8.8.8", json.dumps({"success": True, "ip": "8.8.8.8", "country": "US",
                                                           "connection": {"isp": "Google"}}))])
    monkeypatch.setattr(ipl.urllib.request, "urlopen", fake)
    r = eng.lookup("8.8.8.8")
    assert "IP: 8.8.8.8" in r and "Country: US" in r and "ISP: Google" in r
    assert fake.calls[0].startswith("https://")
    assert "not a valid IP" in eng.lookup("999.1.1.1")
    assert "not a valid IP" in eng.lookup("1.2.3")
    assert eng.validate_ip("255.255.255.255") and eng.validate_ip("256.0.0.1") is None
    # fallback endpoint + failure message
    monkeypatch.setattr(ipl.urllib.request, "urlopen", _fake_urlopen([
        ("ipwho.is", (500, b"")), ("ip-api.com", json.dumps({"status": "fail", "message": "reserved range"}))]))
    assert "reserved range" in eng.lookup("10.0.0.1")
    # domain resolves the domain, not the user's own IP
    seen = []
    o = _Orch(ip_lookup=SimpleNamespace(lookup=lambda x: seen.append(x) or "r", get_public_ip=lambda: "mine"))
    handle_ip_lookup(o, "lookup Example.com")
    handle_ip_lookup(o, "ip of 8.8.4.4")
    handle_ip_lookup(o, "what is my ip")
    assert seen == ["Example.com", "8.8.4.4"] and o.last == "mine"


def test_ip_domain_resolution(monkeypatch):
    from engines import ip_lookup as ipl
    monkeypatch.setattr(ipl.socket, "gethostbyname", lambda n: "93.184.216.34")
    seen = []
    eng = ipl.IPLookupEngine()
    monkeypatch.setattr(eng, "_fetch", lambda url: seen.append(url) or {"success": True, "ip": "93.184.216.34"})
    assert "93.184.216.34" in eng.lookup("example.com")
    assert seen[0].endswith("/93.184.216.34")
    assert eng.resolve_domain("not a domain") is None


# ================================================================ image gen ===


def test_image_gen_unique_names_content_type_cleanup(tmp_path, monkeypatch):
    from core.handlers.image_gen import handle_image_gen
    from engines import image_gen as ig
    e = ig.ImageGenEngine(output_dir=str(tmp_path))
    urls = []

    def ok(url, **k):
        urls.append(url)
        return _RequestsResp(status=200, content=b"PNGDATA", headers={"Content-Type": "image/png"})
    monkeypatch.setattr(ig.requests, "get", ok)
    r1 = e.generate("draw a picture of a red Fox & hound")
    r2 = e.generate("draw a picture of a red Fox & hound")
    p1, p2 = r1.split("saved to ")[1], r2.split("saved to ")[1]
    assert p1 != p2 and os.path.isabs(p1) and os.path.isfile(p1) and os.path.isfile(p2)
    assert "red%20Fox%20%26%20hound" in urls[0] and "+" not in urls[0].split("prompt/")[1].split("?")[0]
    monkeypatch.setattr(ig.requests, "get", lambda url, **k: _RequestsResp(status=200, content=b"<html>", headers={"Content-Type": "text/html"}))
    before = set(os.listdir(tmp_path))
    assert "did not return an image" in e.generate("x")
    assert set(os.listdir(tmp_path)) == before
    monkeypatch.setattr(ig.requests, "get", lambda url, **k: _RequestsResp(status=503))
    assert "status 503" in e.generate("x")

    class Boom(_RequestsResp):
        def iter_content(self, n):
            yield b"abc"
            raise ConnectionError("cut")
    monkeypatch.setattr(ig.requests, "get", lambda url, **k: Boom(status=200, headers={"Content-Type": "image/png"}))
    before = set(os.listdir(tmp_path))
    assert "error" in e.generate("y").lower()
    assert set(os.listdir(tmp_path)) == before                      # partial file deleted
    monkeypatch.setattr(ig.requests, "get", ok)
    o = _Orch(image_gen=e)
    handle_image_gen(o, "Generate an image of a Red Fox")
    assert "Generating image of a Red Fox" in o.said[0]              # case preserved
    assert "red" not in urls[-1].split("prompt/")[1][:3].lower() or "Red%20Fox" in urls[-1]


def test_image_gen_default_dir_is_absolute():
    from engines import image_gen as ig
    assert os.path.isabs(ig.ImageGenEngine().output_dir)


# ================================================================ color info ==


def test_color_complement_is_hue_rotation():
    from engines.color_info import ColorInfoEngine
    e = ColorInfoEngine()
    assert "#00ffff" in e.complementary("#ff0000")
    assert "#ff0000" in e.complementary("00ffff")
    assert "#808080" in e.complementary("808080")        # grey is its own complement (RGB invert would give 7f7f7f)
    assert "#ffffff" in e.complementary("ffffff") and "#000000" in e.complementary("000000")
    assert e.complementary("xyz") == "Invalid hex code."


def test_color_lookup_quotes_names_and_handler_hex(monkeypatch):
    from core.handlers.color_info import handle_color
    from engines import color_info as ci
    fake = _fake_urlopen([("thecolorapi", json.dumps({"name": {"value": "Red"}, "hex": {"value": "#FF0000"}}))])
    monkeypatch.setattr(ci.urllib.request, "urlopen", fake)
    e = ci.ColorInfoEngine()
    e.lookup("dark & stormy/blue")
    assert "name=dark%20%26%20stormy%2Fblue" in fake.calls[0]
    got = []
    o = _Orch(color_info=SimpleNamespace(from_hex=lambda h: got.append(("hex", h)) or "x",
                                         complementary=lambda h: got.append(("comp", h)) or "y",
                                         lookup=lambda n: got.append(("name", n)) or "z",
                                         random_color=lambda: "r"))
    handle_color(o, "hex #FfAa00")
    handle_color(o, "complementary of #12ABef")
    handle_color(o, "hex deadbeef1234")                  # 12 hex chars: not a 6-char colour
    assert got[0] == ("hex", "FfAa00") and got[1] == ("comp", "12ABef")
    assert len(got) == 2 and "Provide a hex code" in o.last   # boundary-checked, no partial match
    handle_color(o, "color Cornflower Blue")
    assert got[-1][0] == "name"


# ===================================================================== lorem ==


def test_lorem_counts_bounds():
    from core.handlers.lorem import handle_lorem
    from engines.lorem import LoremEngine
    o = _Orch(lorem=LoremEngine())
    handle_lorem(o, "lorem ipsum 0 words")
    assert "at least 1" in o.last
    handle_lorem(o, "lorem ipsum 5 words")
    assert o.ctx.last_response.count(" ") == 4
    handle_lorem(o, "lorem ipsum 99999 words")
    assert "limited to 1000" in o.last and len(o.ctx.last_response.split()) == 1000
    handle_lorem(o, "lorem ipsum 2 paragraphs")
    assert o.ctx.last_response.count("\n\n") == 1
    handle_lorem(o, "lorem ipsum")
    assert o.ctx.last_response.count("\n\n") == 2
    e = LoremEngine()
    assert e.generate_words(0) == "" and e.generate(0) == ""
    assert len(e.generate_words(10**9).split()) == 1000
    assert all(not w.startswith(" ") for w in e.WORDS)


# ================================================================= notes ======


def test_handlers_do_not_store_wake_word_payload_lowercased():
    """Cross-cutting: payload extraction uses the original text (case kept)."""
    assert hashlib.sha256(b"HeLLo").hexdigest() in _hash("hey flexie, sha256 HeLLo")
    assert _text('reverse "AbC"') == "CbA"
