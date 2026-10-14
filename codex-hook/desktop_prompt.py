"""Local desktop approval companion. No operation execution or policy changes."""
import json
import queue
import sys
import threading
import tkinter as tk
from desktop_monitors import work_area, clamp_position, window_scale, rescale_children
from tkinter import ttk

from bridge_hook import exchange, diagnostic
from desktop_queue import DesktopQueue
from pathlib import Path
import hashlib
import time
from datetime import datetime


def rounded_window(root, radius):
    if sys.platform!='win32':return
    import ctypes
    from ctypes import wintypes
    user32,gdi32=ctypes.windll.user32,ctypes.windll.gdi32
    user32.GetAncestor.argtypes=[wintypes.HWND,wintypes.UINT];user32.GetAncestor.restype=wintypes.HWND
    user32.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
    gdi32.CreateRoundRectRgn.argtypes=[ctypes.c_int]*6;gdi32.CreateRoundRectRgn.restype=wintypes.HANDLE
    user32.SetWindowRgn.argtypes=[wintypes.HWND,wintypes.HANDLE,wintypes.BOOL]
    gdi32.DeleteObject.argtypes=[wintypes.HANDLE]
    handle=user32.GetAncestor(root.winfo_id(),2) or root.winfo_id()
    rect=wintypes.RECT()
    if not user32.GetWindowRect(handle,ctypes.byref(rect)):return
    size=(rect.right-rect.left,rect.bottom-rect.top)
    if size[0]<=1 or size[1]<=1 or size==getattr(root,'_rounded_size',None):return
    region=gdi32.CreateRoundRectRgn(0,0,size[0]+1,size[1]+1,radius*2,radius*2)
    if user32.SetWindowRgn(handle,region,True):root._rounded_size=size
    else:gdi32.DeleteObject(region)


class PillButton(tk.Canvas):
    def __init__(self, parent, text, color, hover, command, scale, background, width):
        self.factor=scale;self.color=color;self.hover=hover;self.caption=text;self.callback=command;self.enabled=True
        self.w=round(width*scale);self.h=round(38*scale)
        super().__init__(parent,width=self.w,height=self.h,bg=background,highlightthickness=0,borderwidth=0,cursor='hand2')
        self.configure(takefocus=True)
        self.bind('<space>',lambda _:self.callback() if self.enabled else None)
        self.bind('<FocusIn>',lambda _:super(PillButton,self).configure(highlightthickness=2,highlightbackground='#9BACBF'))
        self.bind('<FocusOut>',lambda _:super(PillButton,self).configure(highlightthickness=0))
        self.bind('<Enter>',lambda _:self.paint(self.hover if self.enabled else '#25282f'))
        self.bind('<Leave>',lambda _:self.paint())
        self.bind('<Button-1>',lambda _:self.callback() if self.enabled else None)
        self.paint()

    def paint(self, fill=None):
        self.delete('all');fill=fill or (self.color if self.enabled else '#25282f');r=self.h/2
        self.create_oval(0,0,self.h,self.h,fill=fill,outline=fill)
        self.create_oval(self.w-self.h,0,self.w,self.h,fill=fill,outline=fill)
        self.create_rectangle(r,0,self.w-r,self.h,fill=fill,outline=fill)
        self.create_text(self.w/2,self.h/2,text=self.caption,fill='white' if self.enabled else '#747b88',font=('Microsoft YaHei UI',10))

    def configure(self, **kwargs):
        if 'state' in kwargs:
            self.enabled=kwargs.pop('state')!='disabled';self.paint()
        if kwargs:super().configure(**kwargs)


