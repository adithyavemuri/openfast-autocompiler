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

## Limits to carry into a first release

GNU/Linux is the supported platform. Host C/C++/Fortran compilers and Python
are prerequisites. Windows/macOS, arbitrary compiler combinations and a new
complete private-library OpenFAST/FAST.Farm build/regression have not been
validated. `--verify` checks binaries and linkage, not physical correctness.
Build jobs and runtime threads are separate settings.

This is preparation of a source release, not publication of solver binaries.
Repository creation, visibility and release tagging are separate final steps.

Run the checks from a clone:

```bash
python3 -m unittest discover -s tests -v
bash build_openfast.sh --preflight
```
