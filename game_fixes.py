"""Spelspecifika fixar som INTE hör hemma i den generella borderless-logiken.

Tanken med filen: main.py ska fortsätta göra exakt samma sak för alla spel som
fungerar idag. Behöver ett enskilt spel särbehandling lägger vi den här, bakom
en identitetskoll, så att `adjust_client_size()` returnerar oförändrade värden
för allt annat.


PRISON ARCHITECT
================
PA (SDL 1.2 + OpenGL) sätter sin renderyta EN gång när fönstret skapas och
läser aldrig om klientytan igen. Två saker följer av det:

1. PA ber om ett fönster på ScreenW x ScreenH (t.ex. 2560x1440) i windowed
   mode. Ryms inte fönstret MED ram (16x39 px) på skärmen klämmer PA
   klientytan så att det gör det: på en 1440 px hög skärm blir renderytan
   2560x**1401**.

2. Ändrar vi klientytan efteråt (t.ex. till profilens 2560x1440) följer inte
   renderytan med. OpenGL ritar från nedre vänstra hörnet, så bilden hamnar
   (klienthöjd - renderhöjd) px för långt ner medan musen träffar där bilden
   *borde* ha legat. Det är precis felet man ser: markeringen hamnar 1-2 rader
   under pekaren, och "Advanced border fix" (resize + z-order) biter inte
   eftersom renderytan aldrig räknas om.

Uppmätt på ett levande PA-fönster (5120x1440-skärm, ScreenH 1440, renderyta
1401) - felet är konstant per klienthöjd och oberoende av fönsterposition:

    klienthöjd 1400 -> svart band överst   0 px, träffel ~21 px
    klienthöjd 1440 -> svart band överst  39 px, träffel ~61 px
    klienthöjd 1479 -> svart band överst  78 px, träffel ~100 px

Modellen som faller ut (S = renderhöjd, R = PA:s ScreenH, C = klienthöjd):

    ritning:  fysisk_y = logisk_y + (C - S)          (OpenGL, nedre vänstra)
    mus:      spel_y   = (S/R) * (klient_y + R - S)  (oberoende av C)

Alltså: den del av felet som ÄR vårt (C - S) försvinner om vi låter klientytan
vara exakt PA:s renderyta. Resten - att PA skalar musen med S/R men ritar 1:1 -
är PA:s eget fel och finns även när spelet körs helt utan True Borders. Den
delen kan inte nollas med fönstergeometri (en skalfaktor går inte att ta bort
med en förskjutning), men den kan CENTRERAS så att felet blir litet mitt på
skärmen istället för stort i överkant. Se COMPENSATE_INPUT_SCALE.
"""

import ctypes
import json
import os
import re
import shutil
from ctypes import wintypes

import win32api
import win32con
import win32gui
import win32process

# Sätt till False för att bara matcha klientytan mot renderytan och lämna
# PA:s egen musskalning orörd (felet blir då 0 px i underkant, ~39 px i
# överkant istället för +/- halva det, jämnt fördelat).
COMPENSATE_INPUT_SCALE = True

_PA_WINDOW_CLASS = "Prison Architect"
_PA_EXES = {
    "prison architect64.exe",
    "prison architect32.exe",
    "prison architect.exe",
}

# hwnd -> True/False (fönsterhandtag återanvänds inte medan fönstret lever)
_is_pa_cache = {}
# hwnd -> (renderbredd, renderhöjd) fastlåst för ett levande spelfönster
# (sätts bara när vi skriver om spelets config, se apply_requested_resolution)
_native_size_cache = {}
# hwnd -> ScreenH som gällde när spelet startade (låses innan vi skriver om
# configen, så ett kommande upplösningsbyte inte förvirrar kompensationen)
_pinned_ref_h = {}
# hwnd -> senast loggade beslut, så vi inte spammar konsolen varje monitor-tick
_logged = {}

GWL_STYLE = -16
WS_CAPTION = 0x00C00000


def _exe_basename(hwnd):
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return ""
        try:
            size = wintypes.DWORD(1024)
            buf = ctypes.create_unicode_buffer(size.value)
            if ctypes.windll.kernel32.QueryFullProcessImageNameW(
                handle, 0, buf, ctypes.byref(size)
            ):
                return os.path.basename(buf.value).lower()
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:
        pass
    return ""


