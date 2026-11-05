#!/usr/bin/env python3
"""Rootless OpenFAST builder. Edit build-settings.ini to configure a build.

Read main() at the bottom for the running order. Each build stage is a named
function below. Only the Python standard library is required (Python >= 3.8).
Commands are passed as argument lists, never evaluated as shell code.
"""

import argparse
import configparser
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parent
OPENFAST_URL = "https://github.com/OpenFAST/openfast.git"
OPENFAST_COMMIT = "3a9d3f29f03b52b536d391fbd360683f847be712"
LAPACK_URL = "https://github.com/Reference-LAPACK/lapack.git"
LAPACK_VERSION = "3.12.1"
LAPACK_COMMIT = "6ec7f2bc4ecf4c4a93496aa2fa519575bc0e39ca"
CMAKE_VERSION = "3.31.6"

# Check actual numerical results, not merely the presence of library files.
MATH_CHECK = """program check_math
  implicit none
  integer :: piv(2), info
  double precision :: a(2,2), b(2,1), m(2,2), c(2,1)
  ! Solve A*x = [9,8]. The expected solution is x = [2,3].
  a = reshape([3d0,1d0,1d0,2d0], [2,2])
  b(:,1) = [9d0,8d0]
  call dgesv(2,1,a,2,piv,b,2,info)
  if (info /= 0) stop 1
  if (maxval(abs(b(:,1)-[2d0,3d0])) > 1d-10) stop 2
  ! Multiply diag(2,3)*x. The expected result is [4,9].
  m = reshape([2d0,0d0,0d0,3d0], [2,2])
  c = 0d0
  call dgemm('N','N',2,1,2,1d0,m,2,b,2,0d0,c,2)
  if (maxval(abs(c(:,1)-[4d0,9d0])) > 1d-10) stop 3
end program
"""


@dataclass
class Settings:
    """Resolved settings: CLI > nonblank INI value > environment > default."""

    config: Path
    root: Path
    version: str
    jobs: int
    fast_farm: bool
    bootstrap_tools: bool
    offline: bool
    policy: str
    cc: str
    cxx: str
    fc: str
    cmake: str
    blas: str
    lapack: str

    @property
    def source(self):
        return self.root / "sources" / ("openfast-v" + self.version)

    @property
    def suffix(self):
        farm = "-fastfarm" if self.fast_farm else ""
        math = "-private" if self.policy == "build" else ""
        return "v" + self.version + farm + math

    @property
    def build(self):
        return self.root / "build" / self.suffix

    @property
    def prefix(self):
        return self.root / "install" / self.suffix


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=PROJECT / "build-settings.ini",
                        help="commented INI settings file (default: beside this script)")
    parser.add_argument("--root", help="directory for downloads, builds and installations")
    parser.add_argument("--version", help="OpenFAST release X.Y.Z (default: 4.2.0)")
    parser.add_argument("--jobs", type=int, help="parallel compilation workers (default: 8)")
    parser.add_argument("--math-libs", choices=("ask", "system", "build"),
                        help="ask, reuse existing libraries, or build private libraries")
    for name, help_text in (
        ("preflight", "check tools and libraries without downloads or installation"),
        ("fetch-only", "download/check sources only; do not compile or install"),
        ("deps-only", "prepare math libraries, then stop before OpenFAST"),
        ("verify", "check an existing installation; do not build or run regressions"),
    ):
        parser.add_argument("--" + name, action="store_true", help=help_text)
    for name, help_text in (
        ("fast-farm", "also build FAST.Farm with OpenMP"),
        ("bootstrap-tools", "install pinned CMake locally if missing"),
        ("offline", "forbid source/tool downloads"),
    ):
        # Explicit negative flags let CLI users override a 'yes' in the INI file.
        group = parser.add_mutually_exclusive_group()
        group.add_argument("--" + name, action="store_true", default=None, help=help_text)
        group.add_argument("--no-" + name, dest=name.replace("-", "_"), action="store_false",
                           help="override this setting to no")
    args = parser.parse_args(argv)
    if sum((args.preflight, args.fetch_only, args.deps_only, args.verify)) > 1:
        parser.error("choose only one stopping point: preflight, fetch-only, deps-only or verify")
    return args


