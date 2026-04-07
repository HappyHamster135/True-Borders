import eel
import win32gui
import win32con
import win32ui
import win32api
from screeninfo import get_monitors
import ctypes
import json
import os
import base64
import io
from PIL import Image, ImageWin
import threading
import time
from ctypes import wintypes
import pystray
from PIL import Image, ImageDraw
from io import BytesIO
import winreg
import keyboard
import sys
import win32process
import subprocess
import tkinter as tk
from tkinter import filedialog
import urllib.request

# ==============================================================================================
# 1. GLOBALA VARIABLER & INITIALISERING
# ==============================================================================================

# Sätt din nuvarande version här
CURRENT_VERSION = "1.0.5" 
# URL till en JSON-fil som du lägger på t.ex. GitHub (Raw länk)
UPDATE_INFO_URL = "https://raw.githubusercontent.com/HappyHamster135/True-Borders/main/update.json"

tray_icon_instance = None
active_taskbar_game = None
taskbar_is_hidden = False
original_taskbar_autohide = False
hotkey_enabled = False
current_hotkey = 'ctrl+shift+b'

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except:
    ctypes.windll.user32.SetProcessDPIAware()

eel.init('web')

GWL_STYLE = -16
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_SYSMENU = 0x00080000
SWP_FRAMECHANGED = 0x0020
SWP_NOZORDER = 0x0004
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002

APP_DATA_DIR = os.path.join(os.environ['APPDATA'], "TrueBorders")
if not os.path.exists(APP_DATA_DIR):
    os.makedirs(APP_DATA_DIR)

PROFILES_FILE = os.path.join(APP_DATA_DIR, "profiles.json")
SETTINGS_FILE = os.path.join(APP_DATA_DIR, "settings.json")
REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "True Borders"

def get_setting(key, default_val):
    if not os.path.exists(SETTINGS_FILE): 
        return default_val
    try:
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f).get(key, default_val)
    except: 
        return default_val
    
# Radera if/else-blocket och skriv bara detta:
start_minimized = get_setting("start_minimized", False)

@eel.expose
def get_current_version():
    return CURRENT_VERSION
# ==============================================================================================
# 2. PROFILHANTERING OCH AUTO-LAUNCHER
# ==============================================================================================

@eel.expose
def save_profile(game_name, data):
    profiles = get_all_profiles()
    if game_name not in profiles:
        profiles[game_name] = {}
        
    icon_b64 = get_window_icon_base64(game_name)
    if icon_b64:
        data['icon'] = icon_b64 
        
    # Auto-learn Exe Path (försök hämta från processen)
    hwnd = find_real_game_window(game_name)
    if hwnd != 0:
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            h_process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if h_process:
                exe_buffer = ctypes.create_unicode_buffer(260)
                size = ctypes.wintypes.DWORD(260)
                if ctypes.windll.kernel32.QueryFullProcessImageNameW(h_process, 0, exe_buffer, ctypes.byref(size)):
                    data['exePath'] = exe_buffer.value
                ctypes.windll.kernel32.CloseHandle(h_process)
        except Exception as e:
            pass

    profiles[game_name].update(data) 
    
    with open(PROFILES_FILE, "w") as f:
        json.dump(profiles, f, indent=4)
    return True

@eel.expose
def get_profile(game_name):
    profiles = get_all_profiles()
    return profiles.get(game_name)

@eel.expose
def get_all_profiles():
    if os.path.exists(PROFILES_FILE):
        with open(PROFILES_FILE, "r") as f:
            return json.load(f)
    return {}

@eel.expose
def delete_profile(game_name):
    profiles = get_all_profiles()
    if game_name in profiles:
        del profiles[game_name]
        with open(PROFILES_FILE, 'w', encoding='utf-8') as f:
            json.dump(profiles, f, indent=4)
        return True
    return False

@eel.expose
def import_profiles_data(new_data):
    try:
        if isinstance(new_data, dict):
            with open(PROFILES_FILE, "w", encoding="utf-8") as f:
                json.dump(new_data, f, indent=4)
            return True
        return False
    except:
        return False

@eel.expose
def reorder_profiles(new_order_list):
    old_profiles = get_all_profiles()
    ordered_profiles = {}
    for name in new_order_list:
        if name in old_profiles:
            ordered_profiles[name] = old_profiles[name]
    for name, data in old_profiles.items():
        if name not in ordered_profiles:
            ordered_profiles[name] = data
    with open(PROFILES_FILE, "w") as f:
        json.dump(ordered_profiles, f, indent=4)

@eel.expose
def launch_game(game_name):
    profile = get_profile(game_name)
    if not profile or 'exePath' not in profile:
        return False
        
    exe_path = profile['exePath']
    if os.path.exists(exe_path):
        try:
            working_dir = os.path.dirname(exe_path)
            subprocess.Popen([exe_path], cwd=working_dir)
            return True
        except:
            return False
    return False

