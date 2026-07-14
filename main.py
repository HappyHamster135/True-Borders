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
import socket
import subprocess
import keyboard
import pystray
import urllib.request
from screeninfo import get_monitors
from PIL import Image, ImageDraw
from io import BytesIO
import tkinter as tk
from tkinter import filedialog
import pywintypes

# pywebview ger oss ett eget nativt fönster (WebView2) istället för att låna
# användarens Chrome. Då dör inte appen om man dödar Chrome i Task Manager.
try:
    import webview
    WEBVIEW_AVAILABLE = True
except Exception:
    webview = None
    WEBVIEW_AVAILABLE = False

# ==============================================================================================
# 1. GLOBALA VARIABLER & INITIALISERING
# ==============================================================================================

CURRENT_VERSION = "1.3.0"
UPDATE_INFO_URL = "https://raw.githubusercontent.com/HappyHamster135/True-Borders/main/update.json"

tray_icon_instance = None
active_taskbar_game = None
taskbar_is_hidden = False
original_taskbar_autohide = False
hotkey_enabled = False
current_hotkey = 'ctrl+shift+b'
user_taskbar_preference = None
is_window_open = False
last_intentional_move_ts = 0.0
is_user_dragging = False

# Hantera DPI-skalning för att få korrekta fönsterstorlekar på högupplösta skärmar
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    ctypes.windll.user32.SetProcessDPIAware()

eel.init('web')

# WebView2 HTTP-cachar annars ui-filerna i storage-mappen, vilket kan ge
# GAMMAL JavaScript mot NY Python efter en appuppdatering. no-cache tvingar
# en revalidering (304 om oförändrad, så det kostar inget lokalt).
try:
    import bottle as _bottle

    @_bottle.hook('after_request')
    def _no_stale_ui_cache():
        _bottle.response.set_header('Cache-Control', 'no-cache')
except Exception:
    pass

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


# Set över spel vi redan varnat om så vi inte spammar
_blocked_games = set()

def safe_set_window_pos(hwnd, hwnd_insert_after, x, y, cx, cy, flags, window_title=None):
    """
    Wrapper runt win32gui.SetWindowPos som hanterar Access Denied tyst.
    För spel som fungerar är beteendet identiskt med direkt-anrop.
    """
    try:
        win32gui.SetWindowPos(hwnd, hwnd_insert_after, x, y, cx, cy, flags)
        return True
    except pywintypes.error as e:
        if e.winerror == 5:  # ERROR_ACCESS_DENIED
            if window_title and window_title not in _blocked_games:
                _blocked_games.add(window_title)
                already_admin = False
                try:
                    already_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
                except Exception:
                    pass
                print(f"[True Borders] '{window_title}' blockerades av Windows (admin krävs).")
                try:
                    eel.notify_blocked_game(window_title, already_admin)()
                except Exception:
                    pass
            return False
        # Andra fel: logga en gång, fortsätt tyst
        if window_title and window_title not in _blocked_games:
            _blocked_games.add(window_title)
            print(f"[True Borders] SetWindowPos misslyckades för '{window_title}': {e}")
        return False

@eel.expose
def restart_as_admin():
    """Startar om True Borders med UAC-prompt och stänger den nuvarande
    instansen. UI-fönstret ägs numera av vår egen process (pywebview),
    så det räcker att avsluta oss själva — inget Chrome att jaga."""
    try:
        if getattr(sys, 'frozen', False):
            exe_path = sys.executable
            params = ""
        else:
            exe_path = sys.executable
            params = f'"{os.path.abspath(sys.argv[0])}"'

        result = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", exe_path, params, None, 1
        )

        if result <= 32:
            return False

        try:
            restore_everything_on_exit()
        except Exception:
            pass

        def shutdown_self():
            # Liten delay så Eel hinner skicka success-värdet till JS
            time.sleep(0.4)
            try:
                if _webview_window is not None:
                    _webview_window.destroy()
            except Exception:
                pass
            # Låt WebView2 flusha localStorage innan processen dör
            time.sleep(2.5)
            os._exit(0)

        threading.Thread(target=shutdown_self, daemon=True).start()
        return True

    except Exception as e:
        print(f"Kunde inte starta om som admin: {e}")
        return False


@eel.expose
def quit_app():
    """Stänger hela appen snyggt (anropas från UI:ts Exit-knapp)."""
    def _quit():
        time.sleep(0.15)
        on_app_close(None, None)
    threading.Thread(target=_quit, daemon=True).start()
    return True


@eel.expose
def save_ui_pref(key, value):
    """Speglar viktiga UI-val (tema, hotkey, sortering) till settings.json.
    WebView2:s localStorage kan gå förlorad vid hård avstängning eller
    uppdatering — då återställer frontend sig från den här kopian."""
    try:
        settings = {}
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r") as f:
                settings = json.load(f)
        prefs = settings.get("ui_prefs") or {}
        prefs[str(key)] = value
        settings["ui_prefs"] = prefs
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f, indent=4)
        return True
    except Exception:
        return False


@eel.expose
def get_ui_prefs():
    return get_setting("ui_prefs", {}) or {}

# ==============================================================================================
# 2. PROFILHANTERING OCH AUTO-LAUNCHER
# ==============================================================================================

@eel.expose
def save_profile(game_name, data):
    # Spara aldrig profiler utan riktigt namn (skräpprofiler med tom nyckel
    # har tidigare kunnat kapa systemfönster som TextInputHost).
    if not game_name or not str(game_name).strip():
        return False

    profiles = get_all_profiles()
    if game_name not in profiles:
        profiles[game_name] = {}
        # Ny profil: stämpla när den skapades (för "senast tillagd"-sortering)
        data['createdAt'] = time.time()

    icon_b64 = get_window_icon_base64(game_name)
    if icon_b64:
        data['icon'] = icon_b64

    # Försök automatiskt hitta spelets exe-fil via den aktiva processen
    hwnd = find_real_game_window(game_name)
    if hwnd != 0:
        exe_path = _get_window_exe_path_cached(hwnd)
        if exe_path:
            data['exePath'] = exe_path
            # Steam-spel? Spara AppID så ▶ kan starta via Steam.
            if 'steamAppId' not in profiles[game_name]:
                appid = _detect_steam_appid(exe_path)
                if appid:
                    data['steamAppId'] = appid

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


