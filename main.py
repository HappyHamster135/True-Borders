import eel
import win32gui
import win32con
import win32ui
import win32process
import ctypes
from ctypes import wintypes
import json
import os
import base64
import threading
import time
import winreg
import sys
import subprocess
import keyboard
import pystray
import urllib.request
from screeninfo import get_monitors
from PIL import Image, ImageDraw
from io import BytesIO
import tkinter as tk
from tkinter import filedialog

# ==============================================================================================
# 1. GLOBALA VARIABLER & INITIALISERING
# ==============================================================================================

CURRENT_VERSION = "1.0.9" 
UPDATE_INFO_URL = "https://raw.githubusercontent.com/HappyHamster135/True-Borders/main/update.json"

tray_icon_instance = None
active_taskbar_game = None
taskbar_is_hidden = False
original_taskbar_autohide = False
hotkey_enabled = False
current_hotkey = 'ctrl+shift+b'
user_taskbar_preference = None
is_window_open = False

# Hantera DPI-skalning för att få korrekta fönsterstorlekar på högupplösta skärmar
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    ctypes.windll.user32.SetProcessDPIAware()

eel.init('web')

# Fönsterstilar och flaggor för Windows API
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

# Sätt upp mappar och filer för appens data
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
    except Exception: 
        return default_val
    
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
        
    # Försök automatiskt hitta spelets exe-fil via den aktiva processen
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
        except Exception:
            pass

    profiles[game_name].update(data) 
    
    with open(PROFILES_FILE, "w") as f:
        json.dump(profiles, f, indent=4)
    
    # NYTT: Om det är ett Paradox-spel, uppdatera även dess settings.txt
    if 'resW' in data and 'resH' in data:
        paradox_folder = _get_paradox_folder_name(game_name)
        if paradox_folder:
            update_paradox_resolution(game_name, data['resW'], data['resH'])
    
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
    except Exception:
        return False

@eel.expose
def reorder_profiles(new_order_list):
    old_profiles = get_all_profiles()
    ordered_profiles = {}
    for name in new_order_list:
        if name in old_profiles:
            ordered_profiles[name] = old_profiles[name]
    
    # Lägg till eventuella profiler som missats i den nya sorteringen
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
            # Tvinga Terraria till windowed INNAN start (config skrivs medan spelet är stängt)
            try:
                force_terraria_windowed(game_name)
            except Exception:
                pass

            working_dir = os.path.dirname(exe_path)
            subprocess.Popen([exe_path], cwd=working_dir)
            return True
        except Exception:
            return False
    return False

@eel.expose
def browse_exe():
    root = tk.Tk()
    root.attributes('-topmost', True) 
    root.withdraw() 
    file_path = filedialog.askopenfilename(
        title="Välj spelets körbara fil",
        filetypes=[("Körbara filer", "*.exe"), ("Alla filer", "*.*")]
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
# 3. KÄRNFUNKTIONER FÖR BORDERLESS
# ==============================================================================================

def _get_window_exe_path(hwnd):
    """Returnerar full sökväg till .exe-filen som äger ett fönster (eller None)."""
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if not pid:
            return None
        h_process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not h_process:
            return None
        try:
            exe_buffer = ctypes.create_unicode_buffer(260)
            size = wintypes.DWORD(260)
            if ctypes.windll.kernel32.QueryFullProcessImageNameW(h_process, 0, exe_buffer, ctypes.byref(size)):
                return exe_buffer.value
        finally:
            ctypes.windll.kernel32.CloseHandle(h_process)
    except Exception:
        pass
    return None


def _enum_candidate_windows():
    """Listar synliga 'riktiga' fönster (rimlig storlek, har titel)."""
    candidates = []
    def cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd).strip()
        if not title or title in EXACT_IGNORE:
            return True
        rect = win32gui.GetWindowRect(hwnd)
        w, h = rect[2] - rect[0], rect[3] - rect[1]
        if w > 100 and h > 100:
            candidates.append((hwnd, title, w * h))
        return True
    win32gui.EnumWindows(cb, None)
    return candidates


@eel.expose
def resolve_profile_name(window_title):
    """Översätter en (möjligen slumpad) live-fönstertitel till namnet på den
    sparade profil som hör till samma fönster (via exe/ikon). Returnerar
    titeln själv om den redan är en profilnyckel, annars None."""
    profiles = get_all_profiles()
    if not profiles:
        return None
    if window_title in profiles:
        return window_title

    live_hwnd = find_real_game_window(window_title)  # fallback-sökning på titel
    if not live_hwnd:
        return None

    for name in profiles:
        if find_window_for_profile(name, profiles) == live_hwnd:
            return name
    return None


