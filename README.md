# True Borders

**True Borders** is a smooth and lightweight tool built in Python that helps you manage your windows and play games in a true "Borderless Windowed" mode. The application runs quietly in the background and features a modern, built-in web interface.

## Features

* **True Borderless:** Removes unwanted window borders and forces applications or games to run in a perfect borderless mode.
* **Custom Hotkeys:** Manage your windows lightning-fast using hotkeys (e.g., `Ctrl + Shift + B`).
* **Profile Management:** Save your specific settings for different games and easily export/import profiles for backup.
* **Runs in the Background:** The application minimizes neatly to the System Tray (down by the Windows clock) so it never gets in your way.
* **Autostart:** Option to let the application start automatically and hidden when Windows boots up.
* **Built-in Auto-Updater:** You'll never need to download the application manually again. True Borders checks for new versions and updates itself with a single click!

## Installation & Usage

You don't need to install anything or understand code to use True Borders!

1. Go to the **[Releases](../../releases)** tab here on GitHub.
2. Download the latest version of `TrueBorders.exe`.
3. Double-click the downloaded file to start the application. Done! 

*(Tip: Go to the Settings tab inside the app and toggle "Run on Startup" so you never have to launch it manually again).*

## For Developers (Build from source)

If you want to look at the code or build the application yourself:

The application is built with **Python** and **Eel** (to power the HTML/CSS/JS interface). It also uses libraries like `pywin32` for window management and `pystray` for the System Tray icon.

**Compile to .exe:**
To build your own executable file using PyInstaller, run the following command in your terminal:

```bash
python -m PyInstaller --onefile --noconsole --name "TrueBorders" --icon "icon.ico" --add-data "web;web" main.py
