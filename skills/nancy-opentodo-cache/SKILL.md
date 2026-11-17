---
name: nancy-opentodo-cache
description: Answer common OpenTodo task questions quickly from Nancy's local cache and keep it synchronized after task changes.
version: 1.0.0
metadata:
  hermes:
    tags: [nancy, opentodo, tasks, cache, performance]
---

# Nancy OpenTodo Cache

Use this workflow for OpenTodo questions about active tasks or tasks due today.

## Reads

1. Call `mcp_nancy_board_get_cached_tasks` for the requested `active` or `today`
   view before calling OpenTodo.
2. If the result has `warm: true` and `fresh: true`, answer from its `tasks` and
   do not query OpenTodo.
3. If it is empty, cold, or stale, retrieve both active tasks and today's tasks
   from OpenTodo, then call `mcp_nancy_board_replace_task_cache` with both complete
   lists. Answer from the authoritative result.
4. A warm, fresh list with `count: 0` is an authoritative empty result; do not
   query OpenTodo again.

Never present stale cached data as current. Do not use this cache for historical,
completed, archived, search, project-list, or routine queries.

## Writes

After every successful OpenTodo task create, edit, reschedule, move, reopen, or
complete operation, call `mcp_nancy_board_update_cached_task` before replying.
Pass the complete task returned by OpenTodo and set:

- `active` to false only when it is completed, deleted, or archived.
- `today` to true only when its current due date is today in the user's timezone
  and it remains active.

After deletion, call `mcp_nancy_board_remove_cached_task` with the deleted ID.
If OpenTodo does not return enough data to determine the complete updated task or
its membership, call `mcp_nancy_board_invalidate_task_cache`. The next common read
will refresh both snapshots rather than risk an incorrect answer.

Cache maintenance is part of the same task operation. Do not mention it unless it
fails. OpenTodo remains the source of truth.