@eel.expose
def get_running_profile_names():
    """Returnerar profilnamn som just nu har ett levande fönster (via exe/ikon),
    så det funkar även för spel som bytt fönstertitel (t.ex. Terraria)."""
    profiles = get_all_profiles()
    return [name for name in profiles if find_window_for_profile(name, profiles)]


def find_window_for_profile(profile_name, profiles=None):
    """Hittar det levande fönstret för en sparad profil – robust mot spel som
    byter fönstertitel (t.ex. Terraria, vars titel kan bli vad som helst).

    Poäng per kandidatfönster:
      exakt exe-sökväg  -> starkast (titel-oberoende)
      samma exe-filnamn -> näst starkast
      ikon matchar      -> reserv om exe saknas
      titel matchar     -> snabb men opålitlig för spel med slumpad titel
    """
    if profiles is None:
        profiles = get_all_profiles()
    profile = profiles.get(profile_name) or {}

    candidates = _enum_candidate_windows()
    if not candidates:
        return 0

    name_l = (profile_name or "").strip().lower()
    saved_exe = profile.get('exePath')
    saved_exe_norm = os.path.normcase(saved_exe) if saved_exe else None
    saved_exe_base = os.path.basename(saved_exe).lower() if saved_exe else None
    saved_icon = profile.get('icon')

    best_hwnd, best_score, best_area = 0, -1, -1

    for hwnd, title, area in candidates:
        title_l = title.lower()
        score = 0

        # 1) Titel (snabb men opålitlig)
        if name_l and title_l == name_l:
            score += 100
        elif name_l and (name_l in title_l or title_l in name_l):
            score += 60

        # 2) Exe-sökväg (titel-oberoende, starkaste signalen)
        if saved_exe_norm:
            win_exe = _get_window_exe_path(hwnd)
            if win_exe:
                if os.path.normcase(win_exe) == saved_exe_norm:
                    score += 250
                elif os.path.basename(win_exe).lower() == saved_exe_base:
                    score += 180

        # 3) Ikon (endast reserv när profilen saknar exe-sökväg)
        if saved_icon and not saved_exe_norm and score < 60:
            if get_icon_base64(hwnd) == saved_icon:
                score += 150

        if score > best_score or (score == best_score and area > best_area):
            best_hwnd, best_score, best_area = hwnd, score, area

    # Minsta säkerhet så vi aldrig kapar ett orelaterat fönster.
    return best_hwnd if best_score >= 60 else 0


def find_real_game_window(search_title):
    """Hittar spelfönstret. Matchar titeln en sparad profil används robust
    profilmatchning (exe/ikon) som klarar spel som byter titel (t.ex. Terraria)."""
    try:
        profiles = get_all_profiles()
        if search_title in profiles:
            hwnd = find_window_for_profile(search_title, profiles)
            if hwnd:
                return hwnd
    except Exception:
        pass

    # Fallback: ren titelsökning (för fönster utan sparad profil, t.ex. när man
    # listar igång spel för att skapa en ny profil).
    found_hwnds = []
    def callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd).strip()
            if search_title.lower() in title.lower():
                rect = win32gui.GetWindowRect(hwnd)
                w, h = rect[2] - rect[0], rect[3] - rect[1]
                if w > 100 and h > 100:
                    found_hwnds.append((hwnd, w * h))
        return True
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
    """Hämtar spelets exakta position och upplösning på skärmen."""
    hwnd = find_real_game_window(window_title)
    if hwnd == 0:
        return None
        
    rect = win32gui.GetWindowRect(hwnd)
    client_rect = win32gui.GetClientRect(hwnd)
    
    return {
        "x": rect[0],
        "y": rect[1],
        "w": client_rect[2], 
        "h": client_rect[3]  
    }

@eel.expose
def is_borderless(window_title):
    global active_taskbar_game
    if active_taskbar_game and active_taskbar_game.get('name') == window_title:
        return True
        
    hwnd = find_real_game_window(window_title)
    if hwnd != 0:
        style = win32gui.GetWindowLong(hwnd, GWL_STYLE)
        return not (style & WS_CAPTION)
    return False

