"""Local companion queue. Caches list summaries, never operations or credentials."""
import os
import time
import uuid
import json
import threading
from functools import wraps
from pathlib import Path


def process_alive(pid):
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        api=ctypes.windll.kernel32
        api.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        api.OpenProcess.restype=wintypes.HANDLE
        api.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
        api.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=api.OpenProcess(0x1000,False,pid)
        if not handle:return api.GetLastError()!=87
        try:
            code=wintypes.DWORD()
            return not api.GetExitCodeProcess(handle,ctypes.byref(code)) or code.value==259
        finally:api.CloseHandle(handle)
    try:os.kill(pid,0);return True
    except ProcessLookupError:return False
    except PermissionError:return True


def cleanup_process(directory,pid):
    """Called by the hook after its own companion has exited."""
    if not isinstance(pid,int):return
    for path in Path(directory).glob('*.queue'):
        try:
            if json.loads(path.read_text(encoding='utf-8')).get('pid')==pid:
                path.unlink(missing_ok=True)
        except (OSError,ValueError):pass


def synchronized(method):
    @wraps(method)
    def call(self,*args,**kwargs):
        with self.lock:return method(self,*args,**kwargs)
    return call


class DesktopQueue:
    def __init__(self, directory, clock=time.time, summary=None, alive=process_alive):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self.alive = alive
        self.lock = threading.RLock()
        # Windows wall-clock timestamps can repeat for several milliseconds.
        # The monotonic performance counter preserves creation order here.
        self.entry = self.directory / (f'{time.perf_counter_ns():020d}-' + uuid.uuid4().hex + '.queue')
        # Only the list summary is cached, never raw operations or credentials.
        with self.entry.open('x',encoding='utf-8') as output:
            json.dump({'pid':os.getpid(),'summary':summary or {}},output,ensure_ascii=False)
        self.handle = None
        self.closed = False

    @synchronized
    def entries(self):
        items = []
        for path in self.directory.glob('*.queue'):
            try:
                age=self.clock()-path.stat().st_mtime
                try:pid=json.loads(path.read_text(encoding='utf-8')).get('pid')
                except (ValueError,OSError):pid=None
                if age > 30 or (isinstance(pid,int) and not self.alive(pid)):
                    path.unlink()
                else:
                    items.append(path)
            except FileNotFoundError:
                pass
        return sorted(items)

    @synchronized
    def summaries(self):
        items=[]
        for path in self.entries():
            try:items.append((path,json.loads(path.read_text(encoding='utf-8')).get('summary',{})))
            except (OSError,ValueError):pass
        return items

    @synchronized
    def select(self, path):
        if path not in self.entries():return False
        temporary=self.directory/(uuid.uuid4().hex+'.focus')
        temporary.write_text(path.name,encoding='utf-8')
        temporary.replace(self.directory/'selected')
        return True

    @synchronized
    def release(self):
        if self.handle is None:return
        try:
            self.handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.handle.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(self.handle,fcntl.LOCK_UN)
        finally:self.handle.close();self.handle=None

    @synchronized
    def acquire(self):
        if self.closed:
            return False
        # Refresh our lease before examining stale entries.
        try:os.utime(self.entry, (self.clock(), self.clock()))
        except FileNotFoundError:return False
        entries = self.entries()
        try:selected=self.directory/(self.directory/'selected').read_text(encoding='utf-8')
        except OSError:selected=None
        head=selected if selected in entries else (entries[0] if entries else None)
        if head != self.entry:
            self.release()
            return False
        if self.handle is not None:return True
        handle = (self.directory / 'window.lock').open('a+b')
        if handle.tell() == 0:
            handle.write(b'0');handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self.handle = handle
        return True

    @synchronized
    def close(self):
        if self.closed:
            return
        self.closed = True
        self.release()
        self.entry.unlink(missing_ok=True)