def sanitize_profiles_on_startup():
    """Rensar bort trasiga profiler: tomma namn eller profiler vars exe är
    en svartlistad process (webbläsare/systemfönster som råkat sparas)."""
    try:
        profiles = get_all_profiles()
        cleaned = {}
        removed = []
        for name, data in profiles.items():
            if not name or not str(name).strip():
                removed.append(repr(name))
                continue
            exe = (data or {}).get('exePath')
            if exe and os.path.basename(exe).lower() in BLACKLISTED_EXES:
                removed.append(name)
                continue
            cleaned[name] = data

        # Backfyll createdAt för äldre profiler (i nuvarande listordning) så
        # att "senast tillagd"-sorteringen har något att gå på. Nya profiler
        # får riktiga tidsstämplar som alltid sorterar över dessa.
        changed = bool(removed)
        for idx, (name, data) in enumerate(cleaned.items()):
            if isinstance(data, dict) and 'createdAt' not in data:
                data['createdAt'] = float(idx)
                changed = True

        if changed:
            if removed:
                print(f"[SANERING] Tog bort trasiga profiler: {removed}")
            with open(PROFILES_FILE, "w") as f:
                json.dump(cleaned, f, indent=4)
    except Exception as e:
        print(f"[SANERING] Kunde inte rensa profiler: {e}")

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

def _detect_steam_appid(exe_path):
    """Hittar spelets Steam-AppID genom att läsa appmanifest-filen i samma
    Steam-bibliotek som exe:n ligger i. Returnerar id-sträng eller None."""
    try:
        if not exe_path:
            return None
        parts = exe_path.replace('/', '\\').split('\\')
        lower = [p.lower() for p in parts]
        if 'steamapps' not in lower:
            return None
        sa_idx = lower.index('steamapps')
        # Sökvägen ska vara ...\steamapps\common\<mappnamn>\...
        if sa_idx + 2 >= len(parts) or lower[sa_idx + 1] != 'common':
            return None
        install_dir = parts[sa_idx + 2]
        steamapps_dir = '\\'.join(parts[:sa_idx + 1])

        import glob
        import re
        for manifest in glob.glob(os.path.join(steamapps_dir, 'appmanifest_*.acf')):
            try:
                with open(manifest, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                m_dir = re.search(r'"installdir"\s+"([^"]+)"', content)
                if m_dir and m_dir.group(1).lower() == install_dir.lower():
                    m_id = re.search(r'"appid"\s+"(\d+)"', content)
                    if m_id:
                        return m_id.group(1)
            except Exception:
                continue
    except Exception:
        pass
    return None


@eel.expose
def launch_game(game_name):
    profile = get_profile(game_name)
    if not profile:
        return False

    # Stämpla "senast använd" för sorteringen i profillistan
    try:
        profiles_all = get_all_profiles()
        if game_name in profiles_all:
            profiles_all[game_name]['lastUsed'] = time.time()
            with open(PROFILES_FILE, 'w') as f:
                json.dump(profiles_all, f, indent=4)
    except Exception:
        pass

    # Tvinga Terraria till windowed INNAN start (config skrivs medan spelet är stängt)
    try:
        force_terraria_windowed(game_name)
    except Exception:
        pass

    # Steam-spel startas via Steam-protokollet — robustare än att köra exe:n
    # direkt (DRM-omstart via Steam, rätt launch-options, osv).
    steam_id = str(profile.get('steamAppId') or '').strip()
    if steam_id.isdigit():
        try:
            os.startfile(f"steam://rungameid/{steam_id}")
            return True
        except Exception:
            pass  # Steam saknas? Falla tillbaka till exe-start nedan.

    exe_path = profile.get('exePath')
    if exe_path and os.path.exists(exe_path):
        try:
            working_dir = os.path.dirname(exe_path)
            subprocess.Popen([exe_path], cwd=working_dir)
            return True
        except Exception:
            return False
    return False


@eel.expose
def set_profile_favorite(game_name, is_fav):
    """Stjärnmärker en profil så den sorteras överst i listan."""
    profiles = get_all_profiles()
    if game_name in profiles:
        profiles[game_name]['favorite'] = bool(is_fav)
        with open(PROFILES_FILE, 'w') as f:
            json.dump(profiles, f, indent=4)
        return True
    return False


@eel.expose
def update_steam_appid(game_name, appid):
    """Manuell ändring av Steam-AppID från profilinställningarna."""
    profiles = get_all_profiles()
    if game_name in profiles:
        profiles[game_name]['steamAppId'] = str(appid or '').strip()
        with open(PROFILES_FILE, 'w') as f:
            json.dump(profiles, f, indent=4)
        return True
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
        # Ny sökväg = nytt spel-bibliotek; detektera om Steam-AppID
        appid = _detect_steam_appid(new_path)
        if appid:
            profiles[game_name]['steamAppId'] = appid
        with open(PROFILES_FILE, 'w') as f:
            json.dump(profiles, f, indent=4)
        return True
    return False

# ==============================================================================================
# 3. KÄRNFUNKTIONER FÖR BORDERLESS
# ==============================================================================================

# Processer som ALDRIG får bli borderless eller matchas som spel.
# Nyckeln är exe-filnamnet i gemener. Detta är mycket mer robust än
# titel-filter eftersom fönstertitlar kan vara vad som helst (en Explorer-
# mapp eller browser-flik kan heta exakt samma sak som ett spel).
BLACKLISTED_EXES = {
    # Webbläsare
    'chrome.exe', 'msedge.exe', 'firefox.exe', 'opera.exe', 'opera_gx.exe',
    'brave.exe', 'vivaldi.exe', 'arc.exe', 'librewolf.exe', 'waterfox.exe',
    'iexplore.exe', 'chromium.exe', 'thorium.exe', 'floorp.exe', 'zen.exe',
    'msedgewebview2.exe',
    # Windows-systemet
    'explorer.exe', 'systemsettings.exe', 'taskmgr.exe', 'textinputhost.exe',
    'searchhost.exe', 'searchapp.exe', 'startmenuexperiencehost.exe',
    'shellexperiencehost.exe', 'lockapp.exe', 'regedit.exe', 'mmc.exe',
    'control.exe', 'dwm.exe', 'sihost.exe', 'conhost.exe', 'openconsole.exe',
    'windowsterminal.exe', 'wt.exe', 'cmd.exe', 'powershell.exe', 'pwsh.exe',
    # Spel-launchers och butiker (aldrig själva spelet)
    'steam.exe', 'steamwebhelper.exe', 'epicgameslauncher.exe', 'epicwebhelper.exe',
    'battle.net.exe', 'galaxyclient.exe', 'goggalaxy.exe',
    'riotclientservices.exe', 'riotclientux.exe', 'riotclientuxrender.exe',
    'eadesktop.exe', 'origin.exe', 'upc.exe', 'ubisoftconnect.exe', 'uplay.exe',
    'playnite.desktopapp.exe', 'playnite.fullscreenapp.exe', 'itch.exe',
    'curseforge.exe', 'overwolf.exe',
    # Kommunikation & media
    'discord.exe', 'discordptb.exe', 'discordcanary.exe', 'slack.exe',
    'teams.exe', 'ms-teams.exe', 'telegram.exe', 'whatsapp.exe', 'signal.exe',
    'zoom.exe', 'spotify.exe', 'vlc.exe', 'wmplayer.exe', 'mpc-hc64.exe',
    # Verktyg & kontor
    'obs64.exe', 'obs32.exe', 'sharex.exe', 'notepad.exe', 'notepad++.exe',
    'wordpad.exe', 'winword.exe', 'excel.exe', 'powerpnt.exe', 'outlook.exe',
    'onenote.exe', 'code.exe', 'devenv.exe', 'rider64.exe', 'pycharm64.exe',
    'idea64.exe', 'sublime_text.exe',
}

# Cache: hwnd -> (pid, exe_path). Gör att vi bara behöver köra OpenProcess
# EN gång per fönster istället för på varje poll (viktigt för mjuk drag).
_hwnd_exe_cache = {}

# Cache: söktitel/profilnamn -> (hwnd, exe_normcase). Gör att vi hittar samma
# fönster igen även om spelet BYTER TITEL (t.ex. Baldur's Gate 3 som har
# upplösningen i titeln), och slipper dyra EnumWindows-svep på varje anrop.
_window_find_cache = {}


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


def _get_window_exe_path_cached(hwnd):
    """Som _get_window_exe_path men cachad per (hwnd, pid)."""
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
    except Exception:
        return None
    if not pid:
        return None
    entry = _hwnd_exe_cache.get(hwnd)
    if entry is not None and entry[0] == pid:
        return entry[1]
    exe = _get_window_exe_path(hwnd)
    # Håll cachen liten: rensa döda fönster om den växer
    if len(_hwnd_exe_cache) > 512:
        for h in list(_hwnd_exe_cache.keys()):
            if not win32gui.IsWindow(h):
                _hwnd_exe_cache.pop(h, None)
    _hwnd_exe_cache[hwnd] = (pid, exe)
    return exe


def _is_blacklisted_window(hwnd):
    """True om fönstret tillhör oss själva eller en svartlistad process
    (webbläsare, Explorer, launchers m.m.)."""
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid == os.getpid():
            return True
    except Exception:
        pass
    exe = _get_window_exe_path_cached(hwnd)
    if exe and os.path.basename(exe).lower() in BLACKLISTED_EXES:
        return True
    return False


def _remember_window(search_key, hwnd):
    """Sparar kopplingen söknamn -> fönster så vi återfinner det titel-oberoende."""
    exe = _get_window_exe_path_cached(hwnd)
    _window_find_cache[search_key] = (hwnd, os.path.normcase(exe) if exe else None)


def _cached_window_for(search_key):
    """Returnerar tidigare hittat fönster om det fortfarande lever och ägs av
    samma exe (skydd mot återanvända fönster-handles). Annars 0."""
    entry = _window_find_cache.get(search_key)
    if not entry:
        return 0
    hwnd, exe_norm = entry
    try:
        if not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd):
            raise ValueError
        if exe_norm:
            current_exe = _get_window_exe_path_cached(hwnd)
            if current_exe and os.path.normcase(current_exe) != exe_norm:
                raise ValueError
        return hwnd
    except Exception:
        _window_find_cache.pop(search_key, None)
        return 0


