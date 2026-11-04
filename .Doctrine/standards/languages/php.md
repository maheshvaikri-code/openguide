# Language Profile: PHP

**Applies when.** Any project with a `composer.json` — Laravel/Symfony apps,
APIs, packages.

## Toolchain
- PHP version pinned in `composer.json` `require.php`; CI matches. Composer for
  everything; `composer.lock` committed. `declare(strict_types=1);` at the top
  of every file — no silent type juggling.

## Format & lint
- **PHP-CS-Fixer** or PHP_CodeSniffer (PSR-12) with a committed config;
  formatting failures block CI.
- **Static analysis is mandatory:** PHPStan (or Psalm) at a high level (>=
  level 6, climbing). PHP's dynamism hides bugs static analysis surfaces.

## Idioms
- Type everything: parameter, return, and property types; `readonly` for
  immutables; enums over class constants for closed sets (PHP 8.1+).
- Constructor property promotion, named arguments for clarity, `match` over
  long `switch`. Value objects over associative-array grab-bags.
- Follow **PSR** standards (PSR-4 autoloading, PSR-12 style, PSR-3 logging,
  PSR-7/15 HTTP) — they are the interop contract of the ecosystem.

## Errors
- Throw typed exceptions; catch **specific** types, never a bare
  `catch (\Throwable)` that swallows (the no-swallow rule,
  `standards/error-handling.md`). Namespaced exception hierarchy for anything
  callers branch on. `null` returns are typed (`?T`), not implicit.

## Security (PHP earns its own line)
- **Never** build SQL by string concatenation — prepared statements /
  parameter binding only (PDO or the framework's query builder). SQL injection
  is the house's most common critical.
- Escape on output by context (HTML/attr/JS/URL); keep the framework's
  templating auto-escaping on. Validate and sanitize all input; CSRF tokens on
  state-changing routes.

## Testing
- **PHPUnit** (or Pest); a fix ships its regression test. Mock at boundaries;
  functional tests for framework routes.

## Dependencies
- Every package passes `standards/dependency-policy.md`; pin and audit.
- **`composer audit`** in CI; findings block merge.

## Review checklist add-ons
- [ ] `declare(strict_types=1)` everywhere; full parameter/return/property types
- [ ] PHPStan/Psalm at the agreed level, green in CI
- [ ] All SQL parameterized; output escaped by context; CSRF on mutations
- [ ] Specific exception catches, namespaced hierarchy, no bare swallow
- [ ] `composer audit` clean; PSR-4/12 conformant
- [ ] Regression test ships with every fix
