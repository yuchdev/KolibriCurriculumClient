# Agent Engineering Guide

## 1. Scope

This repository currently provides a deterministic curriculum ingestion and query layer.
The next milestone will add an AI study-planning agent that reads the SQLite catalog.

The agent must not replace the catalog importer, infer source facts that are absent, or
write arbitrary SQL.

## 2. Development rules

1. **Preserve source truth.** Treat `node_id`, `parent_id`, `kind`, and `source_path` as
   authoritative. Course/unit/lesson labels in the planning export are heuristic.
2. **Keep deterministic and probabilistic work separate.** SQL filtering, hierarchy,
   updates, and progress calculations belong in Python/SQLite. The model handles choices,
   explanations, and plan proposals.
3. **No arbitrary SQL from the model.** Expose explicit tool functions with validated
   inputs and bounded result sizes.
4. **Read before write.** The first agent milestone is read-only. Personal study-plan
   writes arrive only after retrieval and evaluation are stable.
5. **Bound every response.** Limit search results, subtree depth, and total serialized
   context sent to the model.
6. **Cite catalog nodes.** Every recommended lesson must retain `channel_id`, `node_id`,
   and `source_path`.
7. **Do not manufacture prerequisites.** Label model-proposed prerequisite relations as
   recommendations until a user approves them.
8. **Test with synthetic channels.** Never require a live Khan Academy download for unit
   tests.
9. **Make surgical changes.** Do not couple the catalog pipeline to a specific LLM SDK.
10. **Keep private progress separate.** User notes and mastery data must not modify source
    catalog rows.

## 3. Existing agent-ready interface

`CatalogQueryService` in `agent_api.py` exposes these bounded read operations:

```python
channels()
search(query, channel_id=None, limit=20)
node(channel_id, node_id)
children(channel_id, parent_id)
subtree(channel_id, node_id, max_depth=3)
recent_changes(channel_id=None, limit=50)
```

This layer is intentionally independent of OpenAI, Ollama, LangChain, or any other agent
framework.

## 4. Next milestone: SQLite-backed study-planning agent

### Milestone objective

Given a learner goal, available time, known topics, and an imported channel, produce a
reviewable study path whose every item refers to a real catalog node.

Example input:

```json
{
  "goal": "Prepare for introductory calculus",
  "channel_id": "...",
  "hours_per_week": 6,
  "target_weeks": 12,
  "known_topics": ["basic linear equations"],
  "preferred_course": "Algebra 1"
}
```

Example output:

```json
{
  "plan": [
    {
      "sequence": 1,
      "channel_id": "...",
      "node_id": "...",
      "source_path": ["Math", "Algebra 1", "Unit 6", "Lesson 1"],
      "reason": "Reviews graphing systems before later function work.",
      "estimated_minutes": 30
    }
  ],
  "assumptions": [],
  "unresolved_gaps": []
}
```

### Step 1: Define tool contracts

Wrap the current service methods as agent tools. Suggested contracts:

```text
catalog_search(query, channel_id, limit)
catalog_get_node(channel_id, node_id)
catalog_list_children(channel_id, parent_id)
catalog_get_subtree(channel_id, node_id, max_depth)
catalog_recent_changes(channel_id, limit)
```

Validation requirements:

- channel and node IDs are strings with a conservative maximum length;
- `limit <= 100`;
- `max_depth <= 10`;
- returned descriptions are truncated to a configured maximum;
- no file paths or database handles are returned to the model.

### Step 2: Add deterministic candidate selection

Before invoking an LLM, use SQL to narrow the catalog:

1. search the learner goal;
2. identify matching course or unit nodes;
3. fetch bounded subtrees;
4. remove inactive nodes;
5. deduplicate by `(channel_id, node_id)`;
6. calculate available duration where present.

The model should receive tens of candidate nodes, not the entire curriculum.

### Step 3: Add personal study tables

Add a separate migration, not changes to `nodes`:

