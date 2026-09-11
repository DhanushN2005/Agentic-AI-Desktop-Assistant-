import os
import re
import time

from engines.system import SystemCtrl


def handle_paste_context_response(orch):
    response_text = orch.ctx.last_response
    if not response_text:
        orch.speak("I don't have any previous answer stored in this session to paste.")
        return True

    orch.speak("Pasting the answer.")

    # 1. Verified Editor Focus
    try:
        import pygetwindow as gw
        active_win = gw.getActiveWindow()

        target_win = None
        active_doc_name = orch.ctx.active_document
        if active_doc_name:
            base_doc_name = os.path.basename(active_doc_name)
            wins = gw.getWindowsWithTitle(base_doc_name)
            if wins:
                target_win = wins[0]

        if not target_win:
            wins = gw.getWindowsWithTitle("Notepad") or gw.getWindowsWithTitle("Document") or gw.getWindowsWithTitle("txt") or gw.getWindowsWithTitle("Editor")
            if wins:
                target_win = wins[0]

        if target_win:
            target_win.activate()
            time.sleep(0.4)
        elif active_win:
            active_win.activate()
            time.sleep(0.3)
    except Exception as fe:
        orch.logger.warning(f"Editor focus failure: {fe}")

    # 2. Clipboard Validation Loop
    import pyautogui
    import pyperclip

    clip_ok = False
    for attempt in range(3):
        try:
            pyperclip.copy(response_text)
            time.sleep(0.2)
            if pyperclip.paste() == response_text:
                clip_ok = True
                break
        except Exception as ce:
            orch.logger.warning(f"Clipboard copy attempt {attempt} failed: {ce}")
            time.sleep(0.1)

    if clip_ok:
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.3)
        orch.speak("Pasted successfully.")
    else:
        orch.logger.warning("Clipboard verification failed completely. Reverting to physical typing fallback.")
        orch.speak("Clipboard paste failed. Typing response out for you.")
        pyautogui.typewrite(response_text[:500])
        if len(response_text) > 500:
            pyautogui.typewrite("\n[Text truncated due to length limits]")
        orch.speak("Completed typing fallback.")
    return True


def handle_copy_context_response(orch):
    response_text = orch.ctx.last_response
    if not response_text:
        orch.speak("I don't have any previous answer stored in this session to copy.")
        return True
    import pyperclip
    pyperclip.copy(response_text)
    orch.speak("Copied the answer to your clipboard.")
    return True


def handle_save_active_context_file(orch):
    title = SystemCtrl.get_active_window_title()
    SystemCtrl.save_active_file()
    orch.speak(f"Saved your work in {title}.")
    return True


def handle_write_context_query(orch, cmd):
    query = cmd.split("write_context_query:")[1].strip()
    orch.speak(f"Researching {query} to write into your document.")
    raw_content = orch.brain.ask(f"Generate a clear, detailed response for: {query}.")
    content = re.sub(r"```(?:\w+)?\n(.*?)\n```", r"\1", raw_content, flags=re.DOTALL).strip()
    if "```" in content:
        content = content.replace("```", "")

    # 1. Verified Editor Focus
    try:
        import pygetwindow as gw
        active_win = gw.getActiveWindow()

        target_win = None
        active_doc_name = orch.ctx.active_document
        if active_doc_name:
            base_doc_name = os.path.basename(active_doc_name)
            wins = gw.getWindowsWithTitle(base_doc_name)
            if wins:
                target_win = wins[0]

        if not target_win:
            wins = gw.getWindowsWithTitle("Notepad") or gw.getWindowsWithTitle("Document") or gw.getWindowsWithTitle("txt") or gw.getWindowsWithTitle("Editor")
            if wins:
                target_win = wins[0]

        if target_win:
            target_win.activate()
            time.sleep(0.4)
        elif active_win:
            active_win.activate()
            time.sleep(0.3)
    except Exception as fe:
        orch.logger.warning(f"Editor focus failure in write_context_query: {fe}")

    # 2. Clipboard Validation Loop
    import pyautogui
    import pyperclip

    clip_ok = False
    for attempt in range(3):
        try:
            pyperclip.copy(content)
            time.sleep(0.2)
            if pyperclip.paste() == content:
                clip_ok = True
                break
        except Exception as ce:
            orch.logger.warning(f"Clipboard copy attempt {attempt} failed: {ce}")
            time.sleep(0.1)

    if clip_ok:
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.3)
        orch.speak("Pasted context research successfully.")
    else:
        orch.logger.warning("Clipboard verification failed completely. Reverting to physical typing fallback.")
        orch.speak("Clipboard paste failed. Typing response out for you.")
        pyautogui.typewrite(content[:500])
        if len(content) > 500:
            pyautogui.typewrite("\n[Text truncated due to length limits]")
        orch.speak("Completed typing fallback.")

    orch.ctx.update(last_response=content, query=query)
    return True


def handle_continue_context_query(orch, cmd):
    query = cmd.split("continue_context_query:")[1].strip()
    orch.speak("Elaborating and extending the previous context.")

    last_resp = orch.ctx.last_response or "empty context"
    prompt = (
        f"The user wants to continue/extend our previous response. The continuation request is: '{query}'.\n"
        f"Our last response was:\n{last_resp}\n\n"
        f"Generate the continuing content/points as requested, expanding on the topic. "
        f"Do NOT repeat the points already mentioned. Provide ONLY the new points/content to append."
    )
    raw_content = orch.brain.ask(prompt)
    content = re.sub(r"```(?:\w+)?\n(.*?)\n```", r"\1", raw_content, flags=re.DOTALL).strip()
    if "```" in content:
        content = content.replace("```", "")

    # Bring Notepad / Editor / App to focus
    try:
        import pygetwindow as gw
        wins = gw.getWindowsWithTitle("Notepad") or gw.getWindowsWithTitle("Document") or gw.getWindowsWithTitle("txt")
        if wins:
            wins[0].activate()
            time.sleep(0.3)
    except Exception:
        pass

    # Verify clipboard and paste content
    import pyautogui
    import pyperclip

    # Append enter first to move to next line
    pyautogui.press('enter')
    pyautogui.press('enter')
    time.sleep(0.1)

    pyperclip.copy(content)
    time.sleep(0.3)

    # Verify clipboard copy
    if pyperclip.paste() == content:
        pyautogui.hotkey('ctrl', 'v')
        orch.speak("Appended continuation points to your document.")
    else:
        orch.logger.warning("Clipboard verification failed. Retrying copy...")
        pyperclip.copy(content)
        time.sleep(0.2)
        pyautogui.hotkey('ctrl', 'v')
        orch.speak("Appended continuation points.")

    orch.ctx.update(last_response=last_resp + "\n\n" + content, query=query)
    return True


def handle_context_command(orch, cmd, silent=False):
    """Handles specialized context workflow commands emitted by ContextMemory.resolve()."""
    if cmd == "paste_context_response":
        return handle_paste_context_response(orch)
    if cmd == "copy_context_response":
        return handle_copy_context_response(orch)
    if cmd == "save_active_context_file":
        return handle_save_active_context_file(orch)
    if cmd.startswith("write_context_query:"):
        return handle_write_context_query(orch, cmd)
    if cmd.startswith("continue_context_query:"):
        return handle_continue_context_query(orch, cmd)
    return False