def get_window_offsets(hwnd):
    """Räknar ut hur tjock fönsterramen och namnlisten är."""
    try:
        rect = win32gui.GetWindowRect(hwnd)
        client_rect = win32gui.GetClientRect(hwnd)
        
        win_w = rect[2] - rect[0]
        win_h = rect[3] - rect[1]
        
        client_w = client_rect[2] 
        client_h = client_rect[3] 
        
        border_x = (win_w - client_w) // 2
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
    
    # Hantera positionering beroende på om vi har sparade inställningar, UI-indata eller standardvärden
    if ui_x is not None:
        target_x, target_y = ui_x, ui_y
        target_w, target_h = ui_w, ui_h
    elif profile:
        target_x = profile.get('realX', 0)
        target_y = profile.get('realY', 0)
        target_w = profile.get('resW', client_rect[2])
        target_h = profile.get('resH', client_rect[3])
    else:
        try:
            pt = win32gui.ClientToScreen(hwnd, (0, 0))
            target_x, target_y = pt[0], pt[1]
        except Exception:
            target_x, target_y = rect[0], rect[1]
        target_w, target_h = client_rect[2], client_rect[3]

    # Applicera inställningarna
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

    # Försök spara spelets sökväg automatiskt om det saknas
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
    except Exception:
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
    global active_taskbar_game, taskbar_is_hidden
    
    set_game_topmost(window_title, False)
    
    if active_taskbar_game and active_taskbar_game.get('name') == window_title:
        active_taskbar_game = None
    
    # Återställ taskbaren direkt
    if taskbar_is_hidden:
        set_taskbars_state(original_taskbar_autohide, False)
        taskbar_is_hidden = False
    
    hwnd = find_real_game_window(window_title)
    if hwnd == 0:
        return False
        
    style = win32gui.GetWindowLong(hwnd, GWL_STYLE)
    
    rect = win32gui.GetWindowRect(hwnd)
    curr_x = rect[0]
    curr_y = rect[1]
    curr_w = rect[2] - rect[0]
    curr_h = rect[3] - rect[1]

    if not (style & win32con.WS_CAPTION):
        curr_w += 16
        curr_h += 39
        curr_x -= 8
        curr_y -= 31

    new_style = style | (win32con.WS_CAPTION | win32con.WS_THICKFRAME | win32con.WS_MINIMIZEBOX | win32con.WS_MAXIMIZEBOX | win32con.WS_SYSMENU)
    win32gui.SetWindowLong(hwnd, GWL_STYLE, new_style)
    win32gui.SetWindowLong(hwnd, -20, 0x00040000) 
    
    if curr_y < 0:
        curr_y = 50
    if curr_x < 0:
        curr_x = 50
        
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
    if x is None or y is None: 
        return 
    
    hwnd = find_real_game_window(window_title)
    if hwnd != 0:
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
        flags = SWP_FRAMECHANGED | 0x0004 | 0x0400 | 0x0040 
        win32gui.SetWindowPos(hwnd, 0, int(x), int(y), int(w), int(h) + 10, flags)
        win32gui.SetWindowPos(hwnd, 0, int(x), int(y), int(w), int(h), flags)

@eel.expose
def force_window_refresh(window_title, x, y, w, h):
    if any(v is None for v in [x, y, w, h]): 
        return 
    hwnd = find_real_game_window(window_title)
    if not hwnd: 
        return
    
    profile = get_profile(window_title)
    should_be_topmost = profile.get('alwaysOnTop', False) if profile else False
    final_z = win32con.HWND_TOPMOST if should_be_topmost else win32con.HWND_NOTOPMOST
    
    SWP_FLAGS = win32con.SWP_FRAMECHANGED | win32con.SWP_NOACTIVATE
    
    # Skapa en liten fönsteruppdatering för att tvinga fram en omritning
    win32gui.SetWindowPos(hwnd, 0, int(x), int(y), int(w) + 1, int(h) + 1, SWP_FLAGS)
    win32gui.SetWindowPos(hwnd, 0, int(x), int(y), int(w), int(h), SWP_FLAGS)
    
    # Växla z-ordning för att säkerställa att ramfixen fungerar som den ska
    win32gui.SetWindowPos(hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0, SWP_FLAGS | win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
    win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, SWP_FLAGS | win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
    
    # Avsluta och applicera det slutgiltiga z-order-läget
    win32gui.SetWindowPos(hwnd, final_z, int(x), int(y), int(w), int(h), win32con.SWP_FRAMECHANGED | win32con.SWP_SHOWWINDOW)

# ==============================================================================================
# 4. FÖNSTER & SKÄRM-AVLÄSNING (Listor, Ikoner)
# ==============================================================================================

EXACT_IGNORE = ["Program Manager", "Settings", "Microsoft Text Input Application", "Windows Input Experience", "True Borders", "Task Manager", "Aktivitetshanteraren"]
SUBSTRING_IGNORE = ["Overlay", "Default IME", " - Opera", " - Google Chrome", " - Mozilla Firefox", " - Microsoft Edge", " - Brave", " - Vivaldi"]

def _is_valid_user_window(hwnd):
    """Hjälpfunktion för att filtrera bort bakgrundsprogram och överlägg när vi listar öppna fönster."""
    if not win32gui.IsWindowVisible(hwnd) or win32gui.GetWindowTextLength(hwnd) == 0:
        return False, ""
    title = win32gui.GetWindowText(hwnd).strip()
    if not title or title in EXACT_IGNORE or any(sub in title for sub in SUBSTRING_IGNORE):
        return False, ""
    return True, title

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
    def enum_windows_proc(hwnd, lParam):
        is_valid, title = _is_valid_user_window(hwnd)
        if is_valid and title not in titles:
            titles.append(title)
        return True
        
    win32gui.EnumWindows(enum_windows_proc, 0)
    return sorted(titles)

@eel.expose
def get_windows_with_icons():
    windows_data = []
    titles_seen = set()

    def enum_windows_proc(hwnd, lParam):
        is_valid, title = _is_valid_user_window(hwnd)
        if is_valid and title not in titles_seen:
            titles_seen.add(title)
            icon_b64 = get_icon_base64(hwnd) 
            windows_data.append({"title": title, "icon": icon_b64})
        return True
        
    win32gui.EnumWindows(enum_windows_proc, 0)
    return sorted(windows_data, key=lambda k: k['title'].lower())

@eel.expose
def get_window_icon_base64(window_title):
    hwnd = find_real_game_window(window_title)
    if hwnd == 0: 
        return None
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

        try: 
            win32gui.DestroyIcon(hicon)
        except Exception: 
            pass 
            
        try:
            hdc.DeleteDC()
            win32gui.DeleteObject(hbmp.GetHandle())
        except Exception:
            pass

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
        except Exception: 
            pass
    settings["start_minimized"] = enabled
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=4)
    return True

