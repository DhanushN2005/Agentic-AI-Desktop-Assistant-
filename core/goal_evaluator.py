"""
Goal Completion Evaluator — verifies that the original user goal was achieved.

Compares ORIGINAL_USER_GOAL against EXECUTION_STATE to determine if
the task is truly complete. Prevents premature success reporting.
"""
import os
import logging
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class GoalCheck:
    """A single check against the goal."""
    description: str
    passed: bool
    details: str = ""


@dataclass
class GoalEvaluation:
    """Result of evaluating goal completion."""
    original_goal: str
    complete: bool
    checks: List[GoalCheck] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "original_goal": self.original_goal,
            "complete": self.complete,
            "checks": [{"desc": c.description, "passed": c.passed, "details": c.details} for c in self.checks],
            "summary": self.summary,
        }


class GoalEvaluator:
    """
    Evaluates whether the original user goal was fully achieved.
    
    Usage:
        evaluator = GoalEvaluator()
        evaluation = evaluator.evaluate(
            original_goal="search code for binary search and save to Downloads/result.py",
            execution_state={
                "searched_code": True,
                "found_implementation": True,
                "file_saved": True,
                "file_path": "C:/Users/Dhanush/Downloads/result.py",
                "file_verified": True,
            }
        )
    """

    def __init__(self):
        self.logger = logging.getLogger("Flexie.GoalEvaluator")

    def evaluate(self, original_goal: str, execution_state: Dict[str, Any]) -> GoalEvaluation:
        """
        Evaluate if the original goal was achieved.
        
        Args:
            original_goal: The user's original command
            execution_state: Dictionary of what was actually done
        
        Returns:
            GoalEvaluation with pass/fail for each check
        """
        checks = []
        goal_lower = original_goal.lower()
        
        # Extract intent components from the goal
        wants_search = any(w in goal_lower for w in ["search", "find", "look for", "locate"])
        wants_local = any(w in goal_lower for w in ["code", "my code", "project", "codebase", "local", "this project"])
        wants_web = any(w in goal_lower for w in ["web", "online", "internet", "google", "youtube"])
        wants_save = any(w in goal_lower for w in ["save", "write", "create file", "store"])
        wants_extract = any(w in goal_lower for w in ["extract", "get", "pull", "copy"])
        wants_verify = any(w in goal_lower for w in ["verify", "check", "confirm"])
        
        # Check: Search was performed
        if wants_search:
            searched = execution_state.get("searched_code", False) or execution_state.get("searched_web", False)
            checks.append(GoalCheck(
                description="Search was performed",
                passed=searched,
                details=execution_state.get("search_method", "unknown"),
            ))
        
        # Check: Local search was used (not web) when user said "search the code"
        if wants_search and wants_local and not wants_web:
            used_local = execution_state.get("search_method", "") in ("local", "code_search", "file_search")
            checks.append(GoalCheck(
                description="Local code search was used (not web)",
                passed=used_local,
                details=f"Search method: {execution_state.get('search_method', 'unknown')}",
            ))
        
        # Check: Results were found
        if wants_search:
            found = execution_state.get("found_implementation", False) or execution_state.get("results_found", False)
            checks.append(GoalCheck(
                description="Implementation/results were found",
                passed=found,
                details=f"Found: {execution_state.get('results_count', 0)} matches",
            ))
        
        # Check: Content was extracted
        if wants_extract or (wants_save and wants_search):
            extracted = execution_state.get("content_extracted", False)
            checks.append(GoalCheck(
                description="Content was extracted",
                passed=extracted,
                details=execution_state.get("extraction_method", "unknown"),
            ))
        
        # Check: File was saved
        if wants_save:
            saved = execution_state.get("file_saved", False)
            file_path = execution_state.get("file_path", "")
            checks.append(GoalCheck(
                description="File was saved",
                passed=saved,
                details=f"Path: {file_path}" if file_path else "No path recorded",
            ))
        
        # Check: File is in correct location
        if wants_save:
            file_path = execution_state.get("file_path", "")
            correct_location = False
            if file_path:
                # Check if it's in the user's Downloads folder (common request)
                if "download" in goal_lower:
                    correct_location = "downloads" in file_path.lower() or "download" in file_path.lower()
                elif "desktop" in goal_lower:
                    correct_location = "desktop" in file_path.lower()
                elif "documents" in goal_lower:
                    correct_location = "documents" in file_path.lower()
                else:
                    # If no specific location mentioned, just check it was saved somewhere
                    correct_location = True
            checks.append(GoalCheck(
                description="File saved to correct location",
                passed=correct_location,
                details=f"Path: {file_path}" if file_path else "No path",
            ))
        
        # Check: File was verified
        if wants_save or wants_verify:
            file_path = execution_state.get("file_path", "")
            verified = execution_state.get("file_verified", False)
            if file_path and os.path.exists(file_path):
                size = os.path.getsize(file_path)
                checks.append(GoalCheck(
                    description="File exists and has content",
                    passed=size > 0,
                    details=f"Size: {size} bytes",
                ))
            elif file_path:
                checks.append(GoalCheck(
                    description="File exists and has content",
                    passed=False,
                    details=f"File not found: {file_path}",
                ))
        
        # Check: Appropriate filename
        if wants_save:
            file_path = execution_state.get("file_path", "")
            if file_path:
                filename = os.path.basename(file_path)
                has_name = bool(filename and filename != "untitled")
                checks.append(GoalCheck(
                    description="File has appropriate name",
                    passed=has_name,
                    details=f"Filename: {filename}",
                ))
        
        # Determine overall completion
        if not checks:
            complete = True
        else:
            complete = all(c.passed for c in checks)
        
        # Generate summary
        passed_count = sum(1 for c in checks if c.passed)
        total_count = len(checks)
        if complete:
            summary = f"Goal achieved: {passed_count}/{total_count} checks passed."
        else:
            failed = [c for c in checks if not c.passed]
            summary = f"Goal incomplete: {passed_count}/{total_count} checks passed. Failed: {', '.join(c.description for c in failed)}"
        
        return GoalEvaluation(
            original_goal=original_goal,
            complete=complete,
            checks=checks,
            summary=summary,
        )
