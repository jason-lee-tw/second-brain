# Task 2 Log: PII Service

## Task Context

### Plan Section
### Task 2: PII Service

**Files:**
- Create: `apps/backend/src/second_brain/services/__init__.py`
- Create: `apps/backend/src/second_brain/services/pii.py`
- Create: `apps/backend/tests/unit/test_services/__init__.py`
- Create: `apps/backend/tests/unit/test_services/test_pii.py`

**Dependency:** Install `presidio-analyzer presidio-anonymizer spacy` and download the spaCy model before running tests:
```bash
pip install presidio-analyzer presidio-anonymizer spacy
python -m spacy download en_core_web_lg
```

- [ ] **Step 1: Write the failing tests**

```python
# apps/backend/tests/unit/test_services/test_pii.py
import pytest
from second_brain.services.pii import redact_pii


def test_redact_person_name():
    result = redact_pii("Hello, my name is John Smith.")
    assert "[NAME]" in result
    assert "John Smith" not in result


def test_redact_email():
    result = redact_pii("Contact me at alice@example.com for details.")
    assert "[EMAIL]" in result
    assert "alice@example.com" not in result


def test_redact_phone_number():
    result = redact_pii("Call me at 555-867-5309 anytime.")
    assert "[PHONE]" in result
    assert "867-5309" not in result


def test_no_pii_passthrough():
    text = "The weather in Tokyo is sunny today."
    result = redact_pii(text)
    # Non-PII text must not be mangled
    assert "weather" in result
    assert "sunny" in result


def test_multiple_pii_types_in_one_string():
    text = "Jane Doe's email is jane.doe@corp.com and her phone is +1-800-555-0199."
    result = redact_pii(text)
    assert "Jane Doe" not in result
    assert "jane.doe@corp.com" not in result
    assert "[NAME]" in result
    assert "[EMAIL]" in result


def test_empty_string():
    result = redact_pii("")
    assert result == ""


def test_credit_card_redaction():
    result = redact_pii("My card number is 4111111111111111.")
    assert "4111111111111111" not in result
    assert "[CARD]" in result
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd apps/backend && pytest tests/unit/test_services/test_pii.py -v
```

Expected: `ModuleNotFoundError` for `second_brain.services.pii`.

- [ ] **Step 3: Implement the PII service**

```python
# apps/backend/src/second_brain/services/__init__.py
# (empty)
```

```python
# apps/backend/src/second_brain/services/pii.py
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

_ENTITIES = [
    "PERSON",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "LOCATION",
    "DATE_TIME",
    "CREDIT_CARD",
    "IBAN_CODE",
    "MEDICAL_LICENSE",
    "NRP",
    "US_SSN",
    "US_PASSPORT",
    "IP_ADDRESS",
]

_OPERATORS: dict[str, OperatorConfig] = {
    "PERSON": OperatorConfig("replace", {"new_value": "[NAME]"}),
    "EMAIL_ADDRESS": OperatorConfig("replace", {"new_value": "[EMAIL]"}),
    "PHONE_NUMBER": OperatorConfig("replace", {"new_value": "[PHONE]"}),
    "LOCATION": OperatorConfig("replace", {"new_value": "[ADDRESS]"}),
    "DATE_TIME": OperatorConfig("replace", {"new_value": "[DATE]"}),
    "CREDIT_CARD": OperatorConfig("replace", {"new_value": "[CARD]"}),
    "IBAN_CODE": OperatorConfig("replace", {"new_value": "[CARD]"}),
    "MEDICAL_LICENSE": OperatorConfig("replace", {"new_value": "[MEDICAL]"}),
    "NRP": OperatorConfig("replace", {"new_value": "[ID]"}),
    "US_SSN": OperatorConfig("replace", {"new_value": "[ID]"}),
    "US_PASSPORT": OperatorConfig("replace", {"new_value": "[ID]"}),
    "IP_ADDRESS": OperatorConfig("replace", {"new_value": "[IP]"}),
}

# Module-level singletons — spaCy load is expensive, do it once
_analyzer = AnalyzerEngine()
_anonymizer = AnonymizerEngine()


def redact_pii(text: str) -> str:
    """Detect and redact PII from text using Presidio + spaCy en_core_web_lg.

    Returns the redacted text with typed placeholders such as [NAME], [EMAIL],
    [PHONE], [ADDRESS], [CARD], [MEDICAL], [ID], [DATE], [IP].
    """
    if not text:
        return text

    results = _analyzer.analyze(text=text, entities=_ENTITIES, language="en")
    if not results:
        return text

    anonymized = _anonymizer.anonymize(
        text=text,
        analyzer_results=results,
        operators=_OPERATORS,
    )
    return anonymized.text
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd apps/backend && pytest tests/unit/test_services/test_pii.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd apps/backend && git add \
  src/second_brain/services/__init__.py \
  src/second_brain/services/pii.py \
  tests/unit/test_services/__init__.py \
  tests/unit/test_services/test_pii.py
git commit -m "feat(pii): add PII redaction service using Presidio + spaCy"
```