```sql
CREATE TABLE learners (
    learner_id INTEGER PRIMARY KEY,
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE study_plans (
    plan_id INTEGER PRIMARY KEY,
    learner_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    goal TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL,
    approved_at TEXT,
    FOREIGN KEY (learner_id) REFERENCES learners(learner_id)
);

CREATE TABLE study_plan_items (
    plan_id INTEGER NOT NULL,
    sequence_number INTEGER NOT NULL,
    channel_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    estimated_minutes INTEGER,
    rationale TEXT,
    status TEXT NOT NULL DEFAULT 'planned',
    PRIMARY KEY (plan_id, sequence_number),
    FOREIGN KEY (channel_id, node_id) REFERENCES nodes(channel_id, node_id)
);

CREATE TABLE learner_progress (
    learner_id INTEGER NOT NULL,
    channel_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    status TEXT NOT NULL,
    confidence REAL,
    notes TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (learner_id, channel_id, node_id),
    FOREIGN KEY (channel_id, node_id) REFERENCES nodes(channel_id, node_id)
);
```

Catalog synchronization must not overwrite these tables.

### Step 4: Implement plan generation as proposal, not mutation

Recommended control flow:

```text
user goal
  -> deterministic catalog retrieval
  -> structured candidate JSON
  -> LLM returns proposed node IDs and rationale
  -> validator checks every node ID
  -> duration and ordering checks
  -> user reviews proposal
  -> explicit approval writes study_plan_items
```

The model never writes directly to SQLite.

### Step 5: Validate generated plans

Reject or repair a proposal when:

- a referenced node does not exist or is inactive;
- a proposed item lies outside the selected channel;
- duplicate node IDs occur without an explicit review reason;
- estimated total time exceeds the user's budget beyond tolerance;
- a parent topic is presented as a leaf lesson without explanation;
- the proposal omits source IDs.

### Step 6: Add an adaptive weekly loop

After a plan is approved:

1. read completed and skipped nodes;
2. read the next bounded portion of the plan;
3. query nearby siblings and ancestors;
4. ask the model for a weekly adjustment;
5. validate it;
6. show a diff to the user before writing.

### Step 7: Evaluation suite

Create fixtures for:

- exact course-name retrieval;
- ambiguous topic search;
- missing descriptions;
- duplicate content IDs at different paths;
- moved/removed nodes after synchronization;
- plan generation under a strict time budget;
- prompt-injection text embedded in a source title or description.

Required metrics:

- percentage of recommendations with valid source node IDs;
- retrieval recall for known fixture paths;
- number of inactive nodes recommended;
- budget deviation;
- deterministic repeatability of candidate selection;
- human acceptance rate of proposed plans.

## 5. Security rules for an agent adapter

- Open SQLite in read-only mode for retrieval tools.
- Use parameterized SQL only.
- Do not allow the model to choose a database path.
- Do not expose arbitrary filesystem reads.
- Treat source titles and descriptions as untrusted data, not instructions.
- Strip or delimit source text in prompts.
- Log tool names and identifiers, but avoid logging private learner notes by default.
- Require explicit user approval before inserting or changing a study plan.

## 6. Suggested agent-neutral Python interface

```python
from dataclasses import dataclass
from kolibri_curriculum.agent_api import CatalogQueryService


@dataclass
class StudyRequest:
    goal: str
    channel_id: str
    hours_per_week: float
    target_weeks: int
    known_topics: list[str]


def retrieve_candidates(service: CatalogQueryService, request: StudyRequest) -> list[dict]:
    matches = service.search(request.goal, channel_id=request.channel_id, limit=20)
    candidates: dict[str, dict] = {}
    for match in matches:
        for node in service.subtree(
            request.channel_id,
            match["node_id"],
            max_depth=3,
        ):
            candidates[node["node_id"]] = node
    return list(candidates.values())[:100]
```

An LLM-specific adapter should depend on this interface, not the reverse.

## 7. Definition of done for the next milestone

- Agent can generate a plan from a synthetic catalog fixture.
- Every plan item resolves to an active SQLite node.
- Agent sees no more than the configured context limit.
- No arbitrary SQL tool exists.
- Proposed plans require user approval before persistence.
- Tests cover invalid IDs, removed nodes, duplicates, time-budget overflow, and source
  prompt injection.
- README includes one local-model example and one cloud-model example without making
  either SDK a core dependency.
