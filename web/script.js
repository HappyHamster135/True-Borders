// ==========================================================================
//  1. GLOBALA VARIABLER & TILLSTÅND (STATE)
// ==========================================================================
let globalScale = 1;
let minRealX = 0, minRealY = 0;
let offsetX = 0, offsetY = 0;
let scaledMonitorW = 0, scaledMonitorH = 0;
let realMonitorW = 0, realMonitorH = 0;

let knownRunningGames = new Set();
let manuallyRestoredGames = new Set();
let isCurrentlyBorderlessSession = false; // Håller koll på om spelet faktiskt är applicerat just nu

let currentGameToEdit = "";
let resizeTimer;
let lastMouseY = 0; // Håller koll på om vi drar profiler uppåt eller neråt

const MIN_INNER_WIDTH = 880;
const MIN_INNER_HEIGHT = 750;


// ==========================================================================
//  2. UPPSTART & INITIALISERING (Körs när appen öppnas)
// ==========================================================================

async function initMap() {
    loadAppVersion();

    await eel.set_app_on_top()();
    await populateWindowDropdown();

    // --- A. RITA KARTAN OCH RÄKNA UT SKALA ---
    const monitors = await eel.get_monitor_layout()();
    const mapContainer = document.getElementById('monitor-map');

    monitors.forEach(m => {
        if (m.x < minRealX) minRealX = m.x;
        if (m.y < minRealY) minRealY = m.y;
    });

    let maxRealX = -Infinity, maxRealY = -Infinity;
    monitors.forEach(m => {
        if (m.x + m.width > maxRealX) maxRealX = m.x + m.width;
        if (m.y + m.height > maxRealY) maxRealY = m.y + m.height;
    });

    realMonitorW = maxRealX - minRealX;
    realMonitorH = maxRealY - minRealY;

    const padding = 20;
    const scaleX = (mapContainer.clientWidth - padding * 2) / realMonitorW;
    const scaleY = (mapContainer.clientHeight - padding * 2) / realMonitorH;
    globalScale = Math.min(scaleX, scaleY);

    offsetX = (mapContainer.clientWidth - (realMonitorW * globalScale)) / 2;
    offsetY = (mapContainer.clientHeight - (realMonitorH * globalScale)) / 2;

    monitors.forEach((m, index) => {
        scaledMonitorW = m.width * globalScale;
        scaledMonitorH = m.height * globalScale;

        const monitorDiv = document.createElement('div');
        monitorDiv.className = 'monitor';
        monitorDiv.style.left = `${(m.x - minRealX) * globalScale + offsetX}px`;
        monitorDiv.style.top = `${(m.y - minRealY) * globalScale + offsetY}px`;
        monitorDiv.style.width = `${scaledMonitorW}px`;
        monitorDiv.style.height = `${scaledMonitorH}px`;
        monitorDiv.innerHTML = `Display ${index + 1} (${m.width}x${m.height})`;
        mapContainer.appendChild(monitorDiv);
    });

    // Skapa Drag-boxen (Den gröna/rosa spelytan)
    const dragBox = document.createElement('div');
    dragBox.id = 'drag-box';
    dragBox.innerText = "Game";

    // Helt osynlig för renderingsmotorn från start
    dragBox.style.display = "none";
    dragBox.style.opacity = "0";
    dragBox.style.left = offsetX + "px"; // Sätt en startposition direkt
    dragBox.style.top = offsetY + "px";

    mapContainer.appendChild(dragBox);
    makeDraggable(dragBox);


    // --- B. LADDA SPARADE STORLEKAR & UI ---
    let savedW = localStorage.getItem('resW');
    let savedH = localStorage.getItem('resH');
    const resWInput = document.getElementById('resW');
    const resHInput = document.getElementById('resH');

    if (savedW) resWInput.value = savedW;
    if (savedH) resHInput.value = savedH;

    if (savedW && savedH) {
        let presetVal = `${savedW}x${savedH}`;
        let optionExists = document.querySelector(`#preset-options .custom-option[data-value="${presetVal}"]`);
        if (typeof setPresetValue === "function") {
            setPresetValue(optionExists ? presetVal : 'custom');
        }
    }

    // Visa/Göm custom-fälten
    const updateCustomVisibility = () => {
        document.getElementById('custom-res-group').style.display =
            document.getElementById('resPreset').value === "custom" ? "flex" : "none";
    };
    document.getElementById('resPreset').addEventListener('change', updateCustomVisibility);
    updateCustomVisibility();


    // --- C. HUVUD-EVENTLISTENERS (Kartan) ---
    document.getElementById('window_title_input').addEventListener('change', async (e) => {
        const gameName = e.target.value;
        const triggerText = document.getElementById("custom-select-text");

        if (!gameName || gameName === "Select a game...") {
            isCurrentlyBorderlessSession = false;
            triggerText.innerHTML = "Select a game...";
            return;
        }

        // Uppdatera visuell text direkt
        const iconBase64 = await eel.get_window_icon_base64(gameName)();
        let iconHtml = iconBase64 ? `<img src="${iconBase64}" class="window-icon">` : `<div style="width:18px; height:18px; margin-right:8px;"></div>`;
        triggerText.innerHTML = `${iconHtml} <span>${gameName}</span>`;

        localStorage.setItem('windowName', gameName);
        const profile = await eel.get_profile(gameName)();
        const isAlreadyBorderless = await eel.is_borderless(gameName)();
        isCurrentlyBorderlessSession = isAlreadyBorderless;

        if (profile) {
            document.getElementById('resW').value = profile.resW;
            document.getElementById('resH').value = profile.resH;

            // Uppdatera Size Preset-menyn
            let presetVal = `${profile.resW}x${profile.resH}`;
            let optionExists = document.querySelector(`#preset-options .custom-option[data-value="${presetVal}"]`);
            if (typeof setPresetValue === "function") {
                setPresetValue(optionExists ? presetVal : 'custom');
            }

            updateDragBoxSize();

            if (profile.realX !== undefined && profile.realY !== undefined) {
                const newUIX = (profile.realX - minRealX) * globalScale + offsetX;
                const newUIY = (profile.realY - minRealY) * globalScale + offsetY;
                const dBox = document.getElementById('drag-box');
                dBox.style.left = newUIX + "px";
                dBox.style.top = newUIY + "px";
                triggerRealTimeMove(dBox, newUIY, newUIX);
            }
            document.getElementById('status-polished').innerText = `Profile loaded: ${gameName}`;
            document.getElementById('status-polished').style.color = "var(--accent-1)";
        }
    });

    // --- D. SCROLL I Rutor (Nudge & Dimensions) ---
    const nudgeInput = document.getElementById('nudge-amount');
    const nudgeDisplay = document.getElementById('nudge-display');
    if (nudgeDisplay) {
        nudgeInput.addEventListener('input', (e) => nudgeDisplay.innerText = e.target.value);
    }
    nudgeInput.addEventListener('wheel', function (e) {
        e.preventDefault();
        let currentValue = parseInt(this.value) || 1;
        if (e.deltaY < 0) {
            if (currentValue < 100) this.value = currentValue + 1;
        } else {
            if (currentValue > 1) this.value = currentValue - 1;
        }
        if (nudgeDisplay) nudgeDisplay.innerText = this.value;
    });

    ['resW', 'resH'].forEach(id => {
        const inputEl = document.getElementById(id);

        inputEl.addEventListener('input', () => {
            if (typeof setPresetValue === "function") setPresetValue("custom");
            updateDragBoxSize();
            triggerRealTimeMove(document.getElementById('drag-box'));
        });

        inputEl.addEventListener('change', () => {
            updateDragBoxSize();
            if (typeof isCurrentlyBorderlessSession !== 'undefined' && isCurrentlyBorderlessSession) {
                if (typeof autoSaveCurrentState === "function") autoSaveCurrentState();
            }
        });

        inputEl.addEventListener('wheel', function (e) {
            e.preventDefault();
            if (typeof setPresetValue === "function") setPresetValue("custom");

            let currentValue = parseInt(this.value) || 200;
            let step = 10;
            let maxVal = (id === 'resW') ? realMonitorW : realMonitorH;

            this.value = e.deltaY < 0 ? Math.min(currentValue + step, maxVal) : Math.max(currentValue - step, 200);
            updateDragBoxSize();
            triggerRealTimeMove(document.getElementById('drag-box'));
        });
    });

    // --- E. KNAPPAR (Apply / Restore) ---
    document.getElementById('btnApply').addEventListener('click', async () => {
        const windowName = document.getElementById('window_title_input').value;
        if (!windowName || windowName === "Select a game...") return;

        let success = await eel.init_borderless(windowName)();
        if (success) {
            isCurrentlyBorderlessSession = true;
            triggerRealTimeMove(document.getElementById('drag-box'));
            const profile = await eel.get_profile(windowName)();
            if (profile) {
                await autoSaveCurrentState();
                document.getElementById('status-polished').innerText = "Applied & Profile Updated!";
            } else {
                document.getElementById('prompt-game-name').innerText = windowName;
                document.getElementById('save-prompt-modal').style.display = "block";
            }
        }
    });

    document.getElementById('btnRestore').addEventListener('click', async () => {
        const windowName = document.getElementById('window_title_input').value;
        if (!windowName || windowName === "Select a game...") return;

        let success = await eel.restore_borders(windowName)();
        if (success) {
            isCurrentlyBorderlessSession = false;
            manuallyRestoredGames.add(windowName);
            document.getElementById('status-polished').innerText = "Restored Normal Borders!";
        }
    });

    // --- F. AUTO-VÄLJ SPELET NÄR ALLT ÄR REDO ---
    const profiles = await eel.get_all_profiles()();
    const openWindows = Array.from(document.querySelectorAll('#custom-options .custom-option span')).map(span => span.innerText);

    let gameToAutoSelect = null;
    for (const win of openWindows) {
        if (profiles[win]) {
            gameToAutoSelect = win;
            break;
        }
    }
    if (!gameToAutoSelect) {
        const lastSaved = localStorage.getItem('windowName');
        if (lastSaved && openWindows.includes(lastSaved)) {
            gameToAutoSelect = lastSaved;
        }
    }

    if (gameToAutoSelect) {
        const hiddenInput = document.getElementById('window_title_input');
        const triggerText = document.getElementById("custom-select-text");

        hiddenInput.value = gameToAutoSelect;
        const iconBase64 = await eel.get_window_icon_base64(gameToAutoSelect)();
        let iconHtml = iconBase64 ? `<img src="${iconBase64}" class="window-icon">` : `<div style="width:18px; height:18px; margin-right:8px;"></div>`;
        triggerText.innerHTML = `${iconHtml} <span>${gameToAutoSelect}</span>`;

        // Ladda profilen nu när kartan är ritad
        hiddenInput.dispatchEvent(new Event('change'));
    }

    // --- G. SPLASH SCREEN (Tona bort mjukt) ---
    setTimeout(() => {
        const splashScreen = document.getElementById('splash-screen');
        const dBox = document.getElementById('drag-box');

        if (splashScreen) {
            splashScreen.classList.add('hide-splash');

            if (dBox) {
                updateDragBoxSize();
                dBox.style.display = "flex";
                requestAnimationFrame(() => {
                    dBox.style.opacity = "1";
                });
            }
        }
    }, 2500);

    // Gömmer i bakgrunden om det är definierat så
    if (window.screenX > 5000) {
        eel.hide_to_tray()();
    }
    setInterval(autoApplyScanner, 2000);
}


