import re


def handle_dictionary(orch, c):
    """Handle dictionary lookup commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    cmd = c.lower().strip()
    cmd = re.sub(r"^(flexi|flexie|hey flexie|ok flexie)\b", "", cmd).strip()

    # Extract the word
    word = re.sub(r"^(define|definition of|meaning of|what does|what is the meaning of|dictionary|spell|look up|word)\s*", "", cmd, flags=re.IGNORECASE).strip()
    # Remove trailing question marks
    word = word.rstrip("?").strip()

    if not word:
        orch.speak("What word should I look up?")
        return True

    if "synonym" in cmd:
        response = orch.dictionary.synonyms(word)
    elif "antonym" in cmd:
        response = orch.dictionary.antonyms(word)
    else:
        response = orch.dictionary.define(word)

    orch.ctx.update(last_response=response, query=c)
    orch.speak(response)
    return True
