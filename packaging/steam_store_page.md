# True Borders — Steam Store Page Kit

Allt som ska in i Steamworks. Texterna är skrivna för att klistras rakt in
(långa beskrivningen är i Steams BBCode). Bildmåtten är verifierade mot
Steamworks-dokumentationen 2026-08-28.

---

## 1. Short description (max 300 tecken — denna är ~275)

> Make any windowed game borderless — and put it exactly where you want it.
> Drag your game into place on a visual map of your monitors, save the profile
> once, and True Borders applies it automatically every time the game starts.
> Built for ultrawide and multi-monitor setups.

---

## 2. About This Software (lång beskrivning, BBCode)

```
[h2]Your games. Your screen. Your rules.[/h2]
True Borders removes the window borders from any windowed game and places it exactly where you want it on your screen — pixel-perfect, every time.

Made for players on ultrawide and super-ultrawide monitors, multi-monitor setups, or anyone who wants the fullscreen feel with instant alt-tab.

[h2]The Visual Map[/h2]
No coordinates, no guesswork. True Borders shows your actual monitor layout and lets you [b]drag your game window into place[/b] — position and size apply live while you drag. Centering a 2560×1440 game on a 5120×1440 screen is one gesture.

[h2]Set it once, forget it[/h2]
Save a profile per game. Next time the game starts, True Borders finds it and applies everything automatically — size, position, borders — no matter how you launched it. Profiles survive games that change their window title or recreate their window.

[h2]What's in the box[/h2]
[list]
[*][b]Auto-apply[/b] — game starts, borders vanish. Per-game on/off.
[*][b]Launch games[/b] straight from the app (Steam games start via the Steam client).
[*][b]Taskbar control[/b] — hide or disable the taskbar while the game has focus.
[*][b]Letterbox[/b] — black out the area around the game for a true fullscreen feel.
[*][b]Mouse lock[/b] — keep the cursor inside the game window. Perfect for edge-scrolling strategy games on multi-monitor setups.
[*][b]Always on top[/b], global hotkey toggle, autostart with Windows, minimize to tray.
[*][b]Built-in fixes[/b] for stubborn games (Prison Architect, Paradox titles, Terraria and more).
[*][b]Xbox Game Pass &amp; Microsoft Store support[/b] — packaged (UWP) apps are matched, managed and launched like any other game.
[*][b]20 themes[/b], profile favorites, drag-and-drop sorting, backup &amp; import.
[/list]

[h2]DRM-free[/h2]
No account, no online check, no Steam requirement after purchase. Copy the app anywhere and it just works. Updates arrive through Steam.

[h2]Good to know[/h2]
[list]
[*]Works with games running in [b]Windowed[/b] mode — set it once in the game's own video settings.
[*]Games that run elevated may need "Restart as admin" (one click in the app).
[/list]
```

---

## 3. System requirements

| Fält | Värde |
|---|---|
| OS | Windows 10 64-bit (21H2 eller senare) / Windows 11 |
| Processor | Any x64 CPU |
| Minne | 200 MB RAM |
| Lagring | 200 MB available space |
| Övrigt | Requires Microsoft Edge WebView2 Runtime (preinstalled on Windows 11 and current Windows 10) |

## 4. Kategorisering & pris

- **App-typ:** Software → genre **Utilities**
- **Taggar:** Utilities, Software, GameDev-free tags som passar (t.ex. "Immersive")
- **Pris:** basvaluta USD **2.99** → kontrollera att EUR blir **2,99 €** (justera
  manuellt om Steams autokonvertering avviker)
- **Lanseringsrabatt:** 10 % (aktiveras i releasesteget)

---

## 5. Bildmaterial — exakta mått (verifierade i Steamworks-doks)

### Butikssidan (obligatoriska)
| Asset | Mått | Regler |
|---|---|---|
| Header capsule | **920 × 430** | Bara logotyp + titel, ingen övrig text |
| Small capsule | **462 × 174** | Logotypen ska nästan fylla ytan, läsbar i 120×45 |
| Main capsule | **1232 × 706** | Logotyp läsbar mot bakgrunden |
| Vertical capsule | **748 × 896** | Visas i reor/säsongsevent |
| Screenshots | **≥ 5 st, 1920 × 1080** | Måste visa appens riktiga UI (inga mockups); ≥ 4 markerade "suitable for all ages" |
| Page background (valfri) | 1438 × 810 | Genereras annars från sista screenshoten |

### Biblioteket (obligatoriska)
| Asset | Mått | Regler |
|---|---|---|
| Library capsule | **600 × 900** | |
| Library header | **920 × 430** | |
| Library hero | **3840 × 1240** | Ingen text; kritiskt innehåll inom safe area 860 × 380 |
| Library logo | PNG, **1280 bred och/eller 720 hög** | Transparent bakgrund |

### App-administration
| Asset | Mått |
|---|---|
| Community icon | 184 × 184 (JPG) |
| Client icon | 32 × 32 (.ico) |

### Trailer — **OBLIGATORISK för mjukvara**
- 1920×1080, 16:9, 30 eller 60 fps
- H.264 i .mp4, 5000+ Kbps, AAC-ljud 44/48 kHz
- Förslag (30–45 s skärminspelning, ingen speakerröst behövs):
  1. Ett spel startar med ram → auto-apply tar bort den (före/efter)
  2. Dra spelrutan på visuella kartan — fönstret följer live
  3. Profilfliken med många spel, en snabb temaväxling
  4. Slutplatta: logotyp + "Set it once. Forget it." + pris

### Screenshot-förslag (5 st)
1. Visuella kartan med ett spel placerat på super-ultrawide-layout
2. Profilfliken med ett gäng spel (favoriter + running-indikatorer)
3. Profilinställningarna (taskbar/letterbox/mouse lock-togglarna)
4. Samma vy i ett annat tema (visar temasystemet — fortfarande riktigt UI)
5. Onboarding-guiden eller Settings

---

## 6. Release-tidslinje (Steams regler)

1. **Steamworks-konto**: $100 app-avgift (dras av mot försäljning vid $1 000),
   identitets-/skatte-/bankuppgifter — räkna med några dagar för verifiering
2. **Skapa appen** (typ: Software), fyll i butikssidan med materialet ovan
3. **Store page review**: 3–5 arbetsdagar (skicka in ≥ 7 dagar före önskat datum)
4. **"Coming Soon" måste ligga ute i minst 2 veckor** innan release —
   wishlistor samlas under tiden
5. **Ladda upp bygget** via SteamPipe: depot = hela innehållet i
   `dist/True Borders Steam/`, launch option = `True Borders.exe`
   (bygg med `pyinstaller "True Borders Steam.spec" --noconfirm`)
6. **Build review** (separat granskning, efter att butikssidan godkänts)
7. Sätt pris + lanseringsrabatt
8. **Tryck själv på "Release App"** — inget släpps automatiskt

Snabbast möjliga väg från noll: ca 3–4 veckor (verifiering + review + 2 veckors
Coming Soon).

---

## 7. Kvar att ordna utanför Steamworks

- [ ] Privacy policy-sida (buggformuläret samlar e-post via Formspree) — länkas
      från butikssidan
- [ ] Formspree: gratisplanen tar 50 rapporter/mån — uppgradera vid behov
- [ ] Bumpa `CURRENT_VERSION` till 1.4.0 inför release
- [ ] Standalone-kanalen (GitHub releases) fortsätter som förr för befintliga
      användare — `update.json` rörs inte av Steam-lanseringen
