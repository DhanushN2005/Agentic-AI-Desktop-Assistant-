import re

from core.handlers.agents import handle_capability_delegation
from core.handlers.age import handle_age
from core.handlers.alarm import handle_alarm
from core.handlers.awareness import handle_awareness
from core.handlers.body_metrics import handle_body_metrics
from core.handlers.browser import (
    handle_browser_control,
    handle_browser_extract,
    handle_browser_navigate,
    handle_browser_tabs,
    handle_gmail,
)
from core.handlers.automation import handle_automation
from core.handlers.clipboard_mgr import handle_clipboard_mgr
from core.handlers.code_gen import handle_code_gen
from core.handlers.code_search import handle_local_code_search
from core.handlers.color_info import handle_color
from core.handlers.converter import handle_convert
from core.handlers.dev import handle_briefing, handle_clipboard, handle_dev_build, handle_dev_explain, handle_intel
from core.handlers.dictionary import handle_dictionary
from core.handlers.facts import handle_facts
from core.handlers.files import (
    handle_file_delete,
    handle_file_op,
    handle_file_rename,
    handle_file_save,
    handle_knowledge_search,
)
from core.handlers.hash_encoder import handle_hash
from core.handlers.image_gen import handle_image_gen
from core.handlers.ip_lookup import handle_ip_lookup
from core.handlers.jokes import handle_jokes
from core.handlers.json_fmt import handle_json
from core.handlers.lorem import handle_lorem
from core.handlers.media import handle_media, handle_play_youtube, handle_youtube
from core.handlers.memory_system import handle_memory_system
from core.handlers.news import handle_news
from core.handlers.notification import handle_notification
from core.handlers.password import handle_password
from core.handlers.pdf import handle_pdf
from core.handlers.pomodoro import handle_pomodoro
from core.handlers.qrcode import handle_qr
from core.handlers.quotes import handle_quotes
from core.handlers.reminders import handle_list_reminders, handle_remind
from core.handlers.research import handle_research
from core.handlers.search import handle_search
from core.handlers.summarize import handle_summarize
from core.handlers.system import (
    handle_app_op,
    handle_auto_save,
    handle_brightness,
    handle_comm,
    handle_exit,
    handle_mode,
    handle_mode_prefix,
    handle_power,
    handle_save_active,
    handle_snap,
    handle_undo,
    handle_voice,
    handle_volume,
)
from core.handlers.text_tools import handle_text_tools
from core.handlers.tip import handle_tip
from core.handlers.tools import handle_calc, handle_memory, handle_status, handle_translate
from core.handlers.uuid import handle_uuid
from core.handlers.vision import handle_camera_capture, handle_vision
from core.handlers.weather import handle_weather
from core.handlers.wiki import handle_wiki
from utils.config import Config

SNAP_KEYWORDS = ["snap ", "maximize", "minimize", "split screen", "put notepad", "put chrome", "put edge", "move notepad", "move chrome", "move edge"]


SOCIAL_RESPONSES = {
    "hi": "Hey there! How can I help you?",
    "hello": "Hello! What can I do for you?",
    "hey flexie": "Hey! I'm here and ready.",
    "hey there": "Hey! What's up?",
    "how are you": "I'm doing great, thanks for asking! How can I assist you?",
    "good morning": "Good morning! Hope you're having a great day. What can I help with?",
    "good night": "Good night! Sleep well. I'll be here when you need me.",
    "thanks": "You're welcome!",
    "thank you": "Happy to help!",
    "what's up": "Not much, just here and ready to assist! What do you need?",
    "are you there": "Yes, I'm here! What can I do for you?",
}


def handle_social(orch, c):
    orch.send_to_ui("STATE", "PROCESSING")
    cmd = c.strip().lower()
    cmd = re.sub(r"^(flexi|flexie|hey flexie|ok flexie)\b", "", cmd).strip()
    cmd = re.sub(r"^[,\.\!\?\s]+", "", cmd).strip()
    for trigger, response in SOCIAL_RESPONSES.items():
        if cmd == trigger or cmd.startswith(trigger):
            orch.ctx.update(last_response=response, query=c)
            orch.speak(response)
            return True
    return handle_conversational(orch, c)


def handle_conversational(orch, c):
    orch.send_to_ui("STATE", "PROCESSING")
    sys_p = Config.SYSTEM_PROMPT_HACKER if orch.current_mode == "hacker" else Config.SYSTEM_PROMPT_STANDARD
    response = orch.brain.ask(c, system_override=sys_p)
    if orch.current_mode == "hacker" and orch._parse_tool_call(response):
        return True
    orch.ctx.update(last_response=response, query=c)
    orch.speak(response)
    return True


