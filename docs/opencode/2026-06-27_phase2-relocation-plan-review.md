# Phase 2 Relocation Plan — review

**To:** Deepseek V4 (opencode, plan author)
**From:** Claude Sonnet 4.6 (review session, 2026-06-27)
**Re:** `docs/plans/2026-06-28_phase2-relocation.md` (Status: draft, Risk: HIGH)
**Verification:** all findings checked against the live system (git tracking, live container mounts, compose)

## Summary

The plan is **mechanically well-engineered** — timestamped backup, RED-before-GREEN, a
10-assertion LOCKED ORACLE, a 12-check verify script, sensible service sequencing, and a
"halt, don't revert silently" stop rule. But it bundles three changes of very different
value and risk under one HIGH-tier umbrella, and the research/docs portion has a blocker plus
a weak security premise. Recommendation: **split it** — ship the secrets consolidation alone
(low risk, real value), give the research relocation its own design, and drop the docs
relocation entirely.

---

## 🔴 BLOCKER — moving `docs/` and `research/` pulls tracked files out of git

The git repo root is **`/root`** (`git rev-parse --show-toplevel` → `/root`), and both target
trees are tracked:

- `docs/` → **92 tracked files** (`git ls-files docs/ | wc -l`), including `ROADMAP.md`,
  `EXECUTOR_CONTRACT.md`, and **every plan under `docs/plans/`** — this relocation plan included.
- `research/` → **104 tracked files** (`git ls-files research/ | wc -l`).

`mv /root/docs /srv/shared/docs` and `mv /root/research /srv/shared/research` move them
**outside the repository working tree**. Consequences the plan does not address:

1. All ~196 files show as mass deletions in `git status`; `/srv/shared/` is **not a git repo**,
   so the relocated files are no longer version-controlled.
2. It is self-defeating for the documented planning workflow: CLAUDE.md states plans in
   `docs/plans/` are the **cross-tool handoff artifact** that opencode/Deepseek read from the
   checkout. Moving `docs/` out of git orphans those plans.
3. Phase 5 says "update ROADMAP.md / OPERATIONS.md … and commit" — but post-move those files
   live at `/srv/shared/docs/`, outside the `/root` repo. **There is no path to commit them.**
   The execution steps stop here with no git story (no symlink-back, submodule, or repo move).

This alone blocks the plan as written for the docs/research portions.

---

## 🟠 MAJOR — the research/docs security premise is largely illusory

The plan's rationale (lines 31, 33) is that read-only consumers "cannot traverse parent to reach
`/root`." **Bind mounts do not expose the host parent directory.** Verified against the live
openclaw container — its mount table is *only*:

```
/root/research -> /research (ro)
/root/docs     -> /docs (ro)
/root/openclaw/config -> /config (ro)
root_openclaw_workspace -> /workspace (rw)
```

There is **no `/root` inside the container** to traverse to. The "parent traversal" hole the
move claims to close does not exist today. So relocating research/docs is **defense-in-depth at
best** (guarding against a *future* mis-authored `/root:/x` mount), not closing a real hole —
yet it carries HIGH risk (all 9 services, ~196 files out of git).

Verify-script check #8 / oracle O9 ("openclaw cannot reach `/root/secrets`") illustrates the
same point: that is **already true today** and stays true wherever secrets live, so it does not
prove the relocation added protection.

---

## 🟢 The genuinely valuable part: secrets consolidation (Phase 3)

A single `/root/secrets/` at mode `700` is a real, modest improvement — it shrinks the surface
for an accidental over-broad mount or a stray `git add`, and centralizes the `env_file:`
references. Critically, this part is **low-risk**: verified that **no secret file is
bind-mounted into any container** (only three `env_file:` references — straitsagent/agent.env,
affectionbot/affection.env, openclaw/openclaw.env), and `windmill-sa-key.json` / `keys.md` are
not mounted anywhere (the SA key is consumed via a Windmill *resource*, not the host path; the
on-disk copy is a reference/backup). So consolidating secrets touches only 3 `env_file:` path
edits + the `.env` symlink + doc updates — no runtime data path moves.

---

## Minor notes
- **`affectionbot` confirmed** as a real compose service (line 252) — that reference is valid.
- **`/srv` and `/root` are the same filesystem** (`/dev/sda1`) — so `mv` is an atomic rename;
  P2.1's "mv may fail if the mount is held" is over-cautious (a held bind mount does not block a
  same-fs rename). Harmless, but the stated reason is imprecise. (Also a plus: same-fs means no
  brief plaintext-secret copy across devices.)
- The `.env` → symlink approach (P3.3) is sound; compose reads through the symlink at parse time.

---

## Recommendation (agreed with owner 2026-06-27)

Split the HIGH-tier plan into three independent pieces:

1. **Secrets consolidation — ship now** as its own LOW/MED plan
   (`docs/plans/2026-06-27_secrets-consolidation.md`). Does not touch git tracking.
   **Plus** a small related hardening the owner requested: **remove openclaw's `/docs:ro`
   mount** (reduce its read surface — openclaw keeps `/research` access). Folded into the
   secrets plan since both are targeted, low-risk hardening.
2. **Research relocation — own design.** Owner agrees with the move in principle, but it needs a
   dedicated plan that explicitly handles the git-tracking question (relocate the repo, keep
   research in-repo and symlink into `/srv`, or move research out of git deliberately with a
   versioning story). Deferred.
3. **Docs relocation — dropped.** No security value (bind mounts already isolate), and it would
   pull the plan/handoff corpus out of git. Owner has instead chosen to **revoke openclaw's docs
   access** (item 1) rather than relocate docs.
