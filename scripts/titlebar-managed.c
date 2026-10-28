/* Maintain only the current prefix's WeCom windows and unique Wine tray. */
typedef unsigned long DWORD;
typedef int BOOL;
typedef void *HANDLE;
typedef struct {long left,top,right,bottom;} RECT;
typedef struct {long x,y;} POINT;
typedef struct {HANDLE hwnd;unsigned message,wparam;long lparam;DWORD time;POINT pt;DWORD private_data;} MSG;
typedef struct {DWORD size;RECT monitor,work;DWORD flags;} MONITORINFO;
typedef struct {DWORD size,usage,pid,heap,module,threads,parent;long priority;DWORD flags;char exe[260];} PROCESSENTRY32;
#define API __declspec(dllimport) __stdcall
API HANDLE FindWindowA(const char *, const char *);
API HANDLE FindWindowExA(HANDLE,HANDLE,const char *,const char *);
API BOOL EnumWindows(BOOL (__stdcall *)(HANDLE,long),long);
API HANDLE GetParent(HANDLE);
API int GetClassNameA(HANDLE,char *,int);
API DWORD GetWindowThreadProcessId(HANDLE,DWORD *);
API long GetWindowLongA(HANDLE,int);
API long SetWindowLongA(HANDLE,int,long);
API BOOL SetWindowPos(HANDLE,HANDLE,int,int,int,int,unsigned);
API BOOL PostMessageA(HANDLE,unsigned,unsigned,long);
API BOOL GetWindowRect(HANDLE,RECT *);
API HANDLE GetStdHandle(DWORD);
API BOOL WriteFile(HANDLE,const void *,DWORD,DWORD *,void *);
API char *GetCommandLineA(void);
API void ExitProcess(DWORD);
API HANDLE CreateMutexA(void *,BOOL,const char *);
API DWORD GetLastError(void);
API HANDLE CreateToolhelp32Snapshot(DWORD,DWORD);
API BOOL Process32First(HANDLE,PROCESSENTRY32 *);
API BOOL Process32Next(HANDLE,PROCESSENTRY32 *);
API HANDLE OpenProcess(DWORD,BOOL,DWORD);
API DWORD WaitForSingleObject(HANDLE,DWORD);
API BOOL CloseHandle(HANDLE);
API void Sleep(DWORD);
API DWORD GetEnvironmentVariableA(const char *,char *,DWORD);
API int GetSystemMetrics(int);
API HANDLE GetForegroundWindow(void);
API BOOL SetForegroundWindow(HANDLE);
API DWORD GetCurrentThreadId(void);
API HANDLE GetModuleHandleA(const char *);
API BOOL AttachThreadInput(DWORD,DWORD,BOOL);
API BOOL IsIconic(HANDLE);
API HANDLE GetPropA(HANDLE,const char *);
API HANDLE CreateFileA(const char *,DWORD,DWORD,void *,DWORD,DWORD,HANDLE);
API HANDLE WindowFromPoint(POINT);
API BOOL ScreenToClient(HANDLE,POINT *);
API short GetAsyncKeyState(int);
API HANDLE SetWindowsHookExA(int,long (__stdcall *)(int,unsigned,long),HANDLE,DWORD);
API long CallNextHookEx(HANDLE,int,unsigned,long);
API BOOL UnhookWindowsHookEx(HANDLE);
API BOOL IsWindowVisible(HANDLE);
API HANDLE MonitorFromRect(const RECT *,DWORD);
API BOOL GetMonitorInfoA(HANDLE,MONITORINFO *);
API BOOL GetCursorPos(POINT *);
API HANDLE MonitorFromPoint(POINT,DWORD);
API int MulDiv(int,int,int);
API DWORD GetTickCount(void);
API HANDLE SetWinEventHook(DWORD,DWORD,HANDLE,void (__stdcall *)(HANDLE,DWORD,HANDLE,long,long,DWORD,DWORD),DWORD,DWORD,DWORD);
API BOOL UnhookWinEvent(HANDLE);
API DWORD MsgWaitForMultipleObjects(DWORD,const HANDLE *,BOOL,DWORD,DWORD);
API BOOL PeekMessageA(MSG *,HANDLE,unsigned,unsigned,unsigned);
API BOOL TranslateMessage(const MSG *);
API long DispatchMessageA(const MSG *);
static HANDLE main_window;static DWORD main_pid;static int apply,found,changed,watch,native_frames;
static long tray_geometry[7],tray_maps[16][8];static int tray_enabled;static HANDLE pending_menu;
static DWORD menu_due;static RECT tray_rect;static POINT tray_point;
static HANDLE pending_tooltip,tooltip_owner;static DWORD tooltip_due;
static RECT tooltip_rect;static POINT tooltip_point;
static HANDLE pending_activation;static DWORD activation_due;
static HANDLE tracked_menu,menu_tray;static DWORD menu_opened_at,menu_external_since;
static HANDLE pending_menu_restore;static DWORD menu_restore_due,menu_restore_deadline;
static POINT menu_click;static int click_in_menu;
static HANDLE pressed_context_menu;
static char output[2048];static unsigned pos;
static void text(const char *s){while(*s&&pos<sizeof(output)-64)output[pos++]=*s++;}
static void hex(DWORD v){text("0x");for(int i=7;i>=0;i--)output[pos++]="0123456789abcdef"[(v>>(4*i))&15];}
static int same(const char*a,const char*b){while(*a&&*a==*b){a++;b++;}return *a==*b;}
static int is_wecom_exe(const char *name){
    const char *base=name;
    while(*name){if(*name=='\\'||*name=='/')base=name+1;name++;}
    const char *expected="wxwork.exe";
    while(*base&&*expected){
        char c=*base++;if(c>='A'&&c<='Z')c+='a'-'A';
        if(c!=*expected++)return 0;
    }
    return !*base&&!*expected;
}
static int wecom_process_alive(void){
    /* Wine's Toolhelp snapshot is scoped to this helper's wineserver/prefix.
       Return -1 for failed enumeration, never mistake it for an app exit. */
    HANDLE snapshot=CreateToolhelp32Snapshot(2,0); /* TH32CS_SNAPPROCESS */
    if(snapshot==(HANDLE)-1)return -1;
    PROCESSENTRY32 entry;entry.size=sizeof(entry);
    BOOL more=Process32First(snapshot,&entry);
    while(more){
        if(entry.pid&&is_wecom_exe(entry.exe)){CloseHandle(snapshot);return 1;}
        more=Process32Next(snapshot,&entry);
    }
    DWORD error=GetLastError();CloseHandle(snapshot);
    return error==18?0:-1; /* ERROR_NO_MORE_FILES */
}
static void wait_for_main_window(void){
    DWORD started=GetTickCount(),absent_since=0;int seen=0,absent=0;
    while(!(main_window=FindWindowA("WeWorkWindow",0))){
        int alive=wecom_process_alive();DWORD now=GetTickCount();
        if(alive>0){seen=1;absent=0;}
        else if(!seen){
            /* Bound an idle helper when the application never starts. A live
               WXWork process may take arbitrarily longer to create a window. */
            if((DWORD)(now-started)>=120000)return;
        }else if(alive==0){
            if(!absent){absent=1;absent_since=now;}
            else if((DWORD)(now-absent_since)>=6000)return;
        }else absent=0;
        /* Allow a short startup process handoff; a missing/hidden window alone
           must not end the watcher. Once bound, retain the main PID watch. */
        Sleep(1000);
    }
}
static BOOL __stdcall inspect(HANDLE w,long unused){
    char cls[128];DWORD pid=0;
    if(!GetClassNameA(w,cls,sizeof(cls)))return 1;
    int is_titlebar=same(cls,"TitleBarWindow"),is_shadow=same(cls,"PerryShadowWnd");
    if((!is_titlebar&&!is_shadow)||GetParent(w)!=main_window)return 1;
    if(native_frames&&is_titlebar)return 1;
    HANDLE frame=GetPropA(main_window,"__wine_x11_wm_window");
    if(is_titlebar&&frame&&frame!=GetPropA(main_window,"__wine_x11_whole_window")&&
       GetPropA(w,"__wine_x11_wm_window")==frame)return 1;
    GetWindowThreadProcessId(w,&pid);if(pid!=main_pid)return 1;
    DWORD style=GetWindowLongA(w,-16),exstyle=GetWindowLongA(w,-20);RECT before,after;
    if(is_shadow&&!(exstyle&0x00080000))return 1; /* Only layered shadows. */
    GetWindowRect(w,&before);found++;
    int needs_change=is_titlebar?(!(style&0x00080000)||(exstyle&0x08000000)):!(exstyle&0x00000020);
    if(!watch || needs_change) {text(cls);text(" hwnd=");hex((DWORD)w);text(" owner=");hex((DWORD)main_window);text(" style=");hex(style);text(" exstyle=");hex(exstyle);text("\n");}
    if(apply&&needs_change){
        /* Legacy Wine needs title-bar style changes for native management.
           The main shadow is passive in both profiles: WeWorkWindow handles
           resizing, and a transparent title-bar hit must reach that owner. */
        if(is_titlebar){
            if(!(style&0x00080000))SetWindowLongA(w,-16,style|0x00080000);
            if(exstyle&0x08000000)SetWindowLongA(w,-20,exstyle&~0x08000000);
        }
        else SetWindowLongA(w,-20,exstyle|0x00000020);
        BOOL ok=SetWindowPos(w,0,0,0,0,0,0x37); /* FRAMECHANGED,NOMOVE,NOSIZE,NOZORDER,NOACTIVATE */
        GetWindowRect(w,&after);
        text("new_style=");hex(GetWindowLongA(w,-16));text(" new_exstyle=");hex(GetWindowLongA(w,-20));text(" position_refresh=");hex(ok);
        text(" geometry_unchanged=");hex(before.left==after.left&&before.top==after.top&&before.right==after.right&&before.bottom==after.bottom);text("\n");
        if(ok&&(is_titlebar?((GetWindowLongA(w,-16)&0x00080000)&&!(GetWindowLongA(w,-20)&0x08000000)):(GetWindowLongA(w,-20)&0x00000020)))changed++;
    }
    return 1;
}
static void flush(void){DWORD written;if(pos)WriteFile(GetStdHandle((DWORD)-11),output,pos,&written,0);pos=0;}
static int read_values(char **cursor,long *values,unsigned count){
    char *s=*cursor;
    for(unsigned i=0;i<count;i++){
        int sign=1;long n=0;if(*s=='-'){sign=-1;s++;}
        if(*s<'0'||*s>'9')return 0;
        while(*s>='0'&&*s<='9'){n=n*10+(*s++-'0');if(n>1000000)return 0;}
        values[i]=n*sign;
        if(i+1<count&&*s++!=',')return 0;
    }
    *cursor=s;return 1;
}
static void read_tray_geometry(void){
    char value[2048];DWORD length=GetEnvironmentVariableA("WECOM_TRAY_GEOMETRY",value,sizeof(value));
    if(!length||length>=sizeof(value))return;
    char *s=value;long version;
    if(!read_values(&s,&version,1)||version!=2||*s++!=',')return;
    if(!read_values(&s,tray_geometry,7)||tray_geometry[6]<1||tray_geometry[6]>16)return;
    for(long i=0;i<tray_geometry[6];i++){
        if(*s++!=';'||!read_values(&s,tray_maps[i],8))return;
        if(tray_maps[i][2]<=0||tray_maps[i][3]<=0||tray_maps[i][6]<=0||tray_maps[i][7]<=0)return;
    }
    if(!*s)tray_enabled=1;
}
static int tray_layout_matches(void){
    static const int metrics[7]={76,77,78,79,0,1,80};
    for(unsigned i=0;i<7;i++)if(GetSystemMetrics(metrics[i])!=tray_geometry[i])return 0;
    return 1;
}
static int is_tray_tooltip(HANDLE w,HANDLE owner){
    char cls[128];DWORD pid=0,owner_pid=0;
    if(!owner||GetParent(w)!=owner||FindWindowA("__wine_tray_icon",0)!=owner||
       FindWindowExA(0,owner,"__wine_tray_icon",0))return 0;
    if(!GetClassNameA(w,cls,sizeof(cls))||!same(cls,"tooltips_class32"))return 0;
    if(GetWindowLongA(w,-16)&0x40)return 0; /* TTS_BALLOON: not a hover tooltip. */
    GetWindowThreadProcessId(w,&pid);GetWindowThreadProcessId(owner,&owner_pid);
    return pid&&pid==owner_pid;
}
static int is_wecom_menu(HANDLE w){
    char cls[128];DWORD pid=0;
    if(!w||!IsWindowVisible(w)||!GetClassNameA(w,cls,sizeof(cls))||!same(cls,"DuiMenuWnd"))return 0;
    GetWindowThreadProcessId(w,&pid);return pid==main_pid;
}
static int is_tray_menu_group(HANDLE w){
    /* A submenu's PerryShadowWnd can briefly become foreground on X11.
       Accept only same-process menu/shadow owner chains reaching this popup;
       main-window shadows and unrelated application menus do not qualify. */
    for(unsigned depth=0;w&&depth<16;depth++){
        char cls[128];DWORD pid=0;
        if(!IsWindowVisible(w)||!GetClassNameA(w,cls,sizeof(cls)))return 0;
        GetWindowThreadProcessId(w,&pid);if(pid!=main_pid)return 0;
        if(w==tracked_menu)return same(cls,"DuiMenuWnd")&&GetParent(w)==main_window;
        if(!same(cls,"DuiMenuWnd")&&!same(cls,"PerryShadowWnd"))return 0;
        w=GetParent(w);
    }
    return 0;
}
static void dismiss_tray_menu(const char *reason){
    HANDLE w=tracked_menu;tracked_menu=0;menu_external_since=0;
    if(pending_menu==w)pending_menu=0;
    if(pending_menu_restore==w)pending_menu_restore=0;
    if(!is_wecom_menu(w)||GetParent(w)!=main_window)return;
    /* Ask the application to close normally, including its shadow/submenus. */
    BOOL posted=PostMessageA(w,0x0010,0,0); /* WM_CLOSE */
    text("tray menu dismiss reason=");text(reason);text(" posted=");hex(posted);text("\n");flush();
}
static BOOL __stdcall menu_contains_click(HANDLE w,long unused){
    RECT r;
    if(is_wecom_menu(w)&&is_tray_menu_group(w)&&GetWindowRect(w,&r)&&menu_click.x>=r.left&&menu_click.x<r.right&&
       menu_click.y>=r.top&&menu_click.y<r.bottom){click_in_menu=1;return 0;}
    return 1;
}
static void restore_foreground_main(HANDLE w){
    /* KDE can activate the X11 window while Wine still has WS_MINIMIZE set.
       Wine then sends IconicState back before its host-state restore finishes.
       Queue the app's normal restore after that transition. Only a current
       foreground event for this prefix's visible, enabled main window counts;
       never infer activation from a timer or from another window's focus. */
    if(!main_window||w!=main_window||GetForegroundWindow()!=w||
       !IsWindowVisible(w)||!IsIconic(w)||(GetWindowLongA(w,-16)&0x08000000))return;
    BOOL posted=PostMessageA(w,0x0112,0xf120,0); /* WM_SYSCOMMAND, SC_RESTORE */
    text("taskbar foreground restore posted=");hex(posted);text("\n");flush();
}
static void __stdcall foreground_changed(HANDLE hook,DWORD event,HANDLE w,long object,long child,DWORD thread,DWORD time){
    if(object||child)return;
    restore_foreground_main(w);
    if(!tracked_menu||(long)(time-menu_opened_at)<0)return;
    if(!is_wecom_menu(tracked_menu)){tracked_menu=0;return;}
    /* Ignore delayed events and transitions within the tray/menu group. */
    if(w!=GetForegroundWindow()||w==menu_tray||is_tray_menu_group(w))return;
    dismiss_tray_menu("foreground change");
}
static void check_tray_menu_focus(void){
    if(!tracked_menu)return;
    if(!is_wecom_menu(tracked_menu)||GetParent(tracked_menu)!=main_window){
        tracked_menu=0;menu_external_since=0;return;
    }
    HANDLE foreground=GetForegroundWindow();
    if(foreground==menu_tray||is_tray_menu_group(foreground)){menu_external_since=0;return;}
    /* Wine can clear foreground on desktop/native-app activation without a
       WinEvent. Check only while this popup lives; allow a brief handoff. */
    DWORD now=GetTickCount();
    if(!menu_external_since)menu_external_since=now;
    else if((long)(now-menu_external_since)>=100)dismiss_tray_menu("foreground left");
}
static void correct_tray_popup(HANDLE w,const RECT *anchor,POINT point,int tooltip);
static void restore_tray_menu(void){
    if(!pending_menu_restore||(long)(GetTickCount()-menu_restore_due)<0)return;
    HANDLE w=pending_menu_restore;RECT r;
    if(w!=tracked_menu||!is_wecom_menu(w)||GetParent(w)!=main_window||!IsIconic(main_window)||
       (GetForegroundWindow()!=menu_tray&&GetForegroundWindow()!=w)||!GetWindowRect(w,&r)){
        pending_menu_restore=0;return;
    }
    /* SHOW may arrive before WeCom has given the menu a nonzero size. */
    if(r.right<=r.left||r.bottom<=r.top){
        if((long)(GetTickCount()-menu_restore_deadline)>=0)pending_menu_restore=0;
        else menu_restore_due=GetTickCount()+50;
        return;
    }
    pending_menu_restore=0;
    /* The earlier placement attempt may have seen the initial 0x0 window,
       or KWin may have put back its pre-minimize rectangle. Recheck now;
       the anchor guard makes this a no-op for an already corrected popup. */
    correct_tray_popup(w,&tray_rect,tray_point,0);
    if(!GetWindowRect(w,&r))return;
    /* KWin iconifies a transient of a minimized owner even though Wine keeps
       WS_MINIMIZE clear. Let our native tray helper map exactly this X11
       window. ShowWindow would restore an empty normal_rect and lose focus.
       The receiver validates age, prefix, PID, owner and host IconicState. */
    unsigned request[8]={0x57434d32,(unsigned)GetPropA(main_window,"__wine_x11_whole_window"),
                        (unsigned)GetPropA(w,"__wine_x11_whole_window"),(unsigned)GetTickCount(),
                        (unsigned)(r.left-GetSystemMetrics(76)),(unsigned)(r.top-GetSystemMetrics(77)),
                        (unsigned)(r.right-r.left),(unsigned)(r.bottom-r.top)};
    if(!request[1]||!request[2]||request[1]==request[2])return;
    HANDLE file=CreateFileA("C:\\windows\\temp\\wecom-tray-menu-request",0x40000000,7,0,2,0x80,0);
    if(file==(HANDLE)-1)return;
    DWORD written=0;BOOL sent=WriteFile(file,request,sizeof(request),&written,0);
    CloseHandle(file);
    text("tray menu native map requested=");hex(sent&&written==sizeof(request));text("\n");flush();
}
static void __stdcall popup_shown(HANDLE hook,DWORD event,HANDLE w,long object,long child,DWORD thread,DWORD time){
    char cls[128];DWORD pid=0;
    if(object||child)return;
    GetWindowThreadProcessId(w,&pid);
    if(!GetClassNameA(w,cls,sizeof(cls)))return;
    if(same(cls,"tooltips_class32")){
        HANDLE owner=GetParent(w);RECT r;POINT p;
        if(!tray_enabled||!is_tray_tooltip(w,owner)||!GetWindowRect(owner,&r)||!GetCursorPos(&p))return;
        if(p.x<r.left||p.x>=r.right||p.y<r.top||p.y>=r.bottom)return;
        tooltip_owner=owner;tooltip_rect=r;tooltip_point=p;
        pending_tooltip=w;tooltip_due=GetTickCount()+50;
        return;
    }
    if(pid!=main_pid||GetParent(w)!=main_window||!same(cls,"DuiMenuWnd"))return;
    HANDLE foreground=GetForegroundWindow();
    if(!GetClassNameA(foreground,cls,sizeof(cls)))return;
    if(!same(cls,"__wine_tray_icon")||!GetWindowRect(foreground,&tray_rect))return;
    if(!GetCursorPos(&tray_point)||tray_point.x<tray_rect.left||tray_point.x>=tray_rect.right||
       tray_point.y<tray_rect.top||tray_point.y>=tray_rect.bottom)return;
    tracked_menu=w;menu_tray=foreground;menu_opened_at=time;menu_external_since=0;
    pending_menu=w;menu_due=GetTickCount()+50;
    if(IsIconic(main_window)){
        pending_menu_restore=w;menu_restore_due=GetTickCount()+100;
        menu_restore_deadline=GetTickCount()+1000;
    }
}
static void correct_tray_popup(HANDLE w,const RECT *anchor,POINT point,int tooltip){
    if(!tray_enabled||!IsWindowVisible(w)||!tray_layout_matches())return;
    RECT r;MONITORINFO m;m.size=sizeof(m);
    if(!GetWindowRect(w,&r))return;
    long width=r.right-r.left,height=r.bottom-r.top;
    if(width<=0||height<=0||width>600||height>600)return;
    /* Only a tray popup close to its icon. Normal context
       menus and submenus do not satisfy this anchor. A tooltip can extend
       to the left of its icon when Wine clamps it to a screen edge. */
    if(r.left<anchor->left-(tooltip?width+32:32)||r.left>anchor->right+32||
       r.top<anchor->top-600||r.top>anchor->bottom+32)return;
    long *mapping=0;
    for(long i=0;i<tray_geometry[6];i++){
        long *v=tray_maps[i];
        if(point.x<v[0]||point.x>=v[0]+v[2]||point.y<v[1]||point.y>=v[1]+v[3])continue;
        if(mapping)return; /* Ambiguous source rectangles: do not guess a screen. */
        mapping=v;
    }
    if(!mapping)return;
    POINT target={mapping[4]+MulDiv(point.x-mapping[0],mapping[6],mapping[2]),
                  mapping[5]+MulDiv(point.y-mapping[1],mapping[7],mapping[3])};
    if(!GetMonitorInfoA(MonitorFromPoint(target,0),&m))return;
    long dx=target.x-point.x,dy=target.y-point.y;
    if(!dx&&!dy)return;
    long x=r.left+dx,y=r.top+dy;
    if(width>m.work.right-m.work.left||height>m.work.bottom-m.work.top)return;
    if(x<m.work.left)x=m.work.left;if(y<m.work.top)y=m.work.top;
    if(x+width>m.work.right)x=m.work.right-width;if(y+height>m.work.bottom)y=m.work.bottom-height;
    if(SetWindowPos(w,0,x,y,0,0,0x15)){ /* NOSIZE,NOZORDER,NOACTIVATE */
        text(tooltip?"tray tooltip coordinate correction dx=":"tray menu coordinate correction dx=");hex(x-r.left);
        text(" dy=");hex(y-r.top);text("\n");flush();
    }
}
static void correct_pending_popups(void){
    if(pending_menu&&(long)(GetTickCount()-menu_due)>=0){
        HANDLE w=pending_menu;pending_menu=0;
        if(GetParent(w)==main_window)correct_tray_popup(w,&tray_rect,tray_point,0);
    }
    if(pending_tooltip&&(long)(GetTickCount()-tooltip_due)>=0){
        HANDLE w=pending_tooltip;pending_tooltip=0;RECT current;
        /* A click may relocate the tray between SHOW delivery and this pass. */
        if(!is_tray_tooltip(w,tooltip_owner)||!GetWindowRect(tooltip_owner,&current))return;
        if(current.left!=tooltip_rect.left||current.top!=tooltip_rect.top||
           current.right!=tooltip_rect.right||current.bottom!=tooltip_rect.bottom)return;
        correct_tray_popup(w,&tooltip_rect,tooltip_point,1);
    }
}
static int is_context_menu(HANDLE w){
    if(!is_wecom_menu(w)||!(GetWindowLongA(w,-20)&0x08000000)||
       (GetWindowLongA(w,-16)&0x08000000)||is_tray_menu_group(w))return 0;
    /* Only in-app no-activate menus rooted at this WeCom main window. */
    for(unsigned depth=0;depth<16;depth++){
        w=GetParent(w);
        if(w==main_window)return 1;
        if(!is_wecom_menu(w))return 0;
    }
    return 0;
}
static int forward_context_click(unsigned message,POINT point){
    HANDLE w;
    if(message==0x0201){
        pressed_context_menu=0;
        if(GetForegroundWindow()!=main_window)return 0;
        w=WindowFromPoint(point);
    }else if(message==0x0202){
        w=pressed_context_menu;pressed_context_menu=0;
        if(!w)return 0;
        /* A menu command can close the popup on button-down. Consume its
           paired release so it cannot click through into a new dialog. */
        if(!is_context_menu(w))return 1;
    }else return 0;
    if(!is_context_menu(w)||!ScreenToClient(w,&point))return message==0x0202;
    unsigned keys=(message==0x0201?1:0)|(GetAsyncKeyState(16)<0?4:0)|(GetAsyncKeyState(17)<0?8:0);
    /* Under Wine/KWin, a hardware press activates DuiMenuWnd and dismisses
       it before the command runs, despite WS_EX_NOACTIVATE. Direct client
       messages preserve the original control's action without activation. */
    if(PostMessageA(w,message,keys,((unsigned)point.y<<16)|((unsigned)point.x&0xffff))){
        if(message==0x0201)pressed_context_menu=w;
        return 1;
    }
    return message==0x0202;
}
static long __stdcall tray_mouse(int code,unsigned message,long data){
    if(code>=0&&data&&tracked_menu&&
       (message==0x0201||message==0x0204||message==0x0207||message==0x020b)){
        /* Wine clicks outside the popup need not change the foreground.
           Native Wayland applications are covered by the foreground hook. */
        menu_click=*(POINT *)data;click_in_menu=0;
        EnumWindows(menu_contains_click,0);
        if(!click_in_menu)dismiss_tray_menu("outside click");
    }
    if(!native_frames&&code>=0&&data&&forward_context_click(message,*(POINT *)data))return 1;
    /* WH_MOUSE_LL runs in this watcher. Only an actual left-button release
       over this prefix's unique Wine tray icon may request activation. */
    if(code>=0&&message==0x0202&&data){
        POINT point=*(POINT *)data;HANDLE w=WindowFromPoint(point);char cls[128];
        if(w&&GetClassNameA(w,cls,sizeof(cls))&&same(cls,"__wine_tray_icon")&&
           FindWindowA("__wine_tray_icon",0)==w&&!FindWindowExA(0,w,"__wine_tray_icon",0)){
            pending_activation=w;activation_due=GetTickCount()+100;
        }
    }
    return CallNextHookEx(0,code,message,data);
}
static void activate_after_tray_click(void){
    if(!pending_activation||(long)(GetTickCount()-activation_due)<0)return;
    HANDLE tray=pending_activation;pending_activation=0;
    /* Let WeCom perform its own restore/hide operation first. Do not undo a
       minimize, activate after a right click, or steal focus after it moved. */
    if(GetForegroundWindow()!=tray||!IsWindowVisible(main_window)||IsIconic(main_window))return;
    char cls[128];
    if(!GetClassNameA(tray,cls,sizeof(cls))||!same(cls,"__wine_tray_icon"))return;
    DWORD own=GetCurrentThreadId(),other=GetWindowThreadProcessId(tray,0);
    if(!other||own==other)return;
    /* Explorer owns the foreground input queue during a tray click. WeCom's
       asynchronous callback alone does not grant foreground permission. */
    BOOL attached=AttachThreadInput(own,other,1);
    BOOL activated=attached&&SetForegroundWindow(main_window);
    if(attached)AttachThreadInput(own,other,0);
    text("tray left-click activation attached=");hex(attached);
    text(" activated=");hex(activated);text("\n");flush();
}
void mainCRTStartup(void){
    char frame_profile[2];
    native_frames=GetEnvironmentVariableA("WINE_X11_OWNED_FRAME",frame_profile,sizeof(frame_profile))==1&&frame_profile[0]=='1';
    char *s=GetCommandLineA();
    while(*s){
        if(s[0]=='-'&&s[1]=='a'&&s[2]=='p'&&s[3]=='p'&&s[4]=='l'&&s[5]=='y')apply=1;
        if(s[0]=='-'&&s[1]=='w'&&s[2]=='a'&&s[3]=='t'&&s[4]=='c'&&s[5]=='h'){apply=1;watch=1;}
        s++;
    }
    HANDLE mutex=0,process=0,event_hook=0,foreground_hook=0,mouse_hook=0;
    if(watch){
        mutex=CreateMutexA(0,0,"Local\\WeComTitleBarManaged");
        if(!mutex||GetLastError()==183)ExitProcess(0);
        wait_for_main_window();
    }else main_window=FindWindowA("WeWorkWindow",0);
    if(!main_window){text("WeCom main window not found\n");flush();ExitProcess(1);}
    GetWindowThreadProcessId(main_window,&main_pid);
    if(watch){
        process=OpenProcess(0x00100000,0,main_pid);
        if(!process){text("Cannot watch WeCom process\n");flush();ExitProcess(1);}
        read_tray_geometry();
        mouse_hook=SetWindowsHookExA(14,tray_mouse,GetModuleHandleA(0),0);
        text("tray activation hook installed=");hex(mouse_hook!=0);text("\n");flush();
        /* Menus belong to WeCom; hover tooltips belong to Wine Explorer.
           Filter both by class and owner in the current Wine desktop. */
        event_hook=SetWinEventHook(0x8002,0x8002,0,popup_shown,0,0,0);
        foreground_hook=SetWinEventHook(3,3,0,foreground_changed,0,0,0);
        text("tray popup hook installed=");hex(event_hook!=0);
        text(" dismiss hook installed=");hex(foreground_hook!=0);text("\n");flush();
    }
    do{
        if(watch){
            HANDLE candidate=FindWindowA("WeWorkWindow",0);DWORD candidate_pid=0;
            if(candidate)GetWindowThreadProcessId(candidate,&candidate_pid);
            if(candidate_pid==main_pid)main_window=candidate;
        }
        /* Native grouping needs no title-bar rewrite; retain the passive shadow role. */
        found=0;changed=0;EnumWindows(inspect,0);
        if(!watch){text("matched=");hex(found);text(" changed=");hex(changed);text("\n");}
        flush();
        if(!watch)break;
        DWORD next_scan=GetTickCount()+1000;
        do{
            DWORD result=MsgWaitForMultipleObjects(1,&process,0,(pending_menu||pending_menu_restore||pending_tooltip||pending_activation||tracked_menu)?50:1000,0x04ff);
            if(result==0||result==0xffffffff)goto done;
            MSG message;
            while(PeekMessageA(&message,0,0,0,1)){TranslateMessage(&message);DispatchMessageA(&message);}
            correct_pending_popups();
            restore_tray_menu();
            activate_after_tray_click();
            check_tray_menu_focus();
        }while((long)(GetTickCount()-next_scan)<0);
    }while(WaitForSingleObject(process,0)==258);
done:
    if(mouse_hook)UnhookWindowsHookEx(mouse_hook);
    if(foreground_hook)UnhookWinEvent(foreground_hook);
    if(event_hook)UnhookWinEvent(event_hook);
    if(process)CloseHandle(process);
    if(mutex)CloseHandle(mutex);
    ExitProcess(watch||found?0:1);
}