@eel.expose
def browse_exe():
    root = tk.Tk()
    root.attributes('-topmost', True) 
    root.withdraw() 
    file_path = filedialog.askopenfilename(
        title="Select Game Executable",
        filetypes=[("Executables", "*.exe"), ("All Files", "*.*")]
    )
    root.destroy()
    return file_path

@eel.expose
def update_exe_path(game_name, new_path):
    profiles = get_all_profiles()
    if game_name in profiles:
        profiles[game_name]['exePath'] = new_path
        with open(PROFILES_FILE, 'w') as f:
            json.dump(profiles, f, indent=4)
        return True
    return False

# ==============================================================================================
# 3. KÄRNFUNKTIONER FÖR BORDERLESS (Smart Search)
# ==============================================================================================

def find_real_game_window(search_title):
    """Hittar fönstret med fuzzy matchning, ignorerar skräp och tar det största fönstret (Perfekt för The Alters/Emulatorer)"""
    found_hwnds = []
    
    def callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd).strip()
            if search_title.lower() in title.lower():
                rect = win32gui.GetWindowRect(hwnd)
                w = rect[2] - rect[0]
                h = rect[3] - rect[1]
                if w > 100 and h > 100:
                    found_hwnds.append((hwnd, w * h))
        return True # MÅSTE finnas för att loopen ska fortsätta!
        
    win32gui.EnumWindows(callback, None)
    
    if not found_hwnds:
        return 0
        
    found_hwnds.sort(key=lambda x: x[1], reverse=True)
    return found_hwnds[0][0]

@eel.expose
def is_game_running(title):
    return find_real_game_window(title) != 0



@eel.expose
def get_actual_window_pos(window_title):
    """Läser av spelets FAKTISKA position på skärmen just nu."""
    hwnd = find_real_game_window(window_title)
    if hwnd == 0:
        return None
        
    rect = win32gui.GetWindowRect(hwnd)
    client_rect = win32gui.GetClientRect(hwnd) # Hämtar spelets sanna upplösning
    
    return {
        "x": rect[0],
        "y": rect[1],
        "w": client_rect[2], # Använder client_rect för exakt bredd (t.ex. 2560)
        "h": client_rect[3]  # Använder client_rect för exakt höjd (t.ex. 1440)
    }

@eel.expose
def is_borderless(window_title):
    global active_taskbar_game
    # Om VI hanterar det just nu är det borderless i vår värld
    if active_taskbar_game and active_taskbar_game.get('name') == window_title:
        return True
        
    hwnd = find_real_game_window(window_title)
    if hwnd != 0:
        style = win32gui.GetWindowLong(hwnd, GWL_STYLE)
        # Om WS_CAPTION saknas returnerar vi True
        return not (style & WS_CAPTION)
    return False

def get_window_offsets(hwnd):
    """Räknar ut exakt hur tjock den vita baren och sidokanterna är."""
    try:
        rect = win32gui.GetWindowRect(hwnd)
        client_rect = win32gui.GetClientRect(hwnd)
        
        win_w = rect[2] - rect[0]
        win_h = rect[3] - rect[1]
        
        # Client rect börjar alltid på 0,0 så vi tar bara bredd och höjd
        client_w = client_rect[2] 
        client_h = client_rect[3] 
        
        # Sidokanten (oftast 8 pixlar)
        border_x = (win_w - client_w) // 2
        
        # Vita baren i toppen (oftast runt 31 pixlar)
        border_top = (win_h - client_h) - border_x
        
        return max(0, border_x), max(0, border_top)
    except Exception:
        return 0, 0
    