def _enum_candidate_windows():
    """Listar synliga 'riktiga' fönster (rimlig storlek, har titel).
    Webbläsare, Explorer och andra svartlistade processer filtreras bort."""
    candidates = []
    def cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd).strip()
        if not title or title in EXACT_IGNORE:
            return True
        # Ignorera webbläsare och overlays på titel-nivå
        if any(sub in title for sub in SUBSTRING_IGNORE):
            return True
        rect = win32gui.GetWindowRect(hwnd)
        w, h = rect[2] - rect[0], rect[3] - rect[1]
        if w > 100 and h > 100 and not _is_blacklisted_window(hwnd):
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

    candidates = _enum_candidate_windows()
    for name in profiles:
        if find_window_for_profile(name, profiles, candidates) == live_hwnd:
            return name
    return None


@eel.expose
def get_running_profile_names():
    """Returnerar profilnamn som just nu har ett levande fönster (via exe/ikon),
    så det funkar även för spel som bytt fönstertitel (t.ex. Terraria)."""
    profiles = get_all_profiles()
    running = []
    candidates = None
    for name in profiles:
        if _cached_window_for(name):
            running.append(name)
            continue
        if candidates is None:
            candidates = _enum_candidate_windows()
        hwnd = find_window_for_profile(name, profiles, candidates)
        if hwnd:
            _remember_window(name, hwnd)
            running.append(name)
    return running


def find_window_for_profile(profile_name, profiles=None, candidates=None):
    """Hittar det levande fönstret för en sparad profil – robust mot spel som
    byter fönstertitel (t.ex. Terraria, vars titel kan bli vad som helst).

    Poäng per kandidatfönster:
      exakt exe-sökväg  -> starkast (titel-oberoende)
      samma exe-filnamn -> näst starkast
      ikon matchar      -> reserv om exe saknas
      titel matchar     -> snabb men opålitlig för spel med slumpad titel

    Skydd: om profilen HAR en sparad exe och kandidatens exe är en HELT ANNAN
    så räknas inte lös titel-likhet ('substring') längre — det var så
    webbläsare/Explorer-fönster med spel-liknande titlar kunde kapas."""
    if profiles is None:
        profiles = get_all_profiles()
    profile = profiles.get(profile_name) or {}

    if candidates is None:
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

        # 1) Exe-sökväg (titel-oberoende, starkaste signalen)
        exe_state = 'unknown'
        if saved_exe_norm:
            win_exe = _get_window_exe_path_cached(hwnd)
            if win_exe:
                if os.path.normcase(win_exe) == saved_exe_norm:
                    exe_state = 'full'
                    score += 250
                elif os.path.basename(win_exe).lower() == saved_exe_base:
                    exe_state = 'base'
                    score += 180
                else:
                    exe_state = 'mismatch'

        # 2) Titel (snabb men opålitlig)
        if name_l and title_l == name_l:
            score += 100
        elif name_l and (name_l in title_l or title_l in name_l):
            # Lös titel-likhet räknas bara om exe:n inte MOTSÄGER matchen
            if exe_state != 'mismatch':
                score += 60

        # 3) Ikon (endast reserv när profilen saknar exe-sökväg)
        if saved_icon and not saved_exe_norm and score < 60:
            if get_icon_base64(hwnd) == saved_icon:
                score += 150

        if score > best_score or (score == best_score and area > best_area):
            best_hwnd, best_score, best_area = hwnd, score, area

    # Minsta säkerhet så vi aldrig kapar ett orelaterat fönster.
    return best_hwnd if best_score >= 60 else 0


