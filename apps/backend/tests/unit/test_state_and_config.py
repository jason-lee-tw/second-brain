from second_brain.graphs.state import (
    ConflictContext,
    MemoryAgentOutput,
    MemoryCase,
)


def test_conflict_context_has_required_fields():
    ctx = ConflictContext(existing="old fact", existing_id="uuid-1", new="new fact")
    assert ctx["existing"] == "old fact"
    assert ctx["existing_id"] == "uuid-1"
    assert ctx["new"] == "new fact"


def test_memory_case_values():
    assert MemoryCase.FACT_EXTRACTION == "fact_extraction"
    assert MemoryCase.CORRECTION == "correction"
    assert MemoryCase.CONFLICT_RESOLUTION == "conflict_resolution"


def test_memory_agent_output_defaults():
    output = MemoryAgentOutput(case=MemoryCase.FACT_EXTRACTION)
    assert output.fact_updates == []
    assert output.correction_updates == []


def test_memory_agent_output_with_facts():
    output = MemoryAgentOutput(
        case=MemoryCase.FACT_EXTRACTION,
        fact_updates=[
            {"fact": "user is a developer", "confidence": 0.9, "conflicts_with": []}
        ],
    )
    assert len(output.fact_updates) == 1


def test_memory_conflict_threshold_default():
    from second_brain.config import settings

    assert settings.memory_conflict_threshold == 0.95