class SlimScrollbar(tk.Canvas):
    def __init__(self,parent,content,scale,background):
        super().__init__(parent,width=round(8*scale),bg=background,highlightthickness=0,borderwidth=0)
        self.content=content;self.scale=scale;self.first=0;self.last=1;self.drag_y=0;self.drag_first=0;self.shown=False
        self.bind('<Configure>',lambda _:self.paint())
        self.bind('<Button-1>',self.press);self.bind('<B1-Motion>',self.drag)
        self.bind('<MouseWheel>',lambda event:self.content.yview_scroll(-int(event.delta/120),'units'))

    def set(self,first,last):
        self.first,self.last=float(first),float(last)
        # Reserve the gutter: changing pack layout inside a yscroll callback can
        # oscillate wrapped text geometry during expand/collapse.
        self.paint()

    def paint(self):
        self.delete('all');height=max(1,self.winfo_height());width=self.winfo_width()
        if self.last-self.first>=.999:return
        self.thumb=max(round(24*self.scale),(self.last-self.first)*height)
        self.top=self.first/max(.0001,1-(self.last-self.first))*max(0,height-self.thumb)
        radius=max(1,round(2*self.scale));x=width/2
        self.create_oval(x-radius,self.top,x+radius,self.top+2*radius,fill='#555b68',outline='')
        self.create_rectangle(x-radius,self.top+radius,x+radius,self.top+self.thumb-radius,fill='#555b68',outline='')
        self.create_oval(x-radius,self.top+self.thumb-2*radius,x+radius,self.top+self.thumb,fill='#555b68',outline='')

    def press(self,event):
        if not self.top<=event.y<=self.top+self.thumb:
            self.content.yview_moveto(max(0,min(1,event.y/max(1,self.winfo_height()))))
        self.drag_y=event.y;self.drag_first=self.first

    def drag(self,event):
        travel=max(1,self.winfo_height()-self.thumb)
        self.content.yview_moveto(self.drag_first+(event.y-self.drag_y)/travel*(1-self.last+self.first))


