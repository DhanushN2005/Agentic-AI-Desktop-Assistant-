import json
import logging
import os
from typing import Dict, Any, List

class ExecutionNode:
    def __init__(self, node_id: str, type: str, content: str):
        self.node_id = node_id
        self.type = type # 'GOAL', 'PLAN', 'ACTION', 'RESULT', 'RECOVERY'
        self.content = content
        self.edges = []
        
    def add_edge(self, target_id: str, relationship: str):
        self.edges.append({"target": target_id, "rel": relationship})
        
    def to_dict(self):
        return {
            "id": self.node_id,
            "type": self.type,
            "content": self.content,
            "edges": self.edges
        }

class ExecutionGraph:
    """
    Stores execution traces as a directed graph.
    Useful for historical replays, debugging, and adaptive learning.
    """
    def __init__(self, storage_path: str = "context/graph_db.json"):
        self.logger = logging.getLogger("Flexie.ExecutionGraph")
        self.storage_path = storage_path
        self.nodes: Dict[str, ExecutionNode] = {}
        self._load()
        
    def add_node(self, node: ExecutionNode):
        self.nodes[node.node_id] = node
        self._save()
        
    def get_node(self, node_id: str) -> ExecutionNode:
        return self.nodes.get(node_id)
        
    def _load(self):
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r") as f:
                    data = json.load(f)
                    for n in data.get("nodes", []):
                        node = ExecutionNode(n["id"], n["type"], n["content"])
                        node.edges = n.get("edges", [])
                        self.nodes[node.node_id] = node
            except Exception as e:
                self.logger.error(f"[GRAPH] Failed to load execution graph: {e}")
                
    def _save(self):
        os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
        try:
            with open(self.storage_path, "w") as f:
                json.dump({
                    "nodes": [n.to_dict() for n in self.nodes.values()]
                }, f, indent=2)
        except Exception as e:
            self.logger.error(f"[GRAPH] Failed to save execution graph: {e}")
