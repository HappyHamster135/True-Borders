import tkinter as tk
from tkinter import ttk
import urllib.request
import os
import sys
import subprocess
import time
import ssl

def start_update(download_url, target_exe):
    root = tk.Tk()
    root.title("True Borders - Uppdaterar")
    root.geometry("300x150")
    root.attributes("-topmost", True)
    
    label = tk.Label(root, text="Laddar ner uppdatering...", pady=10)
    label.pack()

    progress = ttk.Progressbar(root, orient="horizontal", length=200, mode="determinate")
    progress.pack(pady=10)

    def run():
        try:
            # 1. Tvinga ner den gamla appen ifall den inte stängt sig själv
            exe_name = os.path.basename(target_exe)
            os.system(f'taskkill /F /IM "{exe_name}" /T >nul 2>&1')
            time.sleep(2) # Ge Windows tid att släppa fil-låset
            
            ctx = ssl._create_unverified_context()
            temp_file = target_exe + ".new"
            
            # 2. Ladda ner
            req = urllib.request.Request(download_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, context=ctx) as response:
                # Resten av din nerladdningskod här...
                total_size = int(response.info().get('Content-Length', 0))
                downloaded = 0
                with open(temp_file, 'wb') as f:
                    while True:
                        chunk = response.read(1024*8)
                        if not chunk: break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            progress['value'] = (downloaded / total_size) * 100
                            root.update_idletasks()

            # 3. Byt ut filen
            if os.path.exists(target_exe):
                os.remove(target_exe)
            os.rename(temp_file, target_exe)
            
            # 4. Starta om
            label.config(text="Klar! Startar om...")
            root.update()
            time.sleep(1)
            subprocess.Popen([target_exe])
            os._exit(0)
            
        except Exception as e:
            tk.messagebox.showerror("Update Error", str(e))
            os._exit(1)

    root.after(100, run)
    root.mainloop()

if __name__ == "__main__":
    import sys
    # sys.argv[0] är själva updater.exe
    # sys.argv[1] bör vara download_url
    # sys.argv[2] bör vara target_exe (True Borders.exe)
    if len(sys.argv) >= 3:
        url = sys.argv[1]
        target = sys.argv[2]
        start_update(url, target)
    else:
        # Om den startas utan argument, visa ett felmeddelande istället för att bara vara tom
        root = tk.Tk()
        root.withdraw()
        tk.messagebox.showerror("Updater Error", "Inga argument mottagna. Starta uppdateringen inifrån True Borders.")
        sys.exit(1)