import time

class TTSGuard:
    """
    TTS Deduplication layer to prevent flooding the voice queue
    with identical messages (like repeated "Step 1" outputs).
    """
    def __init__(self, cache_timeout: float = 10.0):
        self._spoken_cache = {}
        self.cache_timeout = cache_timeout

    def should_speak(self, text: str) -> bool:
        """
        Returns True if the message should be spoken, False if it was
        spoken recently (within cache_timeout).
        """
        if not text:
            return False
            
        now = time.time()
        
        # Check cache
        if text in self._spoken_cache:
            if now - self._spoken_cache[text] < self.cache_timeout:
                return False
                
        # Register in cache
        self._spoken_cache[text] = now
        
        # Cleanup old entries to prevent memory leak
        keys_to_delete = [k for k, v in self._spoken_cache.items() if now - v > (self.cache_timeout * 1.5)]
        for k in keys_to_delete:
            del self._spoken_cache[k]
            
        return True