@eel.expose
def is_start_minimized():
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

def remember_user_taskbar_preference():
    """Sparar användarens inställning för taskbaren innan vi börjar manipulera den."""
    global user_taskbar_preference
    if user_taskbar_preference is None:
        user_taskbar_preference = get_taskbar_autohide_state()

def refresh_user_taskbar_preference():
    """Fångar upp ändringar användaren gjort manuellt i Windows när inget spel körs."""
    global user_taskbar_preference, active_taskbar_game, taskbar_is_hidden
    if not active_taskbar_game and not taskbar_is_hidden:
        user_taskbar_preference = get_taskbar_autohide_state()

def set_taskbars_state(hide_mode, disable_mode):
    user32 = ctypes.windll.user32
    
    if disable_mode:
        remember_user_taskbar_preference()
        
        # Vi sätter taskbaren till Autohide först för att undvika att fönster hoppar runt på skärmen
        set_taskbar_autohide(True)
        
        def enum_handler_disable(hwnd, lParam):
            if win32gui.GetClassName(hwnd) in ["Shell_TrayWnd", "Shell_SecondaryTrayWnd"]:
                user32.ShowWindow(hwnd, 0)
                user32.EnableWindow(hwnd, False)
            return True
        win32gui.EnumWindows(enum_handler_disable, 0)
        return
    
    if hide_mode:
        remember_user_taskbar_preference()
        set_taskbar_autohide(True)
        def enum_handler_soft(hwnd, lParam):
            if win32gui.GetClassName(hwnd) in ["Shell_TrayWnd", "Shell_SecondaryTrayWnd"]:
                user32.ShowWindow(hwnd, 5) 
                user32.EnableWindow(hwnd, True)
            return True
        win32gui.EnumWindows(enum_handler_soft, 0)
        return
    
    # Återställ till användarens ursprungliga preferens
    pref = user_taskbar_preference if user_taskbar_preference is not None else False
    set_taskbar_autohide(pref)
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
    
    global active_taskbar_game, taskbar_is_hidden
    if active_taskbar_game and active_taskbar_game['name'] == window_title:
        active_taskbar_game['hide'] = hide
        active_taskbar_game['disable'] = disable
        
        if hide or disable:
            set_taskbars_state(hide, disable)
            taskbar_is_hidden = True
        else:
            set_taskbars_state(False, False)
            taskbar_is_hidden = False
            
    # Åtgärda ramen först så att vi inte påverkar z-ordningen i onödan
    if border_fix:
        p = profiles.get(window_title)
        if p:
            force_window_refresh(window_title, p['realX'], p['realY'], p['resW'], p['resH'])
    
    set_game_topmost(window_title, on_top)

@eel.expose
def update_taskbar_setting(game_name, hide_val, disable_val):
    profiles = get_all_profiles()
    if game_name in profiles:
        profiles[game_name]['hideTaskbar'] = hide_val
        profiles[game_name]['disableTaskbar'] = disable_val
        with open(PROFILES_FILE, "w") as f:
            json.dump(profiles, f, indent=4)
            
        global active_taskbar_game, taskbar_is_hidden
        if active_taskbar_game and active_taskbar_game['name'] == game_name:
            active_taskbar_game['hide'] = hide_val
            active_taskbar_game['disable'] = disable_val
            
            if hide_val or disable_val:
                set_taskbars_state(hide_val, disable_val)
                taskbar_is_hidden = True
            else:
                set_taskbars_state(False, False)
                taskbar_is_hidden = False
                
        return True
    return False

@eel.expose
def is_admin():
    try: 
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception: 
        return False

