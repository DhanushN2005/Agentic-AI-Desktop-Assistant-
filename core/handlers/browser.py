import re


def handle_browser_navigate(orch, c):
    url = re.sub(r"\b(open website|go to|navigate to|open url|visit|open it again)\b", "", c).strip()
    orch.speak(f"Navigating to {url}...")
    res = orch.browser.navigate(url)
    orch.ctx.update(url=url)
    orch.speak(res)
    return True


def handle_browser_control(orch, c):
    if "click" in c:
        target = re.sub(r"(click on|click the|click)", "", c).strip()
        orch.ctx.update(selector=target)

        # SAFETY CHECK
        if orch.browser.is_risky(target):
            orch.browser.highlight_element(target)
            if not orch.voice.confirm(f"Dhanush, clicking '{target}' might be a sensitive action. Are you sure you want me to proceed?"):
                orch.speak("Action cancelled for security.")
                return True

        orch.speak(orch.browser.click_element(target))
    elif "fill" in c or "type" in c:
        cmd_parts = re.split(r" with | as ", c)
        val = cmd_parts[1] if len(cmd_parts) > 1 else "data"
        target = re.sub(r"(fill field|fill|type in|type)", "", cmd_parts[0]).strip()
        orch.speak(orch.browser.fill_field(target, val))
    elif "scroll" in c:
        direction = "up" if "up" in c else "down"
        orch.speak(orch.browser.scroll(direction))
    elif "capture" in c or "screenshot" in c:
        orch.speak(orch.browser.capture_page())
    return True


def handle_browser_tabs(orch, c):
    if "new" in c:
        url = re.sub(r"(open a new tab|new tab|open new tab)", "", c).strip()
        if not url:
            url = "https://www.google.com"
        orch.speak(orch.browser.new_tab(url))
    elif "close" in c:
        orch.speak(orch.browser.close_current_tab())
    elif "switch" in c or "go to" in c or "index" in c or "tab" in c:
        # Try to find a number in the command
        match = re.search(r"\d+", c)
        if match:
            idx = int(match.group())
            orch.speak(orch.browser.switch_tab(idx))
        else:
            orch.speak(orch.browser.list_tabs())
    elif "list" in c or "show" in c:
        orch.speak(orch.browser.list_tabs())
    return True


def handle_browser_extract(orch, c):
    if "summarize" in c:
        res = orch.browser.get_summary(orch.brain)
    elif "links" in c:
        res = "Found links: " + orch.browser.extract_page_data("links")
    else:
        res = orch.browser.extract_page_data("text")
    orch.ctx.update(last_response=res)
    orch.speak(res)
    return True


def handle_gmail(orch):
    orch.speak("Checking your Gmail inbox...")
    # Try EmailEngine first (direct IMAP)
    try:
        emails = orch.email.get_unread_emails(count=5)
        if emails and "credentials are missing" not in emails[0].lower() and "could not" not in emails[0].lower():
            for e in emails:
                orch.speak(e)
            orch.ctx.update(last_response="\n".join(emails))
            return True
    except Exception as e:
        orch.logger.warning(f"EmailEngine failed: {e}")
    # Fallback to browser automation
    orch.speak(orch.browser.gmail_read_unread())
    return True
