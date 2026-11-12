# Research — Claude Code on a session longer than one context window

> Not a taxonomy cluster. Filed 2026-11-12 as the benchmark for Atlas's
> agentic per-call limits. Citations are Anthropic's Claude Code docs,
> read that day. Nothing here is built into the lens loop.

Hard caps exist to stop a runaway call. They are not a way to make a
review shallower than the change needs. Claude Code's own session
routines are the comparison: how a long agentic session stays inside a
model window, how turn and dollar limits stop it, and how the operator
can tell which limit fired.

## What Claude Code does

Pages read 2026-11-12:

- [Explore the context window](https://code.claude.com/docs/en/context-window)
- [Model configuration](https://code.claude.com/docs/en/model-config)
- [Create custom subagents](https://code.claude.com/docs/en/sub-agents)
- [CLI reference](https://code.claude.com/docs/en/cli-reference)

**Context and compaction.** With automatic compaction on, which is
the session these pages describe, Claude Code summarizes the
conversation as it approaches the model's context limit, so a full
window does not end the session. That is not true with auto-compaction
off. The model-config page says that under
`CLAUDE_CODE_DISABLE_1M_CONTEXT=1`, a native 1M model then stops at the
200K boundary with the context-limit error instead of compacting.
`DISABLE_COMPACT` turns compaction off entirely. The automatic pass,
when it runs, is what `/compact` does. `/compact` can take a focus instruction. `/rewind` can summarize
from a chosen message or up to it. `/clear` drops the conversation when
the next task is unrelated. `/autocompact`, `autoCompactWindow`,
`--autocompact`, and `CLAUDE_CODE_AUTO_COMPACT_WINDOW` set how full the
window may get first. A configured window is capped at the model's own
context window, and a usable `CLAUDE_CODE_AUTO_COMPACT_WINDOW` is a
token count from 100,000 to 1,000,000 (the env var warns and substitutes
when the value is outside that, or ignores a value that is not a token
count).

The default threshold is the model's context limit, with these
exceptions named on the model-config page: cloud sessions compact as
the conversation approaches the limit; Sonnet 4.6 and Opus 4.6 without
extended context compact at the 200K boundary; `CLAUDE_CODE_DISABLE_1M_CONTEXT=1`
makes a native 1M model compact at 200K; models that run with a native
1M window (Fable, Sonnet 5 and later, Haiku 5.5, Opus 4.7 and later)
compact at about 967K. An unrecognized model id is assumed to be 200K
until the operator sets the window.

Compaction keeps the system prompt and output style, re-injects the
project-root CLAUDE.md, unscoped rules, auto memory, and a plan written
in plan mode, rebuilds skill descriptions (v2.1.304 or later), and
re-reads up to five files the session read or edited, most recently
modified first. A file over 5,000 tokens comes back as a path reference
without its content. Invoked skill bodies are re-injected, capped at
5,000 tokens each and 25,000 in all. Hook output that was added earlier
is summarized with the rest of the history. There is no separate
"delete old tool results" switch in these pages: compaction is the
mechanism that drops history, including tool results, and the five-file
re-read is what comes back.

**Subagents.** A subagent has its own context window, sized by its own
model. A delegation for a large read keeps those file contents in the
subagent; the parent receives a summary. Spend still counts toward the
same usage limits as the parent. `maxTurns` stops the subagent and, on
v2.1.246 or later, marks the returned output partial so it can be
resumed. `autoCompactWindow` in frontmatter (100,000 to 1,000,000,
v2.1.296 or later) compacts that subagent earlier, unless
`CLAUDE_CODE_AUTO_COMPACT_WINDOW` is set and not ignored, in which case
the variable wins. A compaction is logged with subtype
`compact_boundary` and a `preTokens` count.

**Turn and cost limits.** In print mode, `--max-turns` limits agentic
turns and has no default. `--max-budget-usd` stops the run when
Claude Code's client-side cost estimate reaches the amount. The doc
says that estimate can differ from the bill, that subagent spend
counts, and that spend can pass the cap, so the operator should leave
headroom. The cap-enforcement behaviors it names (a later subagent
fails with `Budget limit reached`, and background subagents are
stopped) require v2.1.217 or later. Totals restored with `--continue`
or `--resume` do not count toward that cap.

**Diagnostics.** `/context` shows a breakdown of the current session.
The status line's `used_percentage` measures against the model's full
context window. While `CLAUDE_CODE_AUTO_COMPACT_WINDOW` is set, that
percentage does not say when compaction will run.

## What Atlas does today

| Claude Code | Atlas, after the per-call limits change |
|---|---|
| Window from the model. With automatic compaction on, compaction runs before the window fills. With it off under `CLAUDE_CODE_DISABLE_1M_CONTEXT=1`, the session stops at the 200K boundary | The agentic per-call input cap is the pinned model's catalog `context_length` minus the output reserve. The output cap defaults to `max_completion_tokens`. There is no compaction. A prompt that does not fit is refused before it is sent. |
| History is summarized; up to five recent files are re-read | Every later turn resends the system prompt and the tool results so far, including diff pages already read. |
| Subagent keeps a large read out of the parent | One lens at a time (`pool_size` 1). A lens does not see another lens's tool results. Inside one lens, tool results stay in that lens's history. |
| `--max-turns`, no default; `--max-budget-usd` can be passed by the estimate | 50 turns, 50 calls, a $5 reservation, 20 minutes per lens and 60 minutes per review, all overridable. The loop reserves the worst case and refuses before the call, so a call is not sent once the reservation would be exceeded. |
| `/context`, and a status percentage that is not the compaction point | A stop names the limit, the configured value, the observed or needed value, and the flag or `ATLAS_*` variable that changes it. The ledger stores those four fields. The status line's `limit_stop` is that object, or null. |

The one-shot path is unchanged in its ceilings: 3 calls, $3.00, and a
200,000 input cap (D25). Its reservation now prices the whole output
cap at the completion rate plus the reasoning rate, because
OpenRouter's `reasoning.max_tokens` is a hint. The agentic path sends
the same kind of hint and does not price from it.

## Follow-ups, not built here

These are what would let one lens finish a pull request whose diff does
not fit in one context window. They are Q26. None of them is in this
change.

1. Drop diff pages the lens has already read from later turns, the way
   compaction drops old tool results and then re-reads only what it
   still needs. The file-read gate (D42) can keep its own record of
   which pages were read; the model does not have to be shown those
   pages again.
2. A summary turn, analogous to `/compact`, before the input cap
   refuses the next call. The summary would be controller text, not a
   silent cut of the lens body.
3. A per-lens subagent only if a later phase needs a large read to stay
   out of the lens's own history. Pool size stays 1 until that is a
   separate decision.
