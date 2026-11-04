# Language Profile: Swift

**Applies when.** Any target with a `Package.swift` or Xcode project — iOS/
macOS apps, server-side Swift, SwiftPM libraries.

## Toolchain
- Swift version pinned via the toolchain / `swift-tools-version` in
  `Package.swift`; CI builds with exactly that. SwiftPM for dependencies;
  `Package.resolved` committed.

## Format & lint
- **SwiftFormat** + **SwiftLint** with committed configs; violations fail CI.
- Warnings-as-errors for shipped targets (`-warnings-as-errors`).

## Idioms
- **Value types by default** — `struct`/`enum` over `class` unless you need
  reference semantics or identity. Immutability by default: `let` over `var`.
- **Optionals express absence; never force-unwrap (`!`) on untrusted values.**
  `guard let`/`if let`/`??`. A force-unwrap is a crash you chose — allowed only
  where nil is a true programmer invariant, with a comment.
- Protocol-oriented over deep class hierarchies; generics + protocol
  constraints for reuse. `Codable` at serialization boundaries.
- Enums with associated values to make illegal states unrepresentable.

## Concurrency
- **Swift Concurrency (`async`/`await`, actors)** over ad-hoc GCD queues for
  new code. Shared mutable state lives in an `actor`; UI work is `@MainActor`.
  Respect `Sendable` — don't silence its warnings; they are data-race
  prevention (`skills/concurrency.md`).

## Errors
- Typed `throws` + `Result` for recoverable failures; do **not** swallow with
  `try?` where the error matters (the no-swallow rule,
  `standards/error-handling.md`). `fatalError`/`precondition` only for broken
  invariants, never for expected input failure.

## Testing
- XCTest (or swift-testing); a fix ships its regression test. UI tests for
  critical flows; assert the five UI states where they apply (`skills/ui.md`).

## Dependencies
- Every SwiftPM/CocoaPods dependency passes `standards/dependency-policy.md`;
  pin and audit. Minimize — the platform SDK is broad.

## Review checklist add-ons
- [ ] SwiftFormat/SwiftLint configs committed and green in CI
- [ ] No force-unwrap on untrusted values; optionals handled explicitly
- [ ] Value types + immutability by default; illegal states unrepresentable
- [ ] Shared mutable state actor-isolated; `Sendable`/`@MainActor` respected
- [ ] Errors typed and handled, none swallowed by `try?`
- [ ] Regression test ships with every fix