def is_prison_architect(hwnd):
    """Snabb identitetskoll. Cachas per hwnd så den kan anropas i hot paths."""
    if not hwnd:
        return False
    cached = _is_pa_cache.get(hwnd)
    if cached is not None:
        return cached

    try:
        cls = win32gui.GetClassName(hwnd)
    except Exception:
        # Fönstret hann dö mellan sökning och koll — cacha INTE ett nej, då
        # skulle ett omskapat fönster med samma handtag klassas fel för alltid.
        return False

    result = cls == _PA_WINDOW_CLASS or _exe_basename(hwnd) in _PA_EXES
    _is_pa_cache[hwnd] = result
    return result


def _frame_size():
    """Ramens bredd/höjd för ett vanligt fönster vid nuvarande DPI (16x39)."""
    try:
        rect = wintypes.RECT(0, 0, 1000, 1000)
        ctypes.windll.user32.AdjustWindowRect(ctypes.byref(rect), 0x00CF0000, False)
        return (rect.right - rect.left) - 1000, (rect.bottom - rect.top) - 1000
    except Exception:
        return 16, 39


def _monitor_size(hwnd):
    try:
        mon = win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONEAREST)
        left, top, right, bottom = win32api.GetMonitorInfo(mon)["Monitor"]
        return right - left, bottom - top
    except Exception:
        return 0, 0


def _pa_dir():
    return os.path.join(
        os.environ.get("LOCALAPPDATA", ""), "Introversion", "Prison Architect"
    )


def _pa_prefs():
    """Läser ScreenW/ScreenH ur PA:s preferences.txt (spelets egen sanning)."""
    path = os.path.join(_pa_dir(), "preferences.txt")
    values = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2 and parts[0] in ("ScreenW", "ScreenH"):
                    try:
                        values[parts[0]] = int(parts[1])
                    except ValueError:
                        pass
    except Exception:
        pass
    return values.get("ScreenW"), values.get("ScreenH")


def _requested_resolution():
    """Upplösningen PA startade med. Launcherns settings.txt vinner över
    preferences.txt (bevisat: preferences sa borderless=1 men launchern
    körde windowed ändå). None = borderless, dvs skrivbordsstorlek."""
    try:
        with open(os.path.join(_pa_dir(), "settings.txt"), encoding="utf-8") as f:
            gfx = json.load(f).get("Graphics", {})
        if gfx.get("display_mode") == "borderless":
            return None
        m = re.match(r"\s*(\d+)\s*x\s*(\d+)", gfx.get("windowed_resolution", ""))
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    w, h = _pa_prefs()
    return (w, h) if w and h else None


def _surface_size(hwnd):
    """Renderytan som PA låste när fönstret skapades.

    Räknas ALLTID ut ur spelets config + skärmen — aldrig ur fönstrets
    nuvarande klientyta. Klientytan är opålitlig så fort appen (eller
    användaren) har rört fönstret: läser vi tillbaka vår egen storlek som
    "spelets renderyta" krymper taket för varje varv och monitor-loopen
    börjar slåss med sig själv."""
    pinned = _native_size_cache.get(hwnd)
    if pinned:
        return pinned

    mon_w, mon_h = _monitor_size(hwnd)
    frame_w, frame_h = _frame_size()
    if not mon_w or not mon_h:
        return None

    req = _requested_resolution()
    if req is None:                       # borderless = hela skrivbordet, ingen ram
        return mon_w, mon_h
    return (
        min(req[0], max(320, mon_w - frame_w)),
        min(req[1], max(240, mon_h - frame_h)),
    )


