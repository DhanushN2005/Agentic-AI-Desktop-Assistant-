import glob
import os

from utils.config import Config

try:
    import pygame
    _PYGAME_OK = True
except Exception:
    pygame = None
    _PYGAME_OK = False


class MusicEngine:
    def __init__(self):
        self._is_playing = False
        if _PYGAME_OK:
            try:
                pygame.mixer.init()
            except Exception:
                pass

    def _unavailable(self) -> str:
        return "Local music playback isn't available because pygame isn't installed. Try 'pip install pygame'."

    def play_music(self, query: str) -> str:
        if not _PYGAME_OK:
            return self._unavailable()
        music_dir = Config.FOLDER_SHORTCUTS.get("music", os.path.expanduser("~/Music"))
        matches = glob.glob(os.path.join(music_dir, f"*{query}*"))

        if not matches:
            for root in [music_dir, os.path.expanduser("~")]:
                for r, _, files in os.walk(root):
                    for f in files:
                        if query.lower() in f.lower() and os.path.splitext(f)[1] in Config.MUSIC_EXTS:
                            matches.append(os.path.join(r, f))
                    if matches:
                        break
                if matches:
                    break

        if not matches:
            return f"I couldn't find any music file matching '{query}'."

        try:
            pygame.mixer.music.load(matches[0])
            pygame.mixer.music.play()
            self._is_playing = True
            return f"Playing: {os.path.basename(matches[0])}"
        except Exception as e:
            return f"Error playing music: {e}"

    def stop(self):
        if not _PYGAME_OK:
            return self._unavailable()
        pygame.mixer.music.stop()
        self._is_playing = False
        return "Music stopped."

    def pause(self):
        if not _PYGAME_OK:
            return self._unavailable()
        pygame.mixer.music.pause()
        return "Music paused."

    def resume(self):
        if not _PYGAME_OK:
            return self._unavailable()
        pygame.mixer.music.unpause()
        return "Music resumed."
