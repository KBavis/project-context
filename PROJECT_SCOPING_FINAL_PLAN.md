# Project Scoping: Final Implementation Plan

> **Status:** Authoritative reference for implementing project-scoped repository ingestion and agent tooling.  
> **Approach:** **B — Finalized composition diff** (local clone + sequential patch application + net diff vs. base branch).  
> **Storage:** Same DocStore namespace and Chroma collection as existing code chunks; isolate project diff nodes via `source_type` + `project_id` metadata (not separate namespaces).  
> **Source of truth for implemented behavior:** Current codebase (e.g. `scope_by_issues` on `DataSource`, provider refactor) overrides older plan documents where they conflict.

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Locked Design Decisions](#2-locked-design-decisions)
3. [Current Implementation Status](#3-current-implementation-status)
4. [Architecture Overview](#4-architecture-overview)
5. [Data Models](#5-data-models)
6. [Composition Diff: Mechanism](#6-composition-diff-mechanism)
7. [Ingestion Flow](#7-ingestion-flow)
8. [Diff Parsing & FileDiffHistory](#8-diff-parsing--filediffhistory)
9. [Persistence: DocStore & Chroma](#9-persistence-docstore--chroma)
10. [Agent Tooling](#10-agent-tooling)
11. [Prompts & Anti-Hallucination](#11-prompts--anti-hallucination)
12. [Provider & API Extensions](#12-provider--api-extensions)
13. [Phased Implementation Roadmap](#13-phased-implementation-roadmap)
14. [Edge Cases & Fallbacks](#14-edge-cases--fallbacks)
15. [Operational & Infrastructure Notes](#15-operational--infrastructure-notes)
16. [Testing Strategy](#16-testing-strategy)
17. [Future Work](#17-future-work)
18. [Appendix: End-to-End Data Flow](#18-appendix-end-to-end-data-flow)

---

## 1. Problem Statement

Today, when a **Project** links to a **Repository DataSource**, the agent treats the entire repository as in scope. In practice, a project only changes a subset of the codebase (tracked via Jira epics → stories/tasks → commits whose messages reference those issue keys).

**Goal:** During ingestion, compute a **single net “composition diff”** per `(project, repository data source)` that represents *only* what that project changed—ignoring unrelated commits on the same branch. Persist that diff in DocStore + Chroma so the agent can:

- Search **project changes** with dedicated tools (semantic + grep).
- Search **full codebase** with existing tools for surrounding context.
- Traverse files via `view_file` / `list_directory` without restriction.

---

## 2. Locked Design Decisions

| Topic | Decision | Rationale |
|-------|----------|-----------|
| Scoping flag location | `DataSource.scope_by_issues` (implemented) | A data source is shared; scoping is a property of how that repo is ingested, not a per-project override that could disagree across projects. |
| How work is attributed | **Commit messages** containing resolved issue keys (from Jira epics) | More reliable than branch-name → PR heuristics; works with squash merges and multiple issues per commit. |
| Diff strategy | **Approach B — composition diff** | One net BEFORE/AFTER per file; net-zero changes disappear; UI-ready unified diff; no overlapping-hunk confusion for the agent. |
| DocStore namespace | **Same** as code: `str(data_source.id)` | User preference; filter with `source_type=DIFF` + `project_id`. |
| Chroma collection | **Same** project collection as code chunks | Filter with metadata; parent-child via `IndexNode.index_id`. |
| General search | `semantic_search` / `grep_search` exclude `source_type=DIFF` | Prevents diff chunks from polluting broad codebase search. |
| Traversal tools | `view_file` / `list_directory` **unrestricted** | Agent needs full repo context beyond project edits. |
| Relational storage for diff text | **No** — tracking metadata only in Postgres | Full diff text in DocStore; embeddings in Chroma. |
| Issue tracker linkage | Project must have **exactly one** linked `ISSUE_TRACKER` DataSource | Per `flow.md`; fail ingestion step for that project if missing. |
| Incremental sync | `project_changes` + `last_synced_at` via `IngestionJob` FK | Re-fetch only new commits since last successful sync. |

### Explicitly rejected (for this phase)

- **Approach A (per-commit hunk aggregation via API):** Overlapping hunks, net-zero noise, no clean UI diff.
- **Cherry-pick replay:** Conflicts when multiple commits touch the same file; fragile.
- **`git diff A...B` on main:** Includes unrelated commits between A and B.
- **Separate DocStore namespace per project:** Replaced by metadata filtering on same namespace.
- **PR-based resolution as primary path:** `resolve_prs` / `get_pr_diff` on `GithubDataProvider` may remain for other features but are **not** the ingestion source of truth for this feature.

---

## 3. Current Implementation Status

### Done

| Area | Location | Notes |
|------|----------|-------|
| `scope_by_issues` on `DataSource` | `app/models/data_source.py`, Pydantic + service | Validated: only for `REPOSITORY` type. |
| Provider hierarchy | `app/data_providers/` | `IngestibleDataProvider` / `RepositoryDataProvider` / `FetchableDataProvider` / `IssueTrackerDataProvider`. |
| `JiraDataProvider.get_issues(epics)` | `fetchable/issue_tracker/jira.py` | Epic → story keys via JQL. |
| `GithubDataProvider` stubs | `ingestible/repository/github.py` | `resolve_prs`, `get_pr_diff` exist (legacy / optional). |
| Ingestion pipeline shell | `IngestionJobService.run_ingestion_job` | Code + docs chunking; temp dirs + cleanup. |
| DocStore insert | `ChunkInsertionService._add_nodes_to_docstore` | Namespace `str(data_source.id)`. |
| Chroma per project | `ChromaService` + `ChunkInsertionService._save_to_chroma_db` | Project-scoped collections. |
| Agent tools (general) | `app/agents/tools.py` | `semantic_search`, `grep_search`, per-DS `view_file` / `list_directory`. |
| `Project.epics` | `app/models/project.py` | Epic keys for issue resolution. |

### Not done (this plan)

- `project_changes` table and Alembic migration
- Commit discovery by message (GitHub API)
- `CompositionDiffService` (clone, apply, diff)
- `diff_parser` / `FileDiffHistory` builder
- `resolve_and_store_project_diffs()` in ingestion
- DIFF node deletion on re-ingest
- Project-scoped search tools + `list_project_files`
- `RecursiveRetriever` for parent swap
- Prompt / workflow wiring
- `GithubDataProvider` commit APIs

---

## 4. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Nightly IngestionJob (per DataSource)                  │
├─────────────────────────────────────────────────────────────────────────────┤
│  1. Existing: download repo files → code_chunk_and_store (all projects)      │
│  2. Existing: docs_convert_chunk_and_store                                   │
│  3. NEW (if REPOSITORY && scope_by_issues):                                    │
│       For each ProjectData on this DataSource:                                 │
│         a. Resolve issue keys (Jira)                                         │
│         b. Discover new commits (GitHub, message match, since last_sync)       │
│         c. Merge commit set → project_changes.commit_hashes                      │
│         d. ONE clone per job → composition_diff(all commits)                   │
│         e. Parse → FileDiffHistory per file → parent DocStore + child Chroma   │
│         f. Update project_changes row                                          │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                              Agent Runtime                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│  Lens (project):  search_project_semantic, search_project_grep,              │
│                   list_project_files                                         │
│  Context (full):  semantic_search, grep_search (exclude DIFF)                │
│  Traverse:        view_file_*, list_directory_* (unrestricted)               │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Mental model:** Project tools = **lens** on what changed. General tools = **surrounding codebase**. Traversal = **live repo** via provider APIs.

---

## 5. Data Models

### 5.1 Existing (no change required for flag)

```python
# data_source.py — already implemented
scope_by_issues: Mapped[bool] = mapped_column(default=False, ...)
```

### 5.2 New: `project_changes`

Tracks sync state and commit set per `(project, repository data source)`. Does **not** store full diff text.

```python
# app/models/project_changes.py

class ProjectChanges(Base):
    __tablename__ = "project_changes"

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=gen_random_uuid())
    project_id: Mapped[UUID] = mapped_column(ForeignKey("project.id"), index=True)
    data_source_id: Mapped[UUID] = mapped_column(ForeignKey("data_source.id"), index=True)
    ingestion_job_id: Mapped[UUID] = mapped_column(ForeignKey("ingestion_job.id"))

  # Ordered list of SHAs that constitute this project's contribution (full set, not delta-only)
    commit_hashes: Mapped[list[str]] = mapped_column(ARRAY(String))

  # Denormalized for UI / prompt summary (recomputed each sync)
    files_touched: Mapped[list[str]] = mapped_column(ARRAY(String))
    file_count: Mapped[int] = mapped_column(default=0)

  # Optional: store raw unified diff for future UI "View project diff" (TEXT or compressed)
  # Start NULL; populate when composition diff succeeds and size is acceptable
    composition_diff_unified: Mapped[str | None] = mapped_column(Text, nullable=True)

    last_synced_at: Mapped[datetime]  # mirrors ingestion_job.end_time on success

    __table_args__ = (
        UniqueConstraint("project_id", "data_source_id", name="uq_project_changes_project_ds"),
    )
```

**Relationships:**

- `project_changes.project_id` + `data_source_id` ↔ `ProjectData` composite key.
- `ingestion_job_id` → audit trail for which job last wrote this row.

### 5.3 Pydantic / service DTOs (ingestion internals)

```python
@dataclass
class DiffHunk:
    file_path: str
    change_type: Literal["added", "modified", "deleted", "context_only"]
    before_lines: list[str]   # lines removed (-)
    after_lines: list[str]    # lines added (+)
    context_lines: list[str]  # context (space prefix)
    raw_hunk: str             # original @@ hunk header + body

@dataclass
class FileDiff:
    file_path: str
    change_type: Literal["added", "modified", "deleted", "renamed"]
    hunks: list[DiffHunk]
    # For renames: old_path in metadata

@dataclass
class CompositionDiffResult:
    files: list[FileDiff]
    unified_diff_raw: str          # full composition diff string
    commit_hashes: list[str]       # ordered chronologically
    failed_commits: list[str]      # SHAs that could not be applied (fallback)
```

### 5.4 Node metadata contract (DocStore + Chroma)

All DIFF nodes **must** include:

```python
{
    "source_type": "DIFF",
    "project_id": str(project_id),
    "data_source_id": str(data_source_id),
    "file_path": "src/auth/handler.py",
    "change_type": "modified",           # file-level on parent
    "change_types": ["modified"],        # list for multi-hunk files
    "commit_count": 3,                   # optional summary on parent
}
```

Child `IndexNode` chunks duplicate `source_type`, `project_id`, `data_source_id`, `file_path` for Chroma filtering.

Code chunks continue using existing metadata (no `source_type` or `source_type != "DIFF"`).

---

## 6. Composition Diff: Mechanism

### 6.1 Why Approach B

| Requirement | Composition diff | Hunk aggregation |
|-------------|------------------|------------------|
| Net state per file | Single BEFORE/AFTER | Overlapping hunks; agent must infer |
| Add then delete same code | Absent from diff | Both ADDED and DELETED appear |
| UI diff viewer later | Store `composition_diff_unified` | Must re-derive |
| Agent reasoning | Trivial read | Hard inference |

### 6.2 Algorithm (recommended)

**One blobless clone per `IngestionJob`** (shared across all `project_data` records on that repository data source in the same job).

```text
INPUT:
  repo_url, branch, commit_hashes[]  # chronological by committer date

STEPS:
  1. git clone --filter=blob:none --no-checkout <url> <tmpdir>/<job_pk>/repo
  2. cd repo && git checkout <branch>
  3. BASE := git rev-parse HEAD

  4. git worktree add <tmpdir>/<job_pk>/composite --detach BASE
     # OR: git checkout -b project-composite-<job_pk>

  5. On composite worktree:
       git reset --hard BASE
       git checkout -B project-composite-empty

       For each sha in commit_hashes (oldest → newest):
         Try:
           git cherry-pick -n <sha>
         On conflict:
           git cherry-pick --abort
           git show <sha> --format=email-patch | git apply --3way --ignore-whitespace
           # if still fails: record sha in failed_commits; continue or abort file

  6. COMPOSITE_HEAD := git rev-parse HEAD
  7. unified_diff := git diff BASE COMPOSITE_HEAD
     # Optionally: --stat, pathspec limit to files touched by any commit in set

  8. Parse unified_diff with `unidiff.PatchSet`
  9. Cleanup worktree / tmpdir in finally block (reuse IngestionJobService._cleanup_tmp_dirs pattern)
```

**Why `cherry-pick -n` (no commit) on BASE instead of orphan + empty tree:**

- `git diff BASE COMPOSITE_HEAD` yields proper **modified** hunks (real BEFORE from BASE, AFTER from composite).
- Orphan-from-empty produces “entire file added” for modifications and loses true BEFORE.

**Why not `git diff A...B` on main:** Non-contiguous project commits would include unrelated work between A and B.

### 6.3 Commit ordering

```python
def sort_commits_chronologically(commits: list[CommitMeta]) -> list[str]:
    return [c.sha for c in sorted(commits, key=lambda c: c.committer_date)]
```

Fetch metadata via `GET /repos/{owner}/{repo}/commits/{sha}` or `git log --format=%H %ct` after clone.

### 6.4 Failure handling

| Failure | Action |
|---------|--------|
| Single commit conflicts on cherry-pick | Fall back to `git apply --3way` for that commit only |
| Apply still fails | Add SHA to `failed_commits`; log warning; optionally exclude file from composition or abort project sync |
| Clone timeout / disk | Fail `project_changes` update; leave previous sync row; mark ingestion job partial success (define policy) |
| Empty commit set | Skip diff persistence; clear DIFF nodes if previously existed |

### 6.5 Optional storage of raw unified diff

If `len(composition_diff_unified) < MAX_DIFF_BYTES` (e.g. 2–5 MB), persist on `project_changes.composition_diff_unified` for future UI. Otherwise store path or omit.

### 6.6 Container requirements

- `git` >= 2.20 in backend image
- Writable temp: `{TMP}/{job_pk}/repo` (align with existing `TMP_CODE` patterns)
- `GIT_TERMINAL_PROMPT=0` for non-interactive runs

---

## 7. Ingestion Flow

Aligned with [`apps/backend/flow.md`](apps/backend/flow.md).

### 7.1 Preconditions

```python
def should_run_project_scoping(data_source: DataSource) -> bool:
    return (
        data_source.type == DataSourceType.REPOSITORY
        and data_source.scope_by_issues is True
    )
```

### 7.2 Hook point in `IngestionJobService.run_ingestion_job`

```python
# After code_chunk_and_store (and docs if any), BEFORE _cleanup_tmp_dirs:

if should_run_project_scoping(data_source):
    await self.chunk_insertion_service.resolve_and_store_project_diffs(
        data_source=data_source,
        job_pk=job_pk,
        repo_clone_path=...,  # from shared clone step
    )

self._cleanup_tmp_dirs(job_pk)  # existing
```

**Important:** Run composition diff **before** deleting the job temp clone, or perform clone in `resolve_and_store_project_diffs` and delete in `finally`.

### 7.3 Per-`ProjectData` steps

For each `project_data` where `data_source` is the repository being ingested:

```
1. Load Project (epics), ProjectData, existing project_changes (if any)

2. Resolve IssueTrackerDataProvider:
   - Find linked DataSources for project where type == ISSUE_TRACKER
   - Require exactly one → else raise / log error and skip this project

3. task_issue_keys = IssueTracker.get_issues(project.epics)
   - Always refresh (new stories may appear under epics)

4. last_sync_time = project_changes.last_synced_at if exists else None

5. new_commits = RepositoryProvider.get_commits_matching_issues(
       issue_keys=task_issue_keys,
       since=last_sync_time,
   )
   - If no project_changes: all matching commits on branch (paginated)
   - Else: commits after last_sync_time with message containing any issue key

6. all_commits = merge_unique(project_changes.commit_hashes, new_commits.shas)

7. composition = CompositionDiffService.build(repo_path, data_source.branch, all_commits)

8. ChunkInsertionService.persist_project_diffs(
       project_id, data_source, composition, job_pk
   )

9. Upsert project_changes:
       commit_hashes, files_touched, file_count,
       composition_diff_unified (optional),
       ingestion_job_id, last_synced_at
```

### 7.4 Issue key matching in commit messages

```python
def commit_matches_issues(message: str, issue_keys: list[str]) -> bool:
    # Word-boundary style match: PROJ-123 should not match PROJ-1234
    for key in issue_keys:
        if re.search(rf'\b{re.escape(key)}\b', message, re.IGNORECASE):
            return True
    return False
```

**Prerequisite for teams:** Document that commits must reference issue keys in messages.

### 7.5 Freshness / re-ingestion

On each successful project diff sync:

1. **Delete** all existing DIFF nodes for `(project_id, data_source_id)` from DocStore and Chroma.
2. Rebuild from full `commit_hashes` set (not incremental patch on old chunks).
3. Upsert `project_changes`.

This keeps agent view consistent when commits are amended or list is corrected.

---

## 8. Diff Parsing & FileDiffHistory

### 8.1 Parser service

**File:** `app/services/diff_parser.py`

```python
from unidiff import PatchSet

def parse_unified_diff(raw: str) -> list[FileDiff]:
    patch_set = PatchSet(raw)
    ...
```

**Per hunk classification:**

| `-` lines | `+` lines | `change_type` |
|-----------|-----------|---------------|
| yes | yes | `modified` |
| no | yes | `added` |
| yes | no | `deleted` |
| whitespace only | whitespace only | `context_only` → **skip** |

Extract:

- `before_lines` from `-` prefixed lines (strip prefix)
- `after_lines` from `+` prefixed lines
- `context_lines` from ` ` prefixed lines

### 8.2 FileDiffHistory text (parent node body)

One **parent `TextNode` per file** in the composition diff. No LLM generation.

```text
[PROJECT CHANGE | MODIFIED | src/auth/handler.py]
This project changed this file (net diff vs. branch {branch} at sync {iso_timestamp}).
Commits included: abc1234, def5678 (3 total)

--- Hunk 1 (MODIFIED) ---
BEFORE:
    if request.auth_type == 'oauth2':
AFTER:
    if request.auth_type == 'oauth2' or request.auth_type == 'saml':
SURROUNDING CONTEXT:
def handle_auth(request):
    ...

--- Hunk 2 (MODIFIED) ---
...
```

**ADDED file** (no BEFORE):

```text
[PROJECT CHANGE | ADDED | src/auth/saml_handler.py]
...
ADDED CODE:
def handle_saml(request):
    ...
```

**DELETED file:**

```text
[PROJECT CHANGE | DELETED | src/auth/legacy.py]

WARNING: The following code was REMOVED by this project and NO LONGER EXISTS in the codebase.

REMOVED CODE:
...
```

### 8.3 Parent node ID stability

```python
def parent_node_id(project_id: UUID, data_source_id: UUID, file_path: str) -> str:
    key = f"{project_id}:{data_source_id}:{file_path}"
    return f"diff_{hashlib.sha256(key.encode()).hexdigest()[:32]}"
```

Stable IDs allow idempotent delete-by-prefix or explicit delete list before re-insert.

### 8.4 Large files

| Case | Policy |
|------|--------|
| File diff text > N tokens (e.g. 8k) | Truncate SURROUNDING CONTEXT; keep all BEFORE/AFTER for hunks |
| Binary / generated files | Skip with log (match existing code ingestion ignore rules) |
| Single file dominates diff | Cap hunks included in parent; store `truncated: true` in metadata |

---

## 9. Persistence: DocStore & Chroma

### 9.1 Namespace & collection

| Store | Scope | Namespace / collection |
|-------|--------|-------------------------|
| DocStore | Data source | `str(data_source.id)` — **unchanged** |
| Chroma | Project | Existing `ChromaCollection` for project — **unchanged** |

### 9.2 Parent-child pattern (prevents “lost update”)

**Problem:** If each hunk is embedded separately, semantic search may return hunk 2 of 3; agent misses later changes.

**Solution:**

```
Parent (DocStore TextNode):
  id_ = parent_node_id(...)
  text = full FileDiffHistory
  metadata = { source_type: DIFF, project_id, data_source_id, file_path, ... }

Children (Chroma IndexNodes):
  TokenTextSplitter(chunk_size=512, chunk_overlap=50)
  For each chunk i:
    IndexNode(
      id_ = f"{parent_id}_chunk_{i}",
      text = <chunk of parent text>,
      index_id = parent_id,
      metadata = { source_type: DIFF, project_id, data_source_id, file_path, chunk_index: i }
    )
```

**Retrieval:** `RecursiveRetriever` on project semantic search — matched child → fetch parent `TextNode` from DocStore → agent always sees **full file net diff**.

### 9.3 Insertion implementation

**File:** extend `ChunkInsertionService`

```python
async def resolve_and_store_project_diffs(self, data_source, job_pk, ...): ...

async def persist_project_diffs(
    self,
    project_id: UUID,
    data_source: DataSource,
    composition: CompositionDiffResult,
    job_pk: UUID,
) -> None:
    await self._delete_project_diff_nodes(project_id, data_source.id)
    parents, children = self._build_diff_nodes(project_id, data_source, composition)
    await self._add_nodes_to_docstore(parents, data_source)  # existing helper
    await self._insert_diff_children_to_chroma(children, project_id, data_source)
```

### 9.4 Deleting old DIFF nodes

**DocStore:**

```sql
-- Via DocstoreChunk OR LlamaIndex delete
DELETE FROM docstore_chunk
WHERE namespace = :data_source_id
  AND (value->'__data__'->'metadata'->>'source_type' = 'DIFF'
       OR value->'metadata'->>'source_type' = 'DIFF')
  AND (value->'__data__'->'metadata'->>'project_id' = :project_id
       OR value->'metadata'->>'project_id' = :project_id);
```

Implement via existing `DocstoreChunk` model queries (same pattern as `chunk_retrieval.grep_search`).

**Chroma:**

```python
collection.delete(
    where={
        "$and": [
            {"source_type": {"$eq": "DIFF"}},
            {"project_id": {"$eq": str(project_id)}},
            {"data_source_id": {"$eq": str(data_source_id)}},
        ]
    }
)
```

Run delete **before** insert on every sync.

### 9.5 Docstore filter for code-only grep

Update `ChunkRetrievalService.grep_search` and BM25 node loading to exclude:

```python
# Pseudocode: skip nodes where metadata.source_type == "DIFF"
```

Chroma retriever: add filter `source_type != DIFF` OR omit DIFF from BM25 node list.

---

## 10. Agent Tooling

### 10.1 Tool matrix

| Tool | Scope | Filters |
|------|-------|---------|
| `semantic_search` | All linked data sources (code + docs) | `source_type != DIFF` |
| `grep_search` | DocStore for project’s data sources | `source_type != DIFF` |
| `search_project_semantic` | Project diff chunks only | `source_type == DIFF`, `project_id == current` |
| `search_project_grep` | DocStore parent diff nodes | same |
| `list_project_files` | Manifest of touched files | `source_type == DIFF`, distinct `file_path` |
| `view_file_*` | Live repo | No project filter |
| `list_directory_*` | Live repo | No project filter |

### 10.2 New `ChunkRetrievalService` methods

```python
async def search_project_semantic(
    self, query: str, project_id: UUID, llm: LLMBase, k: int = 10,
) -> list[str]:
    filters = MetadataFilters(filters=[
        MetadataFilter(key="source_type", value="DIFF", operator=EQ),
        MetadataFilter(key="project_id", value=str(project_id), operator=EQ),
    ])
    # Chroma retriever + RecursiveRetriever(docstore, child_to_parent)

async def search_project_grep(
    self, key_word: str, project_id: UUID, k: int = 10,
) -> list[str]:
    # SQL on DocstoreChunk: namespace in project's DS ids, source_type=DIFF, project_id, text ~* keyword
    # Return full parent text (not chunk fragments)

async def list_project_files(self, project_id: UUID) -> list[dict]:
    # SELECT DISTINCT file_path, change_type FROM docstore metadata
    # Return: [{ "file_path": "...", "change_type": "modified" }, ...]
```

### 10.3 `Tools` class changes

```python
class Tools:
    def __init__(
        ...,
        project_scoping_enabled: bool = False,
    ):
        ...
        if project_scoping_enabled:
            self._search_project_semantic_tool = ...
            self._search_project_grep_tool = ...
            self._list_project_files_tool = ...

    def get_planning_tools(self) -> list[FunctionTool]:
        tools = [...,]
        if self.project_scoping_enabled:
            tools.append(self._list_project_files_tool)
        return tools

    def get_research_tools(self, ...) -> list[FunctionTool]:
        tools = [...,]
        if self.project_scoping_enabled:
            tools.extend([
                self._search_project_semantic_tool,
                self._search_project_grep_tool,
                self._list_project_files_tool,
            ])
        return tools
```

### 10.4 Enabling scoping at runtime

```python
# AgentService / workflow setup
project_scoping_enabled = any(
    ds.scope_by_issues and ds.type == REPOSITORY
    for ds in data_sources_for_project
)

tools = Tools(..., project_scoping_enabled=project_scoping_enabled)
```

### 10.5 Tool descriptions (agent-facing)

**`search_project_semantic`:** Search only code changes introduced by this project (net diff). Returns BEFORE/AFTER/ADDED/REMOVED. DELETED means code no longer exists.

**`search_project_grep`:** Exact keyword search within project diff content only.

**`list_project_files`:** List all files this project changed and how (added/modified/deleted). Call early to orient before deep search.

### 10.6 Compact summary for planning prompt

At workflow start, compute:

```python
{
  "commit_count": len(project_changes.commit_hashes),
  "file_count": project_changes.file_count,
  "top_files": project_changes.files_touched[:10],
  "failed_commits": composition.failed_commits if any,
}
```

Inject into `planning.md` / `research.md` as `{project_scoping_context}`.

---

## 11. Prompts & Anti-Hallucination

### 11.1 New fragment: `app/agents/prompts/project_scoping_rules.md`

```markdown
## Project-scoped search rules

- Use `list_project_files` first to see what this project touched.
- Use `search_project_semantic` / `search_project_grep` for "what did WE change?"
- Use `semantic_search` / `grep_search` for architecture and code outside project edits.
- Do NOT attribute full-repo search results to this project unless also found in project search.

### Reading diff results
- **MODIFIED:** BEFORE is gone; AFTER is current on the branch.
- **ADDED:** New code introduced by this project.
- **DELETED:** Removed by this project — do NOT cite as existing.

### Composition diff semantics
Results reflect the **net change** from all project commits combined, not individual commit history.
```

### 11.2 Updates to existing prompts

| File | Changes |
|------|---------|
| `planning.md` | When scoping enabled: include compact summary; prefer `list_project_files` in plan step 1 |
| `research.md` | Include `project_scoping_rules.md`; tool selection guidance |
| `synth.md` | Cite project changes vs pre-existing context explicitly |

### 11.3 Chunk-level protections (already in v4 plan)

- Structured header in every diff chunk
- `WARNING:` on DELETED blocks
- Embed warnings so they surface in semantic search

---

## 12. Provider & API Extensions

### 12.1 `RepositoryDataProvider` (GitHub)

Add to `github.py` / `base.py`:

```python
async def get_commits_matching_issues(
    self,
    issue_keys: list[str],
    since: datetime | None = None,
    branch: str | None = None,
) -> list[CommitMeta]:
    """
    List commits on branch whose message contains any issue_key.
    Use GitHub REST: GET /repos/{owner}/{repo}/commits?sha={branch}&since={iso}
    Client-side filter with commit_matches_issues().
    Paginate until no since bound or no new SHAs.
    """

async def get_commit(self, sha: str) -> CommitMeta:
    """Metadata for ordering."""
```

**Note:** `resolve_prs` / `get_pr_diff` can remain but are not used by this pipeline.

### 12.2 `IssueTrackerDataProvider`

Already has `get_issues(epics)`. Ensure credentials from DataSource URL/secrets (TODOs in Jira provider).

### 12.3 Resolving the project's issue tracker DataSource

```python
async def get_issue_tracker_for_project(db, project_id: UUID) -> DataSource:
    sources = await data_source_svc.aget_project_data_sources(project_id)
    trackers = [s for s in sources if s.type == DataSourceType.ISSUE_TRACKER]
    if len(trackers) != 1:
        raise ProjectScopingError("Project must have exactly one ISSUE_TRACKER data source")
    return trackers[0]
```

### 12.4 New service: `CompositionDiffService`

**File:** `app/services/composition_diff.py`

- `async def ensure_repo_clone(data_source, job_pk) -> Path`
- `def build(repo_path: Path, branch: str, commit_shas: list[str]) -> CompositionDiffResult`
- Subprocess wrappers with timeouts
- Unit-testable with fixture repo

---

## 13. Phased Implementation Roadmap

### Phase 1 — Schema & tracking (S)

- [ ] Alembic: `project_changes` table
- [ ] SQLAlchemy model + export in `models/__init__.py`
- [ ] `ProjectChangesService` CRUD (get by project+ds, upsert)

### Phase 2 — Commit discovery (M)

- [ ] `get_commits_matching_issues` on GitHub provider
- [ ] Issue key matcher util + tests
- [ ] `get_issue_tracker_for_project` validation
- [ ] Wire epic → issues in ingestion prelude

### Phase 3 — Composition diff (L)

- [ ] `CompositionDiffService` (clone, cherry-pick -n chain, diff BASE..HEAD)
- [ ] `unidiff` dependency in `pyproject.toml` / requirements
- [ ] Conflict fallback (`git apply --3way`)
- [ ] `diff_parser.py` → `FileDiff` / `DiffHunk`

### Phase 4 — Persistence (M)

- [ ] `_delete_project_diff_nodes`
- [ ] `_build_diff_nodes` (parent TextNode + child IndexNodes)
- [ ] `persist_project_diffs` + Chroma insert with metadata
- [ ] `resolve_and_store_project_diffs` orchestration
- [ ] Hook in `IngestionJobService.run_ingestion_job`
- [ ] Shared clone per job (optimize)

### Phase 5 — Retrieval & tools (M)

- [ ] Exclude DIFF from `semantic_search` / `grep_search` / BM25
- [ ] `search_project_semantic` + `RecursiveRetriever`
- [ ] `search_project_grep` + `list_project_files`
- [ ] `Tools` conditional registration
- [ ] `AgentService` / `workflow.py` wiring + compact summary

### Phase 6 — Prompts & polish (S)

- [ ] `project_scoping_rules.md`
- [ ] Update planning / research / synth prompts
- [ ] Logging + metrics (commits found, apply failures, diff size)
- [ ] Frontend: expose `scope_by_issues` if not already on DS forms

### Phase 7 — Hardening (M)

- [ ] Integration test: fixture repo + 3 commits → composition → nodes
- [ ] Load test clone time on representative repo size
- [ ] Document commit-message convention for users

---

## 14. Edge Cases & Fallbacks

| Edge case | Handling |
|-----------|----------|
| No commits match issue keys | Clear DIFF nodes; `project_changes` with empty hashes or skip row |
| `git apply --3way` fails | Record in `failed_commits`; optional per-file fallback to single-commit diff via `git show <sha> -- <path>` |
| Commits already on main (double-apply risk) | `cherry-pick -n` may noop or conflict; prefer `git show` patch format from each commit **as isolated patch** applied sequentially—document that patches are relative to parent trees; test heavily |
| Merge commits in list | Skip merge commits without direct changes (`git show -m` policy) or use first parent only |
| Forked repo / wrong branch | Use `data_source.branch`; log warning if zero commits |
| Multiple projects on same DS | Each has own `project_changes` + DIFF metadata `project_id`; shared clone OK |
| Re-ingest code without scoping | General code chunks refresh independently |
| Issue tracker down | Fail project diff step; do not delete previous DIFF nodes unless policy says otherwise |

**Open implementation detail to validate in Phase 3 spike:** cherry-pick -n of commits **already contained in BASE** may produce empty or conflicting results. If so, use **format-patch from parent^** for each commit:

```bash
git format-patch -1 <sha> --stdout | git apply --3way
```

on a branch that tracks only applied project state (not BASE’s full history).

---

## 15. Operational & Infrastructure Notes

- **Timing:** Run in nightly ingestion; 5–30s clone + N × cherry-pick is acceptable.
- **Concurrency:** One ingestion job per data source (existing lock); clone path includes `job_pk`.
- **Secrets:** `GITHUB_SECRET_TOKEN` for API + clone HTTPS.
- **Disk:** Monitor `tmp/` per job; ensure `_cleanup_tmp_dirs` removes repo worktrees.
- **Observability:** Structured logs: `project_id`, `data_source_id`, `commit_count`, `file_count`, `failed_commits`, `diff_bytes`.

---

## 16. Testing Strategy

| Level | What |
|-------|------|
| Unit | `commit_matches_issues`, hunk classifier, FileDiffHistory formatter |
| Unit | `PatchSet` parsing on fixture unified diffs |
| Integration | Local git repo with 3 non-contiguous commits on main → composition diff |
| Integration | Delete + re-insert DIFF nodes; metadata filters |
| Agent | Manual: “What did we change in auth?” uses project tools first |

---

## 17. Future Work

- **UI diff viewer:** Render `project_changes.composition_diff_unified` with diff2html
- **Webhook-triggered ingestion** instead of nightly-only
- **Bitbucket provider** parity for commit APIs
- **PR list on `project_changes`** for display-only (derived from commits)
- **Partial sync** without full commit list rebuild (optimization; not v1)

---

## 18. Appendix: End-to-End Data Flow

```mermaid
sequenceDiagram
    participant Job as IngestionJob
    participant Jira as JiraDataProvider
    participant GH as GithubDataProvider
    participant Comp as CompositionDiffService
    participant Parse as DiffParser
    participant CIS as ChunkInsertionService
    participant PG as Postgres DocStore
    participant Chroma as ChromaDB

    Job->>Job: scope_by_issues and REPOSITORY?
    Job->>Job: git clone once per job_pk

    loop Each ProjectData on DataSource
        Job->>Jira: get_issues(project.epics)
        Jira-->>Job: task_issue_keys
        Job->>GH: get_commits_matching_issues(keys, since)
        GH-->>Job: new SHAs
        Job->>Job: merge into project_changes.commit_hashes
        Job->>Comp: build(repo, branch, all_shas)
        Comp-->>Job: unified_diff_raw
        Job->>Parse: parse_unified_diff
        Parse-->>Job: list FileDiff
        Job->>CIS: delete DIFF nodes project+ds
        Job->>CIS: parent TextNodes to DocStore
        Job->>CIS: child IndexNodes to Chroma
        Job->>PG: upsert project_changes
    end

    Note over Job,Chroma: Agent runtime

    participant Agent
    Agent->>Chroma: search_project_semantic
    Chroma-->>Agent: IndexNode match
    Agent->>PG: RecursiveRetriever fetch parent
    PG-->>Agent: full FileDiffHistory
    Agent->>GH: view_file for surrounding context
```

---

## Document history

| Date | Change |
|------|--------|
| 2026-05-23 | Initial finalized plan: Approach B, commit-based attribution, metadata isolation, parent-child storage, tooling matrix aligned with `flow.md` and `PROJECT_SCOPE_LATEST.md` conversation. |

**Supersedes for implementation:** `scoping_changes_to_project_plan.md` and `PROJECT_SCOPING_UPDATES.md` where they conflict with commit-based flow and `scope_by_issues` on `DataSource`. Keep those files for historical chunk-format reference only.