def _target_height(surface_h, limit_h=None, ref_h=None):
    """Klienthöjd som ger minsta möjliga träffel.

    surface_h == R  -> PA mappar musen 1:1, klientytan ska vara exakt lika stor.
    surface_h <  R  -> PA skalar musen med k = S/R men ritar 1:1. Felet
                       E(y) = (k-1)*y + k*(R-S) + (C-S) går inte att nolla för
                       alla y, men vi väljer C så att E(C/2) = 0, dvs felet blir
                       lika stort men motsatt tecken i över- och underkant."""
    req = _requested_resolution()
    pref_h = ref_h or (req[1] if req else None)
    if not COMPENSATE_INPUT_SCALE or not pref_h or pref_h <= surface_h:
        return surface_h

    # Säkerhetsspärr: kompensera bara när preferences.txt faktiskt FÖRKLARAR
    # renderytan (renderyta == begärd höjd klämd mot skärmen). Stämmer de inte
    # överens kör spelet något annat än configen säger, och då är k fel gissad.
    if limit_h and surface_h != min(pref_h, limit_h):
        return surface_h

    k = float(surface_h) / float(pref_h)
    target = 2.0 * (surface_h - k * (pref_h - surface_h)) / (k + 1.0)
    target = int(round(target))
    # Aldrig mer än ramhöjden extra bortklippt - då är modellen fel någonstans.
    lowest = surface_h - (pref_h - surface_h) - 5
    return max(lowest, min(surface_h, target))


def adjust_client_size(hwnd, width, height):
    """Returnerar klientstorleken som ska sättas på fönstret.

    Oförändrad för alla spel utom Prison Architect.

    För PA gäller ETT tak: appen ger aldrig ett fönster som är större än vad
    spelet faktiskt renderar - då skulle ytan utanför bli ett tomt band OCH
    muspekaren hamna fel (se modulens docstring). Under taket bestämmer
    användaren fritt och fönstret ändras live som vanligt."""
    if width is None or height is None:
        return width, height
    if not is_prison_architect(hwnd):
        return width, height

    surface = _surface_size(hwnd)
    if not surface:
        return width, height

    limit = max_client_size(hwnd)
    cap_w = surface[0]
    cap_h = _target_height(surface[1], limit[1] if limit else None,
                           _pinned_ref_h.get(hwnd))

    new_w = min(int(width), cap_w)
    new_h = min(int(height), cap_h)
    if (new_w, new_h) != (int(width), int(height)) and \
            (new_w, new_h) != _logged.get(hwnd):
        _logged[hwnd] = (new_w, new_h)
        print(
            f"[FIX] Prison Architect: renderyta {surface[0]}x{surface[1]}, "
            f"begärd {width}x{height} -> kapad till {new_w}x{new_h} "
            f"(spelet renderar inte större; byt upplösning i spelet + starta om)"
        )
    return new_w, new_h


def max_client_size(hwnd):
    """Största fönster PA kan skapa i windowed mode på den här skärmen.

    PA skapar alltid fönstret MED ram och krymper renderytan tills allt får
    plats på skärmen - därför är taket skärmen minus ramen, inte skärmen."""
    mon_w, mon_h = _monitor_size(hwnd)
    frame_w, frame_h = _frame_size()
    if not mon_w or not mon_h:
        return None
    return mon_w - frame_w, mon_h - frame_h


def _is_supported_mode(width, height):
    """Är WxH ett läge skärmen rapporterar? PA snäppar till närmaste kända
    upplösning, så skriver vi något annat till configen ljuger den efteråt."""
    try:
        i = 0
        while True:
            mode = win32api.EnumDisplaySettings(None, i)
            if (mode.PelsWidth, mode.PelsHeight) == (int(width), int(height)):
                return True
            i += 1
    except Exception:
        return False


