---
name: nancy-personal-knowledge
description: Save, search, recall, correct, archive, and visually present the user's private notes, ideas, bookmarks, meetings, and voice notes.
version: 1.0.0
metadata:
  hermes:
    tags: [nancy, memory, knowledge, notes, ideas, bookmarks, meetings]
---

# Nancy Personal Knowledge

Use Nancy's private knowledge base for durable information the user deliberately
wants to keep or recall later.

## Saving

Save only when the user explicitly asks with language such as "remember this",
"save this", "make a note", "keep this idea", "bookmark this", or "save these
meeting notes". Ordinary conversation, questions, task commands and incidental
personal details must not be stored automatically.

Call `mcp__nancy_board__save_knowledge` with:

- a concise descriptive title;
- the complete useful content, preserving facts and decisions;
- the closest kind: `note`, `idea`, `bookmark`, `meeting`, or `voice_note`;
- the original URL for bookmarks when supplied;
- a small set of lowercase topic tags; and
- related OpenTodo task IDs only when the relationship is explicit.

Never claim something was remembered until the save tool succeeds.

## Recall

For "what did I say/decide/save about…", recent-note requests, or knowledge
searches, call `mcp__nancy_board__search_knowledge_base`. Use a short factual
query, not the whole user sentence. If a result needs full context, call
`mcp__nancy_board__get_knowledge_entry`.

Clearly distinguish saved facts from your own inference. Preserve source URLs
when reporting bookmarks.

## Corrections and forgetting

Search first to identify the exact entry. Use
`mcp__nancy_board__update_knowledge_entry` only after the user asks to correct or
extend saved information. Use `mcp__nancy_board__archive_knowledge_entry` only
after an explicit request to forget, remove or archive it. If several entries
could match a destructive request, ask which one.

## Visual board

When multiple results benefit from display, use the `knowledge_list` component.
For one full entry, use `knowledge_detail`. The board is read-only; never imply
that entries can be edited from it.
