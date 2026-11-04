#!/usr/bin/env bash
# Rootless GNU/Linux OpenFAST + FAST.Farm compiler. No sudo/profile edits.
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT="${OPENFAST_BUILD_ROOT:-$(dirname -- "$SCRIPT_DIR")/openfast-local}"
VERSION="${OPENFAST_VERSION:-4.2.0}"
JOBS="${JOBS:-8}"
CC="${CC:-gcc}"; CXX="${CXX:-g++}"; FC="${FC:-gfortran}"
PREFLIGHT=0; BOOTSTRAP=0; OFFLINE=0; VERIFY=0; FETCH_ONLY=0
FAST_FARM=0; DEPS_ONLY=0; MATH_LIBS=ask
usage() {
  cat <<'EOF'
Usage: build_openfast.sh [--preflight] [--bootstrap-tools] [--offline]
  [--fetch-only] [--verify] [--root PATH] [--version VERSION] [--jobs N]
  [--fast-farm] [--math-libs ask|system|build] [--deps-only]

Default version: 4.2.0, GNU compilers, Release, double precision, shared
OpenFAST libraries. All generated files are under a user-selected root.
--preflight       Inspect tools and test available BLAS/LAPACK ABI in a
                  temporary directory; no persistent build/install/download.
--math-libs ask   Present detected libraries and ask: use them or build private
                  BLAS/LAPACK. Batch jobs must explicitly choose system/build.
--math-libs system Use detected or BLAS_LIBRARY/LAPACK_LIBRARY paths after an
                  actual Fortran link/run test. Never replace system files.
--math-libs build  Build pinned Reference-LAPACK 3.12.1 (includes BLAS) locally.
                  Uses separate -private solver build/install directories.
--deps-only       Build/check selected math libraries, then stop.
--bootstrap-tools Install CMake 3.31.6 under ROOT/tools only if CMake is missing.
--offline         Use only existing sources/tools; never download.
--fetch-only      Fetch/check selected OpenFAST source, then stop.
--verify          Verify an existing installation; run no build or regression.
--fast-farm       Build FAST.Farm/OpenMP in separate -fastfarm directories.
--root PATH       User-owned sources/build/install/deps/log root.
--jobs N          Build workers. Does not set simulation CPU counts.
Environment: OPENFAST_BUILD_ROOT, OPENFAST_VERSION, CC, CXX, FC, JOBS,
             BLAS_LIBRARY, LAPACK_LIBRARY, CMAKE_COMMAND.
No sudo, APT, Conda, global linker changes or shell-profile modifications.
EOF
}
die() { printf 'ERROR: %s\n' "$*" >&2; exit 2; }
while (($#)); do
  case "$1" in
    --preflight) PREFLIGHT=1;; --bootstrap-tools) BOOTSTRAP=1;;
    --offline) OFFLINE=1;; --verify) VERIFY=1;; --fetch-only) FETCH_ONLY=1;;
    --fast-farm) FAST_FARM=1;; --deps-only) DEPS_ONLY=1;;
    --math-libs) MATH_LIBS="${2:?missing library choice}"; shift;;
    --root) ROOT="${2:?missing root}"; shift;;
    --version) VERSION="${2:?missing version}"; shift;;
    --jobs) JOBS="${2:?missing jobs}"; shift;;
    -h|--help) usage; exit 0;; *) die "Unknown option: $1";;
  esac
  shift