@eel.expose
def init_borderless(window_title, ui_x=None, ui_y=None, ui_w=None, ui_h=None):
    hwnd = find_real_game_window(window_title)
    if hwnd == 0:
        return False
        
    profile = get_profile(window_title)
    rect = win32gui.GetWindowRect(hwnd)
    client_rect = win32gui.GetClientRect(hwnd) 
    
    style = win32gui.GetWindowLong(hwnd, GWL_STYLE)
    
    # --- DEN ULTIMATA LOGIKEN FÖR POSITION ---
    # 1. Om Visual Map skickar in koordinater (När du trycker Apply på ett nytt spel)
    if ui_x is not None:
        target_x, target_y = ui_x, ui_y
        target_w, target_h = ui_w, ui_h
    # 2. Om spelet redan har en profil (Auto-apply i bakgrunden)
    elif profile:
        target_x = profile.get('realX', 0)
        target_y = profile.get('realY', 0)
        target_w = profile.get('resW', client_rect[2])
        target_h = profile.get('resH', client_rect[3])
    # 3. Fallback om något går snett (Använder ClientToScreen för att slippa -8px buggen)
    else:
        try:
            pt = win32gui.ClientToScreen(hwnd, (0, 0))
            target_x, target_y = pt[0], pt[1]
        except:
            target_x, target_y = rect[0], rect[1]
        target_w, target_h = client_rect[2], client_rect[3]

    # --- APPLICERA ---
    if style & win32con.WS_CAPTION:
        new_style = style & ~(win32con.WS_CAPTION | win32con.WS_THICKFRAME | win32con.WS_MINIMIZEBOX | win32con.WS_MAXIMIZEBOX | win32con.WS_SYSMENU)
        win32gui.SetWindowLong(hwnd, GWL_STYLE, new_style)
        
        win32gui.SetWindowPos(hwnd, 0, 0, 0, 0, 0, win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOZORDER | win32con.SWP_FRAMECHANGED)
        time.sleep(0.05) 
        
        flags = win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE
        win32gui.SetWindowPos(hwnd, 0, int(target_x), int(target_y), int(target_w), int(target_h), flags)
    else:
        flags = win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE
        win32gui.SetWindowPos(hwnd, 0, int(target_x), int(target_y), int(target_w), int(target_h), flags)

    # --- AUTO LEARN EXE ---
    global active_taskbar_game
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        h_process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if h_process:
            exe_buffer = ctypes.create_unicode_buffer(260)
            size = ctypes.wintypes.DWORD(260)
            if ctypes.windll.kernel32.QueryFullProcessImageNameW(h_process, 0, exe_buffer, ctypes.byref(size)):
                exe_path = exe_buffer.value
                if profile and not profile.get('exePath'):
                    profile['exePath'] = exe_path
                    profiles = get_all_profiles()
                    profiles[window_title] = profile
                    with open(PROFILES_FILE, 'w') as f:
                        json.dump(profiles, f, indent=4)
            ctypes.windll.kernel32.CloseHandle(h_process)
    except Exception as e:
        pass

    if profile:
        active_taskbar_game = {
            'name': window_title, 
            'hide': profile.get('hideTaskbar', False), 
            'disable': profile.get('disableTaskbar', False),
            'realX': int(target_x),
            'realY': int(target_y),
            'resW': int(target_w),
            'resH': int(target_h)
        }
    else:
        active_taskbar_game = {'name': window_title, 'hide': False, 'disable': False}
            
    return True

@eel.expose
def restore_borders(window_title):
    global active_taskbar_game
    if active_taskbar_game and active_taskbar_game.get('name') == window_title:
        active_taskbar_game = None
        
    hwnd = find_real_game_window(window_title)
    if hwnd == 0:
        return False
        
    style = win32gui.GetWindowLong(hwnd, GWL_STYLE)
    
    rect = win32gui.GetWindowRect(hwnd)
    curr_x = rect[0]
    curr_y = rect[1]
    curr_w = rect[2] - rect[0]
    curr_h = rect[3] - rect[1]

    # --- FIXEN FÖR KRYMPANDE FÖNSTER ---
    # Om fönstret just nu SAKNAR list, kommer Windows stjäla plats från spelytan 
    # när listen läggs tillbaka. Vi måste göra ramen större för att kompensera!
    if not (style & win32con.WS_CAPTION):
        curr_w += 16  # 8px på varje sida
        curr_h += 39  # 31px top + 8px botten
        curr_x -= 8   # Dra fönstret lite åt vänster så det förblir centrerat
        curr_y -= 31
    # -----------------------------------

    # 1. Lägg tillbaka standard-stilarna (den vita baren och kanterna)
    new_style = style | (win32con.WS_CAPTION | win32con.WS_THICKFRAME | win32con.WS_MINIMIZEBOX | win32con.WS_MAXIMIZEBOX | win32con.WS_SYSMENU)
    win32gui.SetWindowLong(hwnd, GWL_STYLE, new_style)
    win32gui.SetWindowLong(hwnd, -20, 0x00040000) 
    
    # 2. SÄKERHETSKOLL: Om fönstret är gömt ovanför skärmen
    if curr_y < 0:
        curr_y = 50
    if curr_x < 0:
        curr_x = 50
        
    # 3. Tvinga fönstret att uppdatera sig
    flags = win32con.SWP_FRAMECHANGED | win32con.SWP_NOZORDER
    win32gui.SetWindowPos(hwnd, 0, curr_x, curr_y, curr_w, curr_h, flags)
        
    return True

@eel.expose
def toggle_borderless(window_title):
    hwnd = find_real_game_window(window_title)
    if hwnd == 0:
        return "not_found"

    style = win32gui.GetWindowLong(hwnd, GWL_STYLE)
    if style & WS_CAPTION:
        init_borderless(window_title)
        return "borderless"
    else:
        restore_borders(window_title)
        return "restored"

