import pyttsx3
import speech_recognition as sr
import threading
import logging
import time
import queue
import pythoncom

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
        
        # TTS dynamic parameters (modulatable by orchestrator commands)
        self.speech_rate = 1 
        self.speech_volume = 100
        
        # Shared TTS Engine
        self.engine_lock = threading.Lock()
        self._engine = None
        
        # Test engine and list voices
        try:
            temp = pyttsx3.init()
            print("\n[Voice Setup] Available Voices:")
            for i, v in enumerate(temp.getProperty('voices')):
                print(f" - Voice {i}: {v.name}")
        except: pass
        
        # Start speech thread
        self.speech_thread = threading.Thread(target=self._speech_worker, daemon=True)
        self.speech_thread.start()
        
        # 1. Establish persistent open microphone stream context to avoid device locking failures
        self._mic = sr.Microphone()
        self._mic_context = None
        try:
            logging.info("Voice: Initializing persistent microphone stream...")
            self._mic_context = self._mic.__enter__()
            logging.info("Voice: Calibrating microphone for ambient noise floor...")
            self.recognizer.adjust_for_ambient_noise(self._mic, duration=1.5)
            logging.info(f"Voice: Calibration complete. Dynamic threshold baseline set to {self.recognizer.energy_threshold:.1f}")
        except Exception as ce:
            logging.error(f"Voice: Persistent mic initialization/calibration failed: {ce}")

    def _speak_powershell(self, text: str) -> bool:
        """Speaks text out-of-process via PowerShell System.Speech, supporting instant interruption."""
        logging.info(f"TTS [PowerShell]: Speaking: '{text}'")
        try:
            import subprocess
            clean_text = text.replace("'", "''")
            
            # PowerShell command: Set rate and volume dynamically and speak
            cmd = (
                "Add-Type -AssemblyName System.Speech; "
                "$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                f"$synth.Rate = {self.speech_rate}; "
                f"$synth.Volume = {self.speech_volume}; "
                f"$synth.Speak('{clean_text}')"
            )
            
            # Launch hidden PowerShell process
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            self._active_speech_proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-Command", cmd],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                startupinfo=startupinfo
            )
            
            # Wait for execution to finish, checking for interruption in a loop
            while self._active_speech_proc.poll() is None:
                if self.interrupt_speech:
                    logging.info("TTS [PowerShell]: Interruption detected. Terminating speech process.")
                    try:
                        self._active_speech_proc.terminate()
                        self._active_speech_proc.wait(timeout=1.0)
                    except: pass
                    self.interrupt_speech = False
                    self._active_speech_proc = None
                    return False
                time.sleep(0.02)
                
            self._active_speech_proc = None
            return True
        except Exception as e:
            logging.error(f"PowerShell TTS Exception: {e}")
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
                
                # Physical Heartbeat Beep
                try:
                    import winsound
                    winsound.Beep(600, 50) # Subtle start beep
                except: pass

                self.is_speaking = True
                self._speak_start_time = time.time()
                
                # P0 Feature 4: Voice Interrupt System - disabled to avoid mic conflict with persistent stream
                # The persistent VAD stream (listen_adaptive) already handles barge-in via is_speaking flag
                pass

                self._speak_powershell(text)
                self.is_speaking = False
                
                self.speech_queue.task_done()
                logging.info("TTS End.")
            except queue.Empty:
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
            except queue.Empty:
                break

    def speak(self, text: str, interrupt: bool = False):
        """Splits long text into sentences for streaming playback (Latency Optimization)."""
        if not text: return
        
        # Suppression filter for duplicate announcements within 4 seconds
        if text == self.last_spoken_text and (time.time() - self.last_spoken_time < 4.0):
            logging.info(f"TTS [Repetition Suppressed]: '{text}'")
            return
        self.last_spoken_text = text
        self.last_spoken_time = time.time()
        
        if interrupt:
            self.stop()
        
        # Regex to split by punctuation followed by space
        import re
        sentences = re.split(r'(?<=[.!?])\s+', text)
        
        for sentence in sentences:
            if sentence.strip():
                self.speech_queue.put(sentence.strip())
        
        # Give the thread a tiny moment to pick it up and set is_speaking=True
        time.sleep(0.05)

    def _get_adaptive_mode(self, timeout=None, phrase_time_limit=None) -> str:
        """Dynamically infers the best listening mode (fast, normal, conversation) based on interaction context."""
        if timeout is not None and timeout <= 5:
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
        except: pass

    def listen_adaptive(self, mode="normal") -> str:
        """Adaptive real-time listening featuring persistent mic streaming, RMS VAD, and echo-safe endpoints."""
        start_time = time.time()
        
        # Ensure lazy instantiation of persistent stream context if needed
        if not hasattr(self, '_mic') or self._mic is None:
            self._mic = sr.Microphone()
        if not getattr(self, '_mic_context', None):
            try:
                self._mic_context = self._mic.__enter__()
            except Exception as e:
                logging.error(f"VAD Persistent Mic stream lazy init failed: {e}")
                return ""

        # 1. Target speech timeouts (FAST: 0.5s, NORMAL: 0.7s, CONVERSATION: 1.0s base)
        if mode == "fast":
            silence_timeout = 0.5
        elif mode == "conversation":
            silence_timeout = 1.0  # Base conversation timeout, scales dynamically
        else:
            silence_timeout = 0.7

        logging.info(f"VAD [Listening]: Mode={mode.upper()}, SilenceTimeout={silence_timeout}s")
        
        import struct
        import math
        
        try:
            source = self._mic
            stream = source.stream
            sample_rate = source.SAMPLE_RATE
            sample_width = source.SAMPLE_WIDTH
            
            # 0.06 seconds per frame for even higher resolution & under-1.5s total latency
            chunk_size = int(sample_rate * 0.06)
            
            # Setup recognizer parameters
            self.recognizer.pause_threshold = silence_timeout
            self.recognizer.phrase_threshold = 0.3
            self.recognizer.non_speaking_duration = 0.5
            
            # Baseline energy threshold
            noise_floor = self.recognizer.energy_threshold
            
            audio_buffer = bytearray()
            speech_started = False
            silence_start_time = None
            total_duration = 0.0
            active_speech_duration = 0.0
            last_partial_time = time.time()
            
            # Timeout for starting to speak (7.0 seconds total wait window)
            max_wait_time = 7.0
            wait_elapsed = 0.0
            err_count = 0
            
            logging.info("VAD: Reading persistent hardware audio stream...")
            self.send_to_ui("STATE", "LISTENING")
            
            while True:
                # Add tiny CPU sleep balance (stream.read is already blocking)
                time.sleep(0.01)
                
                try:
                    raw_chunk = stream.read(chunk_size)
                    
                    if getattr(self, 'is_speaking', False):
                        # Hard mute: prevent feedback loop - but with timeout to avoid stuck mute
                        # If speaking for >8s, allow mic anyway (TTS likely stuck)
                        if time.time() - getattr(self, '_speak_start_time', 0) > 8.0:
                            logging.warning("VAD: is_speaking stuck >8s, forcing unmute")
                            self.is_speaking = False
                        else:
                            audio_buffer.clear()
                            total_duration = 0.0
                            wait_elapsed = 0.0
                            continue
                        
                    audio_buffer.extend(raw_chunk)
                    total_duration += 0.06
                    
                    count = len(raw_chunk) // 2
                    if count == 0:
                        continue
                    
                    shorts = struct.unpack(f"{count}h", raw_chunk)
                    sum_squares = sum((s / 32768.0) ** 2 for s in shorts)
                    rms = math.sqrt(sum_squares / count) * 1000
                    
                    # Optional webrtcvad: if installed, use it for better detection
                    try:
                        import webrtcvad
                        vad_obj = getattr(self, '_webrtc_vad', None)
                        if vad_obj is None:
                            vad_obj = webrtcvad.Vad(2)
                            self._webrtc_vad = vad_obj
                        is_webrtc_speech = vad_obj.is_speech(raw_chunk, sample_rate)
                    except:
                        is_webrtc_speech = None
                    
                    # Adapt ambient noise floor during silent gaps (and only when AI is NOT speaking)
                    if not speech_started and not self.is_speaking:
                        noise_floor = (noise_floor * 0.95) + (rms * 0.05)
                        noise_floor = max(noise_floor, 35.0)
                        
                    # 3. Echo-Proof Barge-In & Self-Trigger Prevention
                    # Lowered from 1.8/120 to 1.5/80 - fixes voice not detected in noisy rooms
                    vad_threshold = max(noise_floor * 1.5, 80.0)
                        
                    is_active_speech = rms > vad_threshold
                    # Boost with webrtcvad if available
                    if is_webrtc_speech is not None:
                        is_active_speech = is_active_speech or is_webrtc_speech
                    
                    if is_active_speech:
                        active_speech_duration += 0.06
                        if not speech_started:
                            speech_started = True
                            logging.info(f"VAD [Speech Started]: Energy={rms:.1f} vs Threshold={vad_threshold:.1f}. Buffering active.")
                        silence_start_time = None
                        
                        # Dynamic partial recognition in background thread to achieve streaming feel
                        buf_len = len(audio_buffer)
                        if buf_len > (sample_rate * sample_width * 1.8) and (time.time() - last_partial_time > 1.5):
                            last_partial_time = time.time()
                            def run_partial_asr(buf_slice):
                                try:
                                    partial_audio = sr.AudioData(buf_slice, sample_rate, sample_width)
                                    partial_text = self.recognizer.recognize_google(partial_audio, language=self.lang).lower().strip()
                                    if partial_text:
                                        logging.info(f"VAD [Partial ASR]: \"{partial_text}...\"")
                                        self.send_to_ui("PARTIAL", partial_text + "...")
                                except:
                                    pass
                            threading.Thread(target=run_partial_asr, args=(bytes(audio_buffer),), daemon=True).start()
                        else:
                            self.send_to_ui("PARTIAL", "Listening...")
                    else:
                        if speech_started:
                            if silence_start_time is None:
                                silence_start_time = time.time()
                            else:
                                elapsed_silence = time.time() - silence_start_time
                                
                                # Adapt timeout based on mode, but STRICTLY cap to reduce lag
                                if mode == "fast":
                                    current_timeout = 0.5
                                else:
                                    current_timeout = 0.7
                                    
                                if elapsed_silence >= current_timeout:
                                    logging.info(f"VAD [Speech Ended]: Paused {elapsed_silence:.1f}s >= {current_timeout:.1f}s. Finalizing.")
                                    break
                        else:
                            wait_elapsed += 0.06
                            if wait_elapsed >= max_wait_time:
                                logging.info("VAD [Timeout]: No human voice detected.")
                                return ""
                                
                    # Safety loop cap
                    if total_duration >= 12.0:
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
                                except: pass
                            self._mic = sr.Microphone()
                            self._mic_context = self._mic.__enter__()
                            stream = self._mic.stream
                            logging.info("VAD: Mic stream context re-instantiated successfully.")
                        except Exception as re_err:
                            logging.error(f"VAD: Re-instantiation of mic context failed: {re_err}")
                        err_count = 0
                    time.sleep(0.2)
                    
            if len(audio_buffer) == 0:
                return ""
                
            elapsed_latency = time.time() - start_time
            logging.info(f"VAD [Timing]: Total buffer capture time: {elapsed_latency:.2f}s. Invoking Google ASR.")
            self.send_to_ui("STATE", "THINKING")
            
            # ASR recognition call
            from utils.helpers import is_online
            audio_data = sr.AudioData(bytes(audio_buffer), sample_rate, sample_width)
            
            recognized_text = ""
            if is_online():
                try:
                    text = self.recognizer.recognize_google(audio_data, language=self.lang)
                    recognized_text = text.lower().strip()
                    logging.info(f"VAD [Recognized Online]: \"{recognized_text}\"")
                except Exception as online_err:
                    logging.warning(f"Online ASR failed, falling back to offline: {online_err}")
                    recognized_text = self._recognize_offline(audio_data, bytes(audio_buffer), sample_rate)
            else:
                logging.info("System is offline. Initiating offline ASR pipeline...")
                recognized_text = self._recognize_offline(audio_data, bytes(audio_buffer), sample_rate)
                
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
            
        # Fallback Tier 2: PocketSphinx (Standard SpeechRecognition offline fallback)
        try:
            text = self.recognizer.recognize_sphinx(audio_data, language="en-US")
            cleaned = text.lower().strip()
            if cleaned:
                logging.info(f"VAD [Offline Sphinx]: \"{cleaned}\"")
                return cleaned
        except Exception as e:
            logging.debug(f"Sphinx offline ASR failed: {e}")

        # Fallback Tier 3: Command Template Pattern Classifier (Heuristic fallback)
        logging.warning("Offline decoders failed to resolve human speech.")
        return ""

    def listen(self, timeout=None, phrase_time_limit=None) -> str:
        """Listens for speech with dynamic VAD, yielding fully sanitized transcripts."""
        mode = self._get_adaptive_mode(timeout, phrase_time_limit)
        try:
            recognized_text = self.listen_adaptive(mode=mode)
            
            # 7. Transcript Sanitization & Noise Token Filtering
            cleaned_text = recognized_text.strip().lower()
            if cleaned_text in ["user", "null", "dhanush", "okay", "yes", "no"]:
                logging.info(f"VAD [Sanitizer]: Discarded static/noise token: '{recognized_text}'")
                return ""
                
            self._last_transcript_len = len(cleaned_text.split())
            return recognized_text
        except sr.UnknownValueError:
            return ""
        except sr.RequestError:
            logging.error("Google Speech service offline.")
            return "[error_offline]"
        except Exception as e:
            logging.error(f"Voice interface listen error: {e}")
            return ""

    def confirm(self, question: str) -> bool:
        self.speak(question)
        while self.is_speaking:
            time.sleep(0.1)
        ans = self.listen(timeout=3)
        return any(x in ans for x in ["yes", "yeah", "do it", "sure", "confirm"])