@eel.expose
def set_app_on_top():
    hwnd = win32gui.FindWindow(None, "True Borders")
    if hwnd != 0: 
        win32gui.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 3)

@eel.expose
def set_game_topmost(window_title, is_topmost):
    hwnd = find_real_game_window(window_title)
    if hwnd != 0:
        z_order = -1 if is_topmost else -2 
        win32gui.SetWindowPos(hwnd, z_order, 0, 0, 0, 0, 3)

@eel.expose
def open_windows_display_settings():
    """Öppnar Windows skärmlayout-inställningar."""
    try:
        os.startfile("ms-settings:display")
        return True
    except Exception:
        try:
            subprocess.Popen(["explorer.exe", "ms-settings:display"])
            return True
        except Exception:
            return False

@eel.expose
def toggle_windows_optimizations(enable=True):
    reg_path = r"Software\Microsoft\DirectX\UserGpuPreferences"
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path, 0, winreg.KEY_ALL_ACCESS)
        try: 
            current_value, _ = winreg.QueryValueEx(key, "DirectXUserGlobalSettings")
        except Exception: 
            current_value = ""

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
            try: 
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError: 
                pass
        winreg.CloseKey(key)
        return True
    except Exception:
        return False

@eel.expose
def check_latency_boost_status():
    user_is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
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
    return {"is_active": is_active, "is_admin": user_is_admin}

@eel.expose
def is_autostart_enabled():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_READ)
        winreg.QueryValueEx(key, APP_NAME)
        winreg.CloseKey(key)
        return True
    except Exception:
        return False

@eel.expose
def set_custom_hotkey(hotkey_str, enable):
    global hotkey_enabled, current_hotkey
    try: 
        keyboard.unhook_all_hotkeys()
    except Exception: 
        pass
        
    hotkey_enabled = enable
    current_hotkey = hotkey_str
    
    if enable and current_hotkey:
        try:
            keyboard.add_hotkey(current_hotkey, hotkey_action)
        except Exception: 
            return False
    return True

def hotkey_action():
    global hotkey_enabled, active_taskbar_game
    if not hotkey_enabled:
        return

    if active_taskbar_game is not None:
        game_name = active_taskbar_game['name']
        toggle_borderless(game_name)
        try:
            eel.update_switch_from_python(game_name, False)
        except Exception:
            pass
        return

    profiles = get_all_profiles()
    if not profiles:
        return

    fg_hwnd = win32gui.GetForegroundWindow()

    # 1) Prioritera profilen vars fönster ligger i förgrunden
    for prof_name in profiles:
        if fg_hwnd and find_window_for_profile(prof_name, profiles) == fg_hwnd:
            toggle_borderless(prof_name)
            try: eel.update_switch_from_python(prof_name, True)
            except Exception: pass
            return

    # 2) Annars första profilen med ett levande fönster
    for prof_name in profiles:
        if find_window_for_profile(prof_name, profiles):
            toggle_borderless(prof_name)
            try: eel.update_switch_from_python(prof_name, True)
            except Exception: pass
            return

try: 
    keyboard.add_hotkey('ctrl+shift+b', hotkey_action)
except Exception: 
    pass

# ==============================================================================================
# 5.5 PARADOX-INTEGRATION (settings.txt-editor för CK3, EU4, Stellaris, HOI4, Vic3, Imperator)
# ==============================================================================================

# Mappar speltitlar till deras Paradox-mappnamn under Documents/Paradox Interactive/
PARADOX_GAMES = {
    "Crusader Kings III": "Crusader Kings III",
    "Europa Universalis IV": "Europa Universalis IV",
    "Stellaris": "Stellaris",
    "Hearts of Iron IV": "Hearts of Iron IV",
    "Victoria 3": "Victoria 3",
    "Imperator: Rome": "Imperator",
}

def _get_paradox_folder_name(game_title):
    """Identifierar om titeln är ett Paradox-spel och returnerar mappnamnet."""
    for known_title, folder in PARADOX_GAMES.items():
        if known_title.lower() in game_title.lower():
            return folder
    return None

def _get_paradox_settings_path(game_title):
    """Bygger den fulla sökvägen till spelets settings.txt."""
    folder = _get_paradox_folder_name(game_title)
    if not folder:
        return None
    
    docs = os.path.join(os.environ['USERPROFILE'], 'Documents')
    path = os.path.join(docs, 'Paradox Interactive', folder, 'settings.txt')
    
    if not os.path.exists(path):
        return None
    return path

