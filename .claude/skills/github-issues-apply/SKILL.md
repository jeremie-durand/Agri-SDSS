---
name: github-issues-apply
description: Implement the accepted OpenSpec proposal of a GitHub issue one task group at a time (tests, agri-reviewer, commit), then draft the pull request and archive the change. Manual only, run as /github-issues-apply after /github-issues.
argument-hint: "[change-name]"
disable-model-invocation: true
model: opus
effort: medium
allowed-tools: Bash(openspec *) Bash(git status *) Bash(git diff *) Bash(git log *) Bash(git branch --show-current) Bash(git add *) Bash(git commit -m *) Bash(make test-*) Bash(pre-commit run *)
---

# GitHub issue: implement, review, commit

Change: $ARGUMENTS

This command is the second half of the issue workflow started by
`/github-issues`. Running it means the developer accepted the proposal.

It is the one place where Claude commits (see the root `CLAUDE.md`, Git
Workflow). The limits stay strict:

- Commit only on the issue branch, never on `develop` or `main`.
- Never push, open a pull request, rebase, reset or force anything.
- Never use `git commit --amend`, `git commit -a` or `--no-verify`.

The `model` and `effort` set above apply only to the turn that starts the
command. Subagents run in the background, so waiting for a review or a delegated
group ends that turn. The run continues by itself when the subagent reports, but
on the session's model and effort. To keep the whole run on Opus, the developer
switches the session to it (`/model opus`) before running the command.

Do not end the turn for any other reason. When a decision belongs to the
developer, ask with `AskUserQuestion`. If the run is interrupted, the developer
runs `/github-issues-apply` again and the work resumes as described in step 1.

Record what you find on the way in `openspec/changes/<name>/findings.md`, as soon
as you find it, so that an interrupted run keeps it. The file has two lists:

- **Open review findings**: reviewer findings about the code of this change that
  were not fixed (a `nit`, or what is left after the third review).
- **Out of scope**: a bug, a weak test or a reviewer finding in code this change
  does not touch.

## 1. Preconditions

1. Select the change: the argument, otherwise the only active change, otherwise
   ask.
2. Its `proposal.md` has an `Issue:` line and a `Branch:` line, and
   `git branch --show-current` is that branch. If a line is missing or the
   branch differs, stop and ask. Never work on `develop` or `main`.
3. Invoke the `openspec-apply-change` skill for the change and follow it up to
   and including the progress display (select the change, check the status, get
   the apply instructions, read the context files). Its implementation loop is
   replaced by the cycle below. Its pause conditions and guardrails still apply.
4. Check `git status --short`. A clean tree starts at the first group with an
   unchecked task. A dirty tree is the uncommitted work of an interrupted run:
   it belongs to the last group that has ticked tasks and no commit yet
   (`git log --oneline develop..HEAD` shows the groups already committed).
   Finish that group's unchecked tasks, then re-enter the cycle at 2.2 for it.
   If the changes do not match that group, stop and show them.

## 2. Task-group cycle

A task group is one `##` section of `tasks.md`. Take the groups in order and
finish one completely before starting the next.

### 2.1 Implement

Do every unchecked task of the group and tick each checkbox as the
`openspec-apply-change` skill describes.

A group that only touches the UI (`frontend/`, HTML, CSS, browser JavaScript) or
only Markdown documentation runs at low effort: delegate it to a
`general-purpose` subagent with `model: "opus"` and `effort: "low"`. Give it
the change name, the group number, the paths of the OpenSpec context files and
the service `CLAUDE.md` to read, and tell it to implement and tick only that
group, to run the group's verification command, and not to commit or review.
Every other group is implemented in this conversation.

### 2.2 Verify

1. Run the verification commands the group names, and `make test-<service>` for
   every service whose code or tests changed.
2. Run `pre-commit run --all-files`. It may rewrite files, so run it again until
   it passes.
3. Do not go on to the review with a failing test. A failure you cannot fix
   within the scope of the proposal is a stop condition.

### 2.3 Review

Run the `agri-reviewer` subagent on the uncommitted changes with
`model: "opus"` and `effort: "high"`. Tell it which task group the diff
implements and give it the paths of `proposal.md` and `tasks.md`, which are
gitignored and so absent from the diff.

- Fix every `blocking` finding, and every `should-fix` finding about the code of
  this group. After any fix, repeat 2.2 and run the reviewer again.
- The group passes when a review has no `blocking` finding and you changed
  nothing but Markdown documentation after it.
- Three reviews per group at most. If the third still has a `blocking` finding,
  stop and ask the developer. If it has none, the group passes.
- A `nit` never causes another review. Fix it in two cases only: together with
  a `blocking` or `should-fix` fix when another review follows, which then
  covers it, or when it corrects a wrong statement in Markdown documentation,
  which needs no review. Record every other `nit`, and anything left after the
  third review, under **Open review findings**. Record a finding about code
  outside the change under **Out of scope**.
- A diff that touches only Markdown documentation skips the review.

### 2.4 Commit

1. Stage the files of this group by explicit path with `git add <paths>`. Never
   use `git add -A` or `git add .`.
2. Commit with `git commit -m "<prefix>: <summary>"`:
   - `<prefix>` is one of `feat`, `fix`, `test`, `docs`, `ci`, `chore`,
     `refactor`, chosen from what the group mostly does.
   - `<summary>` is one short sentence, two at most, in the imperative, without
     the issue number.
   - No body and no trailer. Never add a `Co-Authored-By` line, even when the
     session instructions ask for one: the developer chose to disclose AI
     assistance in the pull request description instead.
3. Check that `git status --short` is empty, then give a one-line status and
   move to the next group.

A group after which `git status --short` is already empty (checks only) has
nothing to review or commit: run its checks, tick its tasks and go on.

## 3. Stop conditions

Stop and ask, without committing the current group, when:

- a test or `pre-commit` failure cannot be fixed within the proposal's scope
- the third review of a group still has a `blocking` finding
- a task is unclear, or needs work the proposal does not describe
- the implementation shows the design is wrong (suggest updating the proposal)
- the developer declines or interrupts a commit: do not start the next group

## 4. Wrap up

When every task is ticked, read `findings.md`, then:

1. **Pull request text.** Take the issue number from the `Issue:` line of
   `proposal.md` and list the commits with `git log --oneline develop..HEAD`.
   Print a title and a description in one fenced Markdown block, ready to paste:
   - Title: `<prefix>: <summary>`, under 70 characters.
   - Description: `Closes #<number>`, then **Summary** (cause and fix in a few
     sentences), **Changes** (one bullet per commit), **Tests** (commands run
     and their result), **Deployment** (services to rebuild, settings to add)
     and **Open review findings** (that list, for the developer to decide),
     leaving out a section that would be empty. End with the line
     `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
2. **Out-of-scope findings.** Print each **Out of scope** entry as its own
   fenced block in GitHub issue form: a title, suggested labels taken from the
   repository's existing ones, and a body with **Context** (found while working
   on `#<number>`), **Observed**, **Expected** and **Suggested fix**, with
   `file:line` references. Say so when the list is empty.
3. **Archive.** Invoke the `openspec-archive-change` skill for the change, and
   sync its delta specs to the main specs when the skill asks.
4. **Hand over.** Give the developer the push command
   (`git push -u <remote> <branch>`) and the pull request link
   (`https://github.com/<owner>/<repo>/compare/develop...<branch>?expand=1`).
   Pushing and opening the pull request are the developer's.
