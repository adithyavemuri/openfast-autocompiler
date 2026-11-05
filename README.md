# OpenFAST autocompiler

**Build OpenFAST and FAST.Farm locally, without administrator access.**

Edit a commented settings file, check your computer, then start the build.
You do not need to edit Bash or Python to select your own libraries or tools.
The builder downloads official upstream sources; it does not bundle or replace
OpenFAST, BLAS/LAPACK, or their licenses.

## Start here

You need GNU/Linux, **Python 3.8 or newer**, compatible C/C++/Fortran compilers
(normally `gcc`, `g++`, `gfortran`), Git, Make, `file` and `ldd`. Python's
`venv` and pip are needed only if you ask the builder to install CMake locally.
The Python builder itself uses only the standard library; no pip installation
is needed to run it.

```bash
git clone https://github.com/adithyavemuri/openfast-autocompiler.git
cd openfast-autocompiler
```

1. Open **[build-settings.ini](build-settings.ini)** in VS Code or another editor.
   Each setting has comments and examples. Choose `policy = system` to reuse
   libraries you already have, or `policy = build` to compile private copies.
   Leave `policy = ask` if you want to choose in an interactive terminal.
2. Run the check below. It shows the selected paths and, for existing math
   libraries, compiles and runs a tiny numerical test. It does not download
   anything or create an installation.
3. If the checks look right, run the build command.

```bash
# Check first. A missing CMake is reported, not installed by this command.
python3 build_openfast.py --preflight

# Build using your settings. Enable bootstrap_tools in the INI file if you
# want the builder to install a missing CMake locally.
python3 build_openfast.py
```

For FAST.Farm as well, set `fast_farm = yes` in the file. FAST.Farm enables
OpenMP and uses a separate installation. `jobs` sets compilation workers;
simulation threads are controlled separately with `OMP_NUM_THREADS`.

The build prints its log and installation paths. After a successful build,
it prints a `source .../activate.sh` command (or the FAST.Farm/private variant).
Run that command **in the terminal where you want to use the solver**. No shell
profile or system configuration is changed.

## Use libraries you already installed

The name `system` means **reuse existing libraries**, including ones in your
home directory. You do not need root access or a system-wide installation.
Change these settings, supplying the actual library **files**, not folders:

```ini
[libraries]
policy = system
blas = /home/yourname/math/lib/libblas.so
lapack = /home/yourname/math/lib/liblapack.so
```

Leave `blas` and `lapack` blank to auto-detect them using your Fortran compiler.
An OpenBLAS library that provides both BLAS and LAPACK can be supplied in both
fields. `.a` static archives are also supported when these two files and the
compiler provide all required dependencies. Arbitrary vendor link-line recipes
are not implemented; the numerical check detects an unusable combination.
Use compatible LP64 BLAS/LAPACK and compiler runtimes.

The check solves a linear system with **DGESV** and multiplies matrices with
**DGEMM**, then compares their results with known answers. A failed test stops
the build. An explicitly supplied missing or incompatible library is **not**
silently replaced by an auto-detected one. Correct its path, select compatible
libraries, or change `policy` to `build` yourself.

Local shared-library directories are passed to the numerical check, recorded
in the solver's CMake runtime search paths, and included in the optional
activation file. The builder changes only its child processes' environment;
it does not modify your system loader settings.

## Use your own compilers or CMake

In the same file, set executable names or full paths. Keep C, C++ and Fortran
from a compatible toolchain:

```ini
[tools]
c_compiler = /home/yourname/gcc/bin/gcc
cxx_compiler = /home/yourname/gcc/bin/g++
fortran_compiler = /home/yourname/gcc/bin/gfortran
cmake = /home/yourname/tools/bin/cmake
```

Blank compiler fields use `CC`, `CXX`, `FC`, then `gcc`, `g++`, `gfortran` on
`PATH`. Blank CMake uses `CMAKE_COMMAND`, then `cmake` on `PATH`, then
`<root>/tools/bin/cmake`. An explicit invalid tool path stops with an error.
The builder checks host compilers, Git and Make; **it does not install them**.