def update_paradox_resolution(game_title, width, height):
    """Skriver upplösning till Paradox-spelets pdx_settings.txt."""
    folder = _get_paradox_folder_name(game_title)
    if not folder:
        return False, "not_paradox"
    
    docs = os.path.join(os.environ['USERPROFILE'], 'Documents')
    settings_path = os.path.join(docs, 'Paradox Interactive', folder, 'pdx_settings.txt')
    
    if not os.path.exists(settings_path):
        return False, "settings_file_not_found"
    
    try:
        with open(settings_path, 'r', encoding='utf-8-sig') as f:
            content = f.read()
        
        # Backup första gången
        backup_path = settings_path + '.truebackup'
        if not os.path.exists(backup_path):
            with open(backup_path, 'w', encoding='utf-8-sig') as f:
                f.write(content)
        
        import re
        new_res = f'"{width}x{height}"'
        
        # Mönstret matchar:  "windowed_resolution"={\n  version=N\n  value="WxH"\n}
        # Vi byter bara value-raden, behåller strukturen
        def replace_res_value(match, new_value):
            block = match.group(0)
            return re.sub(r'value="\d+x\d+"', f'value={new_value}', block)
        
        # Uppdatera windowed_resolution
        windowed_pattern = r'"windowed_resolution"=\{[^}]*\}'
        if re.search(windowed_pattern, content):
            content = re.sub(
                windowed_pattern,
                lambda m: replace_res_value(m, new_res),
                content,
                count=1
            )
        
        # Uppdatera även fullscreen_resolution som backup ifall användaren togglar lägen
        fullscreen_pattern = r'"fullscreen_resolution"=\{[^}]*\}'
        if re.search(fullscreen_pattern, content):
            content = re.sub(
                fullscreen_pattern,
                lambda m: replace_res_value(m, new_res),
                content,
                count=1
            )
        
        # Tvinga windowed mode (matchar "display_mode"={ version=0 value="windowed" })
        display_mode_pattern = r'("display_mode"=\{[^}]*?value=)"[^"]+"'
        content = re.sub(display_mode_pattern, r'\1"windowed"', content, count=1)
        
        with open(settings_path, 'w', encoding='utf-8-sig') as f:
            f.write(content)
        
        return True, "updated"
    except Exception as e:
        return False, str(e)

@eel.expose
def is_paradox_game(game_title):
    """Frontend-helper för att veta om vi ska visa varningen om omstart."""
    return _get_paradox_folder_name(game_title) is not None

@eel.expose
def apply_paradox_resolution(game_title, width, height):
    """Anropas från frontend när användaren sparar profil för ett Paradox-spel."""
    success, msg = update_paradox_resolution(game_title, int(width), int(height))
    return {"success": success, "message": msg}


# ==============================================================================================
# 5.6 TERRARIA-INTEGRATION (config.json display mode -> tvinga äkta windowed)
# ==============================================================================================

def _exe_basename_for_game(game_name, profile=None):
    """Hämtar exe-filnamnet (gemener) för ett spel, från profilen eller det
    levande fönstret. Robust mot Terrarias slumpade fönstertitlar."""
    if profile is None:
        profile = get_profile(game_name) or {}
    exe = profile.get('exePath')
    if exe:
        return os.path.basename(exe).lower()
    hwnd = find_real_game_window(game_name)
    if hwnd:
        live = _get_window_exe_path(hwnd)
        if live:
            return os.path.basename(live).lower()
    return ''

def _terraria_config_path(exe_base):
    docs = os.path.join(os.environ['USERPROFILE'], 'Documents', 'My Games')
    if exe_base == 'tmodloader.exe':
        for folder in ('tModLoader', os.path.join('Terraria', 'tModLoader')):
            p = os.path.join(docs, folder, 'config.json')
            if os.path.exists(p):
                return p
        return None
    if exe_base == 'terraria.exe':
        p = os.path.join(docs, 'Terraria', 'config.json')
        return p if os.path.exists(p) else None
    return None

def force_terraria_windowed(game_name):
    """Sätter Terrarias config till äkta windowed (Fullscreen=false,
    WindowBorderless=false). Returnerar (changed, msg).
    OBS: tar effekt nästa gång spelet STARTAS. Körs spelet redan skrivs
    filen över vid avslut, så detta är till för nästa launch."""
    base = _exe_basename_for_game(game_name)
    path = _terraria_config_path(base)
    if not path:
        return False, "not_terraria"
    try:
        with open(path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)

        if not cfg.get('Fullscreen', False) and not cfg.get('WindowBorderless', False):
            return False, "already_windowed"

        backup = path + '.truebackup'
        if not os.path.exists(backup):
            with open(backup, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, indent=4)

        cfg['Fullscreen'] = False
        cfg['WindowBorderless'] = False

        with open(path, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=4)
        return True, "fixed"
    except Exception as e:
        return False, str(e)

@eel.expose
def ensure_terraria_windowed(game_name):
    changed, msg = force_terraria_windowed(game_name)
    return {"changed": changed, "message": msg}

