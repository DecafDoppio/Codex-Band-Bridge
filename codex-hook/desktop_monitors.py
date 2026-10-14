"""Work-area selection supports negative desktop coordinates."""
import sys


def clamp_position(x,y,width,height,rect):
    left,top,right,bottom=rect
    return max(left,min(x,right-width)),max(top,min(y,bottom-height))


def work_area(position,root):
    if sys.platform!='win32':return (0,0,root.winfo_screenwidth(),root.winfo_screenheight())
    import ctypes
    from ctypes import wintypes as w
    class Info(ctypes.Structure):
        _fields_=[('size',w.DWORD),('monitor',w.RECT),('work',w.RECT),('flags',w.DWORD)]
    api=ctypes.windll.user32
    api.MonitorFromPoint.argtypes=[w.POINT,w.DWORD];api.MonitorFromPoint.restype=w.HANDLE
    api.GetMonitorInfoW.argtypes=[w.HANDLE,ctypes.POINTER(Info)]
    x,y=position or (root.winfo_pointerx(),root.winfo_pointery())
    monitor=api.MonitorFromPoint(w.POINT(x,y),2);info=Info();info.size=ctypes.sizeof(info)
    if api.GetMonitorInfoW(monitor,ctypes.byref(info)):
        r=info.work;return (r.left,r.top,r.right,r.bottom)
    return (0,0,root.winfo_screenwidth(),root.winfo_screenheight())


def window_scale(root,default):
    if sys.platform!='win32':return default
    import ctypes
    from ctypes import wintypes as w
    api=ctypes.windll.user32
    api.GetAncestor.argtypes=[w.HWND,w.UINT];api.GetAncestor.restype=w.HWND
    api.GetDpiForWindow.argtypes=[w.HWND];api.GetDpiForWindow.restype=w.UINT
    try:
        dpi=api.GetDpiForWindow(api.GetAncestor(root.winfo_id(),2) or root.winfo_id())
        return max(1,min(3,dpi/96)) if dpi else default
    except AttributeError:return default


def rescale_children(root,old,new):
    ratio=new/old;root.tk.call('tk','scaling',new*96/72)
    def pixels(value):return tuple(round(float(n)*ratio) for n in root.tk.splitlist(value))
    def visit(parent):
        for child in parent.winfo_children():
            info=child.grid_info() if child.winfo_manager()=='grid' else child.pack_info() if child.winfo_manager()=='pack' else {}
            changes={k:pixels(info[k]) for k in ('padx','pady','ipadx','ipady') if k in info}
            if changes:
                if child.winfo_manager()=='grid':child.grid_configure(**changes)
                else:child.pack_configure(**changes)
            if 'font' in child.keys():child.configure(font=child.cget('font'))
            if hasattr(child,'factor'):
                child.factor=new;child.w=round(child.w*ratio);child.h=round(child.h*ratio)
                child.configure(width=child.w,height=child.h);child.paint()
            elif hasattr(child,'scale'):
                child.scale=new
                if hasattr(child,'stride'):child.stride=round(80*new)
                child.configure(width=round(float(child.cget('width'))*ratio),height=round(float(child.cget('height'))*ratio))
                child.paint()
            visit(child)
    visit(root)