// ==========================================================================
//  3. VISUAL MAP LOGIK (Flytta, Storlek, D-Pad, Snaps)
// ==========================================================================

async function autoSaveCurrentState() {
    const windowName = document.getElementById('window_title_input').value;
    const dragBox = document.getElementById('drag-box');
    if (!windowName || windowName === "Select a game...") return;

    let safeW = Math.max(200, parseInt(document.getElementById('resW').value) || 200);
    let safeH = Math.max(200, parseInt(document.getElementById('resH').value) || 200);
    safeW = Math.min(safeW, realMonitorW);
    safeH = Math.min(safeH, realMonitorH);

    const profileData = {
        resW: safeW,
        resH: safeH,
        realX: Math.round(((dragBox.offsetLeft - offsetX) / globalScale) + minRealX),
        realY: Math.round(((dragBox.offsetTop - offsetY) / globalScale) + minRealY)
    };

    await eel.save_profile(windowName, profileData)();
}

function updateDragBoxSize() {
    const dragBox = document.getElementById('drag-box');
    if (!dragBox) return;

    let resW = Math.max(200, parseInt(document.getElementById('resW').value) || 200);
    let resH = Math.max(200, parseInt(document.getElementById('resH').value) || 200);

    if (resW > realMonitorW) { resW = realMonitorW; document.getElementById('resW').value = resW; }
    if (resH > realMonitorH) { resH = realMonitorH; document.getElementById('resH').value = resH; }

    const scaledW = resW * globalScale;
    const scaledH = resH * globalScale;

    let realX = Math.round(((parseFloat(dragBox.style.left) - offsetX) / globalScale) + minRealX);
    let realY = Math.round(((parseFloat(dragBox.style.top) - offsetY) / globalScale) + minRealY);

    let maxRealX = minRealX + realMonitorW - resW;
    let maxRealY = minRealY + realMonitorH - resH;

    if (maxRealX < minRealX) maxRealX = minRealX;
    if (maxRealY < minRealY) maxRealY = minRealY;

    if (realX < minRealX) realX = minRealX;
    if (realY < minRealY) realY = minRealY;
    if (realX > maxRealX) realX = maxRealX;
    if (realY > maxRealY) realY = maxRealY;

    let newUIX = (realX - minRealX) * globalScale + offsetX;
    let newUIY = (realY - minRealY) * globalScale + offsetY;

    dragBox.style.left = newUIX + "px";
    dragBox.style.top = newUIY + "px";
    dragBox.style.width = scaledW + "px";
    dragBox.style.height = scaledH + "px";
}

