import tkinter as tk
from tkinter import ttk, messagebox
import urllib.request
import os
import sys
import subprocess
import time
import threading
import ssl

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000


def start_update(download_url, target_exe):
    root = tk.Tk()
    root.title("True Borders - Uppdaterar")
    root.geometry("320x160")
    root.attributes("-topmost", True)
    root.resizable(False, False)

    label = tk.Label(root, text="Förbereder...", pady=10)
    label.pack()

    progress = ttk.Progressbar(root, orient="horizontal",
                               length=240, mode="determinate", maximum=100)
    progress.pack(pady=10)

    status = tk.Label(root, text="", fg="gray")
    status.pack()

    # --- Thread-safe UI-uppdateringar via root.after ---
    def ui(fn): root.after(0, fn)

    def set_label(text): ui(lambda: label.config(text=text))
    def set_status(text): ui(lambda: status.config(text=text))
    def set_progress(v): ui(lambda: progress.configure(value=v))
    def fail(msg):
        ui(lambda: messagebox.showerror("Update Error", msg))
        ui(root.destroy)

    def replace_with_retry(src, dst, attempts=20, delay=0.5):
        """Atomär ersättning med retry om filen är låst. os.replace är atomärt
        på Windows när källa och mål ligger på samma volym."""
        last_err = None
        for _ in range(attempts):
            try:
                os.replace(src, dst)  # ersätter dst atomärt
                return True
            except PermissionError as e:
                last_err = e
                time.sleep(delay)
            except OSError as e:
                last_err = e
                time.sleep(delay)
        raise last_err if last_err else OSError("replace failed")

    def worker():
        try:
            target_dir = os.path.dirname(os.path.abspath(target_exe))
            exe_name = os.path.basename(target_exe)
            temp_file = os.path.join(target_dir, exe_name + ".new")

            # 1) Säkerställ att gamla appen är död (utan konsolfönster)
            set_label("Stänger gamla versionen...")
            try:
                subprocess.run(
                    ["taskkill", "/F", "/IM", exe_name, "/T"],
                    creationflags=CREATE_NO_WINDOW,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=10,
                )
            except Exception:
                pass
            time.sleep(1.0)  # OK här — vi är på worker-tråden

            # 2) Ladda ner till .new (verifierad SSL)
            set_label("Laddar ner uppdatering...")
            ctx = ssl.create_default_context()
            req = urllib.request.Request(
                download_url, headers={"User-Agent": "TrueBorders-Updater/1.0"}
            )
            with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                total = int(resp.headers.get("Content-Length") or 0)
                downloaded = 0
                last_pct = -1
                with open(temp_file, "wb") as f:
                    while True:
                        chunk = resp.read(64 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            pct = int(downloaded * 100 / total)
                            if pct != last_pct:
                                set_progress(pct)
                                set_status(f"{downloaded // 1024} / {total // 1024} KB")
                                last_pct = pct
                        else:
                            set_status(f"{downloaded // 1024} KB")

            if downloaded == 0:
                raise RuntimeError("Tom nedladdning")

            # 3) Atomär ersättning med retry om fil-handle dröjer kvar
            set_label("Installerar...")
            set_progress(100)
            replace_with_retry(temp_file, target_exe)

            # 4) Starta nya exe:n helt detacherad, i sin egen arbetskatalog
            set_label("Klar! Startar om...")
            time.sleep(0.4)
            subprocess.Popen(
                [target_exe],
                cwd=target_dir,
                creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
                close_fds=True,
            )
            ui(root.destroy)
            os._exit(0)

        except Exception as e:
            # Städa upp om något gick fel mitt i
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except Exception:
                pass
            fail(str(e))

    threading.Thread(target=worker, daemon=True).start()
    root.mainloop()


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        start_update(sys.argv[1], sys.argv[2])
    else:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "Updater Error",
            "Inga argument mottagna. Starta uppdateringen inifrån True Borders.",
        )
        root.destroy()
        sys.exit(1)