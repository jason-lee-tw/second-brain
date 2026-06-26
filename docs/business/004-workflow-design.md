# Workflow Design

## Two Independent Graphs

The system has two LangGraph graphs that share the database but never share runtime state:

| Graph | Trigger | State |
|-------|---------|-------|
| **Query Graph** | `POST /query` | `SecondBrainState` |
| **Ingestion Graph** | `POST /ingest/file`, `POST /ingest/url` | `IngestionState` |

---

## 1. User Query Workflow

### Flow

```mermaid
flowchart TD
    A([POST /query\nmessage + sessionId]) --> B

    B["PIIRedactionNode · inbound\nredact messages[-1].content\nreplace with typed placeholders\nNAME · EMAIL · PHONE · ADDRESS · ID · CARD · MEDICAL"]
    B --> C

    C["MemoryRetrievalNode\ncosine similarity on learned_facts + model_corrections\npopulates retrieved_memory"]
    C --> D

    D["Orchestrator · claude-haiku-4-5\nreads messages[-1] + retrieved_memory\nroutes via LangGraph Send fan-out"]

    D -->|rag| E
    D -->|web| F
    D -->|both| E & F
    D -->|neither| G

    E["RAG Retrieval\ntool call\npgvector cosine top-k=5\nembeds query via Ollama"]
    F["Web Research · claude-haiku-4-5\nTavily search top-3 results"]
    G["pass through\n(chat history + memory only)"]

    E --> H
    F --> H
    G --> H

    H["Synthesis · claude-sonnet-4-6\ncombines rag_results + web_results\n+ retrieved_memory + messages\n→ final_answer + confidence 0–1"]

    H -->|confidence < 0.7| H1["set is_uncertain=True\nawaiting_correction=True"]
    H -->|confidence >= 0.7| H2["is_uncertain=False"]

    H1 --> I
    H2 --> I

    I["PIIRedactionNode · outbound\nredact final_answer\nbefore appending to messages / chat history"]
    I --> J

    J["Memory Agent · claude-haiku-4-5\nwith_structured_output MemoryAgentOutput\nclassifies via MemoryCase"]

    J -->|FACT_EXTRACTION\ndefault| J1["extract self-referential facts\n→ fact_updates"]
    J -->|CORRECTION\nawaiting_correction=True + user corrects| J2["walk messages by type\nextract correction + root_cause\n→ correction_updates\nreset awaiting_correction=False"]
    J -->|CORRECTION\nawaiting_correction=True + unrelated query| J3["reset awaiting_correction=False\nnormal fact extraction"]
    J -->|CONFLICT_RESOLUTION\nawaiting_conflict_clarification=True| J4["resolve conflict\nreset awaiting_correction=False"]

    J1 --> K
    J2 --> K
    J3 --> K
    J4 --> K

    K["MemoryPersistenceNode\nwrites fact_updates → learned_facts\nwrites correction_updates → model_corrections\ngenerates embeddings via Ollama\nper-fact retry x3"]

    K -->|conflict detected\ncosine > 0.85| L["set awaiting_conflict_clarification=True\npopulate ConflictContext\nsurface conflict in response"]
    K -->|no conflict| M["pass through"]

    L --> N
    M --> N

    N([Response\nanswer + sessionId + confidence\nisUncertain + conflictDetected + conflictContext])
```

### Agent Responsibilities

| Agent | Model | Responsibility |
|-------|-------|----------------|
| PIIRedactionNode (in) | rule-based | Redact PII from `messages[-1]` before any LLM sees it |
| MemoryRetrievalNode | tool call | Cosine similarity on `learned_facts` + `model_corrections`, populates `retrieved_memory` |
| Orchestrator | `claude-haiku-4-5` | Route to `rag` / `web` / `both` / `neither` using LangGraph `Send` for fan-out |
| RAG Retrieval | tool call | Embed query via Ollama, pgvector top-k=5 from `document_chunks` |
| Web Research | `claude-haiku-4-5` | Tavily search, top-3 results |
| Synthesis | `claude-sonnet-4-6` | Produce `final_answer` + `confidence`. Sets `is_uncertain=True` + `awaiting_correction=True` when `confidence < 0.7` |
| PIIRedactionNode (out) | rule-based | Redact `final_answer` before persisting to chat history |
| Memory Agent | `claude-haiku-4-5` | Classify turn as `FACT_EXTRACTION` / `CORRECTION` / `CONFLICT_RESOLUTION`, output structured `MemoryAgentOutput` |
| MemoryPersistenceNode | tool call | Write facts + corrections with embeddings; conflict-check via cosine similarity (threshold 0.85) |