@eel.expose
def get_terraria_display_status(game_name):
    """För frontend: är detta Terraria, och står den i fullscreen/borderless?"""
    base = _exe_basename_for_game(game_name)
    if base not in ('terraria.exe', 'tmodloader.exe'):
        return {"is_terraria": False}
    path = _terraria_config_path(base)
    if not path:
        return {"is_terraria": True, "config_found": False, "needs_fix": False}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        fs = bool(cfg.get('Fullscreen', False))
        bl = bool(cfg.get('WindowBorderless', False))
        return {"is_terraria": True, "config_found": True,
                "fullscreen": fs, "borderless": bl, "needs_fix": fs or bl}
    except Exception:
        return {"is_terraria": True, "config_found": True, "needs_fix": False, "error": True}

# ==============================================================================================
# 6. BAKGRUNDS-TRÅDAR & TRAY
# ==============================================================================================

@eel.expose
def check_for_updates():
    """Kollar om det finns en nyare version av appen tillgänglig via GitHub."""
    try:
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
    try:
        current_exe = sys.executable
        
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
            updater_path = os.path.join(base_path, "updater.exe")
        else:
            updater_path = os.path.join(os.path.dirname(__file__), "updater.exe")

        if not os.path.exists(updater_path):
            ctypes.windll.user32.MessageBoxW(0, f"Saknas: {updater_path}", "Fel", 0x10)
            return False

        cmd = [updater_path, download_url, current_exe]
        
        subprocess.Popen(
            cmd,
            creationflags=subprocess.DETACHED_PROCESS, 
            shell=False,
            close_fds=True 
        )
        
        os._exit(0)
        return True
    except Exception as e:
        ctypes.windll.user32.MessageBoxW(0, f"Kunde inte köra updater: {str(e)}", "Systemfel", 0x10)
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
        if tray_icon_instance is not None: 
            return 
            
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
                if active_taskbar_game:
                    restore_borders(active_taskbar_game['name'])
            except Exception: 
                pass
            os._exit(0)

        menu = pystray.Menu(
            pystray.MenuItem("Visa True-Borders", show_window, default=True),
            pystray.MenuItem("Avsluta helt", quit_app)
        )
        
        tray_icon_instance = pystray.Icon("True-Borders", image, "True-Borders", menu)
        threading.Thread(target=tray_icon_instance.run, daemon=True).start()

def taskbar_monitor():
    global taskbar_is_hidden, active_taskbar_game
    poll_counter = 0
    while True:
        time.sleep(0.1)
        try:
            if not active_taskbar_game:
                if taskbar_is_hidden: 
                    set_taskbars_state(False, False)
                    taskbar_is_hidden = False
                
                poll_counter += 1
                if poll_counter >= 20:
                    poll_counter = 0
                    refresh_user_taskbar_preference()
                continue
            
            poll_counter = 0
                
            game_name = active_taskbar_game['name']
            hwnd = find_real_game_window(game_name)
            
            if hwnd != 0:
                style = win32gui.GetWindowLong(hwnd, GWL_STYLE)
                rect = win32gui.GetWindowRect(hwnd)
                has_coords = 'realY' in active_taskbar_game

                drifted = False
                if has_coords:
                    cur_x, cur_y = rect[0], rect[1]
                    cur_w, cur_h = rect[2] - rect[0], rect[3] - rect[1]
                    if (abs(cur_x - active_taskbar_game['realX']) > 2 or
                        abs(cur_y - active_taskbar_game['realY']) > 2 or
                        abs(cur_w - active_taskbar_game['resW'])  > 2 or
                        abs(cur_h - active_taskbar_game['resH'])  > 2):
                        drifted = True

                if (style & WS_CAPTION) or drifted:
                    if has_coords:
                        force_reapply_borderless(
                            hwnd,
                            active_taskbar_game['realX'],
                            active_taskbar_game['realY'],
                            active_taskbar_game['resW'],
                            active_taskbar_game['resH'],
                        )

                foreground_hwnd = win32gui.GetForegroundWindow()
                if foreground_hwnd == hwnd:
                    h_mode = active_taskbar_game.get('hide', False)
                    d_mode = active_taskbar_game.get('disable', False)
                    if (h_mode or d_mode) and not taskbar_is_hidden:
                        set_taskbars_state(h_mode, d_mode)
                        taskbar_is_hidden = True
                else:
                    if taskbar_is_hidden:
                        set_taskbars_state(False, False)
                        taskbar_is_hidden = False
            else:
                if taskbar_is_hidden:
                    set_taskbars_state(False, False)
                    taskbar_is_hidden = False
                active_taskbar_game = None 
        except Exception:
            pass

known_auto_applied_games = set()

