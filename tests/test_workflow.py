from core.workflow_gatekeeper import ClassificationType, WorkflowGatekeeper
from core.workflow_parser import WorkflowParser


def test_simple_two_step_workflow():
    is_simple, steps = WorkflowParser.parse_simple_workflow("open chrome and open vscode")
    assert is_simple is True
    assert len(steps) == 2
    assert "open chrome" in steps
    assert "open vscode" in steps


def test_three_step_workflow():
    is_simple, steps = WorkflowParser.parse_simple_workflow(
        "search for photosynthesis and create a document and paste the result"
    )
    assert is_simple is True
    assert len(steps) == 3


def test_then_workflow():
    is_simple, steps = WorkflowParser.parse_simple_workflow("open chrome, then open vscode")
    assert is_simple is True
    assert "open chrome" in steps
    assert "open vscode" in steps


def test_filler_words_stripped():
    is_simple, steps = WorkflowParser.parse_simple_workflow(
        "please open chrome and open vscode"
    )
    assert is_simple is True
    assert len(steps) == 2


def test_pronoun_escalates_to_semantic():
    is_simple, steps = WorkflowParser.parse_simple_workflow("delete it")
    assert is_simple is False
    assert steps == []


def test_pronoun_inside_word_does_not_escalate():
    # "submit" contains "it" but not as a standalone word — must NOT escalate.
    is_simple, steps = WorkflowParser.parse_simple_workflow("submit the form")
    assert is_simple is False
    assert steps == []


def test_conditional_escalates_to_semantic():
    is_simple, steps = WorkflowParser.parse_simple_workflow(
        "research quantum computing because I need it"
    )
    assert is_simple is False
    assert steps == []


def test_single_action_not_a_workflow():
    is_simple, steps = WorkflowParser.parse_simple_workflow("open chrome")
    assert is_simple is False
    assert steps == []


def test_gatekeeper_deterministic_compound():
    assert WorkflowGatekeeper().classify("open chrome and open vscode") == ClassificationType.DETERMINISTIC


def test_gatekeeper_pronoun_is_semantic():
    assert WorkflowGatekeeper().classify("delete it") == ClassificationType.SEMANTIC


def test_gatekeeper_hybrid():
    assert WorkflowGatekeeper().classify("research quantum computing") == ClassificationType.HYBRID


def test_gatekeeper_pronoun_plus_hybrid():
    assert WorkflowGatekeeper().classify("summarize that file") == ClassificationType.HYBRID


def test_gatekeeper_conditional_is_semantic():
    assert WorkflowGatekeeper().classify("save this because I need it") == ClassificationType.SEMANTIC


def test_gatekeeper_substring_no_false_positive():
    assert WorkflowGatekeeper().classify("submit the form") == ClassificationType.DETERMINISTIC
