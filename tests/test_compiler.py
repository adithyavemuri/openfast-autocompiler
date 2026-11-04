"""Rootless compiler contracts; no solver build or network in these tests."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/'build_openfast.sh'


class CompilerTests(unittest.TestCase):
    def command(self,*args,**kwargs):
        return subprocess.run(['bash',str(SCRIPT),*args],capture_output=True,text=True,timeout=60,**kwargs)

    def test_help_and_shell_syntax(self):
        self.assertEqual(self.command('--help').returncode,0)
        text=self.command('--help').stdout
        self.assertIn('--math-libs',text);self.assertIn('--deps-only',text)
        subprocess.run(['bash','-n',str(SCRIPT)],check=True)

    def test_invalid_policy_and_system_destination_fail_before_writes(self):
        self.assertNotEqual(self.command('--math-libs','invalid').returncode,0)
        self.assertNotEqual(self.command('--root','/usr/local/should-not-build','--preflight').returncode,0)

    @unittest.skipUnless(all(shutil.which(c) for c in ('gcc','g++','gfortran','git','make','file','ldd')),'GNU toolchain required')
    def test_batch_must_choose_math_policy_without_creating_root(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'generated'
            result=self.command('--root',str(root),stdin=subprocess.DEVNULL)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('choose --math-libs system or --math-libs build',result.stderr)
            self.assertFalse(root.exists())

    @unittest.skipUnless(shutil.which('gfortran'),'Fortran compiler required')
    def test_system_numerical_preflight_does_not_install(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'generated'
            env=os.environ.copy()
            cmake=os.environ.get('CMAKE_COMMAND') or shutil.which('cmake') or ROOT.parent/'openfast-local/tools/bin/cmake'
            if not Path(cmake).is_file():self.skipTest('CMake unavailable')
            env['CMAKE_COMMAND']=str(cmake)
            result=self.command('--root',str(root),'--preflight','--math-libs','system',env=env)
            if 'UNAVAILABLE/INCOMPATIBLE' in result.stdout:self.skipTest('System math development/runtime libraries unavailable')
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('PASS: Fortran DGESV and DGEMM',result.stdout)
            self.assertFalse(root.exists())

    def test_fastscale_bundled_copy_matches(self):
        copy=ROOT.parent/'FASTScale/tools/build_openfast.sh'
        if not copy.exists():self.skipTest('Independent compiler checkout has no FASTScale sibling')
        canonical=SCRIPT.read_text().replace('$(dirname -- "$SCRIPT_DIR")/openfast-local','$(dirname -- "$SCRIPT_DIR")/../openfast-local')
        self.assertEqual(copy.read_text(),canonical)


if __name__=='__main__':unittest.main()
