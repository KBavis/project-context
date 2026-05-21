# Project Scoping Uplift: Final Implementation Plan

This document synthesizes all design decisions, edge case resolutions (Lost Updates, massive files, tool isolation), and structural designs into a concrete plan of attack.

---

## Phase 0: Prerequisite Data Providers (Issue #6)
*Laying the foundation to fetch PRs and Diffs.*

1. **`IssueTrackerDataProvider` Abstraction**
   - Implement `JiraDataProvider`.
   - Method: `resolve_stories(epic_keys: list[str]) -> list[str]`
2. **`RepositoryDataProvider` Extensions**
   - Extend `GithubDataProvider` to support resolving PRs by branch name (matching Jira story keys).
   - Method: `resolve_prs(story_keys: list[str]) -> list[int]`
   - Method: `get_pr_diffs(pr_numbers: list[int]) -> list[UnifiedDiff]` (Raw patch format)

---

## Phase 1: Database & Configuration
*Allowing projects to opt-in to this feature.*

1. **Update `ProjectData` Model**
   - Add `scope_by_issues: Mapped[bool] = mapped_column(default=False)`
   - Add `issue_tracker_provider: Mapped[str | None]` (e.g., `"jira"`)
2. **Alembic Migration**
   - Generate and apply migration for `project_data` table.
3. **Frontend / API Sync**
   - Expose these fields in the `Project` creation/update Pydantic schemas.

---

## Phase 2: Diff Parsing & File-Level Aggregation
*The core logic for processing what changed.*

1. **Diff Parser Service (`app/services/diff_parser.py`)**
   - Parse unified diff patches into structured hunks.
   - Implement the `classify_hunk` logic:
     - Both `+` and `-` -> `modified`
     - Only `+` -> `added`
     - Only `-` -> `deleted`
     - Only whitespace changes -> `context_only` (skip)
2. **File-Level Diff Aggregation**
   - Group all valid hunks by `file_path` across all resolved PRs.
   - Sort hunks chronologically by PR merge date.
   - Generate the `FileDiffHistory` string for each file:
     ```text
     [PROJECT CHANGE | src/auth/handler.py]
     This project made 2 changes to this file across PR #12, PR #42.
     
     --- Change 1 (PR #12 - MODIFIED) ---
     BEFORE: ...
     AFTER: ...
     ```

---

## Phase 3: Parent-Child Ingestion Pipeline
*Storing data to prevent "Lost Updates" while respecting token limits.*

1. **`resolve_and_store_project_diffs()` in `ChunkInsertionService`**
   - Called during `IngestionJobService.run_ingestion_job()` if `scope_by_issues == True`.
   - Clear existing diff chunks for this `project_id`.
   - Call DataProviders to get epics -> stories -> PRs -> Diffs.
   - Generate the `FileDiffHistory` strings (Phase 2).
2. **Parent Node Creation (DocStore)**
   - For each file, create a `TextNode` containing the full `FileDiffHistory`.
   - Metadata: `source_type="DIFF"`, `project_id`, `file_path`, `change_types` (list).
   - Save directly to Postgres DocStore.
3. **Child Node Creation (ChromaDB)**
   - Use `TokenTextSplitter` to split the `FileDiffHistory`.
   - Convert resulting chunks to `IndexNode`s (setting `index_id` to the Parent Node's ID).
   - Metadata: `source_type="DIFF"`, `project_id`, `parent_file_path`.
   - Insert into ChromaDB.

---

## Phase 4: Retrieval & Tool Separation
*Building the strict boundaries between general codebase and project changes.*

1. **Strict Tool Boundaries in `ChunkRetrievalService`**
   - Update `semantic_search()` and `grep_search()` to explicitly filter: `source_type != "DIFF"`.
2. **Implement Project-Scoped Retrievers**
   - **`search_project_semantic`**: 
     - Search ChromaDB with filter `source_type == "DIFF" AND project_id == current`.
     - Wrap the retriever in LlamaIndex's `RecursiveRetriever` so it automatically fetches the Parent Node (`FileDiffHistory`) from the DocStore when a Child `IndexNode` is matched.
   - **`search_project_grep`**:
     - Search Postgres DocStore directly matching `source_type == "DIFF" AND project_id == current`. Returns the full Parent Node.
3. **Implement `list_project_files` Tool**
   - Query DocStore metadata for all distinct `file_path` and `change_types` where `source_type == "DIFF" AND project_id == current`.

---

## Phase 5: Agent Prompt & Context Wiring
*Grounding the agent with the new tools.*

1. **Conditional Tool Registration (`Tools` class)**
   - Accept `project_scoping_enabled: bool`.
   - Register the 3 project tools (`search_project_semantic`, `search_project_grep`, `list_project_files`) only if True.
   - Update descriptions to emphasize "MODIFIED means BEFORE is gone, AFTER is current".
2. **Prompt Injection (`workflow.py`)**
   - Calculate the "Compact Summary" at agent startup (PR count, file count, top 10 files).
   - Inject the `project_scoping_rules.md` template fragment into the `ResearchAgent` prompt via `{project_scoping_context}`.
   - Include the Chronological Reasoning rule: "higher PR number = later change = current state".

---

## Summary of the Final Flow

1. **Ingestion**: Diffs are grouped by file into massive `FileDiffHistory` Parent nodes (Docstore). Small Child nodes are embedded (Chroma).
2. **Search**: Agent searches for a concept using a project tool.
3. **Retrieval**: Chroma matches a Child node. The Retriever automatically swaps it for the Parent node.
4. **Comprehension**: The Agent receives the entire, unbroken chronological history of the file, completely bypassing token limits and avoiding the "Lost Update" hallucination.