@eel.expose
def update_window_pos(window_title, x, y, w, h):
    if x is None or y is None: return 
    
    hwnd = find_real_game_window(window_title)
    if hwnd != 0:
        # Bara flytta mjukt - inga overscan-beräkningar
        flags = 0x0004 | 0x0010 | 0x4000
        win32gui.SetWindowPos(hwnd, 0, int(x), int(y), int(w), int(h), flags)

        global active_taskbar_game
        if active_taskbar_game and active_taskbar_game.get('name') == window_title:
            active_taskbar_game['realX'] = int(x)
            active_taskbar_game['realY'] = int(y)
            active_taskbar_game['resW'] = int(w)
            active_taskbar_game['resH'] = int(h)

def force_reapply_borderless(hwnd, x, y, w, h):
    style = win32gui.GetWindowLong(hwnd, GWL_STYLE)
    if not (style & WS_CAPTION):
        flags = SWP_NOZORDER | win32con.SWP_NOACTIVATE
        win32gui.SetWindowPos(hwnd, 0, int(x), int(y), int(w), int(h), flags)
    else:
        new_style = style & ~(WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU | 0x00800000)
        win32gui.SetWindowLong(hwnd, GWL_STYLE, new_style)
        win32gui.SetWindowLong(hwnd, -20, 0) 
        # Lade in SWP_NOZORDER (0x0004) så den INTE tvingar spelet till Always on Top!
        flags = SWP_FRAMECHANGED | 0x0004 | 0x0400 | 0x0040 
        win32gui.SetWindowPos(hwnd, 0, int(x), int(y), int(w), int(h) + 10, flags)
        win32gui.SetWindowPos(hwnd, 0, int(x), int(y), int(w), int(h), flags)

@eel.expose
def force_window_refresh(window_title, x, y, w, h):
    if any(v is None for v in [x, y, w, h]): return 
    hwnd = find_real_game_window(window_title)
    if not hwnd: return
    SWP_FLAGS = win32con.SWP_FRAMECHANGED | win32con.SWP_NOACTIVATE
    win32gui.SetWindowPos(hwnd, 0, int(x), int(y), int(w) + 1, int(h) + 1, SWP_FLAGS)
    win32gui.SetWindowPos(hwnd, 0, int(x), int(y), int(w), int(h), SWP_FLAGS)
    win32gui.SetWindowPos(hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0, SWP_FLAGS | win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
    win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, SWP_FLAGS | win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
    win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, int(x), int(y), int(w), int(h), win32con.SWP_FRAMECHANGED | win32con.SWP_SHOWWINDOW)

# ==============================================================================================
# 4. FÖNSTER & SKÄRM-AVLÄSNING (Listor, Ikoner)
# ==============================================================================================

@eel.expose
def get_monitor_layout():
    monitors = []
    for m in get_monitors():
        monitors.append({
            "name": m.name, "x": m.x, "y": m.y,
            "width": m.width, "height": m.height, "is_primary": m.is_primary
        })
    return monitors

@eel.expose
def get_open_windows():
    titles = []
    exact_ignore = ["Program Manager", "Settings", "Microsoft Text Input Application", "Windows Input Experience", "True Borders", "Task Manager", "Aktivitetshanteraren"]
    substring_ignore = ["Overlay", "Default IME", " - Opera", " - Google Chrome", " - Mozilla Firefox", " - Microsoft Edge", " - Brave", " - Vivaldi"]

    def enum_windows_proc(hwnd, lParam):
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowTextLength(hwnd) > 0:
            title = win32gui.GetWindowText(hwnd).strip()
            if not title or title in exact_ignore or any(sub in title for sub in substring_ignore):
                return True
            if title not in titles:
                titles.append(title)
        return True
        
    win32gui.EnumWindows(enum_windows_proc, 0)
    return sorted(titles)

@eel.expose
def get_windows_with_icons():
    windows_data = []
    titles_seen = []
    exact_ignore = ["Program Manager", "Settings", "Microsoft Text Input Application", "Windows Input Experience", "True Borders", "Task Manager", "Aktivitetshanteraren"]
    substring_ignore = ["Overlay", "Default IME", " - Opera", " - Google Chrome", " - Mozilla Firefox", " - Microsoft Edge", " - Brave", " - Vivaldi"]

    def enum_windows_proc(hwnd, lParam):
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowTextLength(hwnd) > 0:
            title = win32gui.GetWindowText(hwnd).strip()
            if not title or title in exact_ignore or any(sub in title for sub in substring_ignore):
                return True
            
            if title not in titles_seen:
                titles_seen.append(title)
                icon_b64 = get_icon_base64(hwnd) 
                windows_data.append({"title": title, "icon": icon_b64})
        return True
        
    win32gui.EnumWindows(enum_windows_proc, 0)
    return sorted(windows_data, key=lambda k: k['title'].lower())

@eel.expose
def get_window_icon_base64(window_title):
    hwnd = find_real_game_window(window_title)
    if hwnd == 0: return None
    return get_icon_base64(hwnd)
    
