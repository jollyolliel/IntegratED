---
name: create-commit-message
description: Commit the current changes with a good message. Use when the user asks to commit, or runs /create-commit-message.
---

# Create commit message

Running this skill is the user's explicit instruction to commit.

1. `git status` and `git diff HEAD` to see what changed; `git log -5 --oneline` for style.
2. Stage the changes that belong to the work (`git add <paths>`; avoid secrets and
   unrelated files).
3. When the changes cover more than one concern, split them into several commits:
   stage and commit one concern at a time. A commit that mixes a couple of related
   things is fine; don't split hairs.
4. Write a short imperative subject, no prefix required, plus a body only if the
   *why* isn't obvious from the diff.
5. Run `git commit` with that message (once per commit). Don't push.
6. Report each commit hash and subject.

Landing on `master` auto-tags a release (`docs/operations/ci-and-releases.md`). For a
direct push to `master`, add `#major`, `#minor` or `#none` to the message only when
the default (patch) is wrong; PRs use `release:*` labels instead.
