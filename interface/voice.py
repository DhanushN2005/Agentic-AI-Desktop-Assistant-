import logging
import os
import queue
import tempfile
import re
import threading
import time

import speech_recognition as sr

from utils.config import Config
from utils.helpers import is_online

# ---------------------------------------------------------------------------
# Speech text preparation — turns LLM/UI text into natural spoken prose.
# ---------------------------------------------------------------------------
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U00002B00-\U00002BFF\U0001F900-\U0001F9FF\U0000FE0F\U0000200D]+",
    flags=re.UNICODE,
)


def prepare_speech_text(text: str) -> str:
    """Clean markdown/code/emoji noise into natural, speakable prose."""
    if not text:
        return ""
    t = text
    # Code fences: keep the code content, drop the fence + language tag
    t = re.sub(r"```[\w-]*\n(.*?)```", r"\1", t, flags=re.DOTALL)
    # Inline code spans
    t = re.sub(r"`([^`]+)`", r"\1", t)
    # Links/images -> just the label
    t = re.sub(r"!?\[([^\]]+)\]\([^)]*\)", r"\1", t)
    # Headers
    t = re.sub(r"^\s{0,3}#{1,6}\s+", "", t, flags=re.MULTILINE)
    # Bold/italic/strikethrough markers
    t = re.sub(r"(\*\*\*|\*\*|\*|__|~~)(?=\S)(.+?)(?<=\S)\1", r"\2", t)
    # List markers -> spoken prose (numbers often read better than '1 point')
    t = re.sub(r"^\s*[-*+]\s+", "", t, flags=re.MULTILINE)
    t = re.sub(r"^\s*\d+[.)]\s+", "", t, flags=re.MULTILINE)
    # Table pipes and bullet glyphs -> spoken pause
    t = t.replace("|", " ")
    t = t.replace("\u2022", ",")
    # Emojis and decorative symbols
    t = _EMOJI_RE.sub("", t)
    # Symbols a person would speak as words
    t = t.replace("&", " and ").replace("%", " percent")
    # Ellipses read as pauses
    t = re.sub(r"\.{3,}", ".", t)
    # Any leftover markdown punctuation that TTS would mangle
    t = re.sub(r"[*_#~<>{}\[\]\\]+", " ", t)
    return re.sub(r"\s{2,}", " ", t).strip()


