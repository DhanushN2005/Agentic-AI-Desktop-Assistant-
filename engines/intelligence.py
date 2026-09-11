import time
import logging
from typing import List, Dict
from utils.config import Config
from engines.system import SystemCtrl

class IntelligenceEngine:
    """Proactive suggestion engine for Flexie 2.0."""
    def __init__(self, orchestrator):
        self.flexie = orchestrator
        self.logger = logging.getLogger("FlexieIntelligence")
        self.last_suggestion_time = 0
        self.suggestion_cooldown = 300 # 5 minutes
        self.context_history: List[str] = []
        
        # Knowledge of features for the AI to suggest
        self.features_map = {
            "developer_mode": "Advanced debugging, project explanation, and terminal execution.",
            "auto_save": "Automatically saves your work in active windows every minute.",
            "vision_analyze": "Taking a screenshot and analyzing what is on your screen.",
            "briefing": "Morning summary of news, weather, and emails.",
            "clipboard_analysis": "Analyzing and summarizing text you've copied.",
            "organize_desktop": "Cleaning up your desktop files into categories.",
            "hacker_mode": "Silent, autonomous tool execution without confirmation."
        }

    def analyze_context(self, current_cmd: str = None) -> str:
        """Analyzes recent activity and system state to suggest a feature."""
        now = time.time()
        if now - self.last_suggestion_time < self.suggestion_cooldown:
            return None
            
        active_window = SystemCtrl.get_active_window_title()
        system_stats = SystemCtrl.cpu_ram()
        
        # Build a prompt for the AI to decide if a suggestion is needed
        prompt = f"""
        User Context:
        - Active Window: {active_window}
        - System Stats: {system_stats}
        - Recent Command: {current_cmd}
        
        Available Flexie Features:
        {self.features_map}
        
        Based on this, should I suggest a feature to the user? 
        If yes, respond ONLY with the feature_key and a 1-sentence helpful suggestion.
        If no, respond with 'NONE'.
        Example: auto_save | I noticed you're working in Word, would you like me to enable auto-save for you?
        """
        
        try:
            decision = self.flexie.brain.ask(prompt, system_override="You are Flexie's Proactive Intelligence. Be helpful but not annoying.")
            if "NONE" in decision.upper() or "|" not in decision:
                return None
                
            key, suggestion = decision.split("|", 1)
            self.last_suggestion_time = now
            return suggestion.strip()
        except Exception as e:
            self.logger.error(f"Intelligence analysis error: {e}")
            return None

    def get_feature_hint(self, topic: str) -> str:
        """Returns a hint about how to use a specific feature."""
        prompt = f"The user asked about '{topic}'. Briefly explain the most relevant Flexie 2.0 feature they can use for this. Be concise."
        return self.flexie.brain.ask(prompt)