def apply_requested_resolution(hwnd, width, height):
    """Skriver användarens önskade storlek till PA:s EGNA inställningar.

    PA:s fönsterstorlek går inte att ändra utifrån - renderytan låses vid
    start - så enda vägen är spelets egen upplösning + omstart. Samma upplägg
    som Paradox- och Terraria-integrationerna.

    Returnerar en dict som frontend kan visa, eller {} för andra spel."""
    if not is_prison_architect(hwnd) or not width or not height:
        return {}

    limit = max_client_size(hwnd)
    want_w, want_h = int(width), int(height)

    # Lika stort som eller större än vad PA kan skapa: skriv INTE till spelets
    # config. PA snäpper ändå till närmaste upplösning den känner igen (testat:
    # 2560x1401 blev 2560x1440), och då skulle preferences.txt ljuga om vad
    # spelet kör - exakt det värde adjust_client_size() räknar kompensationen
    # på. Kör hellre på runtime-fixen, den bygger på uppmätt renderyta.
    if limit and (want_w > limit[0] or want_h >= limit[1]):
        eff_w, eff_h = min(want_w, limit[0]), min(want_h, limit[1])
        return {
            "changed": False,
            "clamped": True,
            "width": eff_w,
            "height": eff_h,
            "message": (
                f"⚠️ Prison Architect kan max rendera {eff_w}x{eff_h} i fönsterläge "
                f"(skärmen minus fönsterramen) — appen följer spelets renderyta "
                f"så muspekaren stämmer"
            ),
        }

    if not _is_supported_mode(want_w, want_h):
        return {
            "changed": False,
            "clamped": False,
            "width": want_w,
            "height": want_h,
            "message": (
                f"⚠️ Prison Architect tar bara upplösningar skärmen stödjer — "
                f"{want_w}x{want_h} finns inte, sätt den i spelets Graphics-meny "
                f"istället"
            ),
        }

    current_w, current_h = _pa_prefs()
    if (current_w, current_h) == (want_w, want_h):
        return {"changed": False, "clamped": False, "width": want_w,
                "height": want_h, "message": ""}

    # Spelet som körs NU har fortfarande sin gamla renderyta. Lås fast den för
    # det här fönstret innan vi skriver om configen, annars skulle
    # adjust_client_size() tro att det redan kör den nya upplösningen.
    pinned = _surface_size(hwnd)
    if pinned:
        _native_size_cache[hwnd] = pinned
    if current_h:
        _pinned_ref_h[hwnd] = current_h

    written = False

    # 1) Paradox-launchern (settings.txt) vinner över preferences.txt vid start
    settings_path = os.path.join(_pa_dir(), "settings.txt")
    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        if not os.path.exists(settings_path + ".truebackup"):
            shutil.copy(settings_path, settings_path + ".truebackup")
        cfg.setdefault("Graphics", {})["display_mode"] = "windowed"
        cfg["Graphics"]["windowed_resolution"] = f"{want_w}x{want_h}"
        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, separators=(",", ":"))
        written = True
    except Exception:
        pass

    # 2) Spelets egen preferences.txt
    prefs_path = os.path.join(_pa_dir(), "preferences.txt")
    try:
        with open(prefs_path, "r", encoding="utf-8", errors="replace") as f:
            txt = f.read()
        if not os.path.exists(prefs_path + ".truebackup"):
            shutil.copy(prefs_path, prefs_path + ".truebackup")
        txt = re.sub(r"^(ScreenW\s+)\S+", r"\g<1>%d" % want_w, txt, flags=re.M)
        txt = re.sub(r"^(ScreenH\s+)\S+", r"\g<1>%d" % want_h, txt, flags=re.M)
        txt = re.sub(r"^(ScreenWindowed\s+)\S+", r"\g<1>true", txt, flags=re.M)
        with open(prefs_path, "w", encoding="utf-8", newline="") as f:
            f.write(txt)
        written = True
    except Exception:
        pass

    if not written:
        return {}

    return {
        "changed": True,
        "clamped": False,
        "width": want_w,
        "height": want_h,
        "message": (
            f"⚠️ Prison Architect: starta om spelet för att köra {want_w}x{want_h} "
            f"(spelet låser renderytan vid start)"
        ),
    }


def skip_frame_nudge(hwnd):
    """True för spel där resize-knuffen i ramfixen gör mer skada än nytta.

    PA:s renderyta påverkas inte av en resize, så +1/-1-knuffen flyttar bara
    bilden fram och tillbaka utan att fixa något."""
    return is_prison_architect(hwnd)