function triggerRealTimeMove(elmnt, exactTop = null, exactLeft = null) {
    const windowName = document.getElementById('window_title_input').value;

    let resW = Math.max(200, parseInt(document.getElementById('resW').value) || 200);
    let resH = Math.max(200, parseInt(document.getElementById('resH').value) || 200);

    resW = Math.min(resW, realMonitorW);
    resH = Math.min(resH, realMonitorH);

    if (!windowName || windowName === "Select a game...") return;

    let calcTop = exactTop !== null ? exactTop : elmnt.offsetTop;
    let calcLeft = exactLeft !== null ? exactLeft : elmnt.offsetLeft;

    let realX = Math.round(((calcLeft - offsetX) / globalScale) + minRealX);
    let realY = Math.round(((calcTop - offsetY) / globalScale) + minRealY);

    const realMaxX = minRealX + realMonitorW - resW;
    const realMaxY = minRealY + realMonitorH - resH;

    const maxTop = offsetY + scaledMonitorH - (resH * globalScale);
    const maxLeft = offsetX + scaledMonitorW - (resW * globalScale);

    if (calcTop >= maxTop - 0.5) realY = realMaxY;
    if (calcLeft >= maxLeft - 0.5) realX = realMaxX;
    if (calcTop <= offsetY + 0.5) realY = minRealY;
    if (calcLeft <= offsetX + 0.5) realX = minRealX;

    eel.update_window_pos(windowName, realX, realY, resW, resH)();
}

function makeDraggable(elmnt) {
    let pos1 = 0, pos2 = 0, pos3 = 0, pos4 = 0;

    elmnt.onmousedown = function (e) {
        e.preventDefault();
        pos3 = e.clientX;
        pos4 = e.clientY;
        document.onmouseup = closeDragElement;
        document.onmousemove = elementDrag;
    };

    function elementDrag(e) {
        e.preventDefault();
        pos1 = pos3 - e.clientX;
        pos2 = pos4 - e.clientY;
        pos3 = e.clientX;
        pos4 = e.clientY;

        let newTop = elmnt.offsetTop - pos2;
        let newLeft = elmnt.offsetLeft - pos1;

        const resW = parseInt(document.getElementById('resW').value) || 2560;
        const resH = parseInt(document.getElementById('resH').value) || 1440;

        const exactW = resW * globalScale;
        const exactH = resH * globalScale;

        let maxLeft = offsetX + scaledMonitorW - exactW;
        let maxTop = offsetY + scaledMonitorH - exactH;

        if (maxLeft < offsetX) maxLeft = offsetX;
        if (maxTop < offsetY) maxTop = offsetY;

        if (Math.abs(newLeft - offsetX) < 3) newLeft = offsetX;
        else if (Math.abs(newLeft - maxLeft) < 3) newLeft = maxLeft;

        if (Math.abs(newTop - offsetY) < 1.5) newTop = offsetY;
        else if (Math.abs(newTop - maxTop) < 1.5) newTop = maxTop;

        if (newLeft < offsetX) newLeft = offsetX;
        if (newTop < offsetY) newTop = offsetY;
        if (newLeft > maxLeft) newLeft = maxLeft;
        if (newTop > maxTop) newTop = maxTop;

        elmnt.style.top = newTop + "px";
        elmnt.style.left = newLeft + "px";

        triggerRealTimeMove(elmnt, newTop, newLeft);
    }

    async function closeDragElement() {
        document.onmouseup = null;
        document.onmousemove = null;

        // Auto-save när du släpper musen!
        const windowName = document.getElementById('window_title_input').value;
        if (isCurrentlyBorderlessSession) {
            const profileExists = await eel.get_profile(windowName)();
            if (profileExists) {
                await autoSaveCurrentState();
                document.getElementById('status-polished').innerText = "Position auto-saved!";
                document.getElementById('status-polished').style.color = "var(--accent-1)";
            }
        }
    }
}

// D-PAD (Finjustera position)
function nudgeBox(dx, dy) {
    const dragBox = document.getElementById('drag-box');
    const amountInput = document.getElementById('nudge-amount');

    if (!dragBox || !amountInput) return;

    let amount = parseInt(amountInput.value) || 1;
    let currentLeft = parseFloat(dragBox.style.left) || offsetX;
    let currentTop = parseFloat(dragBox.style.top) || offsetY;

    let newLeft = currentLeft + (dx * amount * globalScale);
    let newTop = currentTop + (dy * amount * globalScale);

    let resW = Math.max(200, parseInt(document.getElementById('resW').value) || 200);
    let resH = Math.max(200, parseInt(document.getElementById('resH').value) || 200);

    let exactW = resW * globalScale;
    let exactH = resH * globalScale;

    let maxLeft = offsetX + (realMonitorW * globalScale) - exactW;
    let maxTop = offsetY + (realMonitorH * globalScale) - exactH;

    if (maxLeft < offsetX) maxLeft = offsetX;
    if (maxTop < offsetY) maxTop = offsetY;

    if (newLeft < offsetX) newLeft = offsetX;
    if (newTop < offsetY) newTop = offsetY;
    if (newLeft > maxLeft) newLeft = maxLeft;
    if (newTop > maxTop) newTop = maxTop;

    dragBox.style.left = newLeft + "px";
    dragBox.style.top = newTop + "px";

    if (typeof triggerRealTimeMove === "function") {
        triggerRealTimeMove(dragBox, newTop, newLeft);
    }

    if (typeof isCurrentlyBorderlessSession !== 'undefined' && isCurrentlyBorderlessSession) {
        if (typeof autoSaveCurrentState === "function") autoSaveCurrentState();
    }
}

