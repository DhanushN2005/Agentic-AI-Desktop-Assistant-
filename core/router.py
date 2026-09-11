import re
from difflib import get_close_matches

from utils.config import Config

# Common typo corrections for voice/typing errors
TYPO_MAP = {
    "nex6t": "next", "nexr": "next", "neext": "next", "nxt": "next",
    "previos": "previous", "previus": "previous",
    "fullscreen": "full screen", "fullscrn": "full screen",
    "youtbe": "youtube", "yotube": "youtube", "ytube": "youtube",
    "ply": "play", "palay": "play", "pla": "play",
    "sng": "song", "sogn": "song",
    "volme": "volume", "vlume": "volume",
    "brghtness": "brightness", "brigtness": "brightness",
    "openn": "open", "opne": "open",
    "closse": "close", "clsoe": "close",
    "searh": "search", "serach": "search", "sarch": "search",
    "timwe": "timer", "tiemr": "timer", "tmer": "timer", "timmer": "timer",
    "seting": "setting", "settign": "setting",
    "secnd": "second", "secod": "second", "seond": "second", "secound": "second",
    "alaram": "alarm", "alarma": "alarm",
    "remnder": "reminder", "remindr": "reminder", "remider": "reminder",
    "weahter": "weather", "wether": "weather", "wheather": "weather",
    "genrate": "generate", "generat": "generate", "generete": "generate",
    "imag": "image", "imege": "image", "imge": "image",
    "clipoard": "clipboard", "clipbard": "clipboard", "clibpard": "clipboard",
    "dictonary": "dictionary", "defination": "definition", "definiton": "definition",
    "diction": "diction", "dictation": "dictation",  # prevent difflib false positive
    "time": "time", "times": "times",  # prevent difflib false positives
    "synonim": "synonym", "synonymns": "synonyms", "anonim": "antonym",
    "passwrd": "password", "passsword": "password", "pasword": "password",
    "qr": "qr code", "qrcde": "qr code",
    "pomodoro": "pomodoro", "pmodoro": "pomodoro", "pomodor": "pomodoro",
    "color": "color", "colour": "color",
    "lorem": "lorem", "lorum": "lorem",
    "uuidd": "uuid", "uid": "uuid",
    "bmi": "bmi", "bmri": "bmi",
    "toip": "tip", "tipp": "tip",
    "dictionnary": "dictionary",
    "encooder": "encoder", "deccoder": "decoder",
    "jokke": "joke", "joookes": "jokes",
    "quoote": "quote", "qoutes": "quotes",
    "faxct": "fact", "faccts": "facts",
    "agee": "age", "agge": "age",
    "ip": "ip",
    "txt": "text", "tect": "text", "texit": "text",
    "jsn": "json", "jsoon": "json",
    "hashh": "hash", "haash": "hash",
    "morse": "morse", "morss": "morse",
}


