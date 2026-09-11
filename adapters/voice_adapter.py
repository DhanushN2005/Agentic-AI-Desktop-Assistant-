from interface.voice import VoiceInterface
from core.event_bus.bus import EventBus, Event

class LegacyVoiceAdapter:
    """Decouples voice VAD thresholds, audio streams, and speech playbacks to standard events."""
    def __init__(self, voice_interface: VoiceInterface):
        self.voice = voice_interface
        self.bus = EventBus()

    def speak(self, text: str, interrupt: bool = False):
        self.bus.publish(Event("voice.speak.start", {"text": text, "interrupt": interrupt}))
        self.voice.speak(text, interrupt)

    def listen(self, timeout=None) -> str:
        self.bus.publish(Event("voice.listen.start", {"timeout": timeout}))
        text = self.voice.listen(timeout)
        self.bus.publish(Event("voice.listen.success", {"text": text}))
        return text

    def stop(self):
        self.voice.stop()
        self.bus.publish(Event("voice.stopped", {}))

    @property
    def is_speaking(self) -> bool:
        return self.voice.is_speaking
