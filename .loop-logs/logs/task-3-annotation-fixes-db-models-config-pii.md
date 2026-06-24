# Task 3: Annotation Fixes — db/models.py, config.py, services/pii.py

## Attempt 1

### Changes Made

- `apps/backend/src/second_brain/db/models.py`: Added `ClassVar` to typing import; annotated all 5 `__tablename__` fields with `ClassVar[str]`; fixed `thread_data: dict` to `dict[str, object]`; fixed `chunk_metadata: Optional[dict]` to `Optional[dict[str, str | int]]`
- `apps/backend/src/second_brain/config.py`: Added `# type: ignore[call-arg]` to `settings = Settings()`
- `apps/backend/src/second_brain/services/pii.py`: Added `# type: ignore[arg-type]` to `_anonymizer.anonymize(...)` call

### Test Outcome

`just test-unit`: 147 passed, 0 failed

### Lint Outcome

`just lint`: All checks passed

### Commit

`ececf99` — fix(types): ClassVar annotations and type-ignores for stub gaps

### Status: SUCCESS