def find_real_game_window(search_title):
    if not search_title or not search_title.strip():
        return 0

    # 0) Snabbspår: samma fönster som förra gången (överlever titelbyten,
    #    t.ex. BG3 som skriver in upplösningen i sin titel).
    cached = _cached_window_for(search_title)
    if cached:
        return cached

    try:
        profiles = get_all_profiles()
        if search_title in profiles:
            hwnd = find_window_for_profile(search_title, profiles)
            if hwnd:
                _remember_window(search_title, hwnd)
                return hwnd
    except Exception:
        pass

    found_hwnds = []
    def callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd).strip()
            # Ignorera systemfönster, webbläsare och overlays
            if not title or title in EXACT_IGNORE or any(sub in title for sub in SUBSTRING_IGNORE):
                return True
            if search_title.lower() in title.lower():
                rect = win32gui.GetWindowRect(hwnd)
                w, h = rect[2] - rect[0], rect[3] - rect[1]
                if w > 100 and h > 100 and not _is_blacklisted_window(hwnd):
                    found_hwnds.append((hwnd, w * h))
        return True
    win32gui.EnumWindows(callback, None)
    if not found_hwnds:
        return 0
    found_hwnds.sort(key=lambda x: x[1], reverse=True)
    best = found_hwnds[0][0]
    _remember_window(search_title, best)
    return best

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
    
def _clamp_to_virtual_screen(x, y, w, h):
    """Ser till att fönstret hamnar inom den totala skärmytan (alla monitorer).
    Skyddar mot sparade positioner från en skärm som inte längre finns."""
    try:
        user32 = ctypes.windll.user32
        vx = user32.GetSystemMetrics(76)   # SM_XVIRTUALSCREEN
        vy = user32.GetSystemMetrics(77)   # SM_YVIRTUALSCREEN
        vw = user32.GetSystemMetrics(78)   # SM_CXVIRTUALSCREEN
        vh = user32.GetSystemMetrics(79)   # SM_CYVIRTUALSCREEN
        x = max(vx, min(int(x), vx + vw - int(w)))
        y = max(vy, min(int(y), vy + vh - int(h)))
    except Exception:
        pass
    return int(x), int(y)


@eel.expose
def init_borderless(window_title, ui_x=None, ui_y=None, ui_w=None, ui_h=None):
    print(f"[INIT] init_borderless('{window_title}', ui_x={ui_x})")
    hwnd = find_real_game_window(window_title)
    if hwnd == 0:
        return False

    # Säkerhetsspärr: gör aldrig webbläsare/Explorer/systemfönster borderless
    if _is_blacklisted_window(hwnd):
        return False

    profile = get_profile(window_title)
    rect = win32gui.GetWindowRect(hwnd)
    client_rect = win32gui.GetClientRect(hwnd)

    style = win32gui.GetWindowLong(hwnd, GWL_STYLE)

    def _current_client_origin():
        try:
            pt = win32gui.ClientToScreen(hwnd, (0, 0))
            return pt[0], pt[1]
        except Exception:
            return rect[0], rect[1]

    # Hantera positionering beroende på om vi har sparade inställningar, UI-indata eller standardvärden
    if ui_x is not None:
        target_x, target_y = ui_x, ui_y
        target_w, target_h = ui_w, ui_h
    elif profile:
        # Saknar profilen position (äldre profiler sparade bara storlek) så
        # behåller vi fönstrets NUVARANDE plats istället för att kasta det
        # till (0,0) längst till vänster på skärmytan.
        if profile.get('realX') is not None and profile.get('realY') is not None:
            target_x = profile['realX']
            target_y = profile['realY']
        else:
            target_x, target_y = _current_client_origin()
        target_w = profile.get('resW', client_rect[2])
        target_h = profile.get('resH', client_rect[3])
    else:
        target_x, target_y = _current_client_origin()
        target_w, target_h = client_rect[2], client_rect[3]

    target_x, target_y = _clamp_to_virtual_screen(target_x, target_y, target_w, target_h)

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

    global last_intentional_move_ts
    last_intentional_move_ts = time.time()

    # Läk profilen: spara exe-sökväg och position om de saknas, så gamla
    # profiler blir robusta och alltid applicerar på rätt plats nästa gång.
    global active_taskbar_game
    try:
        if profile:
            profile_changed = False
            if not profile.get('exePath'):
                exe_path = _get_window_exe_path_cached(hwnd)
                if exe_path:
                    profile['exePath'] = exe_path
                    profile_changed = True
                    if 'steamAppId' not in profile:
                        appid = _detect_steam_appid(exe_path)
                        if appid:
                            profile['steamAppId'] = appid
            if profile.get('realX') is None or profile.get('realY') is None:
                profile['realX'] = int(target_x)
                profile['realY'] = int(target_y)
                profile_changed = True
            # Stämpla "senast använd" (max en skrivning per minut per spel)
            now = time.time()
            if now - float(profile.get('lastUsed') or 0) > 60:
                profile['lastUsed'] = now
                profile_changed = True
            if profile_changed:
                profiles = get_all_profiles()
                profiles[window_title] = profile
                with open(PROFILES_FILE, 'w') as f:
                    json.dump(profiles, f, indent=4)
    except Exception:
        pass

    if profile:
        active_taskbar_game = {
            'name': window_title,
            'hide': profile.get('hideTaskbar', False),
            'disable': profile.get('disableTaskbar', False),
            'letterbox': profile.get('letterbox', False),
            'mouseLock': profile.get('mouseLock', False),
            'realX': int(target_x),
            'realY': int(target_y),
            'resW': int(target_w),
            'resH': int(target_h)
        }
    else:
        active_taskbar_game = {'name': window_title, 'hide': False, 'disable': False,
                               'letterbox': False, 'mouseLock': False}

    return True

@eel.expose
def restore_borders(window_title):
    global active_taskbar_game, taskbar_is_hidden

    set_game_topmost(window_title, False)

    if active_taskbar_game and active_taskbar_game.get('name') == window_title:
        active_taskbar_game = None

    # Släpp muslåset och göm letterbox-panelerna direkt (trådsäkra anrop)
    _release_cursor_clip()
    _hide_letterbox()

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
def begin_user_drag():
    global is_user_dragging, last_intentional_move_ts
    is_user_dragging = True
    last_intentional_move_ts = time.time()
    print("[DRAG] BEGIN")

@eel.expose
def end_user_drag():
    global is_user_dragging, last_intentional_move_ts
    is_user_dragging = False
    last_intentional_move_ts = time.time()
    print("[DRAG] END")

