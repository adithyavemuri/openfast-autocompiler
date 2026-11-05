# Public-source release review — 4 November 2026

The original compiler, tests and documentation have an Apache-2.0 license
and NOTICE. No upstream solver, library source tree or binary is bundled.
The builder downloads official upstream sources and retains them locally.
The generated installation remains subject to upstream licenses.

## Checks completed

- Five automated tests passed on the development GNU/Linux host, including
  shell syntax, invalid arguments, protected destination rejection, explicit
  noninteractive library policy, bundled-copy consistency and numerical
  DGESV/DGEMM system-library preflight.
- The default OpenFAST 4.2.0 and optional Reference-LAPACK 3.12.1 sources are
  checked against their documented exact commits.
- Existing system-library solver/farm simulations and the private LAPACK
  numerical checks are described in README with their actual scope.

## Publication checks — 5 November 2026

The staged checkout has clean Git history and contains eight source,
documentation and test files. LICENSE/NOTICE, local README links, source/stage
byte identity, shell syntax, and high-confidence credential patterns were checked.
No generated installations or upstream source/binary trees are included.

Using the existing local CMake, all five development tests passed. In the
independent staged checkout, four passed and the sibling-only FASTScale copy
check was skipped; the numerical DGESV/DGEMM check passed. No new OpenFAST,
FAST.Farm or private-LAPACK build was run for publication.

## Limits to carry into a first release

GNU/Linux is the supported platform. Host C/C++/Fortran compilers and Python
are prerequisites. Windows/macOS, arbitrary compiler combinations and a new
complete private-library OpenFAST/FAST.Farm build/regression have not been
validated. `--verify` checks binaries and linkage, not physical correctness.
Build jobs and runtime threads are separate settings.

This publishes the build-orchestrator source, not solver binaries.
The source upload does not create a release tag or validate additional platforms.

Run the checks from a clone:

```bash
python3 -m unittest discover -s tests -v
bash build_openfast.sh --preflight
```