// QUICK SNAPS (Mitten, vänster, höger)
function snapWindow(position) {
    const dragBox = document.getElementById('drag-box');
    const displayElement = document.querySelector('.monitor');
    const mapContainer = document.getElementById('monitor-map');

    if (!dragBox || !displayElement) return;

    const screenW = displayElement.offsetWidth;
    const screenH = displayElement.offsetHeight;
    const offsetX = displayElement.offsetLeft;
    const offsetY = displayElement.offsetTop;

    const boxW = dragBox.offsetWidth;
    const boxH = dragBox.offsetHeight;

    let targetX = 0;

    switch (position) {
        case 'left': targetX = 0; break;
        case 'center-left': targetX = (screenW * 0.33) - (boxW / 2); break;
        case 'center': targetX = (screenW / 2) - (boxW / 2); break;
        case 'center-right': targetX = (screenW * 0.66) - (boxW / 2); break;
        case 'right': targetX = screenW - boxW; break;
    }

    let finalX = targetX + offsetX;
    let finalY = ((screenH / 2) - (boxH / 2)) + offsetY;

    if (finalX < offsetX) finalX = offsetX;
    if (finalX > (offsetX + screenW - boxW)) finalX = offsetX + screenW - boxW;

    dragBox.style.left = finalX + "px";
    dragBox.style.top = finalY + "px";

    if (typeof triggerRealTimeMove === "function") {
        triggerRealTimeMove(dragBox, finalY, finalX);
    }
}


// ==========================================================================
//  4. DROPDOWNS OCH PRESETS LOGIK
// ==========================================================================

async function populateWindowDropdown() {
    let windowData = await eel.get_windows_with_icons()();
    let listContainer = document.getElementById("game-options-list");
    let triggerText = document.getElementById("custom-select-text");
    let hiddenInput = document.getElementById("window_title_input");
    let searchInput = document.getElementById("game-search");

    listContainer.innerHTML = '';

    windowData.forEach(win => {
        let opt = document.createElement("div");
        opt.className = "custom-option";
        let iconHtml = win.icon ? `<img src="${win.icon}" class="window-icon">` : `<div style="width:18px; height:18px; margin-right:8px;"></div>`;
        opt.innerHTML = `${iconHtml} <span>${win.title}</span>`;

        opt.addEventListener("click", () => {
            hiddenInput.value = win.title;
            triggerText.innerHTML = `${iconHtml} <span>${win.title}</span>`;
            document.getElementById("custom-options").classList.remove("open");
            hiddenInput.dispatchEvent(new Event('change'));
        });

        listContainer.appendChild(opt);
    });

    // FILTER-LOGIK för Target Game
    searchInput.addEventListener('input', (e) => {
        const term = e.target.value.toLowerCase();
        const options = listContainer.querySelectorAll('.custom-option');

        options.forEach(opt => {
            const text = opt.querySelector('span').innerText.toLowerCase();
            opt.style.display = text.includes(term) ? 'flex' : 'none';
        });
    });

    searchInput.addEventListener('click', (e) => e.stopPropagation());
}

document.getElementById("custom-select-trigger").addEventListener("click", async () => {
    const optionsContainer = document.getElementById("custom-options");
    const searchInput = document.getElementById("game-search");

    if (!optionsContainer.classList.contains("open")) {
        document.getElementById("game-options-list").innerHTML = '<div style="padding: 10px; text-align: center; color: var(--text-muted);">Loading windows...</div>';
        await populateWindowDropdown();
    }

    optionsContainer.classList.toggle("open");
    document.getElementById("preset-options").classList.remove("open");

    if (optionsContainer.classList.contains("open") && searchInput) {
        setTimeout(() => searchInput.focus(), 50);
    }
});

function setPresetValue(val) {
    const input = document.getElementById('resPreset');
    const textDisplay = document.getElementById('preset-select-text');

    if (!input || !textDisplay) return;

    input.value = val;

    const selectedOption = document.querySelector(`#preset-options .custom-option[data-value="${val}"]`);
    if (selectedOption) {
        textDisplay.innerHTML = selectedOption.innerHTML;
    } else {
        textDisplay.innerHTML = "<span>Custom Size...</span>";
    }
}

document.getElementById("preset-select-trigger").addEventListener("click", () => {
    document.getElementById("preset-options").classList.toggle("open");
    document.getElementById("custom-options").classList.remove("open");
});

document.querySelectorAll('#preset-options .custom-option').forEach(option => {
    option.addEventListener('click', function () {
        const text = this.querySelector('span').innerText;
        const value = this.getAttribute('data-value');

        document.getElementById('preset-select-text').innerText = text;
        document.getElementById('resPreset').value = value;
        document.getElementById('preset-options').classList.remove('open');

        if (value !== 'custom') {
            const dims = value.split('x');
            if (dims.length === 2) {
                document.getElementById('resW').value = dims[0];
                document.getElementById('resH').value = dims[1];
                updateBoxFromInputs();
            }
        }
    });
});

function updateBoxFromInputs() {
    updateDragBoxSize();
    const dBox = document.getElementById('drag-box');
    if (dBox) triggerRealTimeMove(dBox);
}

// Stäng menyer om man klickar utanför
window.addEventListener("click", function (e) {
    if (!document.getElementById("custom-select-wrapper").contains(e.target)) {
        document.getElementById("custom-options").classList.remove("open");
    }
    if (!document.getElementById("preset-select-wrapper").contains(e.target)) {
        document.getElementById("preset-options").classList.remove("open");
    }
});


// ==========================================================================
//  5. PROFILER & TABS (Listan med spel, editera, radera)
// ==========================================================================

function showTab(tabName) {
    document.querySelectorAll('.tab-content').forEach(content => {
        content.style.display = 'none';
    });
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.remove('active');
    });

    if (tabName === 'map') {
        document.getElementById('map-tab').style.display = 'block';
        document.getElementById('tab-btn-map').classList.add('active');
    } else if (tabName === 'profiles') {
        document.getElementById('profiles-tab').style.display = 'block';
        document.getElementById('tab-btn-profiles').classList.add('active');
        loadProfilesTab();
    } else if (tabName === 'settings') {
        document.getElementById('settings-tab').style.display = 'block';
        document.getElementById('tab-btn-settings').classList.add('active');
    }
}

