# Language Profile: Ruby

**Applies when.** Any project with a `Gemfile` — Rails/Sinatra services, CLIs,
gems.

## Toolchain
- Ruby version pinned in `.ruby-version` and the `Gemfile`; CI uses exactly
  that. Bundler for everything; `Gemfile.lock` always committed.

## Format & lint
- **RuboCop** with a committed `.rubocop.yml`; offending code fails CI.
  `rubocop -a` for safe autocorrect only — review `-A` changes.
- Prefer `standard` (the zero-config RuboCop preset) if the team wants fewer
  style debates; either way, one enforced config, not per-file taste.

## Idioms
- Small methods, expressive names, blocks over manual loops. Follow the
  community style guide; least surprise beats cleverness.
- **Freeze mutable constants** and use `# frozen_string_literal: true`.
  Mutating a shared string is a spooky-action bug.
- Keyword arguments for anything with more than two params; avoid boolean
  positional flags. `Struct`/`Data` over hashes for known shapes.
- Metaprogramming is a scalpel, not a hammer: `method_missing`/`define_method`
  earn their keep only when they remove real duplication, always paired with
  `respond_to_missing?`.

## Errors
- Rescue **specific** exceptions, never a bare `rescue` (which swallows
  `StandardError` and hides real bugs) — the no-swallow rule,
  `standards/error-handling.md`. Namespaced custom error classes for anything
  callers branch on. Never rescue `Exception` (it catches signals).

## Testing
- RSpec or Minitest — one per project, not both. Tests are first-class; a bug
  fix ships its regression spec.
- Mock at boundaries, not internals; `WebMock`/`VCR` for HTTP. Avoid
  `let`-soup — readable setup over DRY-to-illegibility.

## Dependencies
- Every gem passes `standards/dependency-policy.md`; pin and audit.
- **`bundler-audit`** (and `brakeman` for Rails) in CI; findings block merge.

## Review checklist add-ons
- [ ] RuboCop/standard config committed and green in CI
- [ ] No bare `rescue`; specific exceptions, namespaced custom errors
- [ ] `frozen_string_literal` on; shared constants frozen
- [ ] Keyword args over positional flags; no boolean-trap params
- [ ] Regression spec ships with every fix
- [ ] `bundler-audit` (+ `brakeman` on Rails) clean in CI