def get_icon_base64(hwnd):
    try:
        hicon = win32gui.SendMessage(hwnd, win32con.WM_GETICON, win32con.ICON_BIG, 0)
        if hicon == 0:
            hicon = win32gui.SendMessage(hwnd, win32con.WM_GETICON, win32con.ICON_SMALL, 0)
        if hicon == 0:
            hicon = win32gui.GetClassLong(hwnd, win32con.GCL_HICON)
        if hicon == 0:
            return None

        hdc = win32ui.CreateDCFromHandle(win32gui.GetDC(0))
        hbmp = win32ui.CreateBitmap()
        hbmp.CreateCompatibleBitmap(hdc, 32, 32)
        hdc = hdc.CreateCompatibleDC()
        hdc.SelectObject(hbmp)
        
        win32gui.DrawIconEx(hdc.GetHandleOutput(), 0, 0, hicon, 32, 32, 0, None, win32con.DI_NORMAL)

        bmpinfo = hbmp.GetInfo()
        bmpstr = hbmp.GetBitmapBits(True)
        img = Image.frombuffer('RGBA', (bmpinfo['bmWidth'], bmpinfo['bmHeight']), bmpstr, 'raw', 'BGRA', 0, 1)

        try: win32gui.DestroyIcon(hicon)
        except: pass 
            
        try:
            hdc.DeleteDC()
            win32gui.DeleteObject(hbmp.GetHandle())
        except: pass

        buffered = BytesIO()
        img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode()
        return f"data:image/png;base64,{img_str}"
    except Exception:
        return None

# ==============================================================================================
# 5. TASKBAR, HOTKEYS & OPTIMIZATIONS
# ==============================================================================================

class APPBARDATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uCallbackMessage", wintypes.UINT),
        ("uEdge", wintypes.UINT),
        ("rc", wintypes.RECT),
        ("lParam", wintypes.LPARAM),
    ]

def get_taskbar_autohide_state():
    ABM_GETSTATE = 0x00000004
    ABS_AUTOHIDE = 0x00000001
    abd = APPBARDATA()
    abd.cbSize = ctypes.sizeof(APPBARDATA)
    state = ctypes.windll.shell32.SHAppBarMessage(ABM_GETSTATE, ctypes.byref(abd))
    return (state & ABS_AUTOHIDE) != 0

@eel.expose
def toggle_start_minimized(enabled):
    settings = {}
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                settings = json.load(f)
        except: 
            pass
    settings["start_minimized"] = enabled
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=4)
    return True

@eel.expose
def is_start_minimized():
    # Returnerar True som standard ifall de inte har ändrat inställningen ännu
    return get_setting("start_minimized", True)

def set_taskbar_autohide(enable):
    ABM_SETSTATE = 0x0000000a
    ABS_AUTOHIDE = 0x00000001
    ABS_ALWAYSONTOP = 0x00000002
    abd = APPBARDATA()
    abd.cbSize = ctypes.sizeof(APPBARDATA)
    abd.hWnd = win32gui.FindWindow("Shell_TrayWnd", None)
    abd.lParam = ABS_AUTOHIDE if enable else ABS_ALWAYSONTOP
    ctypes.windll.shell32.SHAppBarMessage(ABM_SETSTATE, ctypes.byref(abd))

def set_taskbars_state(hide_mode, disable_mode):
    user32 = ctypes.windll.user32
    if disable_mode:
        set_taskbar_autohide(True)
        def enum_handler_disable(hwnd, lParam):
            if win32gui.GetClassName(hwnd) in ["Shell_TrayWnd", "Shell_SecondaryTrayWnd"]:
                user32.ShowWindow(hwnd, 0) 
                user32.EnableWindow(hwnd, False)
            return True
        win32gui.EnumWindows(enum_handler_disable, 0)
        return
    if hide_mode:
        set_taskbar_autohide(True)
        def enum_handler_soft(hwnd, lParam):
            if win32gui.GetClassName(hwnd) in ["Shell_TrayWnd", "Shell_SecondaryTrayWnd"]:
                user32.ShowWindow(hwnd, 5) 
                user32.EnableWindow(hwnd, True)
            return True
        win32gui.EnumWindows(enum_handler_soft, 0)
    else:
        set_taskbar_autohide(False)
        def enum_handler_show(hwnd, lParam):
            if win32gui.GetClassName(hwnd) in ["Shell_TrayWnd", "Shell_SecondaryTrayWnd"]:
                user32.ShowWindow(hwnd, 5)
                user32.EnableWindow(hwnd, True)
            return True
        win32gui.EnumWindows(enum_handler_show, 0)