async function loadProfilesTab() {
    const profiles = await eel.get_all_profiles()();
    const list = document.getElementById('profile-list');
    list.innerHTML = "";

    for (const name of Object.keys(profiles)) {
        const p = profiles[name];
        const isCurrentlyBorderless = await eel.is_borderless(name)();
        const checkedState = isCurrentlyBorderless ? "checked" : "";
        let iconBase64 = p.icon || await eel.get_window_icon_base64(name)();

        let iconHtml = iconBase64 ? `<img src="${iconBase64}" class="window-icon" style="width: 16px; height: 16px; margin-right: 8px;">` : '';

        const card = document.createElement('div');
        card.className = 'profile-card';
        card.draggable = true;
        card.dataset.name = name;

        card.innerHTML = `
            <div class="drag-handle">⋮⋮</div>
            <div class="profile-info">
                <h3>${iconHtml}${name}</h3>
                <p>${p.resW}x${p.resH}</p>
            </div>
            <div class="profile-actions">
                <button class="icon-btn play-btn" onclick="launchGame('${name}')" title="Play Game">▶️</button>
                
                <button class="icon-btn" onclick="editProfile('${name}')" title="Profile Settings">⚙️</button>
                <label class="neon-switch">
                    <input type="checkbox" onchange="handleToggle(event, '${name}')" ${checkedState}>
                    <span class="slider"></span>
                </label>
            </div>
        `;

        card.addEventListener('dragstart', (e) => {
            card.classList.add('dragging');
            document.documentElement.classList.add('is-dragging-active');
            e.dataTransfer.effectAllowed = "move";
            e.dataTransfer.setData('text/plain', name);
        });

        card.addEventListener('dragend', () => {
            card.classList.remove('dragging');
            document.documentElement.classList.remove('is-dragging-active');
            saveNewOrder();
        });

        list.appendChild(card);
    }
}

async function handleToggle(event, name) {
    const checkbox = event.target;
    const isChecked = checkbox.checked;
    const profileStatus = document.getElementById('profile-status');

    if (isChecked) {
        let isRunning = await eel.is_game_running(name)();
        if (!isRunning) {
            checkbox.checked = false;
            if (profileStatus) {
                profileStatus.innerText = `⚠️ Start "${name}" first!`;
                profileStatus.style.opacity = "1";
                setTimeout(() => { profileStatus.style.opacity = "0"; }, 3000);
            }
            return;
        }
    }

    let status = await eel.toggle_borderless(name)();

    if (status === "borderless") {
        const profile = await eel.get_profile(name)();
        if (profile) {
            document.getElementById('window_title_input').value = name;
            document.getElementById('resW').value = profile.resW;
            document.getElementById('resH').value = profile.resH;

            const dragBox = document.getElementById('drag-box');
            if (profile.realX !== undefined && profile.realY !== undefined) {
                const newUIX = (profile.realX - minRealX) * globalScale + offsetX;
                const newUIY = (profile.realY - minRealY) * globalScale + offsetY;
                dragBox.style.left = newUIX + "px";
                dragBox.style.top = newUIY + "px";
                updateDragBoxSize();
                triggerRealTimeMove(dragBox, newUIY, newUIX);
            }

            if (profile.borderFix) {
                await eel.force_window_refresh(name, profile.realX, profile.realY, profile.resW, profile.resH)();
            }
        }
        checkbox.checked = true;
    } else if (status === "restored") {
        manuallyRestoredGames.add(name);
        checkbox.checked = false;
    } else {
        checkbox.checked = false;
        alert(`Game "${name}" not found! Make sure it is running.`);
    }
}

async function editProfile(name) {
    const p = await eel.get_profile(name)();
    document.getElementById('modal-border-fix').checked = p.borderFix || false;
    if (!p) return;

    document.getElementById('modal-game-name').innerText = name;
    document.getElementById('modal-hide-taskbar').checked = p.hideTaskbar || false;
    document.getElementById('modal-disable-taskbar').checked = p.disableTaskbar || false;
    document.getElementById('modal-always-ontop').checked = p.alwaysOnTop || false;

    const borderFixToggle = document.getElementById('modal-border-fix');
    if (borderFixToggle) {
        borderFixToggle.checked = p.borderFix || false;
    }

    document.getElementById('modal-exe-path').value = p.exePath || "";
    document.getElementById('exe-save-status').innerText = ""; // Nollställ status-texten

    document.getElementById('settings-modal').style.display = 'block'; // Denna rad har du redan!
}

function editProfileOnMap() {
    closeModal();
    document.getElementById('window_title_input').value = currentGameToEdit;
    const event = new Event('change');
    document.getElementById('window_title_input').dispatchEvent(event);
    showTab('map');
}

async function deleteCurrentProfile() {
    const gameName = document.getElementById('modal-game-name').innerText.trim();
    if (!gameName) return;

    if (confirm(`Are you sure you want to delete the profile for ${gameName}?`)) {
        const success = await eel.delete_profile(gameName)();
        if (success) {
            closeModal();
            if (typeof loadProfilesTab === "function") loadProfilesTab();
        } else {
            alert("Failed to delete profile. Please check the console.");
        }
    }
}
async function launchGame(name) {
    // 1. Kolla om spelet redan är igång!
    const isRunning = await eel.is_game_running(name)();
    if (isRunning) {
        alert(`"${name}" is already running!`);
        return;
    }

    // 2. Ge visuell feedback
    const status = document.getElementById('status-polished');
    if (status) {
        status.innerText = `Launching ${name}...`;
        status.style.color = "var(--accent-1)";
    }

    // 3. Försök starta
    const success = await eel.launch_game(name)();

    if (!success) {
        // Om vi inte har sökvägen (t.ex. en gammal profil som skapades innan denna uppdatering)
        alert(`Could not launch "${name}".\n\nTo fix this: Start the game manually once while True Borders is running. It will learn the file path automatically for next time!`);

        if (status) {
            status.innerText = `Failed to launch ${name}.`;
            status.style.color = "var(--accent-2)";
        }
    }
}
// --- HANTERA EXE SÖKVÄGAR ---
async function browseForExe() {
    const gameName = document.getElementById('modal-game-name').innerText;
    const newPath = await eel.browse_exe()(); // Öppnar Windows filväljare!

    if (newPath) {
        document.getElementById('modal-exe-path').value = newPath;
        await eel.update_exe_path(gameName, newPath)(); // Sparar direkt
        document.getElementById('exe-save-status').innerText = "✓ Path saved!";
        document.getElementById('exe-save-status').style.color = "var(--accent-1)";
    }
}