def read_settings(args):
    """Read plain data, reject misspelled keys, and resolve paths explicitly."""
    config_path = args.config.expanduser().resolve()
    config = configparser.ConfigParser(interpolation=None)
    with config_path.open() as handle:
        config.read_file(handle)
    allowed = {
        "build": {"root", "version", "jobs", "fast_farm", "bootstrap_tools", "offline"},
        "tools": {"c_compiler", "cxx_compiler", "fortran_compiler", "cmake"},
        "libraries": {"policy", "blas", "lapack"},
    }
    if config.defaults():
        raise ValueError("Use the named sections, not a [DEFAULT] section")
    for section in config.sections():
        unknown = set(config[section]) - allowed.get(section, set())
        if section not in allowed or unknown:
            raise ValueError("Unknown settings in [{}]: {}".format(section, ", ".join(sorted(unknown))))

    def value(section, key, cli=None, env=None, default="", is_path=False):
        # CLI/environment relative paths use the terminal directory. INI paths
        # use the settings file's directory, so IDE working folders do not matter.
        base = Path.cwd()
        text = cli
        if text is None:
            text = config.get(section, key, fallback="").strip()
            if text:
                base = config_path.parent
            else:
                text = os.environ.get(env, default) if env else default
        if is_path and text:
            path = Path(str(text)).expanduser()
            if path.is_absolute() or "/" in str(text) or key in ("root", "blas", "lapack"):
                return str((base / path).resolve())
        return str(text)

    def flag(name):
        override = getattr(args, name)
        return override if override is not None else config.getboolean("build", name, fallback=False)

    settings = Settings(
        config=config_path,
        root=Path(value("build", "root", args.root, "OPENFAST_BUILD_ROOT",
                        str(PROJECT.parent / "openfast-local"), is_path=True)),
        version=value("build", "version", args.version, "OPENFAST_VERSION", "4.2.0"),
        jobs=int(value("build", "jobs", args.jobs, "JOBS", "8")),
        fast_farm=flag("fast_farm"), bootstrap_tools=flag("bootstrap_tools"), offline=flag("offline"),
        policy=value("libraries", "policy", args.math_libs, default="ask"),
        cc=value("tools", "c_compiler", env="CC", default="gcc", is_path=True),
        cxx=value("tools", "cxx_compiler", env="CXX", default="g++", is_path=True),
        fc=value("tools", "fortran_compiler", env="FC", default="gfortran", is_path=True),
        cmake=value("tools", "cmake", env="CMAKE_COMMAND", is_path=True),
        blas=value("libraries", "blas", env="BLAS_LIBRARY", is_path=True),
        lapack=value("libraries", "lapack", env="LAPACK_LIBRARY", is_path=True),
    )
    if not re.fullmatch(r"\d+\.\d+\.\d+", settings.version):
        raise ValueError("Version must be X.Y.Z")
    if settings.jobs < 1:
        raise ValueError("Jobs must be a positive integer")
    if settings.policy not in ("ask", "system", "build"):
        raise ValueError("Library policy must be ask, system or build")
    protected = ("/usr", "/etc", "/bin", "/lib", "/lib64", "/sbin", "/boot", "/proc", "/sys", "/dev")
    if settings.root == Path("/") or any(Path(p) in (settings.root, *settings.root.parents) for p in protected):
        raise ValueError("Choose a user-owned build root, outside system directories")
    if PROJECT in (settings.root, *settings.root.parents):
        raise ValueError("Keep generated files outside the compiler source")
    return settings


def capture(command, env=None):
    """For small checks. Build output is streamed by Builder.run instead."""
    return subprocess.check_output([str(x) for x in command], text=True,
                                   stderr=subprocess.STDOUT, env=env).strip()


def sha256(path):
    with Path(path).open("rb") as handle:
        digest = hashlib.sha256()
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_manifest(path, contents):
    contents["verified_utc"] = datetime.now(timezone.utc).isoformat()
    Path(path).write_text(json.dumps(contents, indent=2) + "\n")


