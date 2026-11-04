# OpenFAST autocompiler

**Reproducible aeroelastic-solver builds without administrator access.**

Rootless GNU/Linux builds of **OpenFAST 4.2.0**, TurbSim and optional FAST.Farm.
Detect existing math libraries, test them, then explicitly choose whether to
reuse them or build private pinned BLAS/LAPACK. No sudo, APT, Conda, global
linker changes or shell-profile edits.

## Run order

```bash
# 1. Read-only inspection, with a temporary numerical link/run test.
bash build_openfast.sh --preflight
# 2. Interactive: inspect detected BLAS/LAPACK, choose system or private build.
bash build_openfast.sh --fast-farm --bootstrap-tools
# Batch/noninteractive callers MUST choose a policy:
bash build_openfast.sh --fast-farm --bootstrap-tools --math-libs system --jobs 8
# Alternative:
bash build_openfast.sh --fast-farm --bootstrap-tools --math-libs build --jobs 8
```

Use `--help` for every option. Host prerequisites are C/C++/Fortran compilers,
Git, Make, Python 3 with venv/pip support, `file` and `ldd`. CMake is required;
`--bootstrap-tools` installs pinned CMake 3.31.6 locally if absent. Host
compilers are checked, not installed or replaced. Choose compatible compilers
with `CC`, `CXX`, `FC`; choose a private writable root with `--root` or
`OPENFAST_BUILD_ROOT`. The default is a sibling `openfast-local` directory.

## System versus private libraries

`--math-libs system` prints the detected paths, compiles a Fortran program
with those libraries, and verifies DGESV linear-system and DGEMM matrix-product
solutions numerically. This checks usable link/runtime ABI, not just filenames.
Override detection with `BLAS_LIBRARY` and `LAPACK_LIBRARY`. Failed checks stop
before building a solver. No system library is altered.

`--math-libs build` downloads the official Reference-LAPACK v3.12.1 source,
verifies commit `6ec7f2bc4ecf4c4a93496aa2fa519575bc0e39ca`, builds its BLAS/LAPACK
under `<root>/deps/lapack-3.12.1`, and runs the same numerical check. The local
manifest records source/compiler/library hashes and verification. The upstream
license stays in the downloaded source. No globally installed library is replaced.

```bash
# Build/check only the math dependencies; stop before OpenFAST:
bash build_openfast.sh --math-libs build --deps-only --jobs 8
# After the required source/tool downloads, use no network:
bash build_openfast.sh --math-libs build --fast-farm --offline --jobs 8
```

The script's interactive default asks; it does not silently select a policy
in an IDE/batch job. `--preflight` lists choices without prompting/installing.
The host compiler and its OpenMP runtime remain one compatible toolchain;
the library choice does not mean independently replacing libgomp/libgfortran.

## Generated files and isolation

| Profile | Build/install suffix | Activation file |
| --- | --- | --- |
| OpenFAST, system math | `v4.2.0` | `activate.sh` |
| FAST.Farm, system math | `v4.2.0-fastfarm` | `activate-fastfarm.sh` |
| OpenFAST, private math | `v4.2.0-private` | `activate-private.sh` |
| FAST.Farm, private math | `v4.2.0-fastfarm-private` | `activate-fastfarm-private.sh` |

Under your selected root: `sources/`, `build/`, `install/`, `deps/`, `tools/`
and `logs/`. Activation is an optional file you explicitly source; no profile
is edited. FAST.Farm enables OpenMP. Its installation also contains OpenFAST,
AeroDyn driver, TurbSim and shared libraries. `--jobs` controls compilation,
not runtime threads. Set `OMP_NUM_THREADS` when launching FAST.Farm or use a
client application's explicit thread setting.

`build-manifest.json` records the OpenFAST source commit, compiler versions,
CMake cache, selected math paths and executable hashes. `--verify` checks
presence, identity and runtime linkage; it preserves an existing build manifest
and writes `verification-manifest.json`. A build/link check is separate from
an OpenFAST or FAST.Farm numerical regression against reference outputs.

## Tested evidence

On GNU/Linux x86_64 / GCC 11.4:

- System BLAS/LAPACK numerical link/run checks passed.
- The system-library OpenFAST 4.2.0 and OpenMP FAST.Farm build was used in the
  recorded FASTScale simulations; the pinned upstream 90 s FAST.Farm regression
  and paired steady farm runs completed.
- The private Reference-LAPACK 3.12.1 build completed without root and passed
  the DGESV/DGEMM numerical checks.
- A complete new OpenFAST/FAST.Farm build/regression linked against that private
  dependency build has **not** been run; no private-solver result is asserted.

`tests/test_compiler.py` exercises argument validation, root restrictions,
explicit batch library policy, numerical preflight and bundled-copy consistency
where host tools are available. Run `python3 -m unittest discover -s tests -v`.

## Sources and publication

Official [OpenFAST source at the tested revision](https://github.com/OpenFAST/openfast/tree/3a9d3f29f03b52b536d391fbd360683f847be712),
[OpenFAST build guidance](https://openfast.readthedocs.io/en/main/source/install/index.html),
and [Reference-LAPACK source](https://github.com/Reference-LAPACK/lapack/tree/6ec7f2bc4ecf4c4a93496aa2fa519575bc0e39ca).
The scripts orchestrate those projects; they do not claim their solver/library
authorship. Newer upstream docs may describe a different release; the tested
4.2.0 source is authoritative for this build.

Original compiler code is licensed under [Apache-2.0](LICENSE); see [NOTICE](NOTICE)
for upstream authorship and licensing boundaries. Upstream source and binary
trees are downloaded/generated locally and are not part of this repository.

This directory is prepared for an independent GitHub upload. See the
[release review](RELEASE_REVIEW.md) for verified scope and remaining limits.
FASTScale includes the same builder with an adjusted default root path so it
can install solvers from its own clone.