async function manuallyUpdateExePath() {
    const gameName = document.getElementById('modal-game-name').innerText;
    const newPath = document.getElementById('modal-exe-path').value;
    await eel.update_exe_path(gameName, newPath)();
    document.getElementById('exe-save-status').innerText = "✓ Path saved manually!";
    document.getElementById('exe-save-status').style.color = "var(--accent-1)";
}

// ==========================================================================
//  6. DRAG AND DROP LOGIK (Spegla & Ordna om profiler)
// ==========================================================================

const profileList = document.getElementById('profile-list');

if (profileList) {
    profileList.addEventListener('dragenter', e => e.preventDefault());

    profileList.addEventListener('dragover', e => {
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";

        const dragging = document.querySelector('.dragging');
        if (!dragging) return;

        const siblings = [...profileList.querySelectorAll('.profile-card:not(.dragging)')];

        let nextSibling = siblings.find(sibling => {
            const box = sibling.getBoundingClientRect();
            const boxCenterY = box.top + box.height / 2;
            return e.clientY < boxCenterY;
        });

        if (nextSibling) {
            if (nextSibling !== dragging.nextSibling) {
                profileList.insertBefore(dragging, nextSibling);
            }
        } else {
            profileList.appendChild(dragging);
        }
    });
}

window.addEventListener('dragover', e => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";

    const dragging = document.querySelector('.dragging');
    const profileListObj = document.getElementById('profile-list');

    if (!dragging || !profileListObj) return;

    const isDraggingDown = e.clientY > lastMouseY;
    lastMouseY = e.clientY;

    const siblings = [...profileListObj.querySelectorAll('.profile-card:not(.dragging)')];

    let nextSibling = siblings.find(sibling => {
        const box = sibling.getBoundingClientRect();
        const sensitivity = isDraggingDown ? 0.25 : 0.75;
        const triggerPoint = box.top + (box.height * sensitivity);
        return e.clientY < triggerPoint;
    });

    if (nextSibling) {
        if (nextSibling !== dragging.nextSibling) {
            profileListObj.insertBefore(dragging, nextSibling);
        }
    } else {
        profileListObj.appendChild(dragging);
    }
});

window.addEventListener('dragenter', e => {
    e.preventDefault();
});

async function saveNewOrder() {
    const cards = [...document.querySelectorAll('.profile-card')];
    const newOrder = cards.map(card => card.dataset.name);
    await eel.reorder_profiles(newOrder)();
}


// ==========================================================================
//  7. INSTÄLLNINGAR, HOTKEYS & LATENCY BOOST
// ==========================================================================

async function updateTaskbarSettings() {
    const gameName = document.getElementById('modal-game-name').innerText;
    const hide = document.getElementById('modal-hide-taskbar').checked;
    const disable = document.getElementById('modal-disable-taskbar').checked;
    const onTop = document.getElementById('modal-always-ontop').checked;
    const borderFix = document.getElementById('modal-border-fix').checked;

    await eel.update_advanced_settings(gameName, hide, disable, onTop, borderFix)();
    loadProfilesTab();
}

function toggleTaskbarDependency() {
    const hideTaskbarChecked = document.getElementById('modal-hide-taskbar').checked;
    const disableRow = document.getElementById('disable-row');
    const disableCheckbox = document.getElementById('modal-disable-taskbar');

    if (hideTaskbarChecked) {
        disableRow.classList.remove('disabled-setting');
        disableCheckbox.disabled = false;
    } else {
        disableRow.classList.add('disabled-setting');
        disableCheckbox.checked = false;
        disableCheckbox.disabled = true;
    }
    updateTaskbarSettings();
}

async function toggleGlobalHotkey() {
    const isEnabled = document.getElementById('global-hotkey-toggle').checked;
    const hotkeyStr = document.getElementById('hotkey-input').value;

    localStorage.setItem('globalHotkeyEnabled', isEnabled);
    localStorage.setItem('customHotkey', hotkeyStr);
    await eel.set_custom_hotkey(hotkeyStr, isEnabled)();
}

function recordHotkey(e) {
    e.preventDefault();
    let keys = [];
    if (e.ctrlKey) keys.push('ctrl');
    if (e.shiftKey) keys.push('shift');
    if (e.altKey) keys.push('alt');

    let key = e.key.toLowerCase();
    if (key !== 'control' && key !== 'shift' && key !== 'alt') {
        if (key === ' ') key = 'space';
        keys.push(key);
    }

    if (keys.length > 0 && !['ctrl', 'shift', 'alt'].includes(keys[keys.length - 1])) {
        const hotkeyStr = keys.join('+');
        document.getElementById('hotkey-input').value = hotkeyStr;
        toggleGlobalHotkey();
    }
}

async function loadGlobalSettings() {
    const hotkeySaved = localStorage.getItem('globalHotkeyEnabled') === 'true';
    const customHotkey = localStorage.getItem('customHotkey') || 'ctrl+shift+b';

    const hotkeyToggle = document.getElementById('global-hotkey-toggle');
    const hotkeyInput = document.getElementById('hotkey-input');

    if (hotkeyToggle) hotkeyToggle.checked = hotkeySaved;
    if (hotkeyInput) hotkeyInput.value = customHotkey;

    await eel.set_custom_hotkey(customHotkey, hotkeySaved)();
}

eel.expose(update_switch_from_python);
function update_switch_from_python(gameName, isBorderless) {
    const checkbox = document.getElementById(`toggle-${gameName}`);
    if (checkbox) {
        checkbox.checked = isBorderless;
    }
}

async function checkAdminStatus() {
    const admin = await eel.is_admin()();
    const btn = document.getElementById('latency-boost-btn');
    const note = document.getElementById('admin-note');

    if (!admin) {
        btn.disabled = true;
        btn.style.opacity = "0.5";
        btn.style.cursor = "not-allowed";
        note.innerText = " (Requires Admin rights to change system settings)";
        note.style.color = "var(--accent-2)";
    }
}

