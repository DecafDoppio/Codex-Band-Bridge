"""PowerShell 5.1 dependency setup isolated from user Python and Hooks."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[1]
PS=shutil.which('powershell.exe')

@unittest.skipUnless(PS,'Windows PowerShell required')
class TclConfigTests(unittest.TestCase):
    def invoke(self, base, python, extra_env=None):
        source=(ROOT/'scripts/Configure-Codex.ps1').read_text(encoding='utf-8-sig')
        functions=source.split('$sourceConfig=')[0]
        file=base/'dependency-test.ps1'
        file.write_text(functions+"\n$chosen=Find-BridgePython\nWrite-Output ('VERIFIED:'+ $chosen)\nif($script:TclLibraries){Write-Output 'TCL_SIDECAR_USED'}\n",encoding='utf-8-sig')
        shutil.copy2(ROOT/'third_party/tcl-tk/tcl-tk.zip',base/'tcl-tk.zip')
        modules=str(Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/Modules')
        env=dict(os.environ,LOCALAPPDATA=str(base/'local'),PROGRAMFILES=str(base/'programs'),PSModulePath=modules,PYTHONIOENCODING='utf-8')
        env.update(extra_env or {})
        return subprocess.run([PS,'-NoProfile','-ExecutionPolicy','Bypass','-File',str(file),'-PythonPath',str(python)],env=env,capture_output=True,timeout=30)

    def test_missing_python_stops_without_installing_anything(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.local') as tmp:
            base=Path(tmp);result=self.invoke(base,base/'missing/python.exe')
            self.assertNotEqual(result.returncode,0)
            self.assertFalse((base/'local').exists())
            self.assertNotIn(b'VERIFIED:',result.stdout)

    def test_old_python_stops_before_tcl_unpack(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.local') as tmp:
            base=Path(tmp);fake=base/'old-version';fake.mkdir()
            (fake/'sitecustomize.py').write_text('import sys\nsys.version_info=(3,9,0,"final",0)\n')
            result=self.invoke(base,sys.executable,{'PYTHONPATH':str(fake)})
            self.assertNotEqual(result.returncode,0)
            self.assertFalse((base/'local').exists())

    def test_working_tk_reuses_python_without_unpacking(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.local') as tmp:
            base=Path(tmp);result=self.invoke(base,sys.executable)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn(b'VERIFIED:',result.stdout)
            self.assertFalse((base/'local').exists())

    def test_missing_support_files_reach_the_bundled_fallback(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.local') as tmp:
            base=Path(tmp);fixture=base/'missing-tcl';fixture.mkdir()
            (fixture/'tkinter.py').write_text('''import os
from pathlib import Path
class Tk:
    def __init__(self):
        if not (Path(os.environ.get("TCL_LIBRARY", "/missing"))/"init.tcl").is_file():
            raise RuntimeError("Tcl support files missing")
    def withdraw(self): pass
    def update_idletasks(self): pass
    def destroy(self): pass
''')
            result=self.invoke(base,sys.executable,{'PYTHONPATH':str(fixture),'TCL_LIBRARY':str(base/'absent'),'TK_LIBRARY':str(base/'absent')})
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn(b'TCL_SIDECAR_USED',result.stdout)
            self.assertEqual(len(list((base/'local/CodexBandBridge/tcl-tk').glob('*/tcl/tcl8.6/init.tcl'))),1)

    def test_tcl_support_contains_no_python_and_fits_budget(self):
        archive=ROOT/'third_party/tcl-tk/tcl-tk.zip'
        with zipfile.ZipFile(archive) as z:
            self.assertFalse(any(n.endswith(('.exe','.dll','.pyd')) for n in z.namelist()))
            self.assertFalse(json.loads(z.read('runtime-manifest.json'))['includesPython'])
            self.assertLess(sum(i.file_size for i in z.infolist())+archive.stat().st_size,50_000_000)

    def test_support_files_create_a_real_tk_window_without_global_configuration(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.local') as tmp:
            base=Path(tmp)
            with zipfile.ZipFile(ROOT/'third_party/tcl-tk/tcl-tk.zip') as z:z.extractall(base)
            env=dict(os.environ,TCL_LIBRARY=str(base/'tcl/tcl8.6'),TK_LIBRARY=str(base/'tcl/tk8.6'),PYTHONIOENCODING='utf-8')
            result=subprocess.run([sys.executable,'-c','import tkinter; r=tkinter.Tk(); r.withdraw(); r.update_idletasks(); print(r.tk.call("info","library")); r.destroy()'],env=env,capture_output=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn(str(base).encode(),result.stdout)

if __name__=='__main__':unittest.main()