done
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die 'Version must be X.Y.Z'
[[ "$JOBS" =~ ^[1-9][0-9]*$ ]] || die 'Jobs must be a positive integer'
[[ "$MATH_LIBS" =~ ^(ask|system|build)$ ]] || die 'Choose --math-libs ask, system or build'
ROOT="$(realpath -m -- "$ROOT")"
case "$ROOT" in /|/usr|/usr/*|/etc|/etc/*|/bin|/bin/*|/lib|/lib/*|/sbin|/sbin/*) die 'Choose a user-owned build root';; esac
[[ "$ROOT" != "$SCRIPT_DIR" && "$ROOT" != "$SCRIPT_DIR/"* ]] || die 'Keep generated files outside the compiler source'
CMAKE="${CMAKE_COMMAND:-}"
if [[ -z "$CMAKE" ]]; then
  if command -v cmake >/dev/null; then CMAKE="$(command -v cmake)"
  elif [[ -x "$ROOT/tools/bin/cmake" ]]; then CMAKE="$ROOT/tools/bin/cmake"; fi
fi
math_library() {
  local name="$1" resolved ext
  for ext in so so.3 a; do
    resolved="$("$FC" -print-file-name="lib${name}.$ext" 2>/dev/null || true)"
    if [[ -f "$resolved" ]]; then realpath -- "$resolved"; return; fi
  done
}
BLAS="${BLAS_LIBRARY:-$(math_library blas || true)}"
LAPACK="${LAPACK_LIBRARY:-$(math_library lapack || true)}"
missing=0
for tool in "$CC" "$CXX" "$FC" git make python3 sha256sum file ldd; do
  if command -v "$tool" >/dev/null; then printf 'FOUND %s: %s\n' "$tool" "$(command -v "$tool")"
  else printf 'MISSING %s\n' "$tool"; missing=1; fi
done
printf 'Root: %s\nVersion: %s\nCMake: %s\nDetected BLAS: %s\nDetected LAPACK: %s\n' "$ROOT" "$VERSION" "${CMAKE:-missing (use --bootstrap-tools)}" "${BLAS:-none}" "${LAPACK:-none}"
probe_math() {
  local probe code=0
  [[ -f "$BLAS" && -f "$LAPACK" ]] || return 1
  probe="$(mktemp -d "${TMPDIR:-/tmp}/openfast-math-check.XXXXXX")"
  cat > "$probe/check.f90" <<'EOF'
program check_math
 implicit none
 integer :: piv(2), info
 double precision :: a(2,2), b(2,1), m(2,2), c(2,1)
 a=reshape([3d0,1d0,1d0,2d0],[2,2]); b(:,1)=[9d0,8d0]
 call dgesv(2,1,a,2,piv,b,2,info)
 if (info/=0 .or. maxval(abs(b(:,1)-[2d0,3d0]))>1d-10) stop 1
 m=reshape([2d0,0d0,0d0,3d0],[2,2]); c=0d0
 call dgemm('N','N',2,1,2,1d0,m,2,b,2,0d0,c,2)
 if (maxval(abs(c(:,1)-[4d0,9d0]))>1d-10) stop 2
end program
EOF
  "$FC" "$probe/check.f90" "$LAPACK" "$BLAS" -o "$probe/check" > "$probe/link.log" 2>&1 || code=$?
  if ((code==0)); then "$probe/check" >> "$probe/link.log" 2>&1 || code=$?; fi
  if ((code!=0)); then cat "$probe/link.log" >&2; fi
  rm -rf -- "$probe"
  return "$code"
}
SYSTEM_MATH_OK=0
if ((missing==0)) && probe_math; then
  SYSTEM_MATH_OK=1; printf 'PASS: Fortran DGESV and DGEMM compile, link and numerical runtime check\n'
else
  printf 'UNAVAILABLE/INCOMPATIBLE: detected system math libraries; private build remains an option\n'
fi
if ((PREFLIGHT)); then
  [[ -n "$CMAKE" ]] || { printf 'MISSING CMake (use --bootstrap-tools during installation)\n'; missing=1; }
  if [[ "$MATH_LIBS" == system ]] && ((SYSTEM_MATH_OK==0)); then missing=1; fi
  printf 'Library choice: %s; --math-libs system reuses tested libraries, build makes private copies\n' "$MATH_LIBS"
  exit "$missing"
fi
((missing==0)) || die 'Install/provide the missing host compilers/tools before building; no system installer is run'
if ((VERIFY==0)); then
  if [[ "$MATH_LIBS" == ask ]]; then
    [[ -t 0 ]] || die 'Batch input cannot answer: choose --math-libs system or --math-libs build explicitly'
    printf '\n1. Use detected system BLAS/LAPACK (available=%s)\n2. Build private pinned BLAS/LAPACK under %s/deps\n' "$SYSTEM_MATH_OK" "$ROOT"
    read -r -p 'Library choice [1/2]: ' answer
    case "$answer" in 1) MATH_LIBS=system;; 2) MATH_LIBS=build;; *) die 'Choose 1 or 2';; esac
  fi
  [[ "$MATH_LIBS" != system || "$SYSTEM_MATH_OK" == 1 ]] || die 'System libraries failed the link/run check; choose --math-libs build or supply compatible library paths'
fi
SOURCE="$ROOT/sources/openfast-v$VERSION"
BUILD_SUFFIX=""
((FAST_FARM==0)) || BUILD_SUFFIX="-fastfarm"
[[ "$MATH_LIBS" != build ]] || BUILD_SUFFIX+="-private"
BUILD="$ROOT/build/v$VERSION$BUILD_SUFFIX"
PREFIX="$ROOT/install/v$VERSION$BUILD_SUFFIX"
mkdir -p "$ROOT/logs"
LOG="$ROOT/logs/build-v$VERSION-$(date -u +%Y%m%dT%H%M%SZ)-$$.log"
exec > >(tee -a "$LOG") 2>&1
trap 'printf "Build failed at line %s; log: %s\n" "$LINENO" "$LOG" >&2' ERR
verify_install() {
  local exe
  local executables=(openfast aerodyn_driver turbsim)
  ((FAST_FARM == 0)) || executables+=(FAST.Farm)
  for exe in "${executables[@]}"; do
    [[ -x "$PREFIX/bin/$exe" ]] || die "Missing executable: $PREFIX/bin/$exe"
    file "$PREFIX/bin/$exe"
    if ldd "$PREFIX/bin/$exe" | grep -q 'not found'; then die "Unresolved runtime libraries for $exe"; fi
  done
  "$PREFIX/bin/openfast" -v
  BUILD_MATH_MODE="$MATH_LIBS" BUILD_VERIFY_ONLY="$VERIFY" BUILD_BLAS="$BLAS" BUILD_LAPACK="$LAPACK" python3 - "$SOURCE" "$BUILD" "$PREFIX" "$LOG" "$CC" "$CXX" "$FC" "${executables[@]}" <<'PY'
import hashlib,json,pathlib,subprocess,sys,datetime,os
source,build,prefix,log,cc,cxx,fc=sys.argv[1:8]
executables=sys.argv[8:]
def command(*args):
    return subprocess.check_output(args,text=True).strip()
p=pathlib.Path(prefix)
manifest={"verified_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
 "repository":"https://github.com/OpenFAST/openfast", "commit":command("git","-C",source,"rev-parse","HEAD"),
 "source":source,"build":build,"install":prefix,"log":log,
 "compiler_versions":{c:command(c,"--version").splitlines()[0] for c in (cc,cxx,fc)},
 "executables":{name:hashlib.sha256((p/"bin"/name).read_bytes()).hexdigest()
                for name in executables},
 "verification":"Executable presence, identity and runtime linkage; physical regression testing is separate."}
cache=pathlib.Path(build)/"CMakeCache.txt"
manifest["cmake_cache_sha256"]=hashlib.sha256(cache.read_bytes()).hexdigest()
manifest["math_libraries"]={"choice":os.environ["BUILD_MATH_MODE"],"blas":os.environ["BUILD_BLAS"],"lapack":os.environ["BUILD_LAPACK"]}
manifest_name="verification-manifest.json" if os.environ["BUILD_VERIFY_ONLY"]=="1" and (p/"build-manifest.json").exists() else "build-manifest.json"
(p/manifest_name).write_text(json.dumps(manifest,indent=2)+"\n")
PY
  local activate="activate.sh"
  ((FAST_FARM == 0)) || activate="activate-fastfarm.sh"
  [[ "$MATH_LIBS" != build ]] || activate="${activate%.sh}-private.sh"
  python3 - "$ROOT" "$PREFIX" "$activate" <<'PY'
import pathlib,shlex,sys
root,prefix=map(pathlib.Path,sys.argv[1:3]); activate=sys.argv[3]; q=shlex.quote
text='export OPENFAST_ROOT='+q(str(prefix))+'\n'
text+='export PATH='+q(str(prefix/'bin'))+':"$PATH"\n'
text+='export LD_LIBRARY_PATH='+q(str(prefix/'lib'))+':'+q(str(prefix/'lib64'))+':"${LD_LIBRARY_PATH:-}"\n'
(root/activate).write_text(text)
PY
  printf 'Verified installation: %s\nActivate: source %q\n' "$PREFIX" "$ROOT/$activate"
}

if ((VERIFY)); then verify_install; exit 0; fi
if [[ -z "$CMAKE" ]]; then
  ((BOOTSTRAP && ! OFFLINE)) || die 'CMake missing; use --bootstrap-tools or CMAKE_COMMAND'
  python3 -m venv "$ROOT/tools"
  "$ROOT/tools/bin/python" -m pip install 'cmake==3.31.6'
  CMAKE="$ROOT/tools/bin/cmake"
fi
if [[ "$MATH_LIBS" == build ]]; then
  MATH_SOURCE="$ROOT/sources/lapack-v3.12.1"
  MATH_PREFIX="$ROOT/deps/lapack-3.12.1"
  if [[ ! -d "$MATH_SOURCE/.git" ]]; then
    ((OFFLINE==0)) || die "Offline LAPACK source missing: $MATH_SOURCE"
    mkdir -p "$ROOT/sources"
    git clone --depth 1 --branch v3.12.1 https://github.com/Reference-LAPACK/lapack.git "$MATH_SOURCE"
  fi
  [[ "$(git -C "$MATH_SOURCE" rev-parse HEAD)" == 6ec7f2bc4ecf4c4a93496aa2fa519575bc0e39ca ]] || die 'Private LAPACK does not match its pinned source commit'
  [[ -z "$(git -C "$MATH_SOURCE" status --porcelain --untracked-files=no)" ]] || die 'Private LAPACK source has local edits'
  "$CMAKE" -S "$MATH_SOURCE" -B "$ROOT/build/lapack-3.12.1" \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER="$(command -v "$CC")" \
    -DCMAKE_Fortran_COMPILER="$(command -v "$FC")" -DCMAKE_INSTALL_PREFIX="$MATH_PREFIX" \
    -DCMAKE_INSTALL_LIBDIR=lib -DBUILD_SHARED_LIBS=OFF -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
    -DBUILD_TESTING=OFF -DCBLAS=OFF -DLAPACKE=OFF
  "$CMAKE" --build "$ROOT/build/lapack-3.12.1" --parallel "$JOBS"
  "$CMAKE" --install "$ROOT/build/lapack-3.12.1"
  BLAS="$MATH_PREFIX/lib/libblas.a"; LAPACK="$MATH_PREFIX/lib/liblapack.a"
  probe_math || die 'Private math library numerical link/run verification failed'
  printf 'Private BLAS/LAPACK verified: %s\n' "$MATH_PREFIX"
  python3 - "$MATH_PREFIX" "$MATH_SOURCE" "$LOG" "$FC" <<'PYDATA'
import datetime,hashlib,json,pathlib,subprocess,sys
prefix,source,log,compiler=sys.argv[1:]
p=pathlib.Path(prefix)
manifest={"source":"https://github.com/Reference-LAPACK/lapack", "commit":"6ec7f2bc4ecf4c4a93496aa2fa519575bc0e39ca", "tag":"v3.12.1", "source_directory":source,"log":log,"compiler":subprocess.check_output([compiler,"--version"],text=True).splitlines()[0],"verified_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),"verification":"Fortran DGESV/DGEMM numerical link/run checks passed", "libraries":{str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in (p/"lib/libblas.a",p/"lib/liblapack.a")}}
(p/"build-manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
PYDATA
fi
if ((DEPS_ONLY)); then printf 'Math dependencies ready; no OpenFAST build requested\n'; exit 0; fi
if [[ ! -d "$SOURCE/.git" ]]; then
  ((OFFLINE==0)) || die "Offline sources unavailable: $SOURCE"
  [[ ! -e "$SOURCE" ]] || die "Existing non-Git source directory: $SOURCE"
  mkdir -p "$ROOT/sources"
  git clone --depth 1 --branch "v$VERSION" https://github.com/OpenFAST/openfast.git "$SOURCE"
fi
[[ "$(git -C "$SOURCE" rev-parse HEAD)" == "$(git -C "$SOURCE" rev-parse "v$VERSION^{commit}")" ]] || die 'Source commit does not match selected tag'
if [[ "$VERSION" == 4.2.0 ]]; then
  [[ "$(git -C "$SOURCE" rev-parse HEAD)" == 3a9d3f29f03b52b536d391fbd360683f847be712 ]] || die 'OpenFAST 4.2.0 source does not match tested commit'
fi
[[ -z "$(git -C "$SOURCE" status --porcelain --untracked-files=no)" ]] || die 'Refusing modified OpenFAST sources'
if ((FETCH_ONLY)); then exit 0; fi
FARM_CMAKE=OFF
((FAST_FARM==0)) || FARM_CMAKE=ON
"$CMAKE" -S "$SOURCE" -B "$BUILD" -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_C_COMPILER="$(command -v "$CC")" -DCMAKE_CXX_COMPILER="$(command -v "$CXX")" \
  -DCMAKE_Fortran_COMPILER="$(command -v "$FC")" -DCMAKE_INSTALL_PREFIX="$PREFIX" \
  -DBLAS_LIBRARIES="$BLAS" -DLAPACK_LIBRARIES="$LAPACK;$BLAS" \
  -DDOUBLE_PRECISION=ON -DBUILD_SHARED_LIBS=ON -DBUILD_TESTING=OFF \
  -DBUILD_FASTFARM="$FARM_CMAKE" -DOPENMP="$FARM_CMAKE" -DBUILD_OPENFAST_CPP_API=OFF
"$CMAKE" --build "$BUILD" --parallel "$JOBS"
"$CMAKE" --install "$BUILD"
verify_install