@eel.expose
def update_window_pos(window_title, x, y, w, h):
    if x is None or y is None:
        return

    hwnd = find_real_game_window(window_title)
    if hwnd != 0:
        flags = 0x0004 | 0x0010 | 0x4000
        success = safe_set_window_pos(hwnd, 0, int(x), int(y), int(w), int(h), flags, window_title)

        if not success:
            return  # Spelet kan inte manipuleras, hoppa över state-uppdateringen

        # Markera flytten som avsiktlig så taskbar-monitorn inte "rättar
        # tillbaka" fönstret mitt under en pågående justering (hackighet).
        global last_intentional_move_ts
        last_intentional_move_ts = time.time()

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
# 3.5 LETTERBOX & MUSLÅS (per profil: svärta ytan runt spelet / lås muspekaren)
# ==============================================================================================

# Panelerna skapas och positioneras av taskbar_monitor-tråden (som pumpar
# meddelanden åt dem). De förstörs aldrig under körning — bara göms — så att
# alla anrop är trådsäkra oavsett varifrån de kommer.
_letterbox_panels = []
_letterbox_class_registered = False
_letterbox_last_layout = None
_cursor_is_clipped = False


def _letterbox_wndproc(hwnd, msg, wparam, lparam):
    if msg == win32con.WM_LBUTTONDOWN:
        # Klick på den svarta ytan -> ge spelet fokus igen
        try:
            if active_taskbar_game:
                game_hwnd = find_real_game_window(active_taskbar_game['name'])
                if game_hwnd:
                    win32gui.SetForegroundWindow(game_hwnd)
        except Exception:
            pass
        return 0
    return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)


def _register_letterbox_class():
    global _letterbox_class_registered
    if _letterbox_class_registered:
        return True
    try:
        wc = win32gui.WNDCLASS()
        wc.lpszClassName = "TrueBordersLetterbox"
        wc.hInstance = win32gui.GetModuleHandle(None)
        wc.hbrBackground = win32gui.GetStockObject(win32con.BLACK_BRUSH)
        wc.lpfnWndProc = _letterbox_wndproc
        win32gui.RegisterClass(wc)
        _letterbox_class_registered = True
        return True
    except Exception:
        return False


def _game_monitor_rect(game_hwnd):
    """Hela skärmytan (inte arbetsytan) för monitorn där spelet ligger."""
    try:
        MONITOR_DEFAULTTONEAREST = 2
        hmon = ctypes.windll.user32.MonitorFromWindow(game_hwnd, MONITOR_DEFAULTTONEAREST)

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                        ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            r = mi.rcMonitor
            return (r.left, r.top, r.right, r.bottom)
    except Exception:
        pass
    return None


def _hide_letterbox():
    """Trådsäker: göm alla paneler (ShowWindow fungerar från valfri tråd)."""
    global _letterbox_last_layout
    _letterbox_last_layout = None
    for p in _letterbox_panels:
        try:
            if win32gui.IsWindowVisible(p):
                win32gui.ShowWindow(p, 0)
        except Exception:
            pass


def _sync_letterbox(game_hwnd, show):
    """Skapar/positionerar/visar de svarta panelerna runt spelfönstret.
    Får ENDAST anropas från taskbar_monitor-tråden (ägartråd + pump)."""
    global _letterbox_last_layout

    if not show:
        if _letterbox_last_layout is not None or any(
            win32gui.IsWindowVisible(p) for p in _letterbox_panels
        ):
            _hide_letterbox()
        return

    if not _register_letterbox_class():
        return

    try:
        game_rect = win32gui.GetWindowRect(game_hwnd)
        mon = _game_monitor_rect(game_hwnd)
        if not mon:
            return
        gl, gt, gr, gb = game_rect
        ml, mt, mr, mb = mon

        # Fyra remsor: vänster, höger, topp, botten (klippta mot skärmen)
        strips = [
            (ml, mt, max(0, gl - ml), mb - mt),
            (gr, mt, max(0, mr - gr), mb - mt),
            (max(ml, gl), mt, min(mr, gr) - max(ml, gl), max(0, gt - mt)),
            (max(ml, gl), gb, min(mr, gr) - max(ml, gl), max(0, mb - gb)),
        ]

        while len(_letterbox_panels) < 4:
            ex_style = win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_NOACTIVATE
            panel = win32gui.CreateWindowEx(
                ex_style, "TrueBordersLetterbox", None, win32con.WS_POPUP,
                0, 0, 0, 0, 0, 0, win32gui.GetModuleHandle(None), None,
            )
            _letterbox_panels.append(panel)

        layout = (game_rect, mon)
        needs_move = _letterbox_last_layout != layout
        _letterbox_last_layout = layout

        flags = win32con.SWP_NOACTIVATE | win32con.SWP_SHOWWINDOW
        for panel, (x, y, w, h) in zip(_letterbox_panels, strips):
            if w <= 0 or h <= 0:
                if win32gui.IsWindowVisible(panel):
                    win32gui.ShowWindow(panel, 0)
                continue
            if needs_move or not win32gui.IsWindowVisible(panel):
                # Lägg panelen direkt UNDER spelet i z-ordningen
                win32gui.SetWindowPos(panel, game_hwnd, x, y, w, h, flags)
    except Exception:
        pass


def _set_cursor_clip(game_hwnd):
    """Låser muspekaren till spelets klientyta (det synliga spelet)."""
    global _cursor_is_clipped
    try:
        cr = win32gui.GetClientRect(game_hwnd)
        left, top = win32gui.ClientToScreen(game_hwnd, (cr[0], cr[1]))
        right, bottom = win32gui.ClientToScreen(game_hwnd, (cr[2], cr[3]))
        if right <= left or bottom <= top:
            return
        rect = wintypes.RECT(left, top, right, bottom)
        if ctypes.windll.user32.ClipCursor(ctypes.byref(rect)):
            _cursor_is_clipped = True
    except Exception:
        pass


def _release_cursor_clip():
    global _cursor_is_clipped
    if _cursor_is_clipped:
        try:
            ctypes.windll.user32.ClipCursor(None)
        except Exception:
            pass
        _cursor_is_clipped = False

# ==============================================================================================
# 4. FÖNSTER & SKÄRM-AVLÄSNING (Listor, Ikoner)
# ==============================================================================================

EXACT_IGNORE = ["Program Manager", "Settings", "Microsoft Text Input Application", "Windows Input Experience", "True Borders", "Task Manager", "Aktivitetshanteraren"]
SUBSTRING_IGNORE = [
    "Overlay", "Default IME",
    " - Opera", " - Google Chrome", " - Mozilla Firefox",
    " - Microsoft Edge", " - Brave", " - Vivaldi",
    " - YouTube",        # YouTube-tabs som kan ha snälla titlar
    " — Mozilla Firefox", # firefox använder em-dash ibland
    "- Discord",         # Discord-meddelanden om spel
    "Twitch",            # Streams av spelet
    "Steam Community",   # Steam-foruminlägg
]