@eel.expose
def update_advanced_settings(window_title, hide, disable, on_top, border_fix):
    profiles = get_all_profiles()
    if window_title in profiles:
        profiles[window_title]['hideTaskbar'] = hide
        profiles[window_title]['disableTaskbar'] = disable
        profiles[window_title]['alwaysOnTop'] = on_top
        profiles[window_title]['borderFix'] = border_fix 
        with open(PROFILES_FILE, 'w') as f:
            json.dump(profiles, f, indent=4)
            
    set_game_topmost(window_title, on_top)
    if border_fix:
        p = profiles.get(window_title)
        force_window_refresh(window_title, p['realX'], p['realY'], p['resW'], p['resH'])

@eel.expose
def update_taskbar_setting(game_name, hide_val, disable_val):
    profiles = get_all_profiles()
    if game_name in profiles:
        profiles[game_name]['hideTaskbar'] = hide_val
        profiles[game_name]['disableTaskbar'] = disable_val
        with open(PROFILES_FILE, "w") as f:
            json.dump(profiles, f, indent=4)
        global active_taskbar_game
        if active_taskbar_game and active_taskbar_game['name'] == game_name:
            active_taskbar_game['hide'] = hide_val
            active_taskbar_game['disable'] = disable_val
        return True
    return False

@eel.expose
def is_admin():
    try: return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except: return False

@eel.expose
def set_app_on_top():
    hwnd = win32gui.FindWindow(None, "True Borders")
    if hwnd != 0: win32gui.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 3)

@eel.expose
def set_game_topmost(window_title, is_topmost):
    hwnd = find_real_game_window(window_title)
    if hwnd != 0:
        z_order = -1 if is_topmost else -2 
        win32gui.SetWindowPos(hwnd, z_order, 0, 0, 0, 0, 3)

@eel.expose
def toggle_windows_optimizations(enable=True):
    reg_path = r"Software\Microsoft\DirectX\UserGpuPreferences"
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path, 0, winreg.KEY_ALL_ACCESS)
        try: current_value, _ = winreg.QueryValueEx(key, "DirectXUserGlobalSettings")
        except: current_value = ""

        settings = {}
        if current_value:
            for part in str(current_value).strip(";").split(";"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    settings[k] = v 

        settings["SwapEffectUpgradeEnable"] = "1" if enable else "0"
        new_value = ";".join([f"{k}={v}" for k, v in settings.items()]) + ";"
        
        win32gui.SetValueEx(key, "DirectXUserGlobalSettings", 0, winreg.REG_SZ, new_value)
        win32gui.CloseKey(key)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

@eel.expose
def toggle_autostart(enabled):
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_SET_VALUE)
        if enabled:
            app_path = sys.executable if getattr(sys, 'frozen', False) else os.path.abspath(sys.argv[0])
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{app_path}" --autostart')
        else:
            try: winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError: pass
        winreg.CloseKey(key)
        return True
    except Exception:
        return False

@eel.expose
def check_latency_boost_status():
    is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
    is_active = False
    reg_path = r"Software\Microsoft\DirectX\UserGpuPreferences"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, "DirectXUserGlobalSettings")
            val_str = str(value)
            parts = val_str.strip(";").split(";")
            for part in parts:
                if part == "SwapEffectUpgradeEnable=1":
                    is_active = True
                    break 
                elif part == "SwapEffectUpgradeEnable=0":
                    is_active = False
                    break 
    except Exception:
        pass
    return {"is_active": is_active, "is_admin": is_admin}

@eel.expose
def is_autostart_enabled():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_READ)
        winreg.QueryValueEx(key, APP_NAME)
        winreg.CloseKey(key)
        return True
    except:
        return False

@eel.expose
def set_custom_hotkey(hotkey_str, enable):
    global hotkey_enabled, current_hotkey
    try: keyboard.unhook_all_hotkeys()
    except Exception: pass
        
    hotkey_enabled = enable
    current_hotkey = hotkey_str
    
    if enable and current_hotkey:
        try:
            keyboard.add_hotkey(current_hotkey, hotkey_action)
        except: return False
    return True

def hotkey_action():
    global hotkey_enabled, active_taskbar_game
    if not hotkey_enabled: return

    if active_taskbar_game is not None:
        game_name = active_taskbar_game['name']
        toggle_borderless(game_name)
        try: eel.update_switch_from_python(game_name, False)
        except: pass
        return

    profiles = get_all_profiles()
    hwnd = win32gui.GetForegroundWindow()
    active_title = win32gui.GetWindowText(hwnd).strip()
    
    if active_title in profiles:
        toggle_borderless(active_title)
        try: eel.update_switch_from_python(active_title, True)
        except: pass
        return
        
    open_windows = get_open_windows()
    for window in open_windows:
        if window in profiles:
            toggle_borderless(window)
            try: eel.update_switch_from_python(window, True)
            except: pass
            return

try: keyboard.add_hotkey('ctrl+shift+b', hotkey_action)
except Exception: pass