With `bootstrap_tools = yes`, a missing CMake is installed as pinned
**CMake 3.31.6** under `<root>/tools`, using a local Python virtual environment.
This requires working venv/pip and network access. It is refused in offline mode.
There are no sudo, APT, Conda, global linker, or shell-profile changes.

## Where files go, and how settings are chosen

Set `[build] root` to your writable output folder. Blank means a sibling
`openfast-local` directory beside this repository. All persistent downloads,
logs and generated files stay there, outside this source repository:

| Folder under `root` | Contents |
| --- | --- |
| `sources/` | Downloaded, revision-checked OpenFAST and optional LAPACK source |
| `build/` | CMake caches and compilation files |
| `install/` | Solver executables, libraries and build manifests |
| `deps/` | Private BLAS/LAPACK installation and its manifest |
| `tools/` | Optional local CMake virtual environment |
| `logs/` | Commands and live build output |

| Profile | Build/install folder | Activation file under `root` |
| --- | --- | --- |
| OpenFAST, existing math | `v4.2.0` | `activate.sh` |
| FAST.Farm, existing math | `v4.2.0-fastfarm` | `activate-fastfarm.sh` |
| OpenFAST, private math | `v4.2.0-private` | `activate-private.sh` |
| FAST.Farm, private math | `v4.2.0-fastfarm-private` | `activate-fastfarm-private.sh` |

Settings precedence is **command-line option → nonblank INI setting → documented
environment variable → built-in default**. For example, `--jobs 4` overrides
`jobs = 8` in the file. Blank INI fields can use `OPENFAST_BUILD_ROOT`,
`OPENFAST_VERSION`, `JOBS`, `CC`, `CXX`, `FC`, `CMAKE_COMMAND`, `BLAS_LIBRARY`
and `LAPACK_LIBRARY`, as explained beside each setting.

INI paths may contain spaces: **do not add quotes**. `~` is expanded. Relative
INI paths are relative to the settings file, so changing your IDE's working
folder does not change their meaning. CLI/environment relative paths use the
terminal's working folder. Shell expressions such as `$HOME` are not expanded
in the INI file; use `~` or an absolute path.

To keep personal paths separate, copy `build-settings.ini` to
`local-settings.ini` (ignored by Git), edit that copy, then use:

```bash
python3 build_openfast.py --config local-settings.ini --preflight
python3 build_openfast.py --config local-settings.ini
```

Use the same settings file and profile flags for building and verification.
The effective paths and choices are printed before building and saved in the
log. Build manifests include the settings file hash, selected library paths,
source revision, compiler versions, CMake cache hash and executable hashes.

## Other stopping points

These commands use the default settings file; add `--config your-file.ini` to
use another one. Run `python3 build_openfast.py --help` for all flags.

```bash
# Build/check only private BLAS/LAPACK; stop before OpenFAST.
python3 build_openfast.py --math-libs build --deps-only --bootstrap-tools

# Download/check OpenFAST and private LAPACK sources, without compiling either.
# CMake is not needed for this stopping point.
python3 build_openfast.py --math-libs build --fetch-only

# Build FAST.Farm using existing math, with four compilation workers.
python3 build_openfast.py --fast-farm --math-libs system --jobs 4 --bootstrap-tools

# After required source/tool downloads: build without network access.
python3 build_openfast.py --fast-farm --math-libs system --offline

# Check that installation's executables and runtime linkage, without rebuilding.
python3 build_openfast.py --fast-farm --math-libs system --verify
```

`--no-fast-farm`, `--no-bootstrap-tools` and `--no-offline` override corresponding
`yes` settings. Batch/IDE input without a terminal cannot answer `ask`: select
`system` or `build` explicitly. `--verify` also requires an explicit policy so
it selects the intended installation. `--preflight` never prompts.

## Understand or change the code

