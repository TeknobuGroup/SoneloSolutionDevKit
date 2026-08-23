# ADR-0001 — Adopt the Claude Code change pipeline

- Date: 2026-08-23
- Status: Accepted

## Context
Changes were breaking other parts of the system; changelog, testing, and UAT plans
drifted out of date; session context was being lost between conversations.

## Decision
All development runs through a gated pipeline in Claude Code: impact review in plan
mode before edits; post-change review, changelog, tests, UAT plan and docs updates
enforced by a Stop-hook gate locally and mirrored in CI; knowledge kept in the docs/
markdown layer that every session re-reads.

## Alternatives considered
Convention-only (CLAUDE.md instructions without hooks) — rejected: advisory, skippable.

## Consequences
Slightly slower per-change; deterministic guarantees that source changes ship with
changelog, regenerated types, green tests, and current UAT/docs.