def background_auto_apply_scanner():
    global known_auto_applied_games
    while True:
        time.sleep(2.5)
        try:
            profiles = get_all_profiles()
            if not profiles:
                known_auto_applied_games.clear()
                continue

            # Behåll bara spel som fortfarande har ett levande fönster (via exe/ikon)
            known_auto_applied_games = {
                g for g in known_auto_applied_games
                if find_window_for_profile(g, profiles)
            }

            for prof_name in profiles:
                if prof_name in known_auto_applied_games:
                    continue
                if not find_window_for_profile(prof_name, profiles):
                    continue

                known_auto_applied_games.add(prof_name)
                if not is_borderless(prof_name):
                    print(f"Automatisk applicering: {prof_name} från bakgrunden")
                    init_borderless(prof_name)
                    if profiles[prof_name].get('alwaysOnTop'):
                        set_game_topmost(prof_name, True)
                    try:
                        eel.update_switch_from_python(prof_name, True)
                    except Exception:
                        pass
        except Exception:
            pass

# ==============================================================================================
# 7. TRAY OCH FÖNSTERHANTERING FÖR NINJA-START
# ==============================================================================================

def open_tb_window():
    """Startar programfönstret (öppnas när användaren klickar på ikonen i meddelandefältet)."""
    global is_window_open
    if is_window_open:
        # Om fönstret redan är öppet hämtar vi det till förgrunden
        hwnd = win32gui.FindWindow(None, "True Borders")
        if hwnd != 0:
            win32gui.ShowWindow(hwnd, 9) 
            win32gui.SetForegroundWindow(hwnd)
        return

    is_window_open = True
    
    # Hämta arbetsytan (skärmen MINUS taskbar)
    SPI_GETWORKAREA = 0x0030
    work_area = wintypes.RECT()
    ctypes.windll.user32.SystemParametersInfoW(
        SPI_GETWORKAREA, 0, ctypes.byref(work_area), 0
    )
    
    work_width = work_area.right - work_area.left
    work_height = work_area.bottom - work_area.top
    
    # Önskad storlek, men krymp om skärmen är mindre
    # 40px marginal så fönstret inte ligger i kanten
    desired_width = 900 
    desired_height = 980
    margin = 40
    
    app_width = min(desired_width, work_width - margin)
    app_height = min(desired_height, work_height - margin)
    
    # Centrera inom arbetsytan (inte hela skärmen!)
    center_x = work_area.left + (work_width - app_width) // 2
    center_y = work_area.top + (work_height - app_height) // 2

    cmd_args = [
        '--disable-extensions', 
        '--no-first-run', 
        '--no-default-browser-check'
    ]

    eel.start('index.html', 
              mode='chrome', 
              size=(app_width, app_height), 
              position=(center_x, center_y), 
              close_callback=on_app_close,
              cmdline_args=cmd_args,
              block=True 
    )
    is_window_open = False

# ==============================================================================================
# 8. HUVUDPROGRAM & TRAY-IKON
# ==============================================================================================

def setup_tray_ninja():
    """Skapar bakgrundsikonen utan att visa fönstret direkt."""
    global tray_icon_instance
    
    image = Image.new('RGB', (64, 64), color=(15, 32, 39))
    draw = ImageDraw.Draw(image)
    draw.rectangle((16, 16, 48, 48), fill=(8, 217, 214), outline=(255, 46, 99), width=4)
    
    def on_show(icon, item):
        threading.Thread(target=open_tb_window, daemon=True).start()

    def on_quit(icon, item):
        icon.stop()
        restore_everything_on_exit()
        os._exit(0)

    menu = pystray.Menu(
        pystray.MenuItem("Öppna True Borders", on_show, default=True),
        pystray.MenuItem("Avsluta helt", on_quit)
    )
    
    tray_icon_instance = pystray.Icon("TrueBordersNinja", image, "True Borders", menu)
    threading.Thread(target=tray_icon_instance.run, daemon=True).start()

def restore_everything_on_exit():
    """Städar upp och återställer alla spel samt systeminställningar när applikationen stängs ner."""
    try:
        set_taskbars_state(original_taskbar_autohide, False)
        
        global active_taskbar_game
        if active_taskbar_game:
            restore_borders(active_taskbar_game['name'])
            
        global known_auto_applied_games
        for game in list(known_auto_applied_games):
            restore_borders(game)
    except Exception:
        pass

def on_app_close(page, sockets):
    """Körs när användaren klickar på stängknappen i huvudfönstret."""
    restore_everything_on_exit()
    os._exit(0)

# === STARTA APPLIKATIONEN ===

original_taskbar_autohide = get_taskbar_autohide_state()
user_taskbar_preference = original_taskbar_autohide
threading.Thread(target=taskbar_monitor, daemon=True).start()
threading.Thread(target=background_auto_apply_scanner, daemon=True).start()

setup_tray_ninja()

if start_minimized:
    print("Programmet startades i bakgrunden. Klicka på ikonen för att öppna fönstret.")
    while True:
        time.sleep(1)
else:
    open_tb_window()