### Acceptance Criteria
- AC-5: PII in user messages is redacted before reaching any LLM node
- AC-6: PII in `final_answer` is redacted before being persisted to `chat_history`

Note: this task builds the underlying `redact_pii()` mechanism only (Task 3 wires it into
the inbound/outbound graph nodes). AC-5/AC-6 depend on this service being correct.

### Repo Convention Deviations from Plan
- `services/__init__.py` and `tests/unit/test_services/__init__.py` already exist — not recreated.
- `presidio-analyzer`, `presidio-anonymizer`, `spacy` already in `apps/backend/pyproject.toml` — not re-installed.
- `en_core_web_lg` spaCy model already downloaded on this machine — not re-downloaded.
- Module style kept minimal per existing `services/embeddings.py` / `services/tavily.py` conventions.

## Attempt 1 — 2026-07-20T00:00:00Z

### Implementation Plan
- Write 7 failing tests in `test_services/test_pii.py` covering name, email, phone, passthrough, multiple PII types, empty string, credit card
- Run tests to confirm ModuleNotFoundError for `second_brain.services.pii`
- Implement `redact_pii()` using Presidio `AnalyzerEngine` + `AnonymizerEngine` with typed placeholder operators for all 12 entity types from the plan
- Run `just lint` and `just test-unit` from the worktree root

### Files Changed
- created `apps/backend/tests/unit/test_services/test_pii.py` — 7 unit tests for `redact_pii`
- created `apps/backend/src/second_brain/services/pii.py` — Presidio+spaCy PII redaction service

### New Tests
- `test_redact_person_name`
- `test_redact_email`
- `test_redact_phone_number`
- `test_no_pii_passthrough`
- `test_multiple_pii_types_in_one_string`
- `test_empty_string`
- `test_credit_card_redaction`

### Key Decisions
- Used the plan's exact test inputs verbatim (`555-867-5309`, `+1-800-555-0199`) — Presidio's default US phone recognizer caught both formats on the first attempt, so no test-input adjustment was needed.
- Did not recreate `services/__init__.py` / `test_services/__init__.py` — both already existed in this repo per the task's repo-convention notes.
- Kept the module docstring-free per existing `services/embeddings.py`/`services/tavily.py` style; only a one-line docstring on `redact_pii` itself.
- Worktree got a fresh `.venv` via `uv sync --all-extras`; the `en_core_web_lg` spaCy model (not in `pyproject.toml`, previously installed by hand into the main repo's `.venv`) had to be installed into the worktree venv too via `uv pip install` from the explosion/spacy-models wheel URL — resolved instantly from uv's local cache, no network download, and not added to `pyproject.toml`/`uv.lock` (worktree diff confirms no lockfile changes).

### Lint Output
PASS

### Test Output
PASS (92 passed, 7 new)

### Commit
`17b55af`

### Outcome: success
