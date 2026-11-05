# Public-source release review — 5 November 2026

The Python builder, commented INI settings, compatibility launcher, tests and
documentation have an Apache-2.0 license and NOTICE. No upstream solver,
library source tree or binary is bundled. Official sources are downloaded
locally, and upstream licenses remain applicable to generated installations.

## Checks completed for the Python runner

Twelve automated tests passed on GNU/Linux x86_64 with GCC 11.4 and an existing
local CMake. They check:

- Both Python and Bash entry points and shell launcher syntax.
- Configuration precedence, relative paths, paths containing spaces, booleans,
  environment fallbacks, invalid options, and protected output destinations.
- Explicit batch library policy and failure for missing supplied libraries,
  without creating an installation.
- Real Fortran DGESV/DGEMM numerical preflight through supplied local library
  paths containing spaces; preflight does not create persistent build files.
- Offline source failure, source-only behavior without compilation, exact
  source-commit validation, and refusal of modified tracked files.
- Activation with local library directories while preserving the existing
  environment.
- A complete configure/build/install/verify cycle using a tiny Fortran/CMake
  fixture, local shared math libraries and paths with spaces. Build provenance
  survives a subsequent verification run.

The default OpenFAST 4.2.0 and private Reference-LAPACK 3.12.1 sources retain
exact commit checks. README documents the running order, every user setting,
local library selection, prerequisites, output folders and code navigation.
No tests require network access or a full solver build.

## Limits

The Python rewrite has not been used for a new full OpenFAST/FAST.Farm build.
Prior system-library builds and simulations, and private LAPACK numerical
checks, are evidence for the selected upstream build settings, not a complete
regression of this runner. A full private-library OpenFAST/FAST.Farm build and
numerical regression remains unverified. Windows/macOS and arbitrary compiler
combinations are unvalidated.

Host compilers, Python, Git, Make, `file` and `ldd` must be provided by the user.
CMake can be installed locally when explicitly enabled and online. `--verify`
checks binaries/linkage, not physical correctness. Compilation workers and
simulation threads are independent.

Only this standalone autocompiler is updated by this release; FASTScale's own
installer and the GitHub profile are not modified. This uploads source to the
public main branch; it does not publish solver binaries or create a release tag.

## Reproduce the checks

```bash
python3 -m unittest discover -s tests -v
python3 build_openfast.py --preflight
```

For CMake outside PATH, supply `CMAKE_COMMAND=/absolute/path/to/cmake` when
running the test command. The numerical/integration tests explicitly skip
when their required toolchain is unavailable.
