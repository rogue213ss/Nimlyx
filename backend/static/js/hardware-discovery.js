/**
 * Global Hardware Discovery & "My Rig" functionality
 */
(function() {
    // ----------------------------------------------------------------
    // 1. My Rig Navigation Hook
    // ----------------------------------------------------------------
    document.addEventListener("DOMContentLoaded", async () => {
        const navPanel = document.querySelector(".home-nav");
        if (navPanel) {
            const myRigBtn = document.createElement("a");
            myRigBtn.className = "home-btn home-btn-primary";
            myRigBtn.href = "/rig";
            myRigBtn.style.cssText = "margin-left: 1rem; background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.2); backdrop-filter: blur(10px); color: white; display: inline-flex; align-items: center; gap: 8px;";
            myRigBtn.innerHTML = `
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect>
                    <line x1="8" y1="21" x2="16" y2="21"></line>
                    <line x1="12" y1="17" x2="12" y2="21"></line>
                </svg>
                <span id="myRigBtnText">My Rig</span>
            `;
            
            navPanel.appendChild(myRigBtn);
            
            try {
                const res = await fetch("/api/rig");
                if (res.ok) {
                    const textSpan = document.getElementById("myRigBtnText");
                    if (textSpan) {
                        textSpan.textContent = "Rig Configured";
                        textSpan.parentElement.style.background = "rgba(59, 130, 246, 0.5)"; // glow blue
                    }
                }
            } catch (e) {
                // Ignore failure
            }
        }
    });

    // ----------------------------------------------------------------
    // 2. Shared Hardware Combobox & API Logic
    // ----------------------------------------------------------------
    let _compatCatalogPromise = null;
    const COMPAT_SEARCH_DEBOUNCE_MS = 150;
    const COMPAT_SEARCH_MAX_RESULTS = 50;

    function getHardwareCatalog() {
        if (!_compatCatalogPromise) {
            _compatCatalogPromise = fetch("/api/hardware/catalog")
                .then(res => {
                    if (!res.ok) throw new Error(`Hardware catalog request failed (${res.status})`);
                    return res.json();
                })
                .catch(error => {
                    _compatCatalogPromise = null;
                    throw error;
                });
        }
        return _compatCatalogPromise;
    }

    function _compactUpper(s) {
        return (s || "").replace(/[^A-Za-z0-9]/g, "").toUpperCase();
    }

    function filterHardwareItems(items, query, vendorKey) {
        const tokens = query.trim().split(/\s+/).filter(Boolean).map(_compactUpper).filter(Boolean);
        if (!tokens.length) return [];

        const scored = [];
        for (const item of items) {
            const haystack = _compactUpper((item[vendorKey] || "") + item.name);
            if (tokens.every(t => haystack.includes(t))) {
                const firstIdx = haystack.indexOf(tokens[0]);
                scored.push({ item, score: firstIdx * 1000 + item.name.length });
            }
        }
        scored.sort((a, b) => a.score - b.score);
        return scored.slice(0, COMPAT_SEARCH_MAX_RESULTS).map(s => s.item);
    }

    function _vramLabel(item) {
        const vram = item && item.vram_gb;
        if (vram === null || vram === undefined || Number.isNaN(Number(vram))) return "";
        const num = Number(vram);
        const formatted = Number.isInteger(num) ? String(num) : num.toFixed(1);
        return `${formatted}GB`;
    }

    function displayHardwareName(item, vendorKey) {
        const vendor = (item[vendorKey] || "").trim();
        const name = (item.name || "").trim();
        const base = (!vendor || name.toUpperCase().startsWith(vendor.toUpperCase()))
            ? name
            : `${vendor} ${name}`;
        const vramLabel = _vramLabel(item);
        if (!vramLabel || base.toUpperCase().includes(vramLabel.toUpperCase())) return base;
        return `${base} (${vramLabel})`;
    }

    function initHardwareCombobox({ inputId, listboxId, clearBtnId, hiddenId, items, vendorKey, placeholder }) {
        const input = document.getElementById(inputId);
        const listbox = document.getElementById(listboxId);
        const clearBtn = document.getElementById(clearBtnId);
        const hidden = document.getElementById(hiddenId);
        const combobox = input ? input.closest(".compat-combobox") : null;
        if (!input || !listbox || !hidden || !combobox) return { reset() {} };

        input.placeholder = placeholder;

        let debounceTimer = null;
        let currentResults = [];
        let highlightedIndex = -1;

        function closeListbox() {
            listbox.classList.add("is-hidden");
            listbox.innerHTML = "";
            input.setAttribute("aria-expanded", "false");
            input.removeAttribute("aria-activedescendant");
            highlightedIndex = -1;
            currentResults = [];
        }

        function selectItem(item) {
            hidden.value = item.external_id;
            input.value = displayHardwareName(item, vendorKey);
            clearBtn.classList.remove("is-hidden");
            closeListbox();
            // Trigger change event if listeners are attached
            input.dispatchEvent(new Event("change"));
            hidden.dispatchEvent(new Event("change"));
        }

        function clearSelection({ focus = true } = {}) {
            hidden.value = "";
            input.value = "";
            clearBtn.classList.add("is-hidden");
            closeListbox();
            if (focus) input.focus();
            input.dispatchEvent(new Event("change"));
            hidden.dispatchEvent(new Event("change"));
        }

        function renderResults(query) {
            const matches = filterHardwareItems(items, query, vendorKey);
            currentResults = matches;
            highlightedIndex = matches.length ? 0 : -1;

            if (!matches.length) {
                listbox.innerHTML = `<li class="compat-combobox__empty">We couldn't find that processor. Try checking the spelling or choose a matching result.</li>`;
                listbox.classList.remove("is-hidden");
                input.setAttribute("aria-expanded", "true");
                return;
            }

            listbox.innerHTML = matches.map((item, i) => {
                const vendor = (item[vendorKey] || "").trim();
                const showVendorTag = vendor && !item.name.trim().toUpperCase().startsWith(vendor.toUpperCase());
                const vramLabel = _vramLabel(item);
                const showVram = vramLabel && !item.name.trim().toUpperCase().includes(vramLabel.toUpperCase());
                return `
                <li class="compat-combobox__option${i === 0 ? " is-highlighted" : ""}"
                    role="option" id="${listboxId}-opt-${i}" data-index="${i}"
                    aria-selected="${i === 0 ? "true" : "false"}">
                    ${showVendorTag ? `<span class="compat-combobox__option-vendor">${vendor}</span>` : ""}
                    <span class="compat-combobox__option-name">${item.name}</span>
                    ${showVram ? `<span class="compat-combobox__option-vram">${vramLabel}</span>` : ""}
                </li>
            `;
            }).join("");
            listbox.classList.remove("is-hidden");
            input.setAttribute("aria-expanded", "true");
            input.setAttribute("aria-activedescendant", `${listboxId}-opt-0`);
        }

        function setHighlighted(index) {
            const options = listbox.querySelectorAll(".compat-combobox__option");
            if (!options.length) return;
            highlightedIndex = ((index % options.length) + options.length) % options.length;
            options.forEach((opt, i) => {
                const isHi = i === highlightedIndex;
                opt.classList.toggle("is-highlighted", isHi);
                opt.setAttribute("aria-selected", isHi ? "true" : "false");
            });
            input.setAttribute("aria-activedescendant", `${listboxId}-opt-${highlightedIndex}`);
            options[highlightedIndex].scrollIntoView({ block: "nearest" });
        }

        input.addEventListener("input", () => {
            if (hidden.value) {
                hidden.value = "";
                clearBtn.classList.add("is-hidden");
                hidden.dispatchEvent(new Event("change"));
            }
            const query = input.value;
            clearTimeout(debounceTimer);
            if (!query.trim()) {
                closeListbox();
                return;
            }
            debounceTimer = setTimeout(() => renderResults(query), COMPAT_SEARCH_DEBOUNCE_MS);
        });

        input.addEventListener("keydown", (e) => {
            const isOpen = !listbox.classList.contains("is-hidden");
            if (e.key === "ArrowDown") {
                e.preventDefault();
                if (!isOpen && input.value.trim()) { renderResults(input.value); return; }
                if (currentResults.length) setHighlighted(highlightedIndex + 1);
            } else if (e.key === "ArrowUp") {
                e.preventDefault();
                if (isOpen && currentResults.length) setHighlighted(highlightedIndex - 1);
            } else if (e.key === "Enter") {
                if (isOpen && highlightedIndex >= 0 && currentResults[highlightedIndex]) {
                    e.preventDefault();
                    selectItem(currentResults[highlightedIndex]);
                }
            } else if (e.key === "Escape") {
                if (isOpen) { e.preventDefault(); closeListbox(); }
            }
        });

        input.addEventListener("blur", () => {
            // Give mousedown on listbox a chance to fire
            setTimeout(() => {
                if (document.activeElement !== input && !combobox.contains(document.activeElement)) {
                    if (input.value.trim() && !hidden.value) {
                        // User typed something but didn't select
                        // Let it stay in input, but backend won't get it
                        closeListbox();
                    } else {
                        closeListbox();
                    }
                }
            }, 100);
        });

        listbox.addEventListener("mousedown", (e) => {
            const optionEl = e.target.closest(".compat-combobox__option");
            if (!optionEl) return;
            const idx = Number(optionEl.dataset.index);
            if (currentResults[idx]) {
                e.preventDefault(); // prevent input blur
                selectItem(currentResults[idx]);
            }
        });

        clearBtn.addEventListener("click", () => clearSelection());

        document.addEventListener("click", (e) => {
            if (!combobox.contains(e.target)) closeListbox();
        });
        
        // Initial set if hidden has value (e.g. from Rig load)
        return {
            reset() { clearSelection({ focus: false }); },
            setValue(id) {
                if (!id) { clearSelection({focus: false}); return; }
                const item = items.find(i => i.external_id === id);
                if (item) {
                    hidden.value = id;
                    input.value = displayHardwareName(item, vendorKey);
                    clearBtn.classList.remove("is-hidden");
                } else {
                    clearSelection({focus: false});
                }
            }
        };
    }

    // Expose for search.js and rig.html
    window.NimlyxHardware = {
        getHardwareCatalog,
        initHardwareCombobox,
        displayHardwareName
    };
})();