def dispatch_intent(orch, intent, c, silent):
    """Runs the intent execution chain. Preserves the historical elif dispatch order."""
    try:
        # --- PHASE 1 & 3: Capability Registry & Agent Delegation ---
        if handle_capability_delegation(orch, intent, c, silent):
            return True

        # Snap/maximize/minimize keywords take priority over intent-specific handlers
        if any(x in c for x in SNAP_KEYWORDS):
            return handle_snap(orch, c)

        if intent == "undo":
            return handle_undo(orch, c)
        if intent == "social":
            return handle_social(orch, c)
        if intent == "weather":
            return handle_weather(orch, c)
        if intent == "news":
            return handle_news(orch, c)
        if intent == "alarm":
            return handle_alarm(orch, c)
        if intent == "image_gen":
            return handle_image_gen(orch, c)
        if intent == "pdf":
            return handle_pdf(orch, c)
        if intent == "clipboard_mgr":
            return handle_clipboard_mgr(orch, c)

        if intent == "local_code_search":
            return handle_local_code_search(orch, c, silent)

        if intent == "summarize":
            return handle_summarize(orch, c)
        if intent == "awareness":
            return handle_awareness(orch, c)
        if intent == "memory_system":
            return handle_memory_system(orch, c)
        if intent == "notification":
            return handle_notification(orch, c)
        if intent == "wiki":
            return handle_wiki(orch, c)
        if intent == "jokes":
            return handle_jokes(orch, c)
        if intent == "quotes":
            return handle_quotes(orch, c)
        if intent == "password":
            return handle_password(orch, c)
        if intent == "qr_code":
            return handle_qr(orch, c)
        if intent == "dictionary":
            return handle_dictionary(orch, c)
        if intent == "facts":
            return handle_facts(orch, c)
        if intent == "pomodoro":
            return handle_pomodoro(orch, c)
        if intent == "ip_lookup":
            return handle_ip_lookup(orch, c)
        if intent == "text_tools":
            return handle_text_tools(orch, c)
        if intent == "hash_encoder":
            return handle_hash(orch, c)
        if intent == "json_fmt":
            return handle_json(orch, c)
        if intent == "color_info":
            return handle_color(orch, c)
        if intent == "lorem":
            return handle_lorem(orch, c)
        if intent == "uuid":
            return handle_uuid(orch, c)
        if intent == "tip_calc":
            return handle_tip(orch, c)
        if intent == "body_metrics":
            return handle_body_metrics(orch, c)
        if intent == "age_calc":
            return handle_age(orch, c)
        if intent == "mode":
            return handle_mode(orch, c, silent)
        if intent == "exit":
            return handle_exit(orch)
        if intent == "browser_navigate":
            return handle_browser_navigate(orch, c)
        if intent == "browser_control":
            return handle_browser_control(orch, c)
        if intent == "browser_tabs":
            return handle_browser_tabs(orch, c)
        if intent == "browser_extract":
            return handle_browser_extract(orch, c)
        if intent == "gmail":
            return handle_gmail(orch)
        if intent == "power":
            return handle_power(orch, c)
        if intent == "play_youtube":
            return handle_play_youtube(orch, c)
        if intent == "youtube":
            return handle_youtube(orch, c)
        if "volume" in c:
            return handle_volume(orch, c, silent)
        if "brightness" in c:
            return handle_brightness(orch, c, silent)
        if c.startswith("mode "):
            return handle_mode_prefix(orch, c, silent)
        if intent == "media":
            return handle_media(orch, c)
        if intent == "app_op":
            return handle_app_op(orch, c, silent)
        if intent.startswith("vision_"):
            return handle_vision(orch, intent, c)
        if intent == "camera_capture":
            return handle_camera_capture(orch)
        if intent == "file_rename":
            return handle_file_rename(orch, c)
        if intent == "file_delete":
            return handle_file_delete(orch, c)
        if intent == "file_save":
            return handle_file_save(orch, c)
        if intent == "file_op":
            return handle_file_op(orch, c)
        if intent == "save_active":
            return handle_save_active(orch)
        if intent == "auto_save":
            return handle_auto_save(orch, c)
        if intent == "dev_build":
            return handle_dev_build(orch, c)
        if intent == "dev_explain":
            return handle_dev_explain(orch)
        if intent == "knowledge_search":
            return handle_knowledge_search(orch, c)
        if intent == "code_gen":
            return handle_code_gen(orch, c)
        if intent == "research":
            return handle_research(orch, c)
        if intent == "automation":
            return handle_automation(orch, c)
        if intent in ("search", "browser_search"):
            return handle_search(orch, c)
        if intent == "remind_me":
            return handle_remind(orch, c)
        if intent == "list_reminders":
            return handle_list_reminders(orch)
        if intent == "briefing":
            return handle_briefing(orch)
        if intent == "clipboard":
            return handle_clipboard(orch)
        if intent == "comm":
            return handle_comm(orch, c)
        if intent == "voice":
            return handle_voice(orch, c)
        if intent == "intel":
            return handle_intel(orch, c)
        if intent == "calc":
            return handle_calc(orch, c)
        if intent == "convert":
            return handle_convert(orch, c)
        if intent == "status":
            return handle_status(orch, c)
        if intent == "memory":
            return handle_memory(orch, c)
        if intent == "translate":
            return handle_translate(orch, c)
        return handle_conversational(orch, c)
    except Exception as e:
        orch.logger.error(f"Error in {intent}: {e}")
        return True
