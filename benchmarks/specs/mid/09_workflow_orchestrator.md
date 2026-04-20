# Durable workflow orchestrator

## Requirements

- A workflow is defined as a sequence of steps; each step is a durable activity call.
- Steps may call external services; failures retry with exponential backoff and a cap.
- If an activity exceeds its deadline, the workflow advances to a compensation step for each already-completed action.
- Workflows survive process restarts: state is persisted, not in-memory.
- An operator can query the current step and the history of any running workflow.

## Acceptance criteria

- Killing the orchestrator mid-workflow and restarting resumes from the last completed step, not from start.
- An activity that succeeds but whose response is lost (e.g., network drop) is retried safely: the workflow does not execute the side-effect twice.
- Timeout on step 3 of 5 triggers compensations for steps 1 and 2 in reverse order.
- Two concurrent runs of the same workflow id are rejected; one instance per id.

## Non-requirements

- No workflow DSL — workflows are defined in code.
- No UI; a CLI or API is fine.
- No cross-region replication.
- No history visualization.