class Builder:
    """Build stages share settings and one log; no global environment changes."""

    def __init__(self, settings):
        self.settings = settings
        self.log = None
        self.log_path = None

    def say(self, text):
        print(text, flush=True)
        if self.log:
            self.log.write(text + "\n")
            self.log.flush()

    def run(self, command, env=None):
        """Show the exact command and stream its output to terminal AND log."""
        command = [str(x) for x in command]
        self.say("\n> " + shlex.join(command))
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, env=env) as process:
            for line in process.stdout:
                self.say(line.rstrip("\n"))
            if process.wait():
                raise RuntimeError("Command failed (exit {}): {}".format(process.returncode, command[0]))

    def inspect_tools(self, need_cmake=True):
        """Print resolved paths. An explicitly wrong path never silently falls back."""
        settings = self.settings
        missing = []
        for name in ("cc", "cxx", "fc"):
            resolved = shutil.which(getattr(settings, name))
            self.say("{}: {}".format(name, resolved or "MISSING " + getattr(settings, name)))
            if resolved:
                setattr(settings, name, resolved)
            else:
                missing.append(name)
        for name in ("git", "make", "file", "ldd"):
            resolved = shutil.which(name)
            self.say("{}: {}".format(name, resolved or "MISSING"))
            if not resolved:
                missing.append(name)
        if settings.cmake:
            resolved = shutil.which(settings.cmake)
            if not resolved:
                raise ValueError("Configured CMake is not executable: " + settings.cmake)
            settings.cmake = resolved
        else:
            settings.cmake = shutil.which("cmake") or ""
            local = settings.root / "tools/bin/cmake"
            if not settings.cmake and os.access(local, os.X_OK) and local.is_file():
                settings.cmake = str(local)
        self.say("CMake: " + (settings.cmake or "missing (enable bootstrap_tools to install locally)"))
        if need_cmake and not settings.cmake:
            missing.append("CMake")
        return missing

    def describe(self):
        settings = self.settings
        self.say("\nSettings: {}\nRoot: {}\nVersion: {}\nBuild workers: {}\nFAST.Farm: {}\n"
                 "Offline: {}\nAllow CMake bootstrap: {}\nLibrary policy: {}\nBLAS: {}\nLAPACK: {}\nInstall: {}".format(
                     settings.config, settings.root, settings.version, settings.jobs, settings.fast_farm, settings.offline, settings.bootstrap_tools, settings.policy,
                     settings.blas or "none", settings.lapack or "none", settings.prefix))
        if settings.policy == "build":
            self.say("Existing math library paths are ignored: private BLAS/LAPACK will be built under "
                     + str(settings.root / "deps"))

    def detect_math(self):
        """Ask the selected Fortran compiler where its default libraries live."""
        if self.settings.policy == "build":
            return
        for name in ("blas", "lapack"):
            if getattr(self.settings, name):
                continue
            if not shutil.which(self.settings.fc):
                continue
            for extension in ("so", "so.3", "a"):
                path = capture([self.settings.fc, "-print-file-name=lib{}.{}".format(name, extension)])
                if Path(path).is_file():
                    setattr(self.settings, name, str(Path(path).resolve()))
                    break

    def math_environment(self):
        # Local shared libraries may not be in the system loader's search path.
        # Change only the child process environment, never the caller's shell.
        environment = os.environ.copy()
        folders = list(dict.fromkeys(str(Path(p).parent) for p in (self.settings.lapack, self.settings.blas) if p))
        existing = environment.get("LD_LIBRARY_PATH", "")
        environment["LD_LIBRARY_PATH"] = ":".join(folders + ([existing] if existing else []))
        return environment

    def probe_math(self):
        """Compile and run a tiny Fortran check, removed automatically afterwards."""
        paths = (self.settings.blas, self.settings.lapack)
        if not all(paths) or not all(Path(p).is_file() for p in paths):
            self.say("UNAVAILABLE/INCOMPATIBLE: supply actual BLAS and LAPACK files or choose build")
            return False
        if not shutil.which(self.settings.fc):
            return False
        try:
            with tempfile.TemporaryDirectory(prefix="openfast-math-check-") as folder:
                source = Path(folder) / "check.f90"
                executable = Path(folder) / "check"
                source.write_text(MATH_CHECK)
                self.run([self.settings.fc, source, self.settings.lapack, self.settings.blas, "-o", executable])
                self.run([executable], env=self.math_environment())
        except RuntimeError:
            self.say("UNAVAILABLE/INCOMPATIBLE: math numerical check failed; no solver was built")
            return False
        self.say("PASS: Fortran DGESV and DGEMM compile, link and numerical runtime check")
        return True

    def choose_math(self):
        settings = self.settings
        math_ok = False
        if settings.policy == "ask":
            if not sys.stdin.isatty():
                raise ValueError("Batch input cannot answer: choose --math-libs system or --math-libs build "
                                 "explicitly, or set [libraries] policy in your INI file")
            math_ok = self.probe_math()
            self.say("\n1. Use the existing BLAS/LAPACK paths (numerical check: {})\n".format(
                "PASS" if math_ok else "FAILED/unavailable") +
                "2. Build private pinned BLAS/LAPACK under " + str(settings.root / "deps"))
            answer = input("Library choice [1/2]: ").strip()
            if answer not in ("1", "2"):
                raise ValueError("Choose 1 or 2")
            settings.policy = "system" if answer == "1" else "build"
        if settings.policy == "system" and not math_ok and not self.probe_math():
            raise ValueError("Existing libraries failed. Correct [libraries] paths, or choose policy = build")

    def start_log(self):
        folder = self.settings.root / "logs"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.log_path = folder / ("build-{}-{}-{}.log".format(self.settings.suffix, stamp, os.getpid()))
        self.log = self.log_path.open("w")
        self.say("Log: " + str(self.log_path))
        self.describe()
        self.say("Compilers: {} | {} | {}\nCMake: {}".format(self.settings.cc, self.settings.cxx, self.settings.fc, self.settings.cmake))

    def ensure_cmake(self):
        settings = self.settings
        if settings.cmake:
            return
        if not settings.bootstrap_tools or settings.offline:
            raise ValueError("CMake missing. Set [tools] cmake, or enable bootstrap_tools online")
        tools = settings.root / "tools"
        self.run([sys.executable, "-m", "venv", tools])
        self.run([tools / "bin/python", "-m", "pip", "install", "cmake==" + CMAKE_VERSION])
        settings.cmake = str(tools / "bin/cmake")

    def ensure_source(self, url, folder, tag, pinned_commit=None):
        """Download if allowed; refuse tag mismatches or edited tracked sources."""
        if not (folder / ".git").exists():
            if self.settings.offline:
                raise ValueError("Offline sources unavailable: " + str(folder))
            if folder.exists():
                raise ValueError("Existing non-Git source directory: " + str(folder))
            folder.parent.mkdir(parents=True, exist_ok=True)
            self.run(["git", "clone", "--depth", "1", "--branch", tag, url, folder])
        commit = capture(["git", "-C", folder, "rev-parse", "HEAD"])
        tagged = capture(["git", "-C", folder, "rev-parse", tag + "^{commit}"])
        if commit != tagged or (pinned_commit and commit != pinned_commit):
            raise ValueError("Source does not match selected tag/pinned commit: " + str(folder))
        if capture(["git", "-C", folder, "status", "--porcelain", "--untracked-files=no"]):
            raise ValueError("Refusing modified sources: " + str(folder))
        self.say("Source verified: {} @ {}".format(folder, commit))

    def lapack_source(self):
        folder = self.settings.root / "sources" / ("lapack-v" + LAPACK_VERSION)
        self.ensure_source(LAPACK_URL, folder, "v" + LAPACK_VERSION, LAPACK_COMMIT)
        return folder

    def openfast_source(self):
        pin = OPENFAST_COMMIT if self.settings.version == "4.2.0" else None
        self.ensure_source(OPENFAST_URL, self.settings.source, "v" + self.settings.version, pin)

    def compile_and_install(self, source, build, prefix, options):
        """The three CMake steps are always configure, parallel build, install."""
        self.run([self.settings.cmake, "-S", source, "-B", build,
                  "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_INSTALL_PREFIX=" + str(prefix), *options])
        self.run([self.settings.cmake, "--build", build, "--parallel", self.settings.jobs])
        self.run([self.settings.cmake, "--install", build])

    def build_private_math(self):
        settings = self.settings
        source = self.lapack_source()
        prefix = settings.root / "deps" / ("lapack-" + LAPACK_VERSION)
        self.compile_and_install(source, settings.root / "build" / ("lapack-" + LAPACK_VERSION), prefix, [
            "-DCMAKE_C_COMPILER=" + settings.cc,
            "-DCMAKE_Fortran_COMPILER=" + settings.fc,
            "-DCMAKE_INSTALL_LIBDIR=lib",
            "-DBUILD_SHARED_LIBS=OFF",
            "-DCMAKE_POSITION_INDEPENDENT_CODE=ON",
            "-DBUILD_TESTING=OFF",
            "-DCBLAS=OFF",
            "-DLAPACKE=OFF",
        ])
        settings.blas = str(prefix / "lib/libblas.a")
        settings.lapack = str(prefix / "lib/liblapack.a")
        if not self.probe_math():
            raise RuntimeError("Private math library numerical verification failed")
        write_manifest(prefix / "build-manifest.json", {
            "source": LAPACK_URL, "commit": LAPACK_COMMIT, "tag": "v" + LAPACK_VERSION,
            "source_directory": str(source), "log": str(self.log_path),
            "compiler": capture([settings.fc, "--version"]).splitlines()[0],
            "libraries": {p: sha256(p) for p in (settings.blas, settings.lapack)},
            "verification": "Fortran DGESV/DGEMM numerical link/run checks passed",
        })
        self.say("Private BLAS/LAPACK verified: " + str(prefix))

    def build_openfast(self):
        settings = self.settings
        farm = "ON" if settings.fast_farm else "OFF"
        # Preserve paths to local shared math libraries in generated binaries.
        # An explicit source-directory setting is never needed for installed libs.
        library_dirs = ";".join(dict.fromkeys(str(Path(p).parent) for p in (settings.lapack, settings.blas)))
        self.compile_and_install(settings.source, settings.build, settings.prefix, [
            "-DCMAKE_C_COMPILER=" + settings.cc,
            "-DCMAKE_CXX_COMPILER=" + settings.cxx,
            "-DCMAKE_Fortran_COMPILER=" + settings.fc,
            "-DBLAS_LIBRARIES=" + settings.blas,
            "-DLAPACK_LIBRARIES=" + settings.lapack + ";" + settings.blas,
            "-DCMAKE_BUILD_RPATH=" + library_dirs,
            "-DCMAKE_INSTALL_RPATH=" + str(settings.prefix / "lib") + ";" + str(settings.prefix / "lib64") + ";" + library_dirs,
            "-DDOUBLE_PRECISION=ON",
            "-DBUILD_SHARED_LIBS=ON",
            "-DBUILD_TESTING=OFF",
            "-DBUILD_FASTFARM=" + farm,
            "-DOPENMP=" + farm,
            "-DBUILD_OPENFAST_CPP_API=OFF",
        ])

    def verify_install(self, verify_only=False):
        settings = self.settings
        names = ["openfast", "aerodyn_driver", "turbsim"]
        if settings.fast_farm:
            names.append("FAST.Farm")
        environment = self.math_environment()
        folders = [str(settings.prefix / "lib"), str(settings.prefix / "lib64")]
        environment["LD_LIBRARY_PATH"] = ":".join(folders + [environment["LD_LIBRARY_PATH"]])
        for name in names:
            executable = settings.prefix / "bin" / name
            if not executable.is_file() or not os.access(executable, os.X_OK):
                raise ValueError("Missing executable: " + str(executable))
            self.run(["file", executable])
            linkage = capture(["ldd", executable], env=environment)
            self.say(linkage)
            if "not found" in linkage:
                raise ValueError("Unresolved runtime libraries for " + name)
        self.run([settings.prefix / "bin/openfast", "-v"], env=environment)
        # Verification must not replace the provenance of the original build.
        manifest = "verification-manifest.json" if verify_only and (settings.prefix / "build-manifest.json").exists() else "build-manifest.json"
        write_manifest(settings.prefix / manifest, {
            "repository": OPENFAST_URL, "commit": capture(["git", "-C", settings.source, "rev-parse", "HEAD"]),
            "source": str(settings.source), "build": str(settings.build), "install": str(settings.prefix), "log": str(self.log_path),
            "compiler_versions": {c: capture([c, "--version"]).splitlines()[0] for c in (settings.cc, settings.cxx, settings.fc)},
            "executables": {name: sha256(settings.prefix / "bin" / name) for name in names},
            "cmake_cache_sha256": sha256(settings.build / "CMakeCache.txt"),
            "math_libraries": {"choice": settings.policy, "blas": settings.blas, "lapack": settings.lapack},
            "settings": {"file": str(settings.config), "sha256": sha256(settings.config),
                         "jobs": settings.jobs, "fast_farm": settings.fast_farm, "offline": settings.offline},
            "verification": "Executable presence, identity and runtime linkage; physical regression testing is separate.",
        })
        self.write_activation()
        self.say("Verified installation: " + str(settings.prefix))

    def write_activation(self):
        settings = self.settings
        name = "activate" + ("-fastfarm" if settings.fast_farm else "") + ("-private" if settings.policy == "build" else "") + ".sh"
        activation = settings.root / name
        folders = [settings.prefix / "lib", settings.prefix / "lib64", Path(settings.lapack).parent, Path(settings.blas).parent]
        loader_path = ":".join(shlex.quote(str(p)) for p in dict.fromkeys(folders))
        activation.write_text(
            "# Optional: source this file in the terminal that will run the solver.\n"
            "export OPENFAST_ROOT=" + shlex.quote(str(settings.prefix)) + "\n"
            "export PATH=" + shlex.quote(str(settings.prefix / "bin")) + ':"$PATH"\n'
            "export LD_LIBRARY_PATH=" + loader_path + '${LD_LIBRARY_PATH:+:"$LD_LIBRARY_PATH"}\n'
        )
        self.say("Activate: source " + shlex.quote(str(activation)))


