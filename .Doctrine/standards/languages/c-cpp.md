# Language Profile: C / C++

**Applies when.** Any target built from `.c`/`.cc`/`.cpp`/`.h`/`.hpp` — native
libraries, systems code, performance-critical modules, FFI targets.

## Toolchain
- Standard pinned explicitly: `-std=c17` / `-std=c++20` (or the project's), in
  the build files, not the developer's memory. CMake or Meson over hand-rolled
  Makefiles for anything multi-file.
- One warning bar for everyone: `-Wall -Wextra -Wpedantic`, and **`-Werror` in
  CI**. Warnings are defects that haven't crashed yet.

## Build hygiene & safety
- **Sanitizers in CI**, not optional: ASan + UBSan on the test build; TSan for
  anything threaded. They catch bugs a manual valgrind pass misses.
- `-fstack-protector-strong`, `_FORTIFY_SOURCE=2`, position-independent code
  for shipped binaries. Static analysis: `clang-tidy` (with its
  `cppcoreguidelines`/`bugprone` checks) and a committed config.

## C++ idioms
- **RAII owns every resource.** No raw `new`/`delete` in application code;
  `unique_ptr`/`shared_ptr` and containers manage lifetime. Rule of zero; rule
  of five only when you truly own a resource.
- Prefer `std::` containers/algorithms and `span`/`string_view` over raw
  pointer + length. Pass by value + move, or by `const&`; return by value.
- `const`-correct and `constexpr` where it holds. No owning raw pointers
  crossing an API; express ownership in the type.

## C idioms
- Every `malloc` has one owner and one `free` on every path (including error
  paths); check the return. No implicit `int`, no VLAs on untrusted sizes.
- Bounds are explicit: pass length with every buffer; `snprintf` over
  `sprintf`, bounded copies over `strcpy`.

## Errors
- No swallowed failures: every `errno`/return-code path handled or propagated
  (the no-swallow rule, `standards/error-handling.md`). C++: exceptions xor
  `expected`/status — pick one per module boundary and document it; destructors
  and FFI boundaries never throw.

## Testing
- A real framework (GoogleTest/Catch2 for C++, Unity/CMocka for C), run in CI
  under ASan/UBSan.
- **Fuzz every parser and untrusted-byte path** (libFuzzer/AFL++). Memory bugs
  live where input meets a buffer.

## Dependencies
- A package manager (vcpkg/Conan) over vendored source blobs; pin versions.
  Every new dep passes `standards/dependency-policy.md`. Audit transitive
  native deps — a CVE in a header-only lib is still your CVE.

## Review checklist add-ons
- [ ] `-Wall -Wextra -Werror` and ASan/UBSan green in CI
- [ ] Every allocation has a single owner and is freed on all paths
- [ ] No owning raw pointers across an API; RAII/smart pointers in C++
- [ ] Buffers carry their length; bounded string/mem operations only
- [ ] Parsers of untrusted input are fuzzed
- [ ] Error/`errno` paths handled or propagated, none dropped