def _is_valid_user_window(hwnd):
    """Hjälpfunktion för att filtrera bort bakgrundsprogram och överlägg när vi listar öppna fönster."""
    if not win32gui.IsWindowVisible(hwnd) or win32gui.GetWindowTextLength(hwnd) == 0:
        return False, ""
    title = win32gui.GetWindowText(hwnd).strip()
    if not title or title in EXACT_IGNORE or any(sub in title for sub in SUBSTRING_IGNORE):
        return False, ""
    # Webbläsare, Explorer, launchers m.m. ska inte gå att välja som spel
    if _is_blacklisted_window(hwnd):
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
def update_advanced_settings(window_title, hide, disable, on_top, border_fix,
                             auto_apply=True, letterbox=False, mouse_lock=False):
    profiles = get_all_profiles()
    if window_title in profiles:
        profiles[window_title]['hideTaskbar'] = hide
        profiles[window_title]['disableTaskbar'] = disable
        profiles[window_title]['alwaysOnTop'] = on_top
        profiles[window_title]['borderFix'] = border_fix
        profiles[window_title]['autoApply'] = auto_apply
        profiles[window_title]['letterbox'] = letterbox
        profiles[window_title]['mouseLock'] = mouse_lock
        with open(PROFILES_FILE, 'w') as f:
            json.dump(profiles, f, indent=4)

    global active_taskbar_game, taskbar_is_hidden
    if active_taskbar_game and active_taskbar_game['name'] == window_title:
        active_taskbar_game['hide'] = hide
        active_taskbar_game['disable'] = disable
        # Letterbox/muslås plockas upp av monitor-loopen inom 100 ms
        active_taskbar_game['letterbox'] = letterbox
        active_taskbar_game['mouseLock'] = mouse_lock

        # Applicera taskbar-state direkt om spelet är i förgrunden
        hwnd = find_real_game_window(window_title)
        is_foreground = (hwnd != 0 and win32gui.GetForegroundWindow() == hwnd)

        if is_foreground:
            if hide or disable:
                set_taskbars_state(hide, disable)
                taskbar_is_hidden = True
            else:
                set_taskbars_state(False, False)
                taskbar_is_hidden = False
        else:
            # Spelet är inte i förgrunden — släck om vi just stängde av
            if not (hide or disable) and taskbar_is_hidden:
                set_taskbars_state(False, False)
                taskbar_is_hidden = False
            
    if border_fix:
        p = profiles.get(window_title)
        if p and 'realX' in p:
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
def emergency_taskbar_fix():
    """Panikknapp: återställer taskbaren till Windows standardläge (synlig,
    aktiverad, ingen autohide) oavsett vilket läge den fastnat i — t.ex.
    efter att appen dödats hårt i Aktivitetshanteraren."""
    global taskbar_is_hidden, user_taskbar_preference, original_taskbar_autohide
    try:
        user_taskbar_preference = False
        original_taskbar_autohide = False
        taskbar_is_hidden = False
        set_taskbars_state(False, False)
        return True
    except Exception:
        return False