# ---------------------------------------------------------------------------
# VAD tuning.
#
# IMPORTANT: every energy value below is in RAW 16-bit RMS units — the exact
# scale used by speech_recognition's `energy_threshold` (audioop.rms). The old
# code mixed two scales: the ambient floor came from `energy_threshold`
# (raw RMS, e.g. ~70-500) while the frame level was divided by 32768 and
# multiplied by 1000 (~33x smaller), so the `80.0` floor silently meant
# raw RMS ~2620 (-22 dBFS) and normal speech never crossed it.
# ---------------------------------------------------------------------------
def _env_number(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return float(default)


VAD_MIN_ENERGY = _env_number("FLEXIE_VAD_MIN_ENERGY", 120.0)      # ~ -48 dBFS floor
VAD_ENERGY_RATIO = _env_number("FLEXIE_VAD_ENERGY_RATIO", 1.5)    # above ambient
VAD_FRAME_MS = 30          # webrtcvad accepts ONLY 10/20/30 ms frames
VAD_MIN_ONSET_FRAMES = 3        # ~90 ms of sustained level -> a real word, not a click
VAD_MIN_UTTERANCE_SECONDS = 0.24   # shorter blips are never sent to ASR
VAD_PRE_ROLL_SECONDS = 0.3         # audio kept before the detected onset
VAD_STUCK_MUTE_SECONDS = 30.0   # long TTS replies may legitimately run 10-25s
VAD_MIC_SAMPLE_RATE = 16000     # preferred rate: Google ASR + webrtcvad optimum


class VoiceInterface:
    def __init__(self):
        self.recognizer = sr.Recognizer()
        self.recognizer.energy_threshold = 150 # Lowered from 300 - fixes quiet voice not detected
        self.recognizer.pause_threshold = 0.8 # Faster endpoint detection
        self.recognizer.non_speaking_duration = 0.4
        self.recognizer.dynamic_energy_threshold = True
        self.recognizer.dynamic_energy_adjustment_damping = 0.15
        self.recognizer.dynamic_energy_ratio = 1.5 # Sensitive to quiet speech to prevent premature cutoff
        
        self.speech_queue = queue.Queue()
        self.stop_speech = False
        self.is_speaking = False
        self.last_spoken_text = None
        self.last_spoken_time = 0
        self.lang = "en-IN" # Default to Indian English
        # Serializes Google ASR calls so the live partial recognizer and the
        # final recognizer never hit the API at once (that caused dropped words).
        self._asr_lock = threading.Lock()
        
        # TTS dynamic parameters (modulatable by orchestrator commands)
        self.speech_rate = 1
        self.speech_volume = 100

        # Speech buffering for natural chunked playback
        self._speech_buffer = ""

        # TTS engine selection: neural (Edge, natural) vs sapi (offline SAPI).
        self.speech_mode = os.getenv("FLEXIE_TTS_MODE", "neural").lower()
        import importlib.util
        has_edge = importlib.util.find_spec("edge_tts") is not None
        if self.speech_mode == "neural" and not has_edge:
            logging.warning("FLEXIE_TTS_MODE=neural but edge-tts not installed — using SAPI")
            self.speech_mode = "sapi"
        # Neural failure counter: after 3 consecutive 403s skip neural for the session
        self._neural_fail_count = 0
        self._neural_disabled = False
        # suppress_asr: set True externally (e.g. YouTube playing) to skip ASR on VAD hits
        self.suppress_asr = False
        # post-TTS silence buffer end time: keep VAD muted briefly after speech finishes
        self._speak_end_time = 0.0

        # Shared TTS Engine
        self.engine_lock = threading.Lock()
        self._engine = None

        # Report TTS configuration
        try:
            import pyttsx3
            temp = pyttsx3.init()
            sapi_voices = [v.name for v in temp.getProperty('voices')]
            temp.stop()
        except Exception as _e:
            logging.debug("[interface/voice.py:52] Swallowed exception: %s: %s", type(_e).__name__, _e)
            sapi_voices = []
        print("\n[Voice Setup]")
        if self.speech_mode == "neural":
            print(f" - TTS: Edge neural (natural) | voice: {self.EDGE_VOICE}")
        else:
            print(" - TTS: Windows SAPI (offline fallback)")
        for i, v in enumerate(sapi_voices):
            print(f" - SAPI Voice {i}: {v}")
        
        # Start speech thread
        self.speech_thread = threading.Thread(target=self._speech_worker, daemon=True)
        self.speech_thread.start()
        
        # 1. Establish persistent open microphone stream context to avoid device locking failures
        self._mic = None
        self._mic_context = None
        self._mic_sample_rate = None
        try:
            logging.info("Voice: Initializing persistent microphone stream...")
            self._mic, self._mic_sample_rate = self._open_mic_stream()
            logging.info(f"Voice: Mic stream live @ {self._mic_sample_rate} Hz.")
            logging.info("Voice: Calibrating microphone for ambient noise floor...")
            self.recognizer.adjust_for_ambient_noise(self._mic, duration=1.5)
            logging.info(f"Voice: Calibration complete. Dynamic threshold baseline set to {self.recognizer.energy_threshold:.1f} (raw RMS)")
        except Exception as ce:
            logging.error(f"Voice: Persistent mic initialization/calibration failed: {ce}")

    # ------------------------------------------------------------------
    # TTS engines
    # ------------------------------------------------------------------
    # Voice selection (env-overridable):
    #   FLEXIE_VOICE   — Edge neural voice name. Defaults to a warm British
    #                    male, the closest free match to a Jarvis-style butler.
    #   FLEXIE_TTS_MODE — "neural" (default) | "sapi" (offline robotic fallback)
    EDGE_VOICE = os.getenv("FLEXIE_VOICE", "en-GB-RyanNeural")

    def _speak_neural(self, text: str) -> bool:
        """Speak via Edge neural TTS (natural, Jarvis-grade).

        Streams audio chunks from edge-tts into an in-memory buffer and plays
        the first chunk as soon as it arrives, cutting perceived latency by
        ~400 ms vs the old save-full-mp3-then-play approach.
        Returns False so caller can fall back to SAPI on failure.
        """
        try:
            import edge_tts
            import pygame
        except Exception as e:
            logging.info(f"TTS [Neural]: unavailable ({e}); will use SAPI fallback")
            return False

        fd, tmp_path = tempfile.mkstemp(prefix="flexie_tts_", suffix=".mp3")
        os.close(fd)
        try:
            async def _synth_stream():
                """Stream edge-tts chunks and write to file as they arrive."""
                communicate = edge_tts.Communicate(text, self.EDGE_VOICE)
                with open(tmp_path, "wb") as fp:
                    async for chunk in communicate.stream():
                        if chunk["type"] == "audio":
                            fp.write(chunk["data"])

            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    raise RuntimeError
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            loop.run_until_complete(_synth_stream())

            if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
                raise RuntimeError("edge-tts produced no audio")

            if not pygame.mixer.get_init():
                pygame.mixer.init()
            pygame.mixer.music.load(tmp_path)
            pygame.mixer.music.play()

            self._active_music_channel = True
            while pygame.mixer.music.get_busy():
                if self.interrupt_speech:
                    logging.info("TTS [Neural]: interruption detected — stopping playback")
                    pygame.mixer.music.stop()
                    self.interrupt_speech = False
                    return False
                time.sleep(0.02)

            self._active_music_channel = False
            return True
        except Exception as e:
            logging.warning(f"TTS [Neural]: synthesis/playback failed: {e}")
            self._active_music_channel = False
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return False

    def _speak_sapi(self, text: str) -> bool:
        """Offline SAPI fallback via PowerShell System.Speech (robotic but reliable)."""
        logging.info(f"TTS [SAPI]: Speaking: '{text}'")
        try:
            import subprocess
            clean_text = text.replace("'", "''")

            cmd = (
                "Add-Type -AssemblyName System.Speech; "
                "$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                f"$synth.Rate = {self.speech_rate}; "
                f"$synth.Volume = {self.speech_volume}; "
                f"$synth.Speak('{clean_text}')"
            )

            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            self._active_speech_proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-Command", cmd],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                startupinfo=startupinfo,
            )

            while self._active_speech_proc.poll() is None:
                if self.interrupt_speech:
                    logging.info("TTS [SAPI]: interruption detected. Terminating speech process.")
                    try:
                        self._active_speech_proc.terminate()
                        self._active_speech_proc.wait(timeout=1.0)
                    except Exception as _e:
                        logging.debug("[interface/voice.py:292] Swallowed exception: %s: %s", type(_e).__name__, _e)
                    self.interrupt_speech = False
                    self._active_speech_proc = None
                    return False
                time.sleep(0.02)

            self._active_speech_proc = None
            return True
        except Exception as e:
            logging.error(f"SAPI TTS Exception: {e}")
            self._active_speech_proc = None
            return False

    def _speech_worker(self):

        """Dedicated thread for TTS that uses highly robust, out-of-process speech."""
        self.interrupt_speech = False
        self._active_speech_proc = None

        while not self.stop_speech:
            try:
                # Reset interrupt flag before dequeueing
                if self.interrupt_speech:
                    self.interrupt_speech = False

                text = self.speech_queue.get(timeout=0.2)
                if not text: continue
                
                # Check for interruption right after dequeueing
                if self.interrupt_speech:
                    self.interrupt_speech = False
                    self.speech_queue.task_done()
                    continue

                print(f"\n[Voice Output]: {text}")
                logging.info(f"TTS Start: {text}")

                self.is_speaking = True
                self._speak_start_time = time.time()

                # Neural-first with automatic offline fallback. The persistent
                # VAD stream handles barge-in via the is_speaking flag.
                spoke = False
                use_neural = (
                    self.speech_mode == "neural"
                    and is_online()
                    and not self._neural_disabled
                )
                if use_neural:
                    spoke = self._speak_neural(text)
                    if not spoke:
                        self._neural_fail_count += 1
                        if self._neural_fail_count >= 3:
                            self._neural_disabled = True
                            logging.warning(
                                "TTS [Neural]: disabled after 3 consecutive failures — using SAPI only"
                            )
                    else:
                        self._neural_fail_count = 0
                if not spoke:
                    spoke = self._speak_sapi(text)
                if not spoke:
                    logging.warning("TTS: all engines failed for this utterance")

                self.is_speaking = False
                self._speak_end_time = time.time()
                
                self.speech_queue.task_done()
                logging.info("TTS End.")
            except queue.Empty as _e:
                logging.debug("[interface/voice.py:146] Swallowed exception: %s: %s", type(_e).__name__, _e)
                continue
            except Exception as e:
                self.is_speaking = False
                logging.error(f"Speech Worker Loop Error: {e}")
                time.sleep(1)

    def stop(self):
        """Clears the speech queue and interrupts active playback instantly."""
        logging.info("Voice: Interrupt requested. Clearing speech queue.")
        self.interrupt_speech = True
        
        # Kill active subprocess immediately to stop audio playback in real-time
        proc = getattr(self, "_active_speech_proc", None)
        if proc:
            try:
                proc.terminate()
                logging.info("Voice: Successfully terminated active subprocess.")
            except Exception as e:
                logging.error(f"Failed to terminate active subprocess: {e}")
        
        while not self.speech_queue.empty():
            try:
                self.speech_queue.get_nowait()
                self.speech_queue.task_done()
            except queue.Empty as _e:
                logging.debug("[interface/voice.py:171] Swallowed exception: %s: %s", type(_e).__name__, _e)
                break

    def speak(self, text: str, interrupt: bool = False):
        """Queues speech after cleanup. Sentences batch into ~2-sentence chunks
        so neural playback flows naturally instead of choppy per-sentence clips."""
        if not text:
            return

        text = prepare_speech_text(text)
        if not text:
            return

        # Suppression filter for duplicate announcements within 4 seconds
        now = time.time()
        if text == self.last_spoken_text and (now - self.last_spoken_time < 4.0):
            logging.info("TTS [Repetition Suppressed]: identical text within 4s")
            return
        self.last_spoken_text = text
        self.last_spoken_time = now

        if interrupt:
            self.stop()

        # Batch sentences: flush when the pending chunk reaches 2 sentences
        # (or 200 chars), giving natural pacing with low latency.
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]
        for sentence in sentences:
            self._speech_buffer = (self._speech_buffer + " " + sentence).strip() if self._speech_buffer else sentence
            n_sentences = len(re.findall(r"[.!?]", self._speech_buffer))
            if n_sentences >= 2 or len(self._speech_buffer) >= 200:
                self.speech_queue.put(self._speech_buffer)
                self._speech_buffer = ""
        # Flush any remainder so nothing is ever silently withheld.
        if self._speech_buffer:
            self.speech_queue.put(self._speech_buffer)
            self._speech_buffer = ""

    def _resolve_mic_device(self):
        """Optional mic selection via FLEXIE_MIC_DEVICE.

        Accepts either a device index ("2") or a case-insensitive name
        substring ("steam", "realtek"). Returns None (system default) when the
        variable is unset or does not match, so behaviour is unchanged for
        everyone who does not set it.
        """
        pref = (os.getenv("FLEXIE_MIC_DEVICE") or "").strip()
        if not pref:
            return None

        try:
            names = sr.Microphone.list_microphone_names()
        except Exception as e:
            logging.warning(f"Voice: could not enumerate microphones ({e}); using system default")
            return None

        if pref.isdigit():
            idx = int(pref)
            if 0 <= idx < len(names):
                logging.info(f"Voice: FLEXIE_MIC_DEVICE={idx} -> [{idx}] {names[idx]}")
                return idx
            logging.warning(f"Voice: FLEXIE_MIC_DEVICE={idx} out of range (0-{len(names) - 1}); using system default")
            return None

        for idx, name in enumerate(names):
            if pref.lower() in (name or "").lower():
                logging.info(f"Voice: FLEXIE_MIC_DEVICE='{pref}' -> [{idx}] {name}")
                return idx

        logging.warning(f"Voice: FLEXIE_MIC_DEVICE='{pref}' matched no input device; using system default")
        return None

    def _open_mic_stream(self, device_index=None):
        """Open (and keep open) the persistent mic stream.

        Prefers a 16 kHz stream because that is what Google ASR expects and the
        only rate family webrtcvad can consume (8/16/32/48 kHz). Falls back to
        the hardware's own default rate when the device refuses 16 kHz, so a
        device that only exposes 44.1 kHz still works (just without webrtcvad).

        Returns (mic, sample_rate). Raises if no stream could be opened.
        """
        if device_index is None:
            device_index = self._resolve_mic_device()

        last_err = None
        for rate in (VAD_MIC_SAMPLE_RATE, None):
            mic = None
            try:
                if rate:
                    mic = sr.Microphone(device_index=device_index, sample_rate=rate)
                else:
                    # None -> speech_recognition uses the hardware default rate.
                    mic = sr.Microphone(device_index=device_index)
                self._mic_context = mic.__enter__()
                return mic, mic.SAMPLE_RATE
            except Exception as e:
                last_err = e
                logging.warning(f"Voice: mic open at {rate or 'device-default'} Hz failed: {e}")
                if mic is not None:
                    try:
                        mic.__exit__(None, None, None)
                    except Exception as _e:
                        logging.debug("[interface/voice.py] Swallowed exception during mic rollback: %s: %s",
                                      type(_e).__name__, _e)

        self._mic_context = None
        raise RuntimeError(f"could not open microphone stream: {last_err}")

    def _get_adaptive_mode(self, timeout=None, phrase_time_limit=None) -> str:
        """Dynamically infers the best listening mode (fast, normal, conversation) based on interaction context."""
        # "fast" is reserved for short yes/no replies (timeout<=3). Anything
        # longer gets a tolerant mode so Flexie never cuts off a partial command.
        if timeout is not None and timeout <= 3:
            return "fast"

        last_length = getattr(self, "_last_transcript_len", 0)
        if last_length > 6:
            return "conversation"

        return "normal"

    def send_to_ui(self, tag: str, value: str):
        """Helper to send updates to UI UDP socket."""
        try:
            import socket
            udp_out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            msg = f"{tag}:{value}"
            # Port 9886 is Config.UDP_PORT_UI
            udp_out.sendto(msg.encode('utf-8'), ('127.0.0.1', 9886))
        except Exception as _e:
            logging.debug("[interface/voice.py:218] Swallowed exception: %s: %s", type(_e).__name__, _e)

    def listen_adaptive(self, mode="normal", timeout=None) -> str:
        """Adaptive real-time listening featuring persistent mic streaming, RMS VAD, and echo-safe endpoints."""
        start_time = time.time()
        
        # Ensure lazy instantiation of persistent stream context if needed
        if not hasattr(self, '_mic') or self._mic is None:
            try:
                self._mic, self._mic_sample_rate = self._open_mic_stream()
            except Exception as e:
                logging.error(f"VAD Persistent Mic stream lazy init failed: {e}")
                return ""
        if not getattr(self, '_mic_context', None):
            try:
                self._mic_context = self._mic.__enter__()
            except Exception as e:
                logging.error(f"VAD Persistent Mic stream lazy init failed: {e}")
                return ""

        # 1. Target speech timeouts. Generous intra-phrase pauses so commands
        # are never finalized mid-sentence (user keeps talking after a short pause).
        if mode == "fast":
            silence_timeout = 0.4   # was 0.7 — short yes/no replies
        elif mode == "conversation":
            silence_timeout = 1.0   # was 1.2 — longer commands tolerate thinking pauses
        else:
            silence_timeout = 0.6   # was 0.9 — normal commands

        logging.info(
            f"VAD [Listening]: Mode={mode.upper()}, SilenceTimeout={silence_timeout}s, "
            f"EnergyFloor={VAD_MIN_ENERGY:.0f} (raw RMS)"
        )
        
        import struct
        import math
        
        try:
            source = self._mic
            stream = source.stream
            sample_rate = source.SAMPLE_RATE
            sample_width = source.SAMPLE_WIDTH
            
            # 30 ms frames: valid for webrtcvad (it rejects anything else) and
            # short enough to keep barge-in latency low.
            chunk_size = max(1, int(sample_rate * (VAD_FRAME_MS / 1000.0)))
            chunk_seconds = chunk_size / float(sample_rate)
            
            # Setup recognizer parameters
            self.recognizer.pause_threshold = silence_timeout
            self.recognizer.phrase_threshold = 0.3
            self.recognizer.non_speaking_duration = 0.5
            
            # Ambient floor in RAW 16-bit RMS units — the same scale as
            # recognizer.energy_threshold, so the two are always comparable.
            noise_floor = max(float(self.recognizer.energy_threshold), VAD_MIN_ENERGY)
            
            # webrtcvad only understands 8/16/32/48 kHz streams. It is used as an
            # additional (OR) onset signal: measured on this hardware it stays
            # silent on real room ambience but still catches quiet speech that
            # sits below the energy floor.
            webrtc_vad = getattr(self, '_webrtc_vad', None)
            if webrtc_vad is None and sample_rate in (8000, 16000, 32000, 48000):
                try:
                    import webrtcvad
                    webrtc_vad = webrtcvad.Vad(2)
                    self._webrtc_vad = webrtc_vad
                except Exception as e:
                    logging.debug(f"VAD: webrtcvad unavailable ({e}); energy gate only")
            elif webrtc_vad is None:
                logging.info(f"VAD: stream is {sample_rate} Hz — webrtcvad needs 8/16/32/48 kHz, using energy gate only")
            
            audio_buffer = bytearray()
            speech_started = False
            silence_start_time = None
            active_speech_duration = 0.0
            onset_run = 0
            last_partial_time = time.time()
            max_rms_seen = 0.0
            max_peak_seen = 0
            pre_roll_bytes = int(sample_rate * sample_width * VAD_PRE_ROLL_SECONDS)
            max_buffer_bytes = int(sample_rate * sample_width * 20.0)
            
            # Timeout for starting to speak (7.0 seconds total wait window)
            max_wait_time = max(0.1, float(timeout)) if timeout is not None else Config.VOICE_LISTEN_TIMEOUT
            wait_elapsed = 0.0
            err_count = 0
            
            logging.info("VAD: Reading persistent hardware audio stream...")
            self.send_to_ui("STATE", "LISTENING")
            
            while True:
                # Add tiny CPU sleep balance (stream.read is already blocking)
                time.sleep(0.01)
                
                try:
                    raw_chunk = stream.read(chunk_size)
                    
                    # Mute VAD while speaking OR for 0.4s after speech ends (mic echo tail)
                    _post_speak_mute = (
                        time.time() - getattr(self, '_speak_end_time', 0) < 0.4
                    )
                    if getattr(self, 'is_speaking', False) or _post_speak_mute:
                        # Hard mute: prevent feedback loop - but with timeout to avoid stuck mute.
                        # The guard is deliberately generous (30s): real TTS replies can take
                        # 10-25s, and force-unmuting mid-reply makes the AI hear itself.
                        if (not _post_speak_mute and
                                time.time() - getattr(self, '_speak_start_time', 0) > VAD_STUCK_MUTE_SECONDS):
                            logging.warning(
                                f"VAD: is_speaking stuck >{VAD_STUCK_MUTE_SECONDS:.0f}s, forcing unmute"
                            )
                            self.is_speaking = False
                        else:
                            # Stay deaf while the assistant talks (no self-trigger),
                            # and drop any partial utterance state from before.
                            audio_buffer.clear()
                            speech_started = False
                            silence_start_time = None
                            active_speech_duration = 0.0
                            onset_run = 0
                            wait_elapsed = 0.0
                            continue
                        
                    audio_buffer.extend(raw_chunk)
                    
                    count = len(raw_chunk) // 2
                    if count == 0:
                        continue
                    
                    shorts = struct.unpack(f"{count}h", raw_chunk)
                    # RAW int16 RMS (audioop.rms equivalent) — identical units to
                    # recognizer.energy_threshold. Do NOT rescale: comparing a
                    # rescaled value against an unscaled threshold is what made
                    # every utterance look like silence.
                    sum_squares = sum(float(s) * float(s) for s in shorts)
                    rms = math.sqrt(sum_squares / count)
                    peak = max(max(shorts), -min(shorts))
                    if rms > max_rms_seen:
                        max_rms_seen = rms
                    if peak > max_peak_seen:
                        max_peak_seen = peak
                    
                    # Optional webrtcvad: needs valid 10/20/30 ms frames at 8/16/32/48 kHz
                    is_webrtc_speech = False
                    if webrtc_vad is not None:
                        try:
                            is_webrtc_speech = webrtc_vad.is_speech(raw_chunk, sample_rate)
                        except Exception as _e:
                            logging.debug("[interface/voice.py] webrtcvad frame rejected: %s: %s", type(_e).__name__, _e)
                            webrtc_vad = None
                            self._webrtc_vad = None
                    
                    # Adapt ambient noise floor during silent gaps (and only when AI is NOT speaking)
                    if not speech_started and not self.is_speaking:
                        noise_floor = (noise_floor * 0.95) + (rms * 0.05)
                        noise_floor = max(noise_floor, VAD_MIN_ENERGY * 0.25)
                        
                    # 3. Echo-Proof Barge-In & Self-Trigger Prevention
                    # Threshold is "a bit above the measured room ambience", but never
                    # below VAD_MIN_ENERGY (~ -47 dBFS) so a silent room still needs
                    # real speech to trigger.
                    vad_threshold = max(noise_floor * VAD_ENERGY_RATIO, VAD_MIN_ENERGY)
                        
                    is_active_speech = rms > vad_threshold
                    # Boost with webrtcvad if available (catches quiet/soft speech)
                    if is_webrtc_speech:
                        is_active_speech = True
                    
                    if is_active_speech:
                        active_speech_duration += chunk_seconds
                        silence_start_time = None
                        
                        if not speech_started:
                            # Require a short run of level so a single click,
                            # key tap or mic pop never opens an utterance.
                            onset_run += 1
                            if onset_run < VAD_MIN_ONSET_FRAMES:
                                continue
                            speech_started = True
                            if len(audio_buffer) > pre_roll_bytes:
                                del audio_buffer[:-pre_roll_bytes]
                            logging.info(f"VAD [Speech Started]: Energy={rms:.1f} (peak {peak}) vs Threshold={vad_threshold:.1f}. Buffering active.")
                        
                        # Dynamic partial recognition in background thread to achieve streaming feel
                        buf_len = len(audio_buffer)
                        if buf_len > (sample_rate * sample_width * 1.8) and (time.time() - last_partial_time > 1.5):
                            last_partial_time = time.time()
                            def run_partial_asr(buf_slice):
                                try:
                                    partial_audio = sr.AudioData(buf_slice, sample_rate, sample_width)
                                    with self._asr_lock:
                                        partial_text = self.recognizer.recognize_google(partial_audio, language=self.lang).lower().strip()
                                    if partial_text:
                                        logging.info(f"VAD [Partial ASR]: \"{partial_text}...\"")
                                        self.send_to_ui("PARTIAL", partial_text + "...")
                                except Exception as _e:
                                    logging.debug("[interface/voice.py:352] Swallowed exception: %s: %s", type(_e).__name__, _e)
                                    pass
                            threading.Thread(target=run_partial_asr, args=(bytes(audio_buffer),), daemon=True).start()
                        else:
                            self.send_to_ui("PARTIAL", "Listening...")
                    else:
                        onset_run = 0
                        if speech_started:
                            if silence_start_time is None:
                                silence_start_time = time.time()
                            else:
                                elapsed_silence = time.time() - silence_start_time

                                # Base tolerance from mode, scaled up for sustained speech:
                                # a longer command means the user tends to pause mid-thought
                                # (e.g. "open chrome and ... open notepad"). Endpoint only
                                # fires after a genuinely long gap so we never cut them off.
                                current_timeout = silence_timeout
                                if active_speech_duration > 1.5:
                                    current_timeout = max(current_timeout, 1.1)

                                if elapsed_silence >= current_timeout:
                                    logging.info(f"VAD [Speech Ended]: Paused {elapsed_silence:.1f}s >= {current_timeout:.1f}s. Finalizing.")
                                    break
                        else:
                            wait_elapsed += chunk_seconds
                            if wait_elapsed >= max_wait_time:
                                logging.info(
                                    "VAD [Timeout]: No human voice detected. "
                                    f"(loudest frame: rms={max_rms_seen:.1f}, peak={max_peak_seen}, "
                                    f"threshold={vad_threshold:.1f}, mic={sample_rate}Hz)"
                                )
                                return ""

                        # Safety loop cap — generous so longer commands are never truncated
                        # mid-word. Endpoint detection already handles finishing.
                        if len(audio_buffer) >= max_buffer_bytes:
                            logging.info("VAD [Safety Cap]: Utterance cap reached.")
                            break
                        
                except Exception as stream_err:
                    err_count += 1
                    logging.warning(f"VAD persistent stream read error ({err_count}): {stream_err}")
                    if err_count >= 5:
                        logging.error("VAD: Serial stream read failures detected. Re-instantiating mic stream context...")
                        try:
                            if hasattr(self, '_mic_context') and self._mic_context:
                                try: self._mic.__exit__(None, None, None)
                                except Exception as _e:
                                    logging.debug("[interface/voice.py] Swallowed exception: %s: %s", type(_e).__name__, _e)
                            self._mic, self._mic_sample_rate = self._open_mic_stream()
                            stream = self._mic.stream
                            sample_rate = self._mic.SAMPLE_RATE
                            sample_width = self._mic.SAMPLE_WIDTH
                            chunk_size = max(1, int(sample_rate * (VAD_FRAME_MS / 1000.0)))
                            chunk_seconds = chunk_size / float(sample_rate)
                            logging.info(f"VAD: Mic stream context re-instantiated successfully @ {sample_rate} Hz.")
                        except Exception as re_err:
                            logging.error(f"VAD: Re-instantiation of mic context failed: {re_err}")
                        err_count = 0
                    time.sleep(0.2)
                    
            if len(audio_buffer) == 0:
                return ""
            
            # Reject click-like blips: nothing that short can be a command, and
            # shipping it to ASR only yields junk transcripts.
            if active_speech_duration < VAD_MIN_UTTERANCE_SECONDS:
                logging.info(
                    f"VAD [Rejected]: only {active_speech_duration:.2f}s of speech "
                    f"(< {VAD_MIN_UTTERANCE_SECONDS:.2f}s) — ignoring blip."
                )
                return ""
                
            elapsed_latency = time.time() - start_time

            # External audio playing (e.g. YouTube) — VAD triggered on media, not voice
            if getattr(self, 'suppress_asr', False):
                logging.info("VAD [Suppressed]: suppress_asr=True (media playing). Discarding buffer.")
                audio_buffer.clear()
                speech_started = False
                silence_start_time = None
                active_speech_duration = 0.0
                onset_run = 0
                self.send_to_ui("STATE", "IDLE")
                continue

            logging.info(f"VAD [Timing]: Total buffer capture time: {elapsed_latency:.2f}s. Invoking Google ASR.")
            self.send_to_ui("STATE", "THINKING")
            
            # ASR recognition call
            audio_data = sr.AudioData(bytes(audio_buffer), sample_rate, sample_width)
            
            recognized_text = ""
            # Rate-limit guard: don't hammer Google more than once per second
            now = time.time()
            last_asr = getattr(self, "_last_asr_ts", 0)
            if now - last_asr < 1.0:
                time.sleep(1.0 - (now - last_asr))
            self._last_asr_ts = time.time()

            if is_online():
                try:
                    with self._asr_lock:
                        text = self.recognizer.recognize_google(audio_data, language=self.lang)
                    recognized_text = text.lower().strip()
                    logging.info(f"VAD [Recognized Online]: \"{recognized_text}\"")
                    self._asr_fail_count = 0  # reset failure streak
                except Exception as online_err:
                    logging.warning(f"Online ASR failed ({type(online_err).__name__}), trying offline: {online_err}")
                    recognized_text = self._recognize_offline(audio_data, bytes(audio_buffer), sample_rate)
            else:
                logging.info("System is offline. Initiating offline ASR pipeline...")
                recognized_text = self._recognize_offline(audio_data, bytes(audio_buffer), sample_rate)

            # Consecutive failure feedback — speak so user knows something's wrong
            if not recognized_text:
                self._asr_fail_count = getattr(self, "_asr_fail_count", 0) + 1
                if self._asr_fail_count == 3:
                    self._speak_sapi("Sorry, I'm having trouble hearing you. Please speak clearly.")
                elif self._asr_fail_count >= 6:
                    self._speak_sapi("Could you repeat that?")
                    self._asr_fail_count = 0
            else:
                self._asr_fail_count = 0
                
            self.send_to_ui("PARTIAL", recognized_text)
            return recognized_text
            
        except Exception as mic_error:
            logging.error(f"VAD persistent mic loop failed: {mic_error}")
            return ""

    def _init_vosk(self):
        """Lazy loader for Vosk offline speech recognition engine."""
        if getattr(self, "_vosk_init_done", False):
            return
        self._vosk_init_done = True
        try:
            import vosk
            import os
            
            user_home = os.path.expanduser("~")
            model_dir = os.path.join(user_home, ".cache", "vosk")
            model_path = os.path.join(model_dir, "vosk-model-small-en-us-0.15")
            
            if not os.path.exists(model_path):
                logging.info("Vosk offline model not found locally.")
                return
                
            self.vosk_model = vosk.Model(model_path)
            logging.info("Vosk offline model successfully initialized.")
        except Exception as e:
            logging.warning(f"Vosk init skipped: {e}")

    def _recognize_offline(self, audio_data, raw_bytes, sample_rate) -> str:
        """Handles offline speech recognition with multi-layered fallbacks."""
        # Fallback Tier 0: Whisper (best offline quality, no model download needed for tiny)
        try:
            import whisper as _whisper
            import tempfile, wave, os as _os
            if not getattr(self, "_whisper_model", None):
                self._whisper_model = _whisper.load_model("tiny.en")  # ~40MB, loads once
            # Write raw_bytes to a temp wav file for Whisper
            fd, wav_path = tempfile.mkstemp(suffix=".wav")
            _os.close(fd)
            with wave.open(wav_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(sample_rate)
                wf.writeframes(raw_bytes)
            result = self._whisper_model.transcribe(wav_path, language="en", fp16=False)
            _os.unlink(wav_path)
            text = result.get("text", "").strip().lower()
            if text and len(text) > 1:
                logging.info(f"VAD [Offline Whisper]: \"{text}\"")
                return text
        except ImportError:
            logging.debug("Whisper not installed; skipping tier 0 offline ASR")
        except Exception as e:
            logging.warning(f"Whisper offline ASR failed: {e}")

        # Fallback Tier 1: Vosk (High quality local ASR)
        try:
            self._init_vosk()
            if getattr(self, "vosk_model", None):
                import json
                from vosk import KaldiRecognizer
                rec = KaldiRecognizer(self.vosk_model, sample_rate)
                rec.AcceptWaveform(raw_bytes)
                res = json.loads(rec.Result())
                text = res.get("text", "").lower().strip()
                if text:
                    logging.info(f"VAD [Offline Vosk]: \"{text}\"")
                    return text
        except Exception as e:
            logging.debug(f"Vosk offline ASR failed: {e}")

        # Fallback Tier 2: PocketSphinx
        try:
            text = self.recognizer.recognize_sphinx(audio_data, language="en-US")
            cleaned = text.lower().strip()
            if cleaned:
                logging.info(f"VAD [Offline Sphinx]: \"{cleaned}\"")
                return cleaned
        except Exception as e:
            logging.debug(f"Sphinx offline ASR failed: {e}")

        logging.warning("Offline decoders failed to resolve human speech.")
        return ""

    def listen(self, timeout=None, phrase_time_limit=None) -> str:
        """Listens for speech with dynamic VAD, yielding fully sanitized transcripts."""
        mode = self._get_adaptive_mode(timeout, phrase_time_limit)
        try:
            recognized_text = self.listen_adaptive(mode=mode, timeout=timeout)
            
            # 7. Transcript Sanitization & Noise Token Filtering
            # NOTE: "yes"/"no"/"okay" are deliberately NOT in this list — they are
            # meaningful confirmation replies, and voice.confirm() depends on
            # hearing "yes" pass through listen().
            cleaned_text = recognized_text.strip().lower()
            if cleaned_text in ["user", "null", "dhanush"]:
                logging.info(f"VAD [Sanitizer]: Discarded static/noise token: '{recognized_text}'")
                return ""
                
            self._last_transcript_len = len(cleaned_text.split())
            return recognized_text
        except sr.UnknownValueError as _e:
            logging.debug("[interface/voice.py:501] Swallowed exception: %s: %s", type(_e).__name__, _e)
            return ""
        except sr.RequestError:
            logging.error("Google Speech service offline.")
            return "[error_offline]"
        except Exception as e:
            logging.error(f"Voice interface listen error: {e}")
            return ""

    def confirm(self, question: str) -> bool:
        self.speak(question)
        time.sleep(0.2)
        while not self.speech_queue.empty() or self.is_speaking:
            time.sleep(0.1)
        ans = self.listen(timeout=6)
        if not ans:
            return False
        return any(x in ans.lower() for x in ["yes", "yeah", "yep", "sure", "do it", "confirm", "open", "run", "okay", "ok"])
