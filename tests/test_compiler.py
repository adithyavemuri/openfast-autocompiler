"""Compiler contracts: no network access or full OpenFAST/LAPACK build.

The numerical checks use tiny Fortran programs and the host's existing math
libraries. The end-to-end orchestration fixture substitutes a tiny CMake
project; it tests configuration/install/verification, not OpenFAST physics.
"""

import importlib.util
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("compiler", PROJECT / "build_openfast.py")
compiler = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = compiler
spec.loader.exec_module(compiler)


class CompilerTests(unittest.TestCase):
    def command(self, *args, launcher=False, **kwargs):
        command = ["bash", str(PROJECT / "build_openfast.sh")] if launcher else [sys.executable, str(PROJECT / "build_openfast.py")]
        return subprocess.run(command + list(args), capture_output=True, text=True, timeout=60, **kwargs)

    def settings(self, folder, text, *args):
        config = Path(folder) / "settings.ini"
        config.write_text(text)
        return compiler.read_settings(compiler.arguments(["--config", str(config), *args]))

    def test_python_and_bash_help(self):
        python = self.command("--help")
        shell = self.command("--help", launcher=True)
        self.assertEqual(python.returncode, 0)
        self.assertEqual(shell.returncode, 0)
        # argparse uses the Python script name for both routes.
        self.assertEqual(python.stdout, shell.stdout)
        self.assertIn("--config", python.stdout)
        self.assertIn("--math-libs", python.stdout)
        subprocess.run(["bash", "-n", str(PROJECT / "build_openfast.sh")], check=True)

    def test_config_paths_spaces_and_precedence(self):
        with tempfile.TemporaryDirectory(prefix="settings with spaces ") as folder:
            text = """[build]
root = output with spaces
jobs = 2
fast_farm = yes
[tools]
fortran_compiler = ./tool chain/gfortran
[libraries]
policy = system
blas = local libraries/libblas.so
lapack = liblapack.so
"""
            with patch.dict(os.environ, {"JOBS": "99", "FC": "wrong-compiler", "BLAS_LIBRARY": "/wrong/libblas.so"}):
                settings = self.settings(folder, text, "--jobs", "3", "--no-fast-farm")
            self.assertEqual(settings.jobs, 3)
            self.assertFalse(settings.fast_farm)
            self.assertEqual(settings.root, Path(folder) / "output with spaces")
            self.assertEqual(settings.fc, str(Path(folder) / "tool chain/gfortran"))
            self.assertEqual(settings.blas, str(Path(folder) / "local libraries/libblas.so"))
            self.assertEqual(settings.lapack, str(Path(folder) / "liblapack.so"))
            self.assertFalse(settings.root.exists())

    def test_blank_settings_keep_environment_fallbacks(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {"JOBS": "4", "CC": "custom-gcc", "OPENFAST_VERSION": "4.1.2"}):
                settings = self.settings(folder, "[build]\njobs =\n[tools]\nc_compiler =\n")
            self.assertEqual(settings.jobs, 4)
            self.assertEqual(settings.cc, "custom-gcc")
            self.assertEqual(settings.version, "4.1.2")
            self.assertIsNone(compiler.arguments([]).fast_farm)

    def test_invalid_settings_fail_before_writes(self):
        for args in (("--math-libs", "invalid"), ("--jobs", "0"), ("--version", "latest"),
                     ("--root", "/usr/local/should-not-build", "--preflight"),
                     ("--root", str(PROJECT / "generated"), "--preflight"),
                     ("--preflight", "--fetch-only")):
            with self.subTest(args=args):
                self.assertNotEqual(self.command(*args).returncode, 0)
        with tempfile.TemporaryDirectory() as folder:
            for text in ("[libraries]\npolciy = system", "[build]\nfast_farm = maybe", "[typo]\nx = 1"):
                with self.subTest(config=text), self.assertRaises((ValueError, compiler.configparser.Error)):
                    self.settings(folder, text)

    @unittest.skipUnless(all(shutil.which(c) for c in ("gcc", "g++", "gfortran", "git", "make", "file", "ldd")), "GNU toolchain required")
    def test_batch_must_choose_policy_without_creating_root(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "generated"
            result = self.command("--root", str(root), stdin=subprocess.DEVNULL)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("choose --math-libs system or --math-libs build", result.stderr)
            self.assertFalse(root.exists())

    @unittest.skipUnless(shutil.which("gfortran"), "Fortran compiler required")
    def test_custom_math_preflight_with_spaces_does_not_install(self):
        with tempfile.TemporaryDirectory(prefix="local math with spaces ") as folder:
            config = Path(folder) / "settings.ini"
            config.write_text("[build]\nroot = generated\n[tools]\ncmake = " + self.cmake() + "\n[libraries]\npolicy = system\n")
            settings = compiler.read_settings(compiler.arguments(["--config", str(config)]))
            builder = compiler.Builder(settings)
            builder.detect_math()
            if not all(Path(p).is_file() for p in (settings.blas, settings.lapack)):
                self.skipTest("System math libraries unavailable")
            # Use local paths containing spaces, not just the auto-detected names.
            blas = Path(folder) / "my BLAS.so"
            lapack = Path(folder) / "my LAPACK.so"
            shutil.copy2(settings.blas, blas)
            shutil.copy2(settings.lapack, lapack)
            with config.open("a") as handle:
                handle.write("blas = my BLAS.so\nlapack = my LAPACK.so\n")
            result = self.command("--config", str(config), "--preflight", cwd="/tmp")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("PASS: Fortran DGESV and DGEMM", result.stdout)
            self.assertIn(str(blas), result.stdout)
            self.assertIn(str(lapack), result.stdout)
            self.assertFalse((Path(folder) / "generated").exists())

    def test_missing_explicit_library_stops_without_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "settings.ini"
            config.write_text("[build]\nroot = generated\n[tools]\ncmake = " + self.cmake() +
                              "\n[libraries]\npolicy = system\nblas = missing.so\nlapack = also-missing.so\n")
            result = self.command("--config", str(config), "--preflight")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("UNAVAILABLE/INCOMPATIBLE", result.stdout)
            self.assertFalse((Path(folder) / "generated").exists())

    def test_offline_missing_source_does_not_run_git_clone(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = self.settings(folder, "[build]\nroot = generated\noffline = yes\n")
            builder = compiler.Builder(settings)
            with patch.object(builder, "run") as run:
                with self.assertRaisesRegex(ValueError, "Offline sources unavailable"):
                    builder.openfast_source()
                run.assert_not_called()
            self.assertFalse(settings.root.exists())

    @unittest.skipUnless(shutil.which("git"), "Git required")
    def test_source_validation_rejects_wrong_tag_and_edits(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source"
            source.mkdir()
            def git(*args):
                return subprocess.run(["git", "-C", str(source), *args], check=True, capture_output=True)
            git("init", "-q")
            git("config", "user.name", "Compiler test")
            git("config", "user.email", "test@example.invalid")
            (source / "source.txt").write_text("reference\n")
            git("add", ".")
            git("commit", "-qm", "reference")
            git("tag", "v1.0.0")
            settings = self.settings(folder, "[build]\nroot = generated\n")
            builder = compiler.Builder(settings)
            commit = compiler.capture(["git", "-C", source, "rev-parse", "HEAD"])
            builder.ensure_source("unused", source, "v1.0.0", commit)
            with self.assertRaisesRegex(ValueError, "pinned commit"):
                builder.ensure_source("unused", source, "v1.0.0", "0" * 40)
            (source / "source.txt").write_text("edited\n")
            with self.assertRaisesRegex(ValueError, "modified sources"):
                builder.ensure_source("unused", source, "v1.0.0", commit)

    def test_activation_preserves_local_paths_and_existing_environment(self):
        with tempfile.TemporaryDirectory(prefix="activation spaces ") as folder:
            settings = self.settings(folder, "[build]\nroot = generated\nfast_farm = yes\n"
                                     "[libraries]\npolicy = system\nblas = local libs/libblas.so\nlapack = local libs/liblapack.so\n")
            settings.root.mkdir()
            compiler.Builder(settings).write_activation()
            activation = settings.root / "activate-fastfarm.sh"
            env = os.environ.copy()
            env["LD_LIBRARY_PATH"] = "/existing/path"
            # Positional arguments keep spaces/quotes out of shell interpolation.
            command = ['bash', '-c', 'source "$1"; printf "%s\\n%s\\n%s" "$OPENFAST_ROOT" "$PATH" "$LD_LIBRARY_PATH"', 'test', str(activation)]
            result = subprocess.run(command, check=True, capture_output=True, text=True, env=env)
            root, path, libs = result.stdout.splitlines()
            self.assertEqual(root, str(settings.prefix))
            self.assertTrue(path.startswith(str(settings.prefix / "bin") + ":"))
            self.assertIn(str(Path(folder) / "local libs"), libs.split(":"))
            self.assertTrue(libs.endswith(":/existing/path"))

    @unittest.skipUnless(all(shutil.which(c) for c in ("gcc", "g++", "gfortran", "git", "make", "file", "ldd", "readelf")), "GNU toolchain and readelf required")
    def test_tiny_project_runs_build_install_verify_with_local_math(self):
        """Exercise the whole runner using seconds of compilation, not OpenFAST."""
        with tempfile.TemporaryDirectory(prefix="build integration spaces ") as folder:
            root = Path(folder) / "generated"
            settings = self.settings(folder, "[build]\nroot = generated\nversion = 9.9.9\njobs = 2\n"
                                     "fast_farm = yes\noffline = yes\n[tools]\ncmake = " + self.cmake() +
                                     "\n[libraries]\npolicy = system\n")
            compiler.Builder(settings).detect_math()
            if not all(Path(p).is_file() for p in (settings.blas, settings.lapack)):
                self.skipTest("System math libraries unavailable")
            local = Path(folder) / "local libraries"
            local.mkdir()
            for name in ("blas", "lapack"):
                original = getattr(settings, name)
                dynamic = compiler.capture(["readelf", "-d", original])
                soname = re.search(r"\(SONAME\).*\[(.+?)\]", dynamic)
                if not soname:
                    self.skipTest("Integration test requires shared math libraries with SONAMEs")
                # Preserve each loader name so runtime checks really load these
                # local copies, rather than falling back to system .so files.
                path = local / soname.group(1)
                if not path.exists():
                    shutil.copy2(original, path)
                with settings.config.open("a") as handle:
                    handle.write(name + " = " + str(path) + "\n")
            source = settings.source
            source.mkdir(parents=True)
            (source / "check.f90").write_text(compiler.MATH_CHECK)
            (source / "CMakeLists.txt").write_text("""cmake_minimum_required(VERSION 3.16)
project(CompilerFixture LANGUAGES C CXX Fortran)
foreach(name openfast aerodyn_driver turbsim FAST.Farm)
  add_executable(${name} check.f90)
  target_link_libraries(${name} PRIVATE ${LAPACK_LIBRARIES})
  install(TARGETS ${name} DESTINATION bin)
endforeach()
""")
            def git(*args):
                subprocess.run(["git", "-C", str(source), *args], check=True, capture_output=True)
            git("init", "-q")
            git("config", "user.name", "Compiler test")
            git("config", "user.email", "test@example.invalid")
            git("add", ".")
            git("commit", "-qm", "tiny numerical build fixture")
            git("tag", "v9.9.9")
            result = self.command("--config", str(settings.config))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            prefix = settings.prefix
            manifest_path = prefix / "build-manifest.json"
            original_manifest = manifest_path.read_bytes()
            manifest = json.loads(original_manifest)
            self.assertEqual(set(manifest["executables"]), {"openfast", "aerodyn_driver", "turbsim", "FAST.Farm"})
            self.assertEqual(Path(manifest["math_libraries"]["blas"]).parent, local)
            self.assertIn("=> " + str(local) + "/", result.stdout)
            self.assertTrue((root / "activate-fastfarm.sh").is_file())
            logs = list((root / "logs").glob("*.log"))
            self.assertEqual(len(logs), 1)
            self.assertIn("--parallel 2", logs[0].read_text())
            verify = self.command("--config", str(settings.config), "--verify")
            self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)
            self.assertEqual(manifest_path.read_bytes(), original_manifest)
            self.assertTrue((prefix / "verification-manifest.json").is_file())

    def test_fetch_only_never_builds_even_with_private_math(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "settings.ini"
            config.write_text("[build]\nroot = generated\n[libraries]\npolicy = build\n")
            with patch.object(compiler.Builder, "inspect_tools", return_value=[]), \
                 patch.object(compiler.Builder, "openfast_source") as openfast, \
                 patch.object(compiler.Builder, "lapack_source") as lapack, \
                 patch.object(compiler.Builder, "ensure_cmake") as cmake, \
                 patch.object(compiler.Builder, "build_private_math") as build:
                self.assertEqual(compiler.main(["--config", str(config), "--fetch-only"]), 0)
                openfast.assert_called_once()
                lapack.assert_called_once()
                cmake.assert_not_called()
                build.assert_not_called()

    def cmake(self):
        cmake = os.environ.get("CMAKE_COMMAND") or shutil.which("cmake")
        if not cmake:
            self.skipTest("Set CMAKE_COMMAND or put CMake on PATH")
        return cmake


if __name__ == "__main__":
    unittest.main()