def _heal_taskbar_if_broken():
    """Körs vid appstart: om en tidigare session dog hårt med taskbaren gömd
    eller inaktiverad lagar vi den — ett gömt/avstängt Shell_TrayWnd är
    aldrig ett normalt Windows-läge."""
    try:
        broken = []

        def cb(h, _):
            try:
                if win32gui.GetClassName(h) in ("Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
                    if not win32gui.IsWindowVisible(h) or not ctypes.windll.user32.IsWindowEnabled(h):
                        broken.append(h)
            except Exception:
                pass
            return True

        win32gui.EnumWindows(cb, None)
        if broken:
            print(f"[LÄKNING] Återställer {len(broken)} trasiga taskbar-fönster från en tidigare session")
            for h in broken:
                ctypes.windll.user32.ShowWindow(h, 5)
                ctypes.windll.user32.EnableWindow(h, True)
    except Exception:
        pass


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

        shutdown_app()
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
            shutdown_app()

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
            # Pumpa meddelanden åt letterbox-panelerna (skapade på denna tråd)
            try:
                win32gui.PumpWaitingMessages()
            except Exception:
                pass

            if not active_taskbar_game:
                if taskbar_is_hidden:
                    set_taskbars_state(False, False)
                    taskbar_is_hidden = False

                # Inget aktivt spel = inga paneler och ingen muslåsning
                _sync_letterbox(None, False)
                _release_cursor_clip()

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
                caption_returned = False

                if has_coords and not is_user_dragging and (time.time() - last_intentional_move_ts) > 1.0:
                    # Jämför KLIENT-storlek (inre yta) inte FÖNSTER-storlek (med ram).
                    # När fönstret transitionerar mellan ramad och borderless skiljer de
                    # sig kort med exakt ram-tjockleken (~16x20 px) — falskt drift.
                    client_rect = win32gui.GetClientRect(hwnd)
                    cur_x, cur_y = rect[0], rect[1]
                    cur_w = client_rect[2]
                    cur_h = client_rect[3]
                    if (abs(cur_x - active_taskbar_game['realX']) > 5 or
                        abs(cur_y - active_taskbar_game['realY']) > 5 or
                        abs(cur_w - active_taskbar_game['resW'])  > 20 or
                        abs(cur_h - active_taskbar_game['resH'])  > 20):
                        drifted = True
                    if style & WS_CAPTION:
                        caption_returned = True

                if (caption_returned or drifted) and has_coords:
                    cur_x, cur_y = rect[0], rect[1]
                    cur_w, cur_h = rect[2] - rect[0], rect[3] - rect[1]
                    time_since = time.time() - last_intentional_move_ts
                    print(f"[MONITOR] reapply: caption={caption_returned} drifted={drifted} "
                          f"dragging={is_user_dragging} time_since_move={time_since:.2f}s "
                          f"target_pos=({active_taskbar_game['realX']},{active_taskbar_game['realY']}) "
                          f"actual_pos=({cur_x},{cur_y}) "
                          f"target_size=({active_taskbar_game['resW']}x{active_taskbar_game['resH']}) "
                          f"actual_size=({cur_w}x{cur_h})")
                    force_reapply_borderless(
                        hwnd,
                        active_taskbar_game['realX'],
                        active_taskbar_game['realY'],
                        active_taskbar_game['resW'],
                        active_taskbar_game['resH'],
                    )

                foreground_hwnd = win32gui.GetForegroundWindow()
                is_borderless_now = not (style & WS_CAPTION)

                if foreground_hwnd == hwnd:
                    h_mode = active_taskbar_game.get('hide', False)
                    d_mode = active_taskbar_game.get('disable', False)
                    if (h_mode or d_mode) and not taskbar_is_hidden:
                        set_taskbars_state(h_mode, d_mode)
                        taskbar_is_hidden = True

                    # Letterbox: svärta ytan runt spelet medan det har fokus
                    _sync_letterbox(hwnd, active_taskbar_game.get('letterbox', False) and is_borderless_now)

                    # Muslås: håll pekaren inne i spelet (om-appliceras varje
                    # tick eftersom Windows kan nollställa ClipCursor själv)
                    if active_taskbar_game.get('mouseLock', False) and is_borderless_now:
                        _set_cursor_clip(hwnd)
                    else:
                        _release_cursor_clip()
                else:
                    if taskbar_is_hidden:
                        set_taskbars_state(False, False)
                        taskbar_is_hidden = False
                    # Alt-tab: släpp musen och göm panelerna direkt
                    _sync_letterbox(hwnd, False)
                    _release_cursor_clip()
            else:
                if taskbar_is_hidden:
                    set_taskbars_state(False, False)
                    taskbar_is_hidden = False
                _sync_letterbox(None, False)
                _release_cursor_clip()
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

            # Hitta alla profiler med levande fönster i ETT svep (kandidatlistan
            # byggs en gång istället för en gång per profil).
            candidates = None
            alive = set()
            for name in profiles:
                hwnd = _cached_window_for(name)
                if not hwnd:
                    if candidates is None:
                        candidates = _enum_candidate_windows()
                    hwnd = find_window_for_profile(name, profiles, candidates)
                if hwnd:
                    _remember_window(name, hwnd)
                    alive.add(name)

            # Behåll bara spel som fortfarande har ett levande fönster
            known_auto_applied_games &= alive

            for prof_name in profiles:
                if prof_name in known_auto_applied_games:
                    continue
                if prof_name not in alive:
                    continue

                known_auto_applied_games.add(prof_name)

                # Profilen har auto-apply avstängt — rör inte spelet
                if profiles[prof_name].get('autoApply', True) is False:
                    continue

                if not is_borderless(prof_name):
                    print(f"[SCANNER] init_borderless for {prof_name}")
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

_webview_window = None
_ui_server_port = None

# Namngivet Win32-event: huvudtråden väntar på detta i minimerat läge, och
# det kan signaleras BÅDE från tray-ikonen och från en andra app-instans
# (som då väcker oss istället för att starta dubbelt).
_SHOW_EVENT_NAME = "TrueBorders_ShowRequest"
_show_request_event = None


def _create_show_event():
    global _show_request_event
    try:
        k32 = ctypes.windll.kernel32
        k32.CreateEventW.restype = ctypes.c_void_p
        _show_request_event = k32.CreateEventW(None, False, False, _SHOW_EVENT_NAME)
    except Exception:
        _show_request_event = None


def _signal_show_request():
    try:
        if _show_request_event:
            ctypes.windll.kernel32.SetEvent(ctypes.c_void_p(_show_request_event))
    except Exception:
        pass


def _wait_for_show_request():
    if _show_request_event:
        INFINITE = 0xFFFFFFFF
        ctypes.windll.kernel32.WaitForSingleObject(ctypes.c_void_p(_show_request_event), INFINITE)
    else:
        # Reservläge om eventet inte kunde skapas: passiv väntan
        while not is_window_open:
            time.sleep(0.5)


def _nudge_ui_window_paint(delay=0.0):
    """WebView2 kan visa en helt tom (cremefärgad) yta när fönstret skapas
    efter en tray-start — sidan renderas i bakgrunden men kompositionen
    presenteras aldrig. En osynlig 1-pixels storleksknuff tvingar fram
    första målningen (verifierat på Win11)."""
    def _do():
        if delay:
            time.sleep(delay)
        try:
            hwnd = win32gui.FindWindow(None, "True Borders")
            if not hwnd:
                return
            rect = win32gui.GetWindowRect(hwnd)
            w, h = rect[2] - rect[0], rect[3] - rect[1]
            flags = win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE
            win32gui.SetWindowPos(hwnd, 0, rect[0], rect[1], w + 1, h, flags)
            time.sleep(0.04)
            win32gui.SetWindowPos(hwnd, 0, rect[0], rect[1], w, h, flags)
        except Exception:
            pass
    threading.Thread(target=_do, daemon=True).start()


def _pick_ui_port():
    """Väljer port för UI-servern. Vi försöker med en FAST port först så att
    origin (127.0.0.1:port) — och därmed localStorage med tema, hotkey och
    senaste spel — blir samma mellan omstarter. Är den upptagen provar vi
    nästa, och som sista utväg en slumpad ledig port."""
    for port in range(8938, 8949):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(('127.0.0.1', port))
            s.close()
            return port
        except OSError:
            s.close()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _start_eel_server():
    """Startar Eels webserver i en egen tråd (utan att öppna någon webbläsare)
    och väntar tills den svarar. Returnerar porten."""
    global _ui_server_port
    if _ui_server_port is not None:
        return _ui_server_port

    port = _pick_ui_port()

    def run_server():
        try:
            # shutdown_delay: ge sidan gott om tid att återansluta vid en
            # kort socket-blipp (t.ex. renderer-omstart) innan close_callback
            # avslutar hela appen.
            eel.start('index.html',
                      mode=None,
                      host='127.0.0.1',
                      port=port,
                      close_callback=on_app_close,
                      shutdown_delay=3.0,
                      block=True)
        except Exception as e:
            print(f"[UI] Eel-servern kraschade: {e}")

    threading.Thread(target=run_server, daemon=True).start()

    # Vänta tills servern faktiskt lyssnar innan fönstret laddar sidan
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.25):
                break
        except OSError:
            time.sleep(0.05)

    _ui_server_port = port
    return port


def _calc_window_geometry():
    """Räknar ut storlek och centrerad position inom arbetsytan (minus taskbar)."""
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

    return app_width, app_height, center_x, center_y


