import glob
import logging
import os

from utils.config import Config
from utils.lazy import LazyModule

pygame = LazyModule("pygame")  # ~1.4 s import: only loaded when music is first played
_PYGAME_OK = pygame.available()
_mixer_ready = False


def _ensure_mixer() -> None:
    global _mixer_ready
    if _PYGAME_OK and not _mixer_ready:
        try:
            pygame.mixer.init()
        except Exception as _e:
            logging.debug("pygame mixer init failed: %s: %s", type(_e).__name__, _e)
        _mixer_ready = True


class MusicEngine:
    def __init__(self):
        self._is_playing = False
        pass

    def _unavailable(self) -> str:
        return "Local music playback isn't available because pygame isn't installed. Try 'pip install pygame'."

    @staticmethod
    def _is_audio(path: str) -> bool:
        return os.path.splitext(path)[1].lower() in {e.lower() for e in Config.MUSIC_EXTS}

    def find_tracks(self, query: str) -> list[str]:
        """Audio files matching ``query``: Music folder first, then the shared bounded index."""
        query = (query or "").strip()
        if not query:
            return []
        music_dir = Config.FOLDER_SHORTCUTS.get("music", os.path.expanduser("~/Music"))
        pattern = os.path.join(glob.escape(music_dir), "*" + glob.escape(query) + "*")
        matches = [p for p in glob.glob(pattern) if os.path.isfile(p) and self._is_audio(p)]
        if not matches:
            # glob is case-sensitive on some platforms: do a case-insensitive scan too
            try:
                low = query.lower()
                matches = [e.path for e in os.scandir(music_dir)
                           if e.is_file() and low in e.name.lower() and self._is_audio(e.name)]
            except OSError:
                matches = []
        if not matches:
            from utils.name_index import get_shared_index
            matches = get_shared_index().find_by_ext(query, Config.MUSIC_EXTS)
        return sorted(matches)

    def play_music(self, query: str) -> str:
        if not _PYGAME_OK:
            return self._unavailable()
        matches = self.find_tracks(query)

        if not matches:
            return f"I couldn't find any music file matching '{query}'."

        try:
            _ensure_mixer()
            pygame.mixer.music.load(matches[0])
            pygame.mixer.music.play()
            self._is_playing = True
            return f"Playing: {os.path.basename(matches[0])}"
        except Exception as e:
            logging.debug("[engines/music.py:51] Swallowed exception: %s: %s", type(e).__name__, e)
            return f"Error playing music: {e}"

    def stop(self):
        if not _PYGAME_OK:
            return self._unavailable()
        _ensure_mixer()
        pygame.mixer.music.stop()
        self._is_playing = False
        return "Music stopped."

    def pause(self):
        if not _PYGAME_OK:
            return self._unavailable()
        _ensure_mixer()
        pygame.mixer.music.pause()
        return "Music paused."

    def resume(self):
        if not _PYGAME_OK:
            return self._unavailable()
        _ensure_mixer()
        pygame.mixer.music.unpause()
        return "Music resumed."