def main(argv=None):
    """Running order. No solver build happens until tools and math pass checks."""
    args = arguments(argv)
    builder = None
    try:
        settings = read_settings(args)
        builder = Builder(settings)

        # 1. Inspect the host. Preflight only creates a temporary Fortran test.
        missing = builder.inspect_tools(need_cmake=args.preflight)
        builder.detect_math()
        builder.describe()
        if args.preflight:
            math_ok = builder.probe_math() if settings.policy != "build" else True
            if settings.policy == "build":
                builder.say("Private math will be built and tested during installation; preflight does not build it.")
            return int(bool(missing) or (settings.policy == "system" and not math_ok))
        if missing:
            raise ValueError("Install/provide missing host tools: " + ", ".join(missing))

        # 2. Resolve the library choice before creating persistent output files.
        if not args.fetch_only:
            if args.verify:
                if settings.policy == "ask":
                    raise ValueError("For verification, select --math-libs system or --math-libs build")
                if settings.policy == "build":
                    prefix = settings.root / "deps" / ("lapack-" + LAPACK_VERSION)
                    settings.blas = str(prefix / "lib/libblas.a")
                    settings.lapack = str(prefix / "lib/liblapack.a")
            else:
                builder.choose_math()

        builder.start_log()
        if args.verify:
            builder.verify_install(verify_only=True)
            return 0

        # 3. A fetch-only request downloads sources, never compiles dependencies.
        if args.fetch_only:
            builder.openfast_source()
            if settings.policy == "build":
                builder.lapack_source()
            builder.say("Sources ready. No compilation or installation was performed.")
            return 0

        # 4. Install CMake locally if allowed; prepare the chosen math libraries.
        builder.ensure_cmake()
        if settings.policy == "build":
            builder.build_private_math()
        if args.deps_only:
            builder.say("Math dependencies ready; no OpenFAST build requested")
            return 0

        # 5. Download/check OpenFAST, configure, compile, install, then verify.
        builder.openfast_source()
        builder.build_openfast()
        builder.verify_install()
        return 0
    except (ValueError, OSError, configparser.Error, subprocess.CalledProcessError, RuntimeError) as error:
        detail = error.output if isinstance(error, subprocess.CalledProcessError) else str(error)
        print("ERROR: " + str(detail), file=sys.stderr)
        if builder and builder.log:
            builder.say("Failed: {}\nLog: {}".format(error, builder.log_path))
        return 2
    except KeyboardInterrupt:
        print("Stopped by user.", file=sys.stderr)
        return 130
    finally:
        if builder and builder.log:
            builder.log.close()


if __name__ == "__main__":
    sys.exit(main())