class PendingCards(tk.Canvas):
    def __init__(self,parent,scale,background,select):
        self.scale=scale;self.items=[];self.selected=None;self.select=select
        self.stride=round(80*scale)
        super().__init__(parent,bg=background,highlightthickness=0,borderwidth=0,
            height=self.stride,yscrollincrement=round(24*scale),cursor='hand2')
        self.bind('<Configure>',lambda _:self.paint())
        self.bind('<Button-1>',self.click)
        self.bind('<MouseWheel>',lambda e:self.yview_scroll(-int(e.delta/120),'units'))

    def set_items(self,items,selected):
        self.items=items;self.selected=selected
        self.configure(height=self.stride*min(3,len(items)))
        self.paint()

    def click(self,event):
        y=self.canvasy(event.y);index=int(y//self.stride)
        if 0<=index<len(self.items) and y%self.stride<round(72*self.scale):self.select(index)

    def paint(self):
        self.delete('all');px=lambda n:round(n*self.scale)
        width=max(px(100),self.winfo_width()-px(2));radius=px(12)
        for index,(path,summary) in enumerate(self.items):
            top=index*self.stride;bottom=top+px(72);left=px(1);right=width
            chosen=path==self.selected
            self.create_polygon(left+radius,top,right-radius,top,right,top,right,top+radius,
                right,bottom-radius,right,bottom,right-radius,bottom,left+radius,bottom,
                left,bottom,left,bottom-radius,left,top+radius,left,top,
                smooth=True,fill='#394453' if chosen else '#2E323A',
                outline='#9BACBF' if chosen else '#454A55',width=px(1))
            project=str(summary.get('project') or '未命名项目')
            self.create_text(px(12),top+px(10),anchor='nw',text=project[:22]+('…' if len(project)>22 else ''),
                fill='#B7C2CF',font=('Microsoft YaHei UI',9))
            self.create_text(right-px(12),top+px(10),anchor='ne',text=summary.get('time',''),
                fill='#B0B4BD',font=('Microsoft YaHei UI',9))
            reason=' '.join(str(summary.get('reason','')).split())
            self.create_text(px(12),top+px(30),anchor='nw',width=right-px(24),
                text=reason[:50]+('…' if len(reason)>50 else ''),fill='#f5f6f8',font=('Microsoft YaHei UI',9))
        self.configure(scrollregion=(0,0,width,self.stride*len(self.items)))


def create_prompt(config, request, queue_directory=None, test_scale=None):
    # System DPI awareness makes geometry and the Windows work area consistent.
    if sys.platform == 'win32':
        import ctypes
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except Exception:
            pass
    root = tk.Tk()
    root.withdraw()
    root.title('Codex Band Bridge · 请求批准')
    root.overrideredirect(True)
    root.attributes('-topmost', True)
    scale = max(1, min(2.5, root.winfo_fpixels('1i') / 96))
    if test_scale is not None:
        scale=float(test_scale);root.tk.call('tk','scaling',scale*96/72)
    px = lambda value: round(value * scale)
    palette = {'background':'#24272D','border':'#454A55','text':'#F0F0F2','muted':'#B0B4BD','blue':'#A4B8CD'}
    root.configure(bg=palette['border'])
    queue_count=1

    def position(expanded=False):
        nonlocal scale
        width = px(420 if queue_count>1 else 320)
        height = px((390 if expanded else 260)+(min(queue_count,3)*80+8 if queue_count>1 else 0))
        left,top,right,bottom=work_area(getattr(root,'_user_position',None),root)
        height=min(height,bottom-top-px(36));width=min(width,right-left)
        x,y=getattr(root,'_user_position',(right-width-px(18),bottom-height-px(18)))
        x,y=clamp_position(x,y,width,height,(left,top,right,bottom))
        # Tk's '-10' means distance from the right edge, not absolute negative
        # desktop coordinates. Use native placement for multi-monitor positions.
        root.geometry(f'{width}x{height}+{max(0,x)}+{max(0,y)}')
        root.update_idletasks()
        if sys.platform=='win32':
            import ctypes
            from ctypes import wintypes
            user32=ctypes.windll.user32
            user32.GetAncestor.argtypes=[wintypes.HWND,wintypes.UINT];user32.GetAncestor.restype=wintypes.HWND
            user32.SetWindowPos.argtypes=[wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.UINT]
            handle=user32.GetAncestor(root.winfo_id(),2) or root.winfo_id()
            user32.SetWindowPos(handle,None,x,y,width,height,0x0014)
            next_scale=window_scale(root,scale) if test_scale is None else scale
            if abs(next_scale-scale)>.05:
                old=scale;scale=next_scale;rescale_children(root,old,scale)
                width=min(px(420 if queue_count>1 else 320),right-left)
                height=min(px((390 if expanded else 260)+(min(queue_count,3)*80+8 if queue_count>1 else 0)),bottom-top-px(36))
                x,y=clamp_position(x,y,width,height,(left,top,right,bottom))
                user32.SetWindowPos(handle,None,x,y,width,height,0x0014)

    card=tk.Frame(root,bg=palette['background'])
    card.place(x=1,y=1,relwidth=1,relheight=1,width=-2,height=-2)
    card.grid_propagate(False)
    card.grid_columnconfigure(0,weight=1);card.grid_rowconfigure(3,weight=1)
    header=tk.Frame(card,bg=palette['background']);header.grid(row=0,column=0,sticky='ew',padx=px(18),pady=(px(12),px(4)))
    icon_path=Path(__file__).resolve().parents[1]/'assets/brand/icon-48.png'
    icon_widget=None
    if icon_path.exists():
        root._brand_icon=tk.PhotoImage(master=root,file=str(icon_path)).zoom(round(scale*2)).subsample(4)
        icon_widget=tk.Label(header,image=root._brand_icon,bg=palette['background'])
        icon_widget.pack(side='left',padx=(0,px(8)));root.iconphoto(True,root._brand_icon)
    brand=tk.Label(header,text='Codex Band Bridge',fg=palette['muted'],bg=palette['background'],font=('Microsoft YaHei UI',9))
    brand.pack(side='left')
    close=tk.Label(header,text='×',fg=palette['muted'],bg=palette['background'],font=('Segoe UI',15),cursor='hand2')
    close.pack(side='right')
    title=tk.Label(card,text='请求批准',fg=palette['text'],bg=palette['background'],font=('Microsoft YaHei UI',12,'bold'))
    title.grid(row=1,column=0,sticky='w',padx=px(18),pady=(0,px(8)))
    pending_list=PendingCards(card,scale,palette['background'],lambda index:select_pending(index))
    list_paths=[];list_signature=None
    panel=tk.Frame(card,bg=palette['background']);panel.grid(row=3,column=0,sticky='nsew',padx=px(18))
    content=tk.Text(panel,wrap='char',font=('Microsoft YaHei UI',10),bg=palette['background'],fg=palette['text'],relief='flat',borderwidth=0,highlightthickness=0,height=3,insertbackground=palette['text'],padx=0,pady=0)
    bar=SlimScrollbar(panel,content,scale,palette['background'])
    bar.pack(side='right',fill='y')
    content.configure(yscrollcommand=bar.set)
    content.pack(fill='both',expand=True)
    reason=request.get('reason')
    detail_open=False
    def show_text(value):
        content.configure(state='normal');content.delete('1.0','end');content.insert('1.0',value);content.configure(state='disabled');content.yview_moveto(0)
    identity='项目：'+str(request.get('project') or '未命名项目')+'\n操作：'+str(request.get('operation') or '请查看完整操作')+'\n目标：'+str(request.get('target') or '请查看完整操作')+'\n\n'
    request_summary=reason or request.get('title') or 'Codex 请求执行一次操作。'
    show_text(request_summary)
    message=tk.StringVar(master=root,value='')
    tk.Label(card,textvariable=message,fg='#ff8291',bg=palette['background'],font=('Microsoft YaHei UI',9)).grid(row=4,column=0,sticky='w',padx=px(18),pady=(px(3),0))
    actions=tk.Frame(card,bg=palette['background']);actions.grid(row=5,column=0,sticky='ew',padx=px(18),pady=(px(5),px(18)))
    def toggle_details():
        nonlocal detail_open
        detail_open=not detail_open
        content.configure(wrap='word' if detail_open else 'char')
        show_text(identity+request['content'] if detail_open else request_summary)
        details.configure(text='收起操作' if detail_open else '查看操作')
        position(detail_open)
    details=tk.Label(actions,text='收起操作' if detail_open else '查看操作',fg=palette['blue'],bg=palette['background'],font=('Microsoft YaHei UI',9),cursor='hand2')
    details.pack(side='left');details.bind('<Button-1>',lambda _:toggle_details())
    def button(text,color,command):
        control=PillButton(actions,text,color,'#739681' if text=='批准本次' else '#596171',command,scale,palette['background'],90 if text=='批准本次' else 62)
        control.pack(side='right',padx=(px(8),0))
        return control
    position(detail_open)
    events = queue.Queue()
    closing = threading.Event()
    busy = False
    poll_in_flight = False
    next_poll = 0
    dismissed = False
    shown_reported = False
    scheduled = []
    queue_directory=queue_directory or (Path(__file__).resolve().parents[1]/'.local/desktop-queue'/hashlib.sha256(config['endpoint'].encode()).hexdigest()[:16])
    window_queue=DesktopQueue(queue_directory,summary={'project':request.get('project','未命名项目'),
        'reason':(request.get('reason') or 'Codex 未提供请求原因')[:160],
        'time':datetime.now().strftime('%H:%M')})
    def select_pending(index):
        if busy:return
        if 0<=index<len(list_paths):
            path=list_paths[index]
            if path!=window_queue.entry and window_queue.select(path):
                # Carry the user's location to the selected companion too.
                position_file=window_queue.directory/'position.json'
                position_file.write_text(json.dumps([root.winfo_x(),root.winfo_y()]),encoding='utf-8')
                window_queue.release();root.withdraw()
    drag_anchor=None
    def drag_start(event):
        nonlocal drag_anchor
        drag_anchor=(event.x_root,event.y_root,root.winfo_x(),root.winfo_y())
    def drag_move(event):
        if drag_anchor is None:return
        sx,sy,x,y=drag_anchor
        root._user_position=(x+event.x_root-sx,y+event.y_root-sy)
        position(detail_open)
        (window_queue.directory/'position.json').write_text(json.dumps(list(root._user_position)),encoding='utf-8')
    def drag_end(event=None):
        nonlocal drag_anchor
        drag_anchor=None
    for surface in (header,brand,title,*([icon_widget] if icon_widget else [])):
        surface.configure(cursor='fleur')
        surface.bind('<ButtonPress-1>',drag_start)
        surface.bind('<B1-Motion>',drag_move)
        surface.bind('<ButtonRelease-1>',drag_end)
    def ui_error(exception, value, traceback):
        diagnostic(config, {'phase':'desktop_ui_error','errorType':exception.__name__})
        message.set('界面操作失败，请在手环处理。')
    root.report_callback_exception=ui_error
    def resize_rounding(event):
        if event.widget is not root or root.state()=='withdrawn':return
        handle=getattr(root,'_round_timer',None)
        if handle:root.after_cancel(handle)
        root._round_timer=root.after(30,lambda:rounded_window(root,px(28)))
    root.bind('<Configure>',resize_rounding,add='+')

    def worker(decision=None):
        try:
            if decision:
                result = exchange(config, 'POST', '/v1/requests/' + request['id'] + '/decision',
                                  {'session_id':request['session_id'], 'decision':decision})
                diagnostic(config, {'phase':'desktop_resolution','requestId':request['id'],
                    'state':result.get('state'),'source':result.get('resolvedBy')})
            else:
                result = exchange(config, 'GET', '/v1/requests/' + request['id'])
            if result.get('id')==request['id'] and result.get('session_id')==request['session_id'] and result.get('state')!='pending':
                # Release before the hook sees the decision and terminates this
                # process; otherwise its stale lease blocks the next card 30s.
                window_queue.close()
            events.put(('result', result))
        except Exception:
            events.put(('error', None))

    def decide(decision):
        nonlocal busy
        if busy:
            return
        busy = True
        allow.configure(state='disabled')
        deny.configure(state='disabled')
        message.set('等待确认…')
        threading.Thread(target=worker, args=(decision,), daemon=True).start()

    allow = button('批准本次','#597E68',lambda:decide('allow'))
    deny = button('拒绝','#4A515E',lambda:decide('deny'))
    close.configure(text='稍后',font=('Microsoft YaHei UI',9),takefocus=True)
    close.bind('<space>',lambda _:dismiss())
    # Hide only this card and let the next queued card appear. The hook keeps
    # polling; no cancel, suspend, stop, or decision is issued here.
    def dismiss():
        nonlocal dismissed
        dismissed=True;window_queue.close();root.withdraw()
        diagnostic(config, {'phase':'desktop_hidden'})
        print('hidden',flush=True)
    root.protocol('WM_DELETE_WINDOW',dismiss)
    close.bind('<Button-1>',lambda _:dismiss())
    root.bind('<Escape>',lambda _:dismiss())
    print('queued',flush=True)

    def pump():
        nonlocal busy, poll_in_flight, shown_reported, queue_count, list_signature, list_paths, next_poll
        if closing.is_set():
            return
        if not dismissed:
            if window_queue.acquire():
                if root.state()=='withdrawn':
                    try:
                        coordinates=json.loads((window_queue.directory/'position.json').read_text(encoding='utf-8'))
                        if isinstance(coordinates,list) and len(coordinates)==2 and all(type(n) is int for n in coordinates):root._user_position=tuple(coordinates)
                    except (OSError,ValueError):pass
                    root.deiconify();root.lift();position(detail_open)
                if not shown_reported:
                    shown_reported=True;scheduled.append(root.after(150,report_ready))
                items=window_queue.summaries();count=len(items)
                signature=tuple((str(path),json.dumps(summary,sort_keys=True)) for path,summary in items)
                if signature!=list_signature:
                    list_signature=signature;queue_count=count;list_paths=[path for path,_ in items]
                    pending_list.set_items(items,window_queue.entry)
                    if count>1:
                        pending_list.grid(row=2,column=0,sticky='ew',padx=px(18),pady=(0,px(8)))
                    else:pending_list.grid_remove()
                    position(detail_open)
                title.configure(text='请求批准' + (f' · 共{count}项' if count>1 else ''))
                details.configure(text='收起操作' if detail_open else '查看操作')
            elif root.state()!='withdrawn':root.withdraw()
        while not events.empty():
            kind, value = events.get_nowait()
            poll_in_flight=False
            if kind == 'error':
                closing.set()
                root.destroy()
                return
            if value.get('id') != request['id'] or value.get('session_id') != request['session_id']:
                closing.set()
                root.destroy()
                return
            if value.get('state') != 'pending':
                closing.set()
                root.destroy()
                return
            if not busy:
                allow.configure(state='normal')
                deny.configure(state='normal')
        if not busy and not poll_in_flight and time.monotonic()>=next_poll:
            poll_in_flight = True
            next_poll=time.monotonic()+.5
            threading.Thread(target=worker, daemon=True).start()
        scheduled.append(root.after(100, pump))

    scheduled.append(root.after(50, pump))
    def report_ready():
        root.update_idletasks()
        diagnostic(config, {'phase':'desktop_shown','windowWidth':root.winfo_width(),'windowHeight':root.winfo_height()})
        print('ready', flush=True)  # Readiness only; never log request text or secrets.
        print(json.dumps({'windowHeight':root.winfo_height(),'scale':scale,'buttons':[
            {'top':control.winfo_rooty()-root.winfo_rooty(),'height':control.winfo_height(),
             'paintedHeight':control.h} for control in (deny,allow)]}),flush=True)
    def cleanup_timers(event):
        if event.widget is not root:return
        closing.set();window_queue.close()
        for handle in scheduled:
            try:root.after_cancel(handle)
            except tk.TclError:pass
        if getattr(root,'_round_timer',None):
            try:root.after_cancel(root._round_timer)
            except tk.TclError:pass
    root.bind('<Destroy>',cleanup_timers,add='+')
    return root, {'toggle_details':toggle_details,'dismiss':dismiss,'decide':decide,
                  'allow':allow,'deny':deny,'details':details,'content':content,
                  'window_queue':window_queue,'message':message,'title':title,
                  'pending_list':pending_list,'select_pending':select_pending,
                  'drag_start':drag_start,'drag_move':drag_move,'drag_end':drag_end,'header':header}


def main():
    data = json.loads(sys.stdin.buffer.read(256 * 1024))
    root, controls=create_prompt(data['config'],data['request'])
    try:root.mainloop()
    finally:controls['window_queue'].close()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('failed',flush=True)
        sys.exit(1)