# ==============================================================================================
# 6. BAKGRUNDS-TRÅDAR & TRAY
# ==============================================================================================
@eel.expose
def check_for_updates():
    """Kollar om det finns en nyare version tillgänglig på nätet."""
    try:
        # Hämta JSON-data från din URL
        req = urllib.request.urlopen(UPDATE_INFO_URL, timeout=5)
        data = json.loads(req.read().decode('utf-8'))
        latest_version = data.get("version")
        download_url = data.get("url")

        if latest_version and latest_version != CURRENT_VERSION:
            return {
                "update_available": True, 
                "version": latest_version, 
                "url": download_url
            }
    except Exception as e:
        print(f"Kunde inte söka efter uppdateringar: {e}")
        
    return {"update_available": False}

update_triggered = False

@eel.expose
def perform_update(download_url):
    global update_triggered
    if update_triggered: return False # Starta inte två!
    update_triggered = True
    
    try:
        current_exe = sys.executable
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
            updater_path = os.path.join(base_path, "updater.exe")
        else:
            updater_path = "updater.exe"

        # Starta updatern med DETACHED_PROCESS så den lever sitt eget liv
        subprocess.Popen([updater_path, download_url, current_exe], 
                         creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
        
        # Stäng ner oss själva SNABBT
        os._exit(0) 
        return True
    except Exception as e:
        update_triggered = False
        return False
    
@eel.expose
def hide_to_tray():
    global tray_icon_instance
    hwnd = win32gui.GetForegroundWindow() 
    title = win32gui.GetWindowText(hwnd)
    if "True-Borders" not in title:
        hwnd = win32gui.FindWindow(None, "True Borders")

    if hwnd != 0:
        win32gui.ShowWindow(hwnd, 0)
        if tray_icon_instance is not None: return 
            
        image = Image.new('RGB', (64, 64), color=(15, 32, 39))
        draw = ImageDraw.Draw(image)
        draw.rectangle((16, 16, 48, 48), fill=(8, 217, 214), outline=(255, 46, 99), width=4)
        
        def show_window(icon, item):
            global tray_icon_instance
            icon.stop() 
            tray_icon_instance = None 
            win32gui.ShowWindow(hwnd, 9) 
            win32gui.SetForegroundWindow(hwnd) 
            
        def quit_app(icon, item):
            icon.stop()
            try:
                set_taskbars_state(original_taskbar_autohide, False)
                if active_taskbar_game: restore_borders(active_taskbar_game['name'])
            except: pass
            os._exit(0)

        menu = pystray.Menu(
            pystray.MenuItem("Show True-Borders", show_window, default=True),
            pystray.MenuItem("Exit Completely", quit_app)
        )
        
        tray_icon_instance = pystray.Icon("True-Borders", image, "True-Borders", menu)
        threading.Thread(target=tray_icon_instance.run, daemon=True).start()

def taskbar_monitor():
    global taskbar_is_hidden, active_taskbar_game
    while True:
        time.sleep(0.1)
        try:
            if not active_taskbar_game:
                if taskbar_is_hidden: 
                    set_taskbars_state(original_taskbar_autohide, False)
                    taskbar_is_hidden = False
                continue
                
            game_name = active_taskbar_game['name']
            hwnd = find_real_game_window(game_name)
            
            if hwnd != 0:
                style = win32gui.GetWindowLong(hwnd, GWL_STYLE)
                rect = win32gui.GetWindowRect(hwnd)
                curr_y = rect[1]
                has_coords = 'realY' in active_taskbar_game
                
                if (style & WS_CAPTION) or (has_coords and abs(curr_y - active_taskbar_game['realY']) > 1):
                    if has_coords:
                        force_reapply_borderless(hwnd, active_taskbar_game['realX'], active_taskbar_game['realY'], active_taskbar_game['resW'], active_taskbar_game['resH'])

                foreground_hwnd = win32gui.GetForegroundWindow()
                if foreground_hwnd == hwnd:
                    h_mode = active_taskbar_game.get('hide', False)
                    d_mode = active_taskbar_game.get('disable', False)
                    if (h_mode or d_mode) and not taskbar_is_hidden:
                        set_taskbars_state(h_mode, d_mode)
                        taskbar_is_hidden = True
                else:
                    if taskbar_is_hidden:
                        set_taskbars_state(original_taskbar_autohide, False)
                        taskbar_is_hidden = False
            else:
                if taskbar_is_hidden:
                    set_taskbars_state(original_taskbar_autohide, False)
                    taskbar_is_hidden = False
                active_taskbar_game = None 
        except Exception:
            pass

known_auto_applied_games = set()

def background_auto_apply_scanner():
    """Körs i Python dygnet runt. Somnar aldrig även om UI:t ligger i Tray!"""
    global known_auto_applied_games
    while True:
        time.sleep(2.5) # Söker varannan sekund
        try:
            profiles = get_all_profiles()
            if not profiles:
                continue
                
            open_windows = get_open_windows()
            
            # 1. Rensa bort spel från minnet som har stängts
            known_auto_applied_games = {g for g in known_auto_applied_games if g in open_windows}
            
            # 2. Leta efter nya spel att applicera på
            for win in open_windows:
                if win in profiles and win not in known_auto_applied_games:
                    known_auto_applied_games.add(win)
                    
                    if not is_borderless(win):
                        print(f"Auto-applied: {win} from background!")
                        init_borderless(win)
                        
                        # Fixa Always on Top om profilen kräver det
                        p = profiles[win]
                        if p.get('alwaysOnTop'):
                            set_game_topmost(win, True)
                            
                        # Försök slå om UI-switchen (om UI:t råkar vara synligt)
                        try: eel.update_switch_from_python(win, True)
                        except: pass
        except Exception:
            pass

# ==============================================================================================
# 7. TRAY OCH FÖNSTERHANTERING FÖR NINJA-START
# ==============================================================================================

def open_tb_window():
    """Startar Eel-fönstret (öppnas bara när användaren klickar i tray)."""
    global is_window_open
    if is_window_open:
        # Om fönstret redan är öppet, ta det till förgrunden
        hwnd = win32gui.FindWindow(None, "True Borders")
        if hwnd != 0:
            win32gui.ShowWindow(hwnd, 9) # SW_RESTORE
            win32gui.SetForegroundWindow(hwnd)
        return

    is_window_open = True
    app_width = 900 
    app_height = 980 
    screen_width = win32api.GetSystemMetrics(0)
    screen_height = win32api.GetSystemMetrics(1)
    center_x = (screen_width // 2) - (app_width // 2)
    center_y = (screen_height // 2) - (app_height // 2)

    cmd_args = [
        '--disable-extensions', 
        '--no-first-run', 
        '--no-default-browser-check'
    ]

    # Starta Eel-fönstret centrerat
    eel.start('index.html', 
              mode='chrome', 
              size=(app_width, app_height), 
              position=(center_x, center_y), 
              close_callback=on_app_close,
              cmdline_args=cmd_args,
              block=True # Detta blockerar tills fönstret stängs
    )
    # När blockeringen släpper har användaren stängt fönstret
    is_window_open = False

# ==============================================================================================
# 8. HUVUDPROGRAM & TRAY-IKON
# ==============================================================================================

is_window_open = False # Flagga för att hålla koll på fönsterstatus

def setup_tray_ninja():
    """Skapar tray-ikonen direkt (inget fönster öppnas)."""
    global tray_icon_instance
    
    # Skapa en enkel ikon
    image = Image.new('RGB', (64, 64), color=(15, 32, 39))
    draw = ImageDraw.Draw(image)
    draw.rectangle((16, 16, 48, 48), fill=(8, 217, 214), outline=(255, 46, 99), width=4)
    
    def on_show(icon, item):
        # Öppnar Eel-fönstret i en ny tråd
        threading.Thread(target=open_tb_window, daemon=True).start()

    def on_quit(icon, item):
        icon.stop()
        restore_everything_on_exit()
        os._exit(0)

    menu = pystray.Menu(
        pystray.MenuItem("Open True Borders", on_show, default=True),
        pystray.MenuItem("Exit Completely", on_quit)
    )
    
    tray_icon_instance = pystray.Icon("TrueBordersNinja", image, "True Borders", menu)
    threading.Thread(target=tray_icon_instance.run, daemon=True).start()

def restore_everything_on_exit():
    """Städar upp och återställer alla spel när appen stängs."""
    try:
        set_taskbars_state(original_taskbar_autohide, False)
        
        # 1. Återställ spelet som styr taskbaren
        global active_taskbar_game
        if active_taskbar_game:
            restore_borders(active_taskbar_game['name'])
            
        # 2. Återställ alla andra spel som scannern har hittat
        global known_auto_applied_games
        for game in list(known_auto_applied_games):
            restore_borders(game)
    except Exception:
        pass

def on_app_close(page, sockets):
    """Callback för när användaren stänger Eel-fönstret med krysset."""
    restore_everything_on_exit()
    os._exit(0)

# === STARTA NINJA-ARKITEKTUREN ===

original_taskbar_autohide = get_taskbar_autohide_state()
threading.Thread(target=taskbar_monitor, daemon=True).start()
threading.Thread(target=background_auto_apply_scanner, daemon=True).start()

# Skapa tray-ikonen direkt
setup_tray_ninja()

if start_minimized:
    # Starta helt osynligt, bara tray-ikonen körs
    print("Ninja-start active. Only tray icon is running.")
    # Vi behöver hålla huvudprogrammet vid liv utan blockering
    while True:
        time.sleep(1)
else:
    # Starta fönstret direkt som vanligt
    open_tb_window()