async function updateLatencyBoostUI() {
    const status = await eel.check_latency_boost_status()();
    const boostBtn = document.getElementById('latency-boost-btn');

    if (!boostBtn) return;

    if (status.is_active) {
        boostBtn.innerHTML = "Active ✓";
        boostBtn.disabled = true;
        boostBtn.style.opacity = "0.6";
        boostBtn.style.cursor = "default";
        boostBtn.style.color = "var(--accent-1)";
        boostBtn.style.borderColor = "var(--accent-1)";
    } else {
        boostBtn.innerHTML = "Apply Boost";
        boostBtn.disabled = !status.is_admin;
        boostBtn.style.opacity = status.is_admin ? "1" : "0.4";
        boostBtn.style.cursor = status.is_admin ? "pointer" : "not-allowed";
        boostBtn.style.color = "";
        boostBtn.style.borderColor = "";
    }
}

async function runSystemOptimize() {
    const result = await eel.toggle_windows_optimizations(true)();

    if (result.success) {
        alert("Success! Windows 11 Optimizations are now active.");
        setTimeout(async () => {
            await updateLatencyBoostUI();
        }, 500);
    } else {
        alert("Error: " + result.error);
    }
}

async function handleAutostartToggle() {
    const isEnabled = document.getElementById('setting-autostart').checked;
    const success = await eel.toggle_autostart(isEnabled)();

    if (success) {
        document.getElementById('status-polished').innerText = isEnabled ? "Autostart enabled!" : "Autostart disabled.";
    } else {
        alert("Could not update startup settings. Try running as Admin.");
        document.getElementById('setting-autostart').checked = !isEnabled;
    }
}

async function checkInitialAutostart() {
    const isEnabled = await eel.is_autostart_enabled()();
    const checkbox = document.getElementById('setting-autostart');
    if (checkbox) checkbox.checked = isEnabled;
}


// ==========================================================================
//  8. THEMES & ACCORDION (Utseende, Animationer)
// ==========================================================================

function toggleAccordion(contentId, headerElement) {
    const content = document.getElementById(contentId);
    const arrow = headerElement.querySelector('.accordion-arrow');

    if (!content.classList.contains('open')) {
        arrow.style.transform = "rotate(0deg)";
        content.classList.add('open');
    } else {
        arrow.style.transform = "rotate(-90deg)";
        content.classList.remove('open');
        headerElement.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
}

document.addEventListener("DOMContentLoaded", () => {
    const themeGrid = document.querySelector(".theme-grid");

    if (themeGrid) {
        themeGrid.addEventListener("click", async (e) => {
            const btn = e.target.closest(".theme-btn");
            if (!btn) return;

            const themeName = btn.getAttribute("data-theme");

            if (themeName === "default") {
                document.documentElement.removeAttribute("data-theme");
            } else {
                document.documentElement.setAttribute("data-theme", themeName);
            }

            document.querySelectorAll(".theme-btn").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");

            if (typeof eel.select_theme === "function") {
                await eel.select_theme(themeName)();
            }
        });
    }
});

function applyTheme(themeName) {
    document.documentElement.setAttribute('data-theme', themeName);
    localStorage.setItem('savedTheme', themeName);
    document.getElementById('status-polished').innerText = `Theme changed to ${themeName}`;
}


// ==========================================================================
//  9. IMPORT & EXPORT AV PROFILER
// ==========================================================================

async function exportProfiles() {
    const profiles = await eel.get_all_profiles()();
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(profiles, null, 4));

    const downloadAnchorNode = document.createElement('a');
    downloadAnchorNode.setAttribute("href", dataStr);
    downloadAnchorNode.setAttribute("download", "TrueBorders_Profiles.json");
    document.body.appendChild(downloadAnchorNode);
    downloadAnchorNode.click();
    downloadAnchorNode.remove();
}

function importProfiles(event) {
    const file = event.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = async function (e) {
        try {
            const importedData = JSON.parse(e.target.result);
            if (typeof importedData === 'object' && importedData !== null) {
                const success = await eel.import_profiles_data(importedData)();
                if (success) {
                    alert("Profiles imported successfully! 🚀");
                    if (typeof loadProfilesTab === "function") {
                        loadProfilesTab();
                    }
                } else {
                    alert("Failed to save imported profiles.");
                }
            } else {
                alert("Invalid file format.");
            }
        } catch (err) {
            alert("Error reading file. Make sure it's a valid True Borders .json file.");
        }
        event.target.value = '';
    };
    reader.readAsText(file);
}


// ==========================================================================
//  10. MODALS & BUG REPORTING
// ==========================================================================

function openBugModal() {
    const modal = document.getElementById('bug-modal');
    const content = modal.querySelector('.modal-content');

    modal.style.display = 'flex';
    content.classList.remove('bug-close-animation');
    content.classList.add('bug-open-animation');
}

function closeBugModal() {
    const modal = document.getElementById('bug-modal');
    const content = modal.querySelector('.modal-content');

    content.classList.remove('bug-open-animation');
    void content.offsetWidth;
    content.classList.add('bug-close-animation');

    setTimeout(() => {
        modal.style.display = 'none';
        content.classList.remove('bug-close-animation');

        const form = document.getElementById('bug-form');
        if (form) form.reset();
        document.getElementById('bug-status').style.display = 'none';
    }, 300);
}

const bugForm = document.getElementById('bug-form');
if (bugForm) {
    bugForm.addEventListener('submit', async function (e) {
        e.preventDefault();

        const status = document.getElementById('bug-status');
        const submitBtn = document.getElementById('bug-submit-btn');
        const formData = new FormData(this);

        submitBtn.disabled = true;
        submitBtn.innerText = "Sending...";
        status.style.display = 'block';
        status.innerText = "Connecting to server...";
        status.style.color = "var(--text-muted)";

        try {
            const response = await fetch("https://formspree.io/f/xkoqkjqj", {
                method: "POST",
                body: formData,
                headers: { 'Accept': 'application/json' }
            });

            if (response.ok) {
                status.innerText = "✓ Bug report sent! Thank you.";
                status.style.color = "var(--accent-1)";
                bugForm.style.display = "none";

                setTimeout(closeBugModal, 2500);
                setTimeout(() => { bugForm.style.display = "block"; }, 3000);
            } else {
                throw new Error();
            }
        } catch (error) {
            status.innerText = "❌ Oops! Something went wrong.";
            status.style.color = "var(--accent-2)";
            submitBtn.disabled = false;
            submitBtn.innerText = "Try Again";
        }
    });
}

function closeModal() {
    const modal = document.getElementById('settings-modal');
    if (!modal) return;

    modal.classList.add('closing');

    setTimeout(() => {
        modal.style.display = "none";
        modal.classList.remove('closing');
    }, 250);
}

