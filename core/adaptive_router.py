import json
import logging
import os
import re


class AdaptiveRouter:
    """
    Learns from past successful semantic routes to short-circuit the planner
    and directly map frequent commands to their resulting atomic actions.
    Now features fast fuzzy matching via Jaccard similarity to catch phrasing variations.
    """
    def __init__(self, history_file: str = "context/routing_history.json"):
        self.logger = logging.getLogger("Flexie.AdaptiveRouter")
        self.history_file = history_file
        self.routes = {}
        self._load()

    def _load(self):
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file) as f:
                    self.routes = json.load(f)
            except Exception as e:
                self.logger.error(f"[ROUTER] Failed to load adaptive routes: {e}")

    def _save(self):
        os.makedirs(os.path.dirname(self.history_file), exist_ok=True)
        try:
            with open(self.history_file, "w") as f:
                json.dump(self.routes, f, indent=2)
        except Exception as e:
            self.logger.error(f"[ROUTER] Failed to save adaptive routes: {e}")

    @staticmethod
    def _jaccard_similarity(str1: str, str2: str) -> float:
        """Calculates token-based Jaccard similarity between two strings."""
        set1 = set(re.findall(r'\w+', str1.lower()))
        set2 = set(re.findall(r'\w+', str2.lower()))
        if not set1 or not set2:
            return 0.0
        intersection = set1.intersection(set2)
        union = set1.union(set2)
        return float(len(intersection)) / len(union)

    def record_route(self, raw_command: str, resolved_intent: str, success: bool):
        """
        Records a mapping from a raw user command to a resolved intent if successful.
        """
        if not success:
            return

        cmd = raw_command.lower().strip()
        if cmd not in self.routes:
            self.routes[cmd] = {"intent": resolved_intent, "hits": 1}
        else:
            if self.routes[cmd]["intent"] == resolved_intent:
                self.routes[cmd]["hits"] += 1

        # Persist after every verified success so learnings survive restarts
        self._save()

    def get_cached_route(self, raw_command: str) -> str | None:
        """
        Returns a cached intent if the user has successfully executed a highly similar
        command multiple times. Uses exact match first, then falls back to fuzzy.
        """
        cmd = raw_command.lower().strip()

        # 1. Fast path: Exact match
        exact_route = self.routes.get(cmd)
        if exact_route and exact_route["hits"] >= 3:
            self.logger.info(f"[ROUTER] Adaptive exact match '{cmd}' -> '{exact_route['intent']}' (Hits: {exact_route['hits']})")
            return exact_route["intent"]

        # 2. Semantic Cache: Fuzzy match via token containment + similarity floor
        # Pure Jaccard at 0.85 is unreachable for short commands (a 2-token cached
        # command can score at most 0.67), so we instead require that the query
        # contains most of the cached command's tokens, with a loose similarity
        # floor to reject unrelated commands.
        best_match_cmd = None
        best_sim = 0.0
        best_route = None

        for cached_cmd, route_data in self.routes.items():
            if route_data["hits"] >= 3:
                cached_tokens = set(re.findall(r'\w+', cached_cmd.lower()))
                query_tokens = set(re.findall(r'\w+', cmd))
                if not cached_tokens:
                    continue
                containment = len(cached_tokens & query_tokens) / len(cached_tokens)
                sim = self._jaccard_similarity(cmd, cached_cmd)
                if containment >= 0.8 and sim >= 0.4 and sim > best_sim:
                    best_sim = sim
                    best_match_cmd = cached_cmd
                    best_route = route_data

        if best_route:
            self.logger.info(f"[ROUTER] Adaptive fuzzy match '{cmd}' ≈ '{best_match_cmd}' ({best_sim:.2f}) -> '{best_route['intent']}'")
            return best_route["intent"]

        return None