def open_tb_window():
    """Startar programfönstret. UI:t körs i ett eget nativt fönster (WebView2
    via pywebview) i VÅR process — appen är alltså inte längre en Chrome-
    process och överlever om användaren dödar Chrome i Task Manager.
    Måste köras på huvudtråden (nativ meddelande-loop)."""
    global is_window_open, _webview_window
    if is_window_open:
        # Om fönstret redan är öppet hämtar vi det till förgrunden
        hwnd = win32gui.FindWindow(None, "True Borders")
        if hwnd != 0:
            win32gui.ShowWindow(hwnd, 9)
            win32gui.SetForegroundWindow(hwnd)
        return

    is_window_open = True

    app_width, app_height, center_x, center_y = _calc_window_geometry()
    port = _start_eel_server()
    url = f"http://127.0.0.1:{port}/index.html"

    if WEBVIEW_AVAILABLE:
        try:
            _webview_window = webview.create_window(
                "True Borders", url,
                x=center_x, y=center_y,
                width=app_width, height=app_height,
                min_size=(900, 800),
                background_color='#efe9d8',
                text_select=False,
            )
            # Paint-knuff när sidan laddats + en reservknuff — utan dessa kan
            # fönstret bli helt tomt när appen öppnas via tray-ikonen.
            try:
                _webview_window.events.loaded += lambda *a: _nudge_ui_window_paint(0.3)
            except Exception:
                pass
            _nudge_ui_window_paint(3.0)
            # private_mode=False + storage_path gör att localStorage
            # (tema, hotkey, senaste spel) överlever omstarter.
            webview.start(
                private_mode=False,
                storage_path=os.path.join(APP_DATA_DIR, "webview"),
                gui='edgechromium',
                debug=False,
            )
            # Hit kommer vi när fönstret stängts — avsluta appen som förr.
            is_window_open = False
            on_app_close(None, None)
            return
        except Exception as e:
            print(f"[UI] pywebview misslyckades ({e}), faller tillbaka till webbläsar-läget.")
            _webview_window = None

    # FALLBACK: öppna UI:t i Chrome (app-läge) eller systemets webbläsare om
    # WebView2 av någon anledning saknas. Servern kör redan, så vi pekar bara
    # ett webbläsarfönster mot den och blockerar medan appen lever.
    try:
        import eel.browsers as eel_browsers
        eel_browsers.open(['index.html'], {
            'mode': 'chrome',
            'host': '127.0.0.1',
            'port': port,
            'app_mode': True,
            'size': (app_width, app_height),
            'position': (center_x, center_y),
            'cmdline_args': ['--disable-extensions', '--no-first-run', '--no-default-browser-check'],
        })
    except Exception as e:
        print(f"[UI] Kunde inte öppna Chrome ({e}), öppnar i standardwebbläsaren.")
        import webbrowser
        webbrowser.open(url)

    while True:
        time.sleep(3600)

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
        if is_window_open:
            # Fönstret finns redan — hämta fram det (bara Win32-anrop, trådsäkert)
            threading.Thread(target=open_tb_window, daemon=True).start()
        else:
            # Släpp fram huvudtråden som väntar på att få skapa fönstret
            _signal_show_request()

    def on_quit(icon, item):
        icon.stop()
        shutdown_app()

    menu = pystray.Menu(
        pystray.MenuItem("Öppna True Borders", on_show, default=True),
        pystray.MenuItem("Avsluta helt", on_quit)
    )
    
    tray_icon_instance = pystray.Icon("TrueBordersNinja", image, "True Borders", menu)
    threading.Thread(target=tray_icon_instance.run, daemon=True).start()

def restore_everything_on_exit():
    """Städar upp och återställer alla spel samt systeminställningar när applikationen stängs ner."""
    try:
        _release_cursor_clip()
        _hide_letterbox()
        set_taskbars_state(original_taskbar_autohide, False)
        
        global active_taskbar_game
        if active_taskbar_game:
            restore_borders(active_taskbar_game['name'])
            
        global known_auto_applied_games
        for game in list(known_auto_applied_games):
            restore_borders(game)
    except Exception:
        pass

def shutdown_app():
    """Gemensam avstängning för alla exit-vägar. Viktigt: WebView2:s
    browserprocess måste få stänga SNYGGT och hinna flusha localStorage
    (tema, hotkey m.m.) till disk — dödas den med värdprocessen via ett
    naket os._exit tappas de senaste skrivningarna och databasen kan
    markeras korrupt och rensas vid nästa start ("temat glöms bort")."""
    restore_everything_on_exit()
    try:
        if _webview_window is not None:
            _webview_window.destroy()
    except Exception:
        pass
    time.sleep(2.5)
    os._exit(0)


def on_app_close(page, sockets):
    """Körs när användaren stänger huvudfönstret (eller UI:t dör)."""
    shutdown_app()

# === STARTA APPLIKATIONEN ===

# --- EN INSTANS I TAGET ---
# Två samtidiga instanser ger ett tomt fönster (WebView2 låser sin
# lagringsmapp), så en andra start väcker den befintliga instansen istället.
_MUTEX_NAME = "TrueBorders_SingleInstance"
_single_instance_handle = None

def _acquire_single_instance(wait_seconds=3.0):
    """Försöker ta instans-mutexen. Vid 'Kör som admin'-omstart lever den
    gamla instansen en kort stund till, därför väntar vi lite innan vi ger
    upp. Returnerar handle eller None om en annan instans äger den."""
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    ERROR_ALREADY_EXISTS = 183
    deadline = time.time() + wait_seconds
    while True:
        ctypes.set_last_error(0)
        handle = k32.CreateMutexW(None, 0, _MUTEX_NAME)
        if not handle:
            return None
        if ctypes.get_last_error() != ERROR_ALREADY_EXISTS:
            return handle
        k32.CloseHandle(handle)
        if time.time() >= deadline:
            return None
        time.sleep(0.25)

_single_instance_handle = _acquire_single_instance()
if _single_instance_handle is None:
    # En annan instans kör redan — väck dess fönster (eller be den öppna ett)
    # och avsluta oss själva tyst.
    try:
        existing = win32gui.FindWindow(None, "True Borders")
        if existing:
            win32gui.ShowWindow(existing, 9)
            try:
                win32gui.SetForegroundWindow(existing)
            except Exception:
                pass
        else:
            k32 = ctypes.windll.kernel32
            k32.OpenEventW.restype = ctypes.c_void_p
            EVENT_MODIFY_STATE = 0x0002
            ev = k32.OpenEventW(EVENT_MODIFY_STATE, False, _SHOW_EVENT_NAME)
            if ev:
                k32.SetEvent(ctypes.c_void_p(ev))
                k32.CloseHandle(ctypes.c_void_p(ev))
    except Exception:
        pass
    os._exit(0)

_create_show_event()

_heal_taskbar_if_broken()
original_taskbar_autohide = get_taskbar_autohide_state()
user_taskbar_preference = original_taskbar_autohide
sanitize_profiles_on_startup()
threading.Thread(target=taskbar_monitor, daemon=True).start()
threading.Thread(target=background_auto_apply_scanner, daemon=True).start()

setup_tray_ninja()

if start_minimized:
    print("Programmet startades i bakgrunden. Klicka på ikonen för att öppna fönstret.")
    # Huvudtråden måste äga UI-loopen (WebView2), så vi väntar här tills
    # användaren klickar på tray-ikonen (eller en ny instans signalerar).
    _wait_for_show_request()

open_tb_window()