async function handleSavePrompt(shouldSave) {
    const modal = document.getElementById('save-prompt-modal');
    const gameName = document.getElementById('window_title_input').value;

    if (shouldSave) {
        const data = {
            resW: parseInt(document.getElementById('resW').value),
            resH: parseInt(document.getElementById('resH').value),
        };

        await eel.save_profile(gameName, data)();
        console.log("Profile saved:", gameName);
    }

    modal.classList.add('closing');

    setTimeout(() => {
        modal.style.display = "none";
        modal.classList.remove('closing');
        document.getElementById('status-polished').innerText = shouldSave ? "Profile saved and applied!" : "Applied without saving.";
    }, 250);
}

// Stäng modaler om du klickar på bakgrunden
window.onclick = function (event) {
    if (event.target.classList.contains('modal')) {
        const openModals = document.querySelectorAll('.modal');
        openModals.forEach(modal => {
            if (window.getComputedStyle(modal).display !== 'none') {
                modal.classList.add('closing');
                setTimeout(() => {
                    modal.style.display = "none";
                    modal.classList.remove('closing');
                }, 250);
            }
        });
    }
}


// ==========================================================================
//  11. BACKGROUND SCANNERS & FÖNSTERHANTERING
// ==========================================================================

async function autoApplyScanner() {
    const profiles = await eel.get_all_profiles()();
    const openWindows = await eel.get_open_windows()();

    for (let game of knownRunningGames) {
        if (!openWindows.includes(game)) {
            knownRunningGames.delete(game);
            manuallyRestoredGames.delete(game);
        }
    }

    for (const win of openWindows) {
        if (profiles[win]) {
            if (!knownRunningGames.has(win) && !manuallyRestoredGames.has(win)) {
                knownRunningGames.add(win);

                const isBorderless = await eel.is_borderless(win)();
                if (!isBorderless) {
                    await eel.init_borderless(win)();
                    const p = profiles[win];
                    if (p) {
                        await eel.update_window_pos(win, p.realX, p.realY, p.resW, p.resH)();
                        if (p.alwaysOnTop) {
                            await eel.set_game_topmost(win, true)();
                        }
                    }

                    document.getElementById('window_title_input').value = win;
                    document.getElementById('window_title_input').dispatchEvent(new Event('change'));

                    if (document.getElementById('profiles-tab').style.display === 'block') {
                        loadProfilesTab();
                    }

                    document.getElementById('status-polished').innerText = `Auto-applied: ${win}`;
                    document.getElementById('status-polished').style.color = "var(--accent-1)";
                }
            }
        }
    }
}

// Bakgrundsvakt: Kollar varannan sekund om det valda spelet faktiskt har stängts helt
setInterval(async () => {
    const hiddenInput = document.getElementById("window_title_input");
    const currentSelected = hiddenInput.value;

    if (currentSelected && currentSelected !== "") {
        // Kontrollera om fönstret fortfarande existerar
        const isRunning = await eel.is_game_running(currentSelected)();

        if (!isRunning) {
            // Spelet är verkligen helt stängt (inte bara laddar eller byter ikon)
            hiddenInput.value = "";
            document.getElementById("custom-select-text").innerHTML = "Select a game...";

            // Töm inte rutorna här, låt värdena stå kvar utifall användaren vill ändra dem
            console.log(`Fönstret "${currentSelected}" stängdes. Nollställer valet.`);
        }
    }
}, 3000); // Ökade tiden till 3 sekunder för att ge Unreal Engine tid att "vakna"

// Tvinga minsta fönsterstorlek (så appen inte krymper ihop sig själv)
window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);

    resizeTimer = setTimeout(() => {
        if (window.innerWidth < MIN_INNER_WIDTH || window.innerHeight < MIN_INNER_HEIGHT) {
            let borderX = window.outerWidth - window.innerWidth;
            let borderY = window.outerHeight - window.innerHeight;

            let targetWidth = window.innerWidth < MIN_INNER_WIDTH ? (MIN_INNER_WIDTH + borderX) : window.outerWidth;
            let targetHeight = window.innerHeight < MIN_INNER_HEIGHT ? (MIN_INNER_HEIGHT + borderY) : window.outerHeight;

            window.resizeTo(targetWidth, targetHeight);
        }
    }, 150);
});

// App-kontroller (Exit & Göm)
function closeApp() { window.close(); }
function exitApp() { window.close(); }
function hideToTray() { eel.hide_to_tray()(); }

// ==========================================================================
//  12. AUTO UPDATER
// ==========================================================================

async function loadAppVersion() {
    try {
        // Lägg märke till TVÅ par parenteser: ()()
        let version = await eel.get_current_version()();
        let displayEl = document.getElementById("app-version-display");
        if (displayEl) displayEl.innerText = version;
    } catch (err) {
        console.error("Kunde inte ladda version:", err);
    }
}

async function manualUpdateCheck() {
    const btn = event.target;
    const originalText = btn.innerText;
    btn.innerText = "Söker...";
    btn.disabled = true;

    try {
        let result = await eel.check_for_updates()();

        if (result.update_available) {
            if (confirm(`En ny version (v${result.version}) hittades!\n\nVill du ladda ner och installera den nu? Programmet kommer att startas om.`)) {
                btn.innerText = "Laddar ner...";
                let success = await eel.perform_update(result.url)();
                if (success === true) {
                    // Stäng ner fönstret! Detta låter Python stänga mjukt.
                    window.close();
                }
            } else {
                alert("Ett fel uppstod vid uppdateringen...");
                btn.innerText = originalText;
                btn.disabled = false;
            }
        } else {
            alert("Du har redan den senaste versionen!");
            btn.innerText = originalText;
            btn.disabled = false;
        }
    } catch (err) {
        alert("Kunde inte söka efter uppdateringar. Kolla din internetuppkoppling.");
        btn.innerText = originalText;
        btn.disabled = false;
    }
}
// ==========================================================================
//  13. KÖRS NÄR HELA SIDAN HAR LADDAT
// ==========================================================================
document.addEventListener('DOMContentLoaded', () => {
    checkAdminStatus();
    loadGlobalSettings();
    updateLatencyBoostUI();
    checkInitialAutostart();

    // FILTER-LOGIK för Profiles-listan
    document.getElementById('profile-search').addEventListener('input', (e) => {
        const term = e.target.value.toLowerCase();
        const cards = document.querySelectorAll('.profile-card');

        cards.forEach(card => {
            const name = card.dataset.name.toLowerCase();
            card.style.display = name.includes(term) ? 'flex' : 'none';
        });
    });
});

window.onload = initMap;