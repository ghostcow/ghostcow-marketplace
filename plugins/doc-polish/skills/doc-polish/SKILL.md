---
name: doc-polish
description: >-
  Forward-facing documentation clarity sweep over a branch or PR. Fixes two
  clarity smells in comments, docstrings, and PR bodies — "empty reassurance"
  (text describing what the code doesn't do or won't affect) and comments that
  aren't self-contained (leaning on a reference the reader can't see). Edits
  only documentation, never code, then runs the repo's own correctness checks
  to confirm nothing but prose changed. Use this whenever the user wants to
  clean up, review, or sweep documentation, comments, or docstrings on a branch
  or PR — including phrasings like "tidy the comments", "remove leftover/defensive
  comments", "make the docstrings clearer", or "make comments self-contained" —
  even if they don't name this skill explicitly.
---

# Forward-facing docs sweep

You are reviewing the documentation — comments, docstrings, and PR bodies — on the branch, PR, or
changes under review. Fix the two clarity smells below, editing only documentation, then report your
fixes and anything you deliberately kept.

Start by getting oriented: map out what this repo leans on to stay correct and to define its
conventions — its tests, and whatever else it uses to check correctness and set its norms — reading
the repo to find them rather than assuming a given tool. That map guides your edits to match the
repo's norms, and it's what you run at the end to confirm you changed nothing but the prose.

Good documentation lets a fresh reader, who wasn't part of building this, form the right mental model
on the first read. Find each smell by reasoning from its test, so you catch any phrasing rather than
a fixed set of words.

**Say what the code is, not what it isn't.** Text describing what something *doesn't* do or *won't*
affect is usually left over from a worry the author had; a reader who never had it only finds it
confusing. State the positive fact, or cut it. Test: *would a first-time reader have had the concern
this sentence answers?* If not, reframe or remove.

**Make every comment self-contained.** A reader should understand a comment without chasing anything
down. When it leans on a reference they can't see — another doc, a PR description, a label defined
elsewhere — inline the fact or drop the pointer. Test: *can this be understood from what's in front
of the reader?* (A reference is fine when its target is in the same file.)

<example>
Before: "Retry once here (see the design doc; satisfies invariant R2)."
After:  "Retry once: the upstream drops the first connection after an idle period."
</example>

The smell is empty reassurance, not every negative word. Keep a "not/never" that states a real
constraint a reader needs to use or change the code safely — ask whether it informs a decision they
must make, or only soothes a non-issue. Keep decision rationale ("chose X over Y because…") too, but
in the PR body where it serves review, not in the code.