**[build_openfast.py](build_openfast.py)** contains the build logic. Start at
`main()` at the bottom to see the running order:

1. `read_settings()` reads and validates the commented settings.
2. `inspect_tools()`, `detect_math()` and `describe()` show the chosen tools,
   libraries and output locations.
3. `choose_math()` asks if needed and tests existing libraries with `probe_math()`.
4. `ensure_cmake()` and, for private math, `build_private_math()` prepare dependencies.
5. `openfast_source()` downloads/checks sources. `build_openfast()` lists every
   CMake option with an explanatory comment. `compile_and_install()` runs the
   configure, parallel build and install steps, in that order.
6. `verify_install()` checks executable presence and runtime linkage, writes
   provenance, and calls `write_activation()`.

The preflight, source-only, dependencies-only and verification branches are
visible in `main()`. External commands use argument lists rather than shell
expressions, and build commands are printed and logged. The six-line
[build_openfast.sh](build_openfast.sh) only launches Python, so existing
`bash build_openfast.sh ...` commands continue to work. No build logic lives
in Bash, and no Python packages are downloaded to run the builder.

## Tested scope and limits

Defaults are pinned to **OpenFAST 4.2.0** commit
`3a9d3f29f03b52b536d391fbd360683f847be712` and private
**Reference-LAPACK 3.12.1** commit
`6ec7f2bc4ecf4c4a93496aa2fa519575bc0e39ca`.
Other `X.Y.Z` OpenFAST versions can be selected; their checked-out commit must
match the chosen tag, but they are not validated here. Modified tracked source
files are refused instead of silently building a different solver.

The Python runner passes twelve automated tests on GNU/Linux x86_64 / GCC 11.4.
They cover configuration precedence, local paths with spaces, invalid settings,
batch choices, offline behavior, pinned-source checks, local BLAS/LAPACK
numerical preflight, activation, and an end-to-end tiny Fortran/CMake fixture
including installation, runtime linkage and manifest-preserving verification.
The fixture is **not** an OpenFAST simulation or full solver build.

```bash
python3 -m unittest discover -s tests -v
```

Numerical/integration tests need the host toolchain, existing BLAS/LAPACK and
CMake; tests requiring unavailable tools are explicitly skipped. If CMake is
outside `PATH`, set `CMAKE_COMMAND` to its executable when running the tests.

Existing system-library OpenFAST 4.2.0 and OpenMP FAST.Farm builds were used in
FASTScale's recorded simulations, including a pinned upstream 90 s farm
regression. The private LAPACK build also passed DGESV/DGEMM checks. **The
Python rewrite has not been used for a new full OpenFAST/FAST.Farm build. A
complete private-library solver build/regression has not been run either.**
Windows/macOS and arbitrary compiler combinations are not validated.

`--verify` checks binary presence, identity and runtime linkage. It preserves
an existing `build-manifest.json` and writes `verification-manifest.json`.
It does not establish physical correctness: numerical solver regressions are
separate. See [RELEASE_REVIEW.md](RELEASE_REVIEW.md).

## Upstream sources and license

Official [OpenFAST source at the pinned revision](https://github.com/OpenFAST/openfast/tree/3a9d3f29f03b52b536d391fbd360683f847be712),
[OpenFAST build guidance](https://openfast.readthedocs.io/en/main/source/install/index.html),
and [Reference-LAPACK source](https://github.com/Reference-LAPACK/lapack/tree/6ec7f2bc4ecf4c4a93496aa2fa519575bc0e39ca).
Upstream documentation may describe newer releases; the pinned source defines
this build's settings. This is an independent orchestrator, not an official
OpenFAST distribution or endorsement.

Original builder code and documentation are [Apache-2.0](LICENSE); see
[NOTICE](NOTICE). Upstream sources, dependencies and generated binaries retain
their own licenses. They are downloaded/generated locally, not rereleased in
this repository. This standalone builder does not require FASTScale; FASTScale's
separately bundled installer is maintained in its own repository.