"""
GRAVEYARD KEEPER 2
==================
GK2 (Unity 6) återställer WS_CAPTION så fort ett externt program tar bort den
i windowed mode. Unity synkar sin fönsterstil mot valt läge (registry
"Screenmanager Fullscreen mode" = 3/windowed) och lägger tillbaka ramen —
appen och spelet hamnar då i en evig krigsloop: caption -> strip -> caption,
och eftersom klientytan mäts mellan varven matas storleken fel (2544x1401,
2528x1362 ... en ramruta mindre per varv). Det går inte att vinna utifrån.

Fix: starta spelet med Unity-flaggan `-popupwindow`. Då bygger Unity fönstret
som popup (borderless) från början och hävdar aldrig någon ram — appen behöver
bara flytta/storlekssätta det som vanligt. Samma lösning communityn använder
för Graveyard Keeper 1 ("Set Launch Options -> -popupwindow").

Kör någon spelet UTAN flaggan (t.ex. direkt från Steam) backar appen istället:
den tar inte fajten mot ramen (skip_borderless_fight) och ber användaren starta
via profilens play-knapp.
"""

_GK2_EXES = {
    "graveyardkeeper2.exe",
}

# hwnd -> True/False (samma cache-regel som PA: cacha aldrig ett nej på ett
# fönster som hann dö mitt i kollen)
_is_gk2_cache = {}

# (profilnamn, hwnd) som redan fått play-knapps-ledtråden — ingen spam
_gk2_hinted = set()


def is_graveyard_keeper_2(hwnd):
    """Snabb identitetskoll på exe-namnet. Klassnamnet duger INTE — alla
    Unity-spel heter UnityWndClass, så där fastnar alla möjliga andra titlar."""
    if not hwnd:
        return False
    cached = _is_gk2_cache.get(hwnd)
    if cached is not None:
        return cached
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if not pid:
            return False
    except Exception:
        return False
    base = _exe_basename(hwnd)
    # _exe_basename returnerar \"\" både vid misslyckad uppslagning och för
    # fönster som hann dö — cacha inget av de fallen (se PA-noten).
    if not base:
        return False
    result = base in _GK2_EXES
    _is_gk2_cache[hwnd] = result
    return result


def is_gk2_profile(profile):
    """True om profilen pekar på Graveyard Keeper 2:s exe (titel-oberoende)."""
    try:
        exe = (profile or {}).get('exePath')
        return bool(exe) and os.path.basename(str(exe)).lower() in _GK2_EXES
    except Exception:
        return False


def launch_args_for(game_name=None, profile=None):
    """Extra startargument för en profil. ['-popupwindow'] för GK2, annars
    None (start via steam:// / exe precis som förut).

    gating bör helst ske på profilens exePath (robust mot titeländringar),
    med namnet som reserv för profiler som ännu inte sparat sin exe-sökväg."""
    if profile and is_gk2_profile(profile):
        return ['-popupwindow']
    if game_name and str(game_name).strip().lower() == 'graveyard keeper 2':
        return ['-popupwindow']
    return None


def skip_borderless_fight(hwnd):
    """True för spel där caption-strip-loopen är förlorad på förhand.

    GK2 räknas alltid hit: körs spelet i popup-läge finns det ändå ingen
    ram att slåss om, och monitor-loopens aggressiva reaply gör mer skada än
    nytta (den matar den egna storleksmätningen fel — se modulens docstring).
    Alla andra spel: False, exakt samma beteende som idag."""
    return is_graveyard_keeper_2(hwnd)


def gk2_hint_and_remember(profile_name, hwnd):
    """Ledtråd om att GK2 måste startas via appens play-knapp. Returnerar
    meddelandet första gången per (namn, hwnd), sedan None (ingen spam)."""
    if not is_graveyard_keeper_2(hwnd):
        return None
    key = (profile_name, hwnd)
    if key in _gk2_hinted:
        return None
    _gk2_hinted.add(key)
    return (
        "This game re-adds its title bar when started from Steam directly. "
        "Launch it with the \u25b6 play button in True Borders instead "
        "(opens in borderless popup mode)."
    )


def forget_window(hwnd):
    """Städa cachen när ett fönster försvinner."""
    for cache in (_is_pa_cache, _native_size_cache, _pinned_ref_h, _logged,
                  _is_gk2_cache):
        cache.pop(hwnd, None)
    for key in list(_gk2_hinted):
        if key[1] == hwnd:
            _gk2_hinted.discard(key)