# Natural language override patterns: (pattern, intent, confidence)
# Checked BEFORE compiled triggers to intercept conversational phrasing.
NL_OVERRIDES = [
    # Alarm / Timer / Time
    (r"\b(what(?:'?s|\s+is)\s+(?:the\s+)?time|current\s+time|tell\s+me\s+(?:the\s+)?time|time\s+is\s+it|whats?\s+the\s+time|what\s+hour)\b", "alarm", 0.95),
    (r"\b(set|start|begin|create|put|make)\s+(?:a\s+)?(?:timer|countdown|alarm|wake)\b", "alarm", 0.9),
    (r"\b(stop|cancel|clear|end|kill)\s+(?:the\s+)?(?:timer|alarm|countdown)\b", "alarm", 0.9),
    (r"\b(how\s+(?:long|much\s+time)\s+(?:left|remaining|until|till))\b", "alarm", 0.9),

    # Weather
    (r"\b(how'?s?\s+(?:the\s+)?weather|is\s+it\s+(?:raining|snowing|sunny|cold|hot|warm)|what'?s?\s+(?:it\s+)?like\s+(?:outside|today|tomorrow)|should\s+i\s+(?:bring|wear|take\s+an?\s+umbrella)|do\s+i\s+need\s+(?:a\s+)?(?:jacket|umbrella|coat))\b", "weather", 0.9),
    (r"\b(temperature|forecast|climate|humidity|wind|rain|snow|sunny|cloudy|storm|thunder)\b", "weather", 0.85),

    # News
    (r"\b(what'?s?\s+(?:happening|going\s+on|in\s+the\s+news|new\s+today)|tell\s+me\s+(?:the\s+)?(?:news|headlines)|any\s+(?:news|updates|happening)|what\s+(?:are?\s+)?the\s+(?:latest|headlines))\b", "news", 0.9),

    # Translate (must come BEFORE daily_briefing to avoid "translate good morning" hijack)
    (r"\b(translate|translation|translate\s+this\s+to|say\s+it\s+in|in\s+(?:spanish|french|hindi|german|japanese|chinese|korean|arabic|portuguese|italian|russian))\b", "translate", 0.9),

    # Reminders (only "remind me" patterns — "remember that" goes to memory_system)
    (r"\b(remind\s+me|set\s+(?:a\s+)?reminder|schedule\s+(?:a\s+)?reminder)\b", "remind_me", 0.9),
    (r"\b(list|show|display|what|any|my)\s+(?:are\s+)?(?:my\s+)?(?:pending\s+)?reminders?\b", "list_reminders", 0.9),

    # Notifications
    (r"\b(notify\s+me|alert\s+me|give\s+me\s+(?:a\s+)?(?:notification|alert)|send\s+(?:me\s+)?(?:a\s+)?(?:notification|alert)|ping\s+me)\b", "notification", 0.9),

    # PDF
    (r"\b(read|open|summarize|analyz|extract|scan|review)\s+(?:this\s+)?(?:the\s+)?pdf\b", "pdf", 0.9),
    (r"\b(pdf|portable\s+document)\b.*\b(read|open|summarize|analyz|extract|what\s+does)\b", "pdf", 0.85),
    (r"\bwhat\s+does\s+(?:this|the)\s+(?:pdf|document|file)\s+say\b", "pdf", 0.95),

    # Clipboard
    (r"\b(clipboard|clip\s+history|what\s+(?:did\s+)?i\s+copy|copy\s+(?:this|that|to|it|the\s+result)|paste\s+(?:from|that|this|it|the\s+result|the\s+output)|search\s+clipboard|clear\s+clipboard)\b", "clipboard_mgr", 0.85),

    # Code Generation (generate/write code) - MUST come BEFORE local_code_search
    # Only match explicit code generation requests, NOT searches
    (r"\b(tell|give|show|write|generate|create|get)\s+(?:me\s+)?(?:a\s+)?(?:the\s+)?(?:an?\s+)?(?:python|java|javascript|js|c\+\+|cpp|html|css|sql|ruby|go|rust|swift|kotlin)\s+(?:code|script|program|implementation|algorithm|function|class)\b", "code_gen", 0.95),
    (r"\b(tell|give|show|write|generate|create|get)\s+(?:me\s+)?(?:a\s+)?(?:the\s+)?(?:binary\s+search|sorting|linked\s+list|tree|graph|queue|stack|hash\s+map|array|matrix|fibonacci|factorial|palindrome)\s+(?:code|script|program|implementation|algorithm|function|class)\b", "code_gen", 0.95),
    (r"\b(python|java|javascript|js|c\+\+|cpp|html|css|sql)\s+(?:code|script|program|implementation)\s+(?:for|of|to)\s+(?:a\s+)?\w+\b", "code_gen", 0.9),
    (r"\b(generate|write|create)\s+(?:me\s+)?(?:a\s+)?(?:full\s+)?(?:code|script|program)\s+(?:for|of|to)\s+(?:a\s+)?\w+\b", "code_gen", 0.85),

    # Local code search (must come AFTER code_gen to prefer code generation)
    # Only match code/project/repository searches, NOT general file searches
    (r"\b(search\s+(?:my\s+|the\s+|this\s+)?(?:code|codebase|project|repository|source|implementation)|find\s+(?:in|within|through)\s+(?:my\s+|the\s+|this\s+)?(?:code|project|codebase|source)|code\s+search|search\s+code|local\s+code\s+search|find\s+function|find\s+class)\b", "local_code_search", 0.9),

    # Summarize
    (r"\b(summariz|summary|brief|overview|tldr|tl;dr|condense|shorten|abbreviate)\b", "summarize", 0.85),

    # Awareness
    (r"\b(who\s+are\s+you|what\s+are\s+you|tell\s+me\s+about\s+yourself|your\s+name|describe\s+yourself|what\s+can\s+you\s+do|your\s+(?:stats|capabilities|abilities|features))\b", "awareness", 0.95),

    # Memory system (must come BEFORE remind_me for "remember that/this/when")
    (r"\b(remember\s+(?:that|this|when)|keep\s+in\s+mind|don'?t\s+forget|what\s+do\s+you\s+remember|what\s+have\s+you\s+learned|memory\s+(?:stats|status)|how\s+much\s+(?:do\s+you\s+)?remember|recent\s+conversations?|what\s+did\s+we\s+talk\s+about|conversation\s+history|search\s+memory|popular\s+topics?)\b", "memory_system", 0.9),

    # Wiki
    (r"\b(wikipedia|wiki\s+(?:search|lookup|page)|look\s+up\s+(?:on\s+)?wiki|search\s+(?:on\s+)?wikipedia|wiki\s+article)\b", "wiki", 0.9),

    # Jokes
    (r"\b(tell\s+(?:me\s+)?(?:a\s+)?joke|make\s+me\s+laugh|say\s+something\s+funny|got\s+(?:any\s+)?jokes?|i'?m\s+(?:bored|sad)|cheer\s+me\s+up|humor\s+me|be\s+funny|comedy|pun(?:chline)?)\b", "jokes", 0.9),

    # Quotes
    (r"\b(quote\s+(?:of\s+the\s+day|me|inspire)|inspire\s+me|motivate\s+me|give\s+me\s+(?:a\s+)?(?:motivational|inspirational|wise)\s+quote|some\s+(?:wisdom|inspiration|motivation)|what'?s?\s+(?:a\s+)?(?:good|nice|great)\s+(?:quote|saying))\b", "quotes", 0.9),

    # Password
    (r"\b(generate|create|make|new|random|strong|secure|need)\s+(?:a\s+)?(?:new\s+)?password\b", "password", 0.9),
    (r"\b(password\s+(?:generator|generator|strength|check|evaluate|secure|strong|safe))\b", "password", 0.9),
    (r"\bhow\s+(?:strong|secure|safe)\s+(?:is|is\s+my)\s+(?:the\s+)?(?:password|pass(?:word)?)\b", "password", 0.9),
    (r"\b(generate|create|make)\s+(?:a\s+)?passphrase\b", "password", 0.9),

    # QR Code
    (r"\b(qr\s*code|qrcode|generate\s+qr|create\s+qr|make\s+qr|qr\s+(?:for|of|with))\b", "qr_code", 0.9),

    # Dictionary
    (r"\b(define|definition\s+of|meaning\s+of|what\s+(?:does|is)\s+(?:the\s+)?(?:word\s+)?\w+\s+mean|dictionary|lookup\s+(?:a\s+)?word|synonym|antonym|spell|how\s+do\s+you\s+spell)\b", "dictionary", 0.85),

    # Facts
    (r"\b(tell\s+me\s+(?:a\s+)?(?:fun\s+)?fact|random\s+fact|did\s+you\s+know|interesting\s+fact|fun\s+fact|learn\s+something\s+new|fact\s+of\s+the\s+day|trivia|i'?m\s+curious|blow\s+my\s+mind)\b", "facts", 0.9),

    # Pomodoro
    (r"\b(pomodoro|focus\s+(?:timer|session|mode|time)|start\s+(?:focusing|focus|work\s+session)|break\s+timer|work\s+(?:timer|session|break))\b", "pomodoro", 0.9),

    # IP Lookup
    (r"\b(what(?:'?s|\s+is)\s+my\s+(?:public\s+)?ip|my\s+ip\s+address|ip\s+(?:address|info|lookup|location|address)|lookup\s+(?:an?\s+)?ip|find\s+(?:my\s+)?ip|where\s+(?:am\s+i|is\s+my\s+ip))\b", "ip_lookup", 0.9),

    # Text Tools
    (r"\b(word\s+count|character\s+count|count\s+(?:the\s+)?(?:words?|chars?|characters?|letters?)|how\s+many\s+(?:words?|characters?|letters?))\b", "text_tools", 0.9),
    (r"\b(reverse\s+(?:this|that|text|it|the\s+text)|make\s+(?:it|this|text)\s+(?:all\s+)?uppercase|make\s+(?:it|this|text)\s+(?:all\s+)?lowercase|title\s+case|sentence\s+case|snake\s+case|camel\s+case|kebab\s+case)\b", "text_tools", 0.9),
    (r"\b(remove\s+duplicates?|sort\s+(?:the\s+)?lines?|slugify|wrap\s+text|extract\s+(?:all\s+)?(?:emails?|urls?|links?|numbers?))\b", "text_tools", 0.9),
    (r"\b(text\s+(?:tools?|utilities?|processor|manipulator|editor))\b", "text_tools", 0.85),

    # Hash / Encoder
    (r"\b(md5|sha[-\s]?(?:1|256|512)|hash\s+(?:this|it|text|the\s+text))\b", "hash_encoder", 0.9),
    (r"\b(base64\s+(?:encode|decode)|hex\s+(?:encode|decode)|binary\s+(?:encode|decode)|morse\s+(?:code|encode))\b", "hash_encoder", 0.9),
    (r"\b(encode|decode)\s+(?:this|that|text|it)\b", "hash_encoder", 0.85),
    (r"\b(encoder|decoder|encoding|decoding)\b", "hash_encoder", 0.8),

    # JSON
    (r"\b(format|pretty|beautify|minify|compact|validate|check|parse)\s+(?:my\s+)?(?:this\s+)?(?:the\s+)?json\b", "json_fmt", 0.9),
    (r"\bjson\s+(?:format|pretty|validate|info|keys?|flatten|minify|parse|lint|tool)\b", "json_fmt", 0.9),
    (r"\b(what|tell\s+me)\s+(?:is\s+)?(?:wrong\s+with|about|are\s+the\s+keys?\s+in)\s+(?:this\s+)?json\b", "json_fmt", 0.85),

    # Color
    (r"\b(color|colour)\s+(?:info|of|meaning|lookup|for|name|hex|rgb|hsl)\b", "color_info", 0.85),
    (r"\b(random\s+(?:color|colour)|complementary\s+(?:color|colour)|hex\s+to|what\s+color)\b", "color_info", 0.9),
    (r"\bwhat\s+(?:is\s+the\s+)?(?:color|colour)\s+(?:of|for|name)\b", "color_info", 0.85),

    # Lorem Ipsum
    (r"\b(lorem\s+ipsum|generate\s+(?:some\s+)?(?:lorem|placeholder|dummy|sample|fake|filler)\s+text|need\s+(?:some\s+)?(?:lorem|placeholder|dummy|sample)\s+text)\b", "lorem", 0.9),

    # UUID
    (r"\b(generate|create|make|new|need)\s+(?:a\s+)?(?:new\s+)?uuid\b", "uuid", 0.9),
    (r"\b(uuid\s+(?:generator|v[145]|valid|check|timestamp|batch))\b", "uuid", 0.9),
    (r"\b(generate|create)\s+(?:a\s+)?batch\s+(?:of\s+)?(?:uuid|uuids)\b", "uuid", 0.9),

    # Tip Calculator
    (r"\b(calculate|compute|figure\s+out|what\s+is)\s+(?:the\s+)?(?:tip|gratuity)\b", "tip_calc", 0.9),
    (r"\b(split|divide|share)\s+(?:the\s+)?(?:bill|check|tab|meal)\b", "tip_calc", 0.9),
    (r"\bhow\s+much\s+(?:should\s+i\s+)?(?:tip|leave|give)\b", "tip_calc", 0.9),
    (r"\b(tip\s+calculator|bill\s+splitter|how\s+much\s+per\s+person)\b", "tip_calc", 0.9),

    # Body Metrics
    (r"\b(calculate|compute|what\s+is|figure\s+out)\s+(?:my\s+)?(?:bmi|bmr|body\s+mass\s+index|basal\s+metabolic)\b", "body_metrics", 0.9),
    (r"\b(am\s+i\s+(?:overweight|underweight|healthy|obese|normal)|my\s+(?:bmi|weight|body\s+mass))\b", "body_metrics", 0.9),
    (r"\b(ideal\s+weight|how\s+(?:much\s+should|i\s+should)\s+(?:i\s+)?weigh|calories?\s+(?:burned?|burning?|do\s+i\s+burn))\b", "body_metrics", 0.9),
    (r"\bbody\s+(?:mass|metrics|fat|weight|index)\b", "body_metrics", 0.85),

    # Age Calculator
    (r"\b(how\s+old\s+(?:am\s+i|is\s+(?:he|she|they|it|my))|calculate\s+(?:my|his|her|their)\s+age)\b", "age_calc", 0.9),
    (r"\b(what\s+(?:is\s+)?(?:my|his|her|their)\s+zodiac|star\s+sign|horoscope)\b", "age_calc", 0.9),
    (r"\b(days?\s+between|date\s+(?:difference|diff)|how\s+many\s+days?\s+(?:until|between|from))\b", "age_calc", 0.9),
    (r"\b(next\s+birthday|add\s+\d+\s+days|subtract\s+\d+\s+days)\b", "age_calc", 0.9),
    (r"\bwhen\s+(?:is|was)\s+(?:my|his|her|their)\s+birthday\b", "age_calc", 0.85),

    # Image Generation
    (r"\b(draw|design|create|generate|make|produce)\s+(?:me\s+)?(?:an?\s+)?(?:image|picture|photo|pic|artwork|illustration|drawing)\b", "image_gen", 0.9),
    (r"\b(image|picture|photo|pic|artwork)\s+(?:of|showing|with|featuring|depicting)\b", "image_gen", 0.85),
    (r"\b(can\s+you\s+)?(?:draw|design|create|generate|make)\s+(?:me\s+)?(?:a\s+)?(?:picture|image|artwork)\b", "image_gen", 0.9),

    # Notification
    (r"\b(notify|alert|remind|ping|buzz|nudge)\s+me\s+(?:at|on|in|about|to|when|if)\b", "notification", 0.85),

    # Code Generation (generate/write code and save) - MUST come before research
    (r"\b(tell|give|show|write|generate|create|get|find|write)\s+(?:me\s+)?(?:a\s+)?(?:the\s+)?(?:an?\s+)?(?:python|java|javascript|js|c\+\+|cpp|html|css|sql|ruby|go|rust|swift|kotlin)\s+(?:code|script|program|implementation|algorithm|function|class)\b", "code_gen", 0.95),
    (r"\b(tell|give|show|write|generate|create|get|find)\s+(?:me\s+)?(?:a\s+)?(?:the\s+)?(?:binary\s+search|sorting|linked\s+list|tree|graph|queue|stack|hash\s+map|array|matrix|fibonacci|factorial|palindrome)\s+(?:code|script|program|implementation|algorithm|function|class)\b", "code_gen", 0.95),
    (r"\b(code|script|program|implementation)\s+(?:for|of|to)\s+(?:a\s+)?(?:binary\s+search|sorting|linked\s+list|tree|graph|queue|stack|hash\s+map|array|matrix)\b", "code_gen", 0.9),
    (r"\b(python|java|javascript|js|c\+\+|cpp|html|css|sql)\s+(?:code|script|program|implementation)\s+(?:for|of|to)\s+(?:a\s+)?\w+\b", "code_gen", 0.9),
    (r"\b(generate|write|create|get)\s+(?:me\s+)?(?:a\s+)?(?:full\s+)?(?:code|script|program)\s+(?:for|of|to)\s+(?:a\s+)?\w+\b", "code_gen", 0.85),

    # Research (search web and summarize) - MUST come before file_save
    (r"\b(what\s+is|what\s+are|how\s+(?:does|do|is|are|to|can)|why\s+(?:does|do|is|are|can)|where\s+(?:is|are|do|does)|when\s+(?:is|are|do|does)|who\s+(?:is|are|do|does))\s+.+\s+(?:and\s+)?(?:save|export|write)\b", "research", 0.9),
    (r"\b(research|look\s+up|find\s+out|google|search\s+(?:the\s+)?(?:web|internet|online|for))\s+.+\b", "research", 0.85),
    (r"\b(explain|describe|tell\s+me\s+about|what\s+(?:is|are|do|does|can|will|should))\s+.+\s+(?:and\s+)?(?:save|export|write)\b", "research", 0.9),

    # Automation
    (r"\b(schedule|automate|run\s+(?:daily|hourly|every)|set\s+automation|cron|repeat\s+(?:daily|hourly))\b", "automation", 0.9),
    (r"\b(list|show|remove|delete|cancel)\s+(?:my\s+)?(?:automations?|scheduled\s+(?:jobs?|tasks?))\b", "automation", 0.9),

    # File Save (save result/output to file)
    (r"\b(save\s+(?:the\s+)?(?:result|output|content|information|data|answer|response|explanation)\s+(?:to|in|into|on|at)\s+(?:a\s+)?(?:file\s+)?(?:in\s+)?(?:the\s+)?(?:downloads?|desktop|documents?|folder|path))\b", "file_save", 0.9),
    (r"\b(save\s+(?:it|this|that|the\s+answer|the\s+result)\s+(?:to|in|into)\s+(?:a\s+)?(?:file\s+)?(?:in\s+)?(?:the\s+)?(?:downloads?|desktop|documents?))\b", "file_save", 0.9),
    (r"\b(write\s+(?:the\s+)?(?:result|output|content|answer)\s+(?:to|into)\s+(?:a\s+)?file\s+(?:in\s+)?(?:the\s+)?(?:downloads?|desktop|documents?))\b", "file_save", 0.9),
    (r"\b(export\s+(?:the\s+)?(?:result|output|answer)\s+(?:to|as)\s+(?:a\s+)?(?:file\s+)?(?:in\s+)?(?:the\s+)?(?:downloads?|desktop|documents?))\b", "file_save", 0.9),
]