### State Flag Invariants

`awaiting_correction` and `awaiting_conflict_clarification` are **mutually exclusive**. Entering `CONFLICT_RESOLUTION` always resets `awaiting_correction=False`.

Session continuity: `sessionId` is the LangGraph `threadId`. `null` = new thread; returning UUID7 continues the same thread via `AsyncPostgresSaver` checkpointing.

---

## 2. Data Ingestion Workflow

### File Ingestion Flow

```mermaid
flowchart TD
    A(["POST /ingest/file\nor\nfiles: list[str] from URL ingestion"]) --> B

    B["move file → in_progress\ncheckpoint state"]
    B --> C

    C["Ingestion Agent · claude-haiku-4-5\n1. hybrid chunk by heading / paragraph / sentence\n2. generate 50–100 token contextual header per chunk\n3. embed via Ollama qwen3-embedding:0.6b\n4. upsert to document_chunks"]

    C -->|success| D
    C -->|failure| E

    D["move in_progress → processed\n(temp/processed/)"]
    E{"retry_count < 3?"}

    E -->|yes| F["increment retry_count\nmove to retry_queue"]
    E -->|no| G["move to failed\n(temp/failed/) — terminal"]

    D --> H
    F --> H
    G --> H

    H{"retry_queue\nnon-empty?"}
    H -->|yes| B
    H -->|no| I

    I(["Response\nnumberOfFilePassed + failedFiles"])
```

### URL Ingestion Flow

```mermaid
flowchart LR
    A["POST /ingest/url\nurls: list[str]"] --> B["Tavily crawl\nextract page content"]
    B --> C["Save as .md\ntemp/pending-digest-docs/"]
    C --> D["Trigger file ingestion\n(same Ingestion Graph)"]
```

### Document Chunking Strategy

```mermaid
flowchart TD
    A([Raw document]) --> B{"Content type?"}

    B -->|code fence| C["Atomic chunk\nnever split inside ```"]
    B -->|meeting transcript| D["Split at sentence boundaries\ntarget 256 tokens · max 512 · overlap 0"]
    B -->|markdown article/note| E["Split order:\n1. H1/H2/H3 headings\n2. blank lines between paragraphs\n3. sentence boundaries if section exceeds max\ntarget 512 tokens · max 1024 · overlap 64"]

    C --> F
    D --> F
    E --> F

    F["Deduplication check\nMD5 hash vs ingested_documents\nskip if already ingested"]
    F -->|new document| G["Generate contextual header per chunk\n50–100 tokens via claude-haiku-4-5\n'This chunk is from [title], section [H1>H2], covering [topic]'"]
    F -->|duplicate| Z([Skip])

    G --> H["Embed chunk + header\nOllama qwen3-embedding:0.6b\nVECTOR(1024)"]
    H --> I["Upsert to document_chunks\nstore heading_path + content_type in metadata"]
```

### File Folder Structure

```
temp/
  pending-digest-docs/   ← drop .md files here; POST /ingest/file reads from here
  processed/             ← moved here after successful ingestion
  failed/                ← moved here after 3 retries exhausted
```

---

## 3. Memory System Workflow

### Fact Lifecycle

```mermaid
flowchart TD
    A["User message contains self-referential fact"] --> B["Memory Agent extracts fact\ncase: FACT_EXTRACTION"]
    B --> C["MemoryPersistenceNode\ncosine similarity check vs learned_facts\nthreshold: 0.85"]

    C -->|no conflict| D["Embed fact via Ollama\nupsert to learned_facts"]
    C -->|conflict detected| E["Populate ConflictContext\nexisting · existing_id · new\nset awaiting_conflict_clarification=True"]

    E --> F["Surface conflict in response\nask user to clarify"]
    F --> G["Next turn: Memory Agent\ncase: CONFLICT_RESOLUTION\ndelete conflicting IDs\nwrite resolved fact"]
```

### Correction Lifecycle

```mermaid
flowchart TD
    A["Synthesis confidence < 0.7"] --> B["Set is_uncertain=True\nawaiting_correction=True\npersisted via LangGraph checkpointing"]
    B --> C["Response surfaces uncertainty to user"]

    C --> D{"Next user message"}
    D -->|is a correction| E["Memory Agent\ncase: CORRECTION\nwalk messages by type\nextract original_answer + correction + root_cause"]
    D -->|unrelated query| F["Memory Agent\nreset awaiting_correction=False\nnormal FACT_EXTRACTION"]

    E --> G["MemoryPersistenceNode\nupsert to model_corrections\nembed correction field\nreset awaiting_correction=False"]
```