class IntentRouter:
    """Enhanced Intent Routing Engine with strict priority hierarchy and advanced DOM automation."""
    def __init__(self):
        # Intent map: (tag, triggers, priority)
        self.intents = [
            ("undo", [
                "undo", "revert", "mistake", "go back", "reverse", "cancel that",
                "undo that", "take it back", "nevermind", "never mind", "scratch that",
                "disregard", "ignore that", "my bad", "oops", "wrong"
            ], 0),

            ("voice_macro", [
                "start coding mode", "research mode", "start macro",
                "begin coding", "enter coding", "activate macro", "run macro"
            ], 1),
            ("daily_briefing", [
                "good morning flexie", "daily briefing", "whats on my agenda",
                "morning briefing", "system report", "good morning",
                "morning update", "today's plan", "what's on my schedule",
                "what do i have today", "start my day", "daily summary"
            ], 1),
            ("meeting_mode", [
                "start meeting mode", "meeting mode", "begin meeting mode",
                "stop meeting mode", "end meeting mode", "enter meeting",
                "join meeting", "meeting started", "in a meeting"
            ], 1),
            ("dictation_mode", [
                "start dictation", "begin dictation", "stop dictation",
                "end dictation", "dictation mode", "start typing",
                "begin typing", "transcribe", "speech to text"
            ], 1),
            ("take_note", [
                "take a note", "remember this", "save this idea", "make a note",
                "write this down", "note this", "jot down", "note to self",
                "save note", "create note", "add note"
            ], 1),
            ("memory_search", [
                "what did we discuss", "last project idea", "what did i save",
                "search memory", "find my notes", "what did i write",
                "recall note", "search notes"
            ], 1),

            ("exit", [
                "bye", "exit", "terminate", "quit", "shutdown flexie",
                "shutdown assistant", "stop assistant", "go to sleep",
                "close yourself", "deactivate", "goodbye", "bye flexie",
                "see you later", "see ya", "catch you later", "i'm done",
                "that's all", "we're done", "end session", "sign off",
                "log off", "power down", "shut down", "close flexie"
            ], 1),

            ("browser_control", [
                "click on", "click the", "fill field", "type in", "submit form",
                "press key", "scroll down", "scroll up", "scroll more", "click it",
                "fill my name", "type my email", "submit this", "capture page",
                "screenshot page", "screenshot website", "press enter", "hit enter",
                "scroll to top", "scroll to bottom", "select all", "copy text",
                "paste here", "click submit", "press tab", "click that button"
            ], 2),

            ("browser_tabs", [
                "new tab", "switch tab", "close tab", "list tabs", "show tabs",
                "open a new tab", "go to tab", "close this tab", "tab one",
                "tab two", "tab three", "next tab", "previous tab", "switch to tab",
                "open new tab", "create tab", "which tab", "tab count"
            ], 2),

            ("browser_extract", [
                "extract text", "extract data", "summarize page", "read table",
                "get links", "extract table", "scrape page", "summarize this page",
                "get all links", "copy page text", "get page content",
                "what's on this page", "read this page"
            ], 2),

            ("play_youtube", [
                "play on youtube", "play song on youtube", "play music on youtube",
                "play some", "play the song", "play video", "play music",
                "play a song", "start playing", "on youtube play", "play it again",
                "put on some music", "play some tunes", "play something",
                "let's listen to", "can you play", "i want to hear",
                "play a video", "play that song", "resume playing",
                "start the music", "queue up", "put on"
            ], 3),

            ("gmail", [
                "check gmail", "read emails", "unread mail", "open inbox",
                "draft email", "check my mail", "any new emails",
                "do i have mail", "email inbox", "check inbox",
                "read my emails", "new messages", "email notifications"
            ]),
            ("github", [
                "github repo", "clone repo", "analyze repo", "github status",
                "check github", "github notifications", "pull requests",
                "github issues", "open github"
            ]),

            ("mode", [
                "set mode", "switch mode", "change mode", "change the mode",
                "mode to", "developer mode", "study mode", "professional mode",
                "hacker mode", "minimal mode", "focus mode", "alert mode",
                "hackathon mode", "enter mode", "activate mode",
                "go professional", "go minimal", "go focus"
            ], 3),

            ("power", [
                "shutdown", "restart", "sleep", "lock", "shutdown pc",
                "restart pc", "lock screen", "reboot", "power off",
                "hibernate", "restart computer", "lock laptop", "log off",
                "turn off", "turn device off", "turn my device off",
                "turn off pc", "turn pc off", "turn off computer",
                "shut down the pc", "restart my computer", "put to sleep",
                "lock my screen", "log out", "sign out"
            ], 4),

            ("browser_navigate", [
                "open website", "go to website", "navigate to", "open url",
                "visit page", "open it again", "refresh page", "open site",
                "go to site", "browse to", "load website", "go to page",
                "open that link", "navigate to page"
            ], 5),

            ("youtube", [
                "youtube", "search youtube", "open youtube", "search on youtube",
                "watch on youtube", "on youtube", "youtube channel",
                "skip ad", "skip the ad", "skip the add",
                "next video", "next song", "skip song", "skip video",
                "pause video", "resume video", "video info",
                "fullscreen", "show full screen", "show in full screen",
                "mute video", "unmute video", "volume up", "volume down",
                "slow down video", "speed up video", "enable captions",
                "turn on subtitles", "video settings", "video quality"
            ], 4),

            ("browser_search", [
                "in chrome", "in firefox", "in edge", "using browser",
                "with chrome", "open in chrome", "open in firefox",
                "on chrome", "on edge", "search in browser",
                "look up in browser", "browse for"
            ], 6),

            ("multi_tab_research", [
                "research", "compare", "research latest", "look into",
                "investigate", "deep dive", "explore topic"
            ], 6),

            ("remind_me", [
                "remind me", "remind me to", "reminder me", "reminder me to",
                "set a reminder", "set reminder", "set an alarm",
                "remember to", "schedule a reminder", "reminder for",
                "don't let me forget", "make sure i remember",
                "i need to remember", "remind me about",
                "can you remind me", "put in my calendar"
            ], 3),

            ("list_reminders", [
                "list reminders", "list my reminders", "show reminders",
                "show reminder", "display reminders", "what reminders",
                "pending reminders", "list reminder", "what are my reminders",
                "do i have reminders", "any reminders", "reminder list",
                "show my reminders", "reminders pending"
            ], 3),

            ("media", [
                "volume", "sound", "mute", "unmute", "brightness", "dim",
                "light up", "spotify", "vlc", "louder", "quieter",
                "stop music", "pause music", "resume music",
                "volume up", "volume down", "turn volume", "turn up",
                "turn down", "mute it", "unmute it", "brighten",
                "dim the screen", "increase brightness", "decrease brightness",
                "max volume", "min volume"
            ], 7),

            ("app_op", [
                "open", "launch", "run", "start", "close", "stop", "kill app",
                "terminate app", "end process", "start application",
                "cloe", "opn", "strt", "lunch", "open up", "fire up",
                "boot up", "spin up", "shut app", "close that", "kill that"
            ], 8),

            ("vision_analyze", [
                "analyze screen", "analyze my screen", "analyse screen",
                "analyse my screen", "describe screen", "what is on my screen",
                "look at this", "what do you see", "what's on screen",
                "screen analysis", "analyze this", "describe what you see"
            ], 9),
            ("vision_debug", [
                "debug my code", "debug screen", "fix my error",
                "why is this failing", "debug this", "what's wrong",
                "find the bug", "error here", "fix this code",
                "what's the issue", "why isn't this working"
            ], 9),
            ("vision_read", [
                "read screen", "ocr", "read text", "grab text",
                "extract text from screen", "what does screen say",
                "read what's on screen", "copy text from screen"
            ], 9),
            ("vision_capture", [
                "screenshot", "capture screen", "take a snap", "snapshot",
                "take a picture of screen", "capture this", "take screenshot",
                "screen capture", "grab screen", "snap the screen"
            ], 9),
            ("camera_capture", [
                "take a picture", "take a pic", "take photo", "take a photo",
                "capture image", "capture photo", "snap photo", "open camera",
                "start camera", "camera on", "take selfie"
            ], 9),
            ("vision_show", [
                "show screenshot", "open screenshot", "view last screen",
                "show it", "show that", "show last capture", "open last snap",
                "view screenshot", "show me the screenshot"
            ], 9),
            ("vision_manage", [
                "delete screenshot", "remove snap", "screenshot folder",
                "open captures", "screenshot gallery", "all screenshots",
                "manage screenshots", "screenshot history"
            ], 9),

            ("dev_explain", [
                "what is this folder", "summarize files", "project overview",
                "what's in this directory", "explain this folder",
                "folder contents", "directory listing"
            ], 9),
            ("repo_analyzer", [
                "analyze this repository", "explain this codebase",
                "show architecture of this project", "analyze repo",
                "repo analysis", "codebase overview", "project structure"
            ], 9),
            ("project_explainer", [
                "explain this project", "teach me this codebase",
                "how does this system work", "explain project",
                "what does this project do", "project explanation"
            ], 9),
            ("bug_hunter", [
                "find bugs", "audit this repository", "find dead code",
                "audit codebase", "code review", "find issues",
                "security audit", "find vulnerabilities"
            ], 9),
            ("test_generator", [
                "generate tests", "create unit tests", "create integration tests",
                "write tests", "add tests", "test coverage",
                "generate test cases", "write unit tests"
            ], 9),
            ("sdd_build", [
                "build a", "build an", "build me a", "create a", "create an",
                "create me a", "code a", "write an app", "build app",
                "create project", "build project", "scaffold", "scaffold a"
            ], 9),

            ("file_rename", [
                "rename", "rename folder", "rename file", "change name of",
                "change the name of", "rname", "rename this", "rename that",
                "what should i call this", "give it a new name"
            ], 10),
            ("file_delete", [
                "delete file", "delete folder", "remove file", "remove folder",
                "erase file", "erase folder", "delte", "delete this",
                "remove this", "trash it", "bin it", "get rid of"
            ], 10),
            ("file_save", [
                "save file", "save this as", "create a file", "write a file",
                "save my note", "create document", "pate a document",
                "paste document", "create a doc", "write document",
                "save as", "export as", "save to file", "write to file",
                "create new file", "save this document",
                "save result", "save the result", "save the output",
                "save to downloads", "save to desktop", "save to documents",
                "write result to file", "export to file",
            ], 10),

            ("file_op", [
                "organize desktop", "create folder", "find file", "move file",
                "folder open", "clean desktop", "desktop files", "new folder",
                "create a folder", "make a folder", "make new folder",
                "create directory", "organize files", "sort files",
                "find folder", "open folder", "list files"
            ], 2),

            ("knowledge_search", [
                "search my files", "find in my documents", "what do my notes say",
                "search for in files", "search indexing", "recent documents",
                "search my computer", "find document", "look for file",
                "search downloads", "search desktop"
            ], 11),

            ("intel", [
                "what should i do", "any suggestions", "suggest me something",
                "what features am i missing", "how can you help me",
                "proactive mode", "what can you do", "help me out",
                "what do you recommend", "any ideas", "give me ideas"
            ], 3),
            ("briefing", [
                "daily briefing", "morning brief", "what's my day look like",
                "tell me the news", "what's the weather", "give me a briefing",
                "day overview", "today's briefing", "morning update"
            ], 3),
            ("clipboard", [
                "analyze my clipboard", "what's in my clipboard",
                "summarize my clipboard", "explain this text",
                "explain my clipboard", "clipboard content",
                "what did i copy", "analyze clipboard"
            ], 3),

            ("auto_save", [
                "start auto save", "stop auto save", "enable auto save",
                "disable auto save", "automatic save", "toggle auto save",
                "auto save on", "auto save off"
            ], 5),
            ("save_active", [
                "save this file", "save current file", "save my work",
                "save this doc", "save the document", "control s",
                "save now", "save changes"
            ], 5),

            ("dev_build", [
                "create a project", "build a project", "start a new project",
                "generate code for", "code a project for", "autonomous build",
                "build a website", "create a website", "build an app",
                "create an app", "build a basic", "scaffold project",
                "new project", "start project"
            ], 10),
            ("dev", [
                "git status", "git diff", "git commit", "run python",
                "execute script", "terminal execute", "analyze traceback",
                "run terminal", "git push", "git pull", "git add",
                "run command", "execute command"
            ], 12),

            ("comm", [
                "email", "whatsapp", "message", "send mail", "compose",
                "inbox", "check mail", "send message", "text someone",
                "reply to email", "forward email"
            ], 13),

            ("voice", [
                "speak faster", "speak shower", "talking speed", "voice rate",
                "talk faster", "talk slower", "voice test", "test voice",
                "can you hear me", "change voice", "voice settings",
                "speak louder", "speak softer", "slow down", "speed up"
            ], 15),

            ("social", [
                "hello", "hi", "hey flexie", "how are you", "good morning",
                "thanks", "thank you", "good night", "what's up",
                "hey there", "are you there", "how's it going",
                "nice to meet you", "long time no see", "howdy",
                "greetings", "welcome", "cheers", "appreciate it",
                "no problem", "you're welcome", "good afternoon",
                "good evening", "sup", "yo", "hola", "namaste"
            ], 16),

            ("search", [
                "search for", "search", "google", "find out", "wikipedia",
                "define", "who is", "what is", "where is", "lyrics for",
                "price of", "leetcode", "lead code", "leet code", "cheat code",
                "earch for", "arch for", "find info on", "tell me about",
                "what's a", "search on chrome", "search in chrome",
                "google search", "earch", "arch", "look up", "look into",
                "find me", "help me find", "what do you know about",
                "explain", "how does", "how do", "what causes",
                "why does", "tell me more about", "give me info on",
                "information about", "details about", "research"
            ], 2),

            ("calc", [
                "calculate", "plus", "minus", "divided by", "times",
                "math problem", "what is", "what's", "compute",
                "do the math", "figure out", "solve", "add",
                "subtract", "multiply", "divide", "percentage",
                "what's the total", "how much is", "math"
            ], 18),

            ("convert", [
                "convert", "conversion", "how many miles", "how many kilometers",
                "how many pounds", "how many kilograms", "dollars to",
                "rupees to", "euros to", "miles to", "kilometers to",
                "inches to", "centimeters to", "pounds to", "kilograms to",
                "celsius to", "fahrenheit to", "change units",
                "unit conversion", "what is in", "equivalent to",
                "how much is in", "swap units", "rate"
            ], 13),

            ("translate", [
                "translate", "translation", "translate this to", "say it in",
                "in spanish", "in french", "in hindi", "in german",
                "in japanese", "in chinese", "in korean", "in arabic",
                "in portuguese", "in italian", "in russian",
                "what is in spanish", "how do you say", "translate to"
            ], 14),

            ("status", [
                "battery", "cpu", "ram", "memory usage", "system status",
                "pc status", "laptop status", "performance", "system health",
                "how's my pc", "system info", "computer status",
                "resource usage", "disk space", "storage"
            ], 16),

            ("memory", [
                "remember", "forget", "recall", "save this", "what did i say",
                "what do you know", "keep in mind", "list memory", "what did i save",
                "save to memory", "store this", "memorize"
            ], 11),

            ("weather", [
                "weather", "temperature", "forecast", "is it raining",
                "will it rain", "how hot", "how cold", "humidity",
                "wind speed", "weather today", "weather tomorrow",
                "weather forecast", "climate", "is it cold outside",
                "is it hot outside", "should i bring umbrella",
                "what's the temp", "how's the weather",
                "what's it like outside", "weather in",
                "what's the forecast", "is it going to rain",
                "sunrise", "sunset", "uv index", "air quality"
            ], 7),

            ("image_gen", [
                "generate image", "create image", "make image", "draw",
                "design image", "create picture", "generate picture",
                "make picture", "draw image", "produce image",
                "show me image", "create artwork", "generate artwork",
                "draw me", "create a drawing", "make an illustration",
                "design a logo", "generate a photo", "create a graphic",
                "visualize", "picture of", "image of", "show me a picture",
                "create visual", "generate visual"
            ], 8),

            ("news", [
                "news", "headlines", "what's happening", "current events",
                "today news", "tech news", "sports news", "world news",
                "breaking news", "what's new", "news today", "latest news",
                "news summary", "any news", "what's going on in the world",
                "news around the world", "today's headlines",
                "top stories", "news brief", "daily news",
                "give me the news", "catch me up", "what happened today"
            ], 8),

            ("alarm", [
                "set alarm", "alarm for", "wake me", "set timer",
                "timer for", "countdown", "count down", "timer", "alarm",
                "wake me up", "remind me in", "set reminder for",
                "how long until", "start timer", "stop timer",
                "cancel timer", "how much time left", "time remaining",
                "set a countdown", "5 minute timer", "10 minute timer",
                "half hour timer", "hour timer"
            ], 10),

            ("pdf", [
                "read pdf", "open pdf", "summarize pdf", "analyze pdf",
                "extract pdf", "pdf file", "read document", "summarize document",
                "what does this pdf say", "pdf content", "scan pdf",
                "review pdf", "pdf summary", "get pdf text",
                "extract text from pdf", "pdf reader", "open document"
            ], 9),

            ("clipboard_mgr", [
                "clipboard history", "show clipboard", "what did i copy",
                "copy to clipboard", "paste from clipboard", "search clipboard",
                "clear clipboard", "clip history", "clipboard search",
                "clipboard contents", "what's in clipboard",
                "recent copies", "paste last", "copy that",
                "copy this", "clipboard manager"
            ], 5),

            ("local_code_search", [
                "search my code", "search the code", "search code", "find in code",
                "search project", "find in project", "code search", "local code search",
                "find function", "find class", "grep for", "search codebase",
                "find in my project", "search my project", "search this project",
                "find implementation", "search for function", "search for class",
            ], 4),

            ("summarize", [
                "summarize", "summary", "summarize file", "summarize document",
                "summarize url", "summarize page", "summarize article",
                "brief summary", "give me summary", "what does this say",
                "tldr", "tl;dr", "short version", "brief overview",
                "quick summary", "condense", "shorten", "abbreviate",
                "give me the gist", "what's this about", "run down"
            ], 6),

            ("awareness", [
                "who are you", "tell me about yourself", "what are you",
                "your name", "your stats", "your statistics", "how you doing",
                "your personality", "what are you like", "describe yourself",
                "what do you know", "what have you learned", "your knowledge",
                "what can you do", "introduce yourself", "tell me about flexie",
                "your capabilities", "what are your skills",
                "how do you work", "what makes you tick"
            ], 3),

            ("memory_system", [
                "remember that", "remember this", "keep in mind", "don't forget",
                "what do you remember", "what have you learned", "recall",
                "memory stats", "memory status", "how much do you remember",
                "recent conversations", "what did we talk about",
                "conversation history", "search memory", "popular topics",
                "what topics", "most discussed", "what have we discussed",
                "our chat history", "what did you learn about me",
                "tell me what you know", "your memory"
            ], 3),

            ("notification", [
                "notify me", "set notification", "set a notification",
                "notification for", "alert me", "set alert",
                "remind me at", "remind me on", "send notification",
                "give me a notification", "ping me", "buzz me",
                "nudge me", "heads up", "give me a heads up",
                "alert me when", "notify when", "let me know"
            ], 4),

            ("wiki", [
                "wiki", "wikipedia", "search wiki", "look up wiki",
                "wiki search", "wiki lookup", "search on wikipedia",
                "wikipedia article", "wiki page", "wikipedia page",
                "what does wikipedia say", "according to wikipedia",
                "wiki summary", "read wiki"
            ], 6),

            ("jokes", [
                "joke", "jokes", "tell me a joke", "make me laugh",
                "say something funny", "funny", "humor", "comedy",
                "programming joke", "dad joke", "pun", "tell me something funny",
                "i'm bored", "cheer me up", "make me smile", "be funny",
                "got any jokes", "say a joke", "another joke", "one more joke",
                "what's funny", "make me giggle", "crack a joke",
                "tell a joke", "joke of the day", "funny joke"
            ], 5),

            ("quotes", [
                "quote", "quotes", "motivational quote", "inspire me",
                "inspirational quote", "quote of the day", "saying",
                "motivate me", "wisdom", "inspiration",
                "give me a quote", "quote me something", "what's a good quote",
                "words of wisdom", "inspire", "encourage me",
                "pick me up", "uplifting quote", "daily quote",
                "life quote", "philosophy", "proverb"
            ], 5),

            ("password", [
                "generate password", "create password", "new password",
                "random password", "password generator", "make password",
                "strong password", "secure password", "password strength",
                "check password", "passphrase", "generate a password",
                "i need a password", "make me a password",
                "create a new password", "password please",
                "secure passphrase", "generate passphrase",
                "how strong is my password", "is my password secure",
                "password checker", "strength check"
            ], 4),

            ("qr_code", [
                "qr code", "qrcode", "generate qr", "create qr",
                "make qr", "scan qr", "qr generate", "qr for",
                "qr code for", "generate a qr code", "create a qr code",
                "make a qr code", "i need a qr code", "qr please",
                "encode as qr", "qr with", "qr of"
            ], 5),

            ("dictionary", [
                "define", "definition", "meaning of", "what does mean",
                "dictionary", "lookup word", "synonym", "antonym",
                "spell", "how do you spell", "word meaning",
                "what does this word mean", "lookup", "define this word",
                "what is the definition", "synonyms for", "antonyms for",
                "opposite of", "similar to", "spelling of",
                "how to spell", "pronunciation", "part of speech"
            ], 5),

            ("facts", [
                "fact", "facts", "random fact", "tell me a fact",
                "fun fact", "did you know", "interesting fact",
                "learn something", "fact of the day", "trivia",
                "tell me something interesting", "give me a fact",
                "i'm curious", "blow my mind", "surprise me",
                "tell me something new", "did you know that",
                "what's an interesting fact", "random knowledge",
                "obscure fact", "cool fact"
            ], 5),

            ("pomodoro", [
                "pomodoro", "focus timer", "start focus", "focus session",
                "work timer", "break timer", "pomodoro timer",
                "start pomodoro", "stop pomodoro", "pomodoro status",
                "start working", "focus mode timer", "productivity timer",
                "25 minute timer", "work break", "time to focus",
                "start a pomodoro", "begin focus session",
                "how many sessions", "pomodoro count", "break time"
            ], 4),

            ("ip_lookup", [
                "ip lookup", "ip address", "my ip", "public ip",
                "what is my ip", "whats my ip", "ip info", "lookup ip",
                "ip of", "find ip", "what's my public ip",
                "what's my ip address", "check my ip", "ip details",
                "where am i", "my network info", "ip location",
                "lookup ip address", "check ip", "find ip address"
            ], 5),

            ("text_tools", [
                "word count", "character count", "count words", "count chars",
                "reverse text", "uppercase", "lowercase", "title case",
                "sentence case", "snake case", "camel case", "kebab case",
                "remove duplicates", "sort lines", "slugify", "wrap text",
                "extract emails", "extract urls", "extract numbers",
                "text tools", "text utility", "text tools",
                "make uppercase", "make lowercase", "all caps",
                "count characters", "how many words", "how many characters",
                "text processor", "string tools", "text manipulation",
                "convert to uppercase", "convert to lowercase",
                "sort text", "wrap lines", "text editor"
            ], 6),

            ("hash_encoder", [
                "md5", "sha1", "sha256", "sha512", "hash",
                "base64 encode", "base64 decode", "hex encode", "hex decode",
                "binary encode", "binary decode", "morse encode",
                "encode text", "decode text", "encoder", "decoder",
                "hash this", "hash it", "md5 hash", "sha hash",
                "base64", "hex", "binary code", "morse code",
                "encoding", "decoding", "encode that", "decode that",
                "cryptographic hash", "checksum", "digest"
            ], 6),

            ("json_fmt", [
                "format json", "pretty json", "json format", "json pretty",
                "minify json", "json minify", "validate json", "json validate",
                "json info", "json keys", "flatten json", "json tools",
                "beautify json", "prettify json", "json beautifier",
                "check json", "lint json", "json lint", "parse json",
                "json parser", "json formatter", "format this json",
                "json pretty print", "json minifier"
            ], 6),

            ("color_info", [
                "color", "colour", "color info", "colour info",
                "color lookup", "hex to", "random color", "complementary color",
                "color of", "what color", "color meaning",
                "colour info", "colour lookup", "what colour",
                "color name", "hex code", "rgb value", "color palette",
                "color scheme", "what's the hex", "convert color",
                "color code", "html color", "css color"
            ], 7),

            ("lorem", [
                "lorem ipsum", "lorem", "generate text", "placeholder text",
                "dummy text", "sample text", "fake text", "lorem generator",
                "need some text", "filler text", "lorem text",
                "generate placeholder", "give me some text",
                "i need dummy text", "lorem for me", "text filler",
                "generate lorem", "lorem paragraphs"
            ], 7),

            ("uuid", [
                "uuid", "generate uuid", "new uuid", "uuid v4", "uuid v1",
                "uuid generator", "batch uuid", "check uuid", "validate uuid",
                "uuid valid", "uuid timestamp", "create uuid",
                "i need a uuid", "generate a uuid", "new unique id",
                "unique identifier", "uuid please", "uuids",
                "batch of uuids", "uuid v5"
            ], 6),

            ("tip_calc", [
                "tip", "tip calculator", "calculate tip", "bill split",
                "split bill", "how much tip", "tip on", "split check",
                "calculate gratuity", "gratuity calculator",
                "how much should i tip", "what tip should i leave",
                "split the check", "split the tab", "divide the bill",
                "tip percentage", "bill calculator", "restaurant bill",
                "how much per person", "even split"
            ], 6),

            ("body_metrics", [
                "bmi", "calculate bmi", "body mass index", "bmr",
                "metabolic rate", "ideal weight", "calories burned",
                "calorie calculator", "body fat", "body metrics",
                "what's my bmi", "am i overweight", "am i underweight",
                "how many calories", "how many calories do i burn",
                "calories burned while", "my ideal weight",
                "basal metabolic rate", "calculate calories",
                "weight calculator", "health metrics"
            ], 6),

            ("age_calc", [
                "age", "calculate age", "how old", "age calculator",
                "days between", "date difference", "next birthday",
                "zodiac", "star sign", "horoscope", "add days", "subtract days",
                "how old am i", "how old is", "what's my age",
                "calculate the age", "age difference",
                "how many days until", "when is my birthday",
                "what's my zodiac sign", "what's my star sign",
                "date calculator", "days until birthday",
                "how many days since",                 "time between dates"
            ], 6),

            ("code_gen", [
                "generate code", "write code", "create code", "get code",
                "python code", "java code", "javascript code", "html code",
                "binary search code", "sorting code", "fibonacci code",
                "write a program", "create a program", "generate a program",
                "code for", "program for", "implementation of",
                "algorithm code", "function code", "class code",
                "write script", "create script", "generate script",
                "python script", "java script", "code generator",
            ], 8),

            ("research", [
                "research", "look up", "find out", "google", "search the web",
                "search online", "search the internet", "research this",
                "look up information", "find information about", "research about",
                "search for information", "what is", "tell me about",
                "explain", "how does", "why does", "what causes",
                "what are the benefits", "what are the differences",
            ], 7),

            ("automation", [
                "schedule", "automate", "every day", "every hour", "daily at",
                "run daily", "run hourly", "cron", "repeat", "scheduled job",
                "list automations", "show automations", "remove automation",
                "cancel automation", "automation",
            ], 6),

            ("file_save", [
                "save file", "save this as", "create a file", "write a file",
                "save my note", "create document", "pate a document",
                "paste document", "create a doc", "write document",
                "save as", "export as", "save to file", "write to file",
                "create new file", "save this document",
                "save result", "save the result", "save the output",
                "save to downloads", "save to desktop", "save to documents",
                "write result to file", "export to file",
            ], 10),
        ]

        # Precompile every trigger regex once so the hot routing path never
        # recompiles patterns. List of (intent, [(compiled_pattern, raw_trigger)], priority)
        self._compiled: list[tuple[str, list, int]] = []
        for intent_data in self.intents:
            intent, triggers = intent_data[0], intent_data[1]
            priority = intent_data[2] if len(intent_data) > 2 else 99
            compiled_triggers = [
                (re.compile(r"\b" + re.escape(t) + r"\b", re.IGNORECASE), t)
                for t in triggers
            ]
            self._compiled.append((intent, compiled_triggers, priority))

    def route_dynamic(self, command: str, brain_instance, context: str = "") -> tuple[str, float, dict]:
        """Agentic routing using LLM with short-term context awareness."""
        prompt = f"""
        Recent Conversation Context:
        {context}

        Analyze the following user command for a desktop AI assistant named Flexie.
        User Command: "{command}"

        Available Intents:
        - file_save (creating files/scripts)
        - file_op (folder creation, organization)
        - app_op (launching apps)
        - browser_navigate (opening websites)
        - play_youtube (playing music/videos)
        - knowledge_search (searching local files/notes)
        - search (web search)
        - conversational (general chat)
        - complex (multi-step tasks)

        Return a JSON object:
        {{
            "intent": "str",
            "confidence": float (0.0 to 1.0),
            "params": {{ "target": "str", "action": "str", "query": "str" }},
            "steps": ["step1", "step2"] (only for complex intent),
            "topic": "str (current conversation topic)",
            "goal": "str (high-level active goal)"
        }}

        IMPORTANT FOR COMPLEX/COMPOUND COMMANDS:
        If the user command contains multiple actions connected by 'and' or 'then', classify intent as "complex" and generate sequential steps.
        Decompose compound tasks into concise, single-action steps. Each step should be ONE clear action.
        Example: "search for photosynthesis and open a document and write the result"
        Should yield:
        "steps": [
            "search for photosynthesis",
            "create a document named photosynthesis",
            "paste the response"
        ]
        
        CRITICAL RULES FOR STEPS:
        - Each step must be a SINGLE action (one verb, one target)
        - Steps should be SHORT and specific (under 10 words each)
        - Break complex actions into separate steps
        - Example: "search alesa and save result as document" should be:
          ["search for alesa", "save the search result as a document in Downloads"]
        - NEVER combine multiple actions into one step
        """
        try:
            res_raw = brain_instance.ask(prompt, system_override="You are a tool router. Return ONLY valid JSON.")
            # Simple JSON extraction
            import json
            json_str = re.search(r'\{.*\}', res_raw, re.DOTALL).group()
            data = json.loads(json_str)
            merged_params = data.get("params", {})
            if "steps" in data:
                merged_params["steps"] = data["steps"]
            if "topic" in data:
                merged_params["topic"] = data["topic"]
            if "goal" in data:
                merged_params["goal"] = data["goal"]
            return data.get("intent", "conversational"), data.get("confidence", 0.0), merged_params
        except Exception:
            return "conversational", 0.0, {}

    def route(self, command: str) -> tuple[str, float]:
        # Keep existing fast regex route as the 'First Tier' (Latency optimization)
        cmd = command.lower().strip()
        if not cmd:
            return "conversational", 0.0

        # 0. TYPO CORRECTION: Fix common voice/typing errors
        words = cmd.split()
        corrected = []
        for w in words:
            if w in TYPO_MAP:
                corrected.append(TYPO_MAP[w])
            else:
                close = get_close_matches(w, TYPO_MAP.keys(), n=1, cutoff=0.85)
                if close:
                    corrected.append(TYPO_MAP[close[0]])
                else:
                    corrected.append(w)
        cmd = " ".join(corrected)

        # 0.1. NATURAL LANGUAGE OVERRIDES: Regex patterns for conversational phrasing
        for pattern, intent, confidence in NL_OVERRIDES:
            if re.search(pattern, cmd, re.IGNORECASE):
                return intent, confidence

        # 0.5. PERSONAL QUERY OVERRIDE: "tell me about X" should be conversational, not web search
        if cmd.startswith("tell me about") or cmd.startswith("who is") or cmd.startswith("what do you know about"):
            return "conversational", 0.9

        # 1. IMMEDIATE OVERRIDES
        if any(x in cmd for x in ["leetcode", "lead code", "leet code", "cheat code"]):
            return "search", 0.99

        # 1.25. LOCAL FILE SEARCH OVERRIDE
        if any(x in cmd for x in [
            "search my files", "search for in files", "search indexing",
            "recent documents", "what do my notes say", "find in my documents",
        ]):
            return "knowledge_search", 0.9

        # 1.5. SPECIAL CASE: WEB DEVELOPMENT
        if any(x in cmd for x in ["build", "create", "make", "generate", "code", "develop"]) and any(y in cmd for y in ["website", "app", "project", "portfolio"]):
            return "dev_build", 0.95

        # 1.55. SPECIAL CASE: MATH
        if any(x in cmd for x in ["plus", "minus", "times", "divided by", "multiplied by", "calculate", "math problem"]) and any(ch.isdigit() for ch in cmd):
            return "calc", 0.95

        # 2. SPECIAL CASE: FILE CREATION VS SEARCH
        if any(x in cmd for x in ["create", "make", "pate", "paste", "write", "generate", "maek", "writ"]) and any(y in cmd for y in ["folder", "directory", "file system", "document", "code", "script", "py", "file", "flder", "fldr"]):
            if any(x in cmd for x in ["folder", "directory", "file system", "flder", "fldr"]):
                return "file_op", 0.95
            return "file_save", 0.95

        # 3. SPECIAL CASE: MUSIC/SONGS
        yt_control_kw = ["full screen", "fullscreen", "next", "skip", "previous", "pause", "resume", "stop", "volume", "speed", "captions", "subtitle", "forward", "backward", "rewind", "show"]
        is_yt_control = any(y in cmd for y in yt_control_kw)
        if any(x in cmd for x in ["song", "music", "play "]) and not cmd.startswith("paste") and not is_yt_control:
            if any(x in cmd for x in ["volume", "sound", "spotify", "vlc", "mute"]):
                return "media", 0.9
            return "play_youtube", 0.85

        # 4. RULE: APP RECOGNITION
        launch_verbs = {"open", "launch", "run", "start", "close", "stop", "kill", "opn", "strt"}
        words = cmd.split()
        if len(words) <= 2:
            app_words = [w for w in words if w in Config.APPS]
            if app_words:
                non_app = [w for w in words if w not in Config.APPS]
                if not non_app or set(non_app) <= launch_verbs:
                    return "app_op", 1.0

        # 5. ROUTING BY PRIORITY
        sorted_intents = sorted(self._compiled, key=lambda x: x[2])
        matches = []
        for intent, compiled_triggers, priority in sorted_intents:
            for pattern, trigger in compiled_triggers:
                if pattern.search(cmd):
                    score = 0.8
                    if cmd == trigger:
                        score = 1.0
                    elif cmd.startswith(trigger):
                        score = 0.95
                    matches.append((intent, score, priority))
                    if priority <= 2 and score >= 0.9:
                        return intent, score

        if matches:
            matches.sort(key=lambda x: (x[2], -x[1]))
            return matches[0][0], matches[0][1]

        return "conversational", 0.0
