/* ==========================================================
   HELPER — search a game (used everywhere a card is clicked)
========================================================== */

function searchGame(name) {
    window.location.href = `/search?q=${encodeURIComponent(name)}`;
}


/* ==========================================================
   GLOBAL HEADER SEARCH (UNIVERSAL DESKTOP vs MOBILE)
========================================================== */

if (typeof window.searchGame !== "function") {
    window.searchGame = function searchGame(name) {
        window.location.href = `/search?q=${encodeURIComponent(name)}`;
    };
}

(function () {
    function isMobileViewport() {
        return window.matchMedia("(max-width: 900px)").matches;
    }

    function redirectToSearchPage() {
        if (window.location.pathname !== "/search" || window.location.search !== "") {
            window.location.href = "/search";
        }
    }

    // 1. Mobile Header Search Icon & Label Interaction
    document.addEventListener("click", (e) => {
        const mobileSearchBtn = e.target.closest(".home-mobile-search-btn");
        if (mobileSearchBtn && isMobileViewport()) {
            e.preventDefault();
            e.stopPropagation();
            const searchToggle = document.getElementById("homeSearchToggle");
            if (searchToggle) searchToggle.checked = false;
            redirectToSearchPage();
        }
    });

    // 2. Header Search Input Events (Mobile Redirection vs Desktop Autocomplete)
    const gameInputEl = document.getElementById("gameInput");
    if (gameInputEl) {
        const handleMobileHeaderInteraction = (e) => {
            if (isMobileViewport()) {
                e.preventDefault();
                gameInputEl.blur();
                const suggestionsBox = document.getElementById("suggestions");
                if (suggestionsBox) suggestionsBox.innerHTML = "";
                redirectToSearchPage();
                return true;
            }
            return false;
        };

        gameInputEl.addEventListener("focus", handleMobileHeaderInteraction);
        gameInputEl.addEventListener("click", handleMobileHeaderInteraction);

        const searchForm = gameInputEl.closest("form.home-search");
        if (searchForm) {
            searchForm.addEventListener("submit", (e) => {
                if (isMobileViewport()) {
                    e.preventDefault();
                    redirectToSearchPage();
                }
            });
        }
    }

    // 3. Search Button Click (Desktop vs Mobile)
    const searchBtn = document.getElementById("searchBtn");
    if (searchBtn) {
        searchBtn.addEventListener("click", (e) => {
            if (isMobileViewport()) {
                e.preventDefault();
                redirectToSearchPage();
                return;
            }
            const gameName = document.getElementById("gameInput").value.trim();
            if (!gameName) return;
            window.location.href = `/search?q=${encodeURIComponent(gameName)}`;
        });
    }

    // 4. Enter Key (Desktop vs Mobile)
    if (gameInputEl) {
        gameInputEl.addEventListener("keydown", (e) => {
            if (isMobileViewport()) {
                if (e.key === "Enter") {
                    e.preventDefault();
                    redirectToSearchPage();
                }
                return;
            }
            if (e.key === "Enter" && searchBtn) {
                searchBtn.click();
            }
        });
    }

    // 5. Autocomplete Suggestions (Debounced - Desktop Only)
    let debounceTimer;

    if (gameInputEl) {
        gameInputEl.addEventListener("input", (e) => {
            const suggestionsBox = document.getElementById("suggestions");
            if (isMobileViewport()) {
                if (suggestionsBox) suggestionsBox.innerHTML = "";
                return;
            }
            clearTimeout(debounceTimer);
            const query = e.target.value;

            if (query.length < 2) {
                if (suggestionsBox) suggestionsBox.innerHTML = "";
                return;
            }

            debounceTimer = setTimeout(() => {
                fetchSuggestions(query);
            }, 400);
        });
    }

    const suggestionCache = new Map();

    async function fetchSuggestions(query) {
        if (isMobileViewport()) return;
        
        const suggestionsBox = document.getElementById("suggestions");
        if (!suggestionsBox) return;

        if (suggestionCache.has(query)) {
            renderSuggestions(suggestionCache.get(query), suggestionsBox);
            return;
        }

        try {
            const response = await fetch(`/api/search/${encodeURIComponent(query)}`);
            const data = await response.json();
            suggestionCache.set(query, data);
            renderSuggestions(data, suggestionsBox);
        } catch (err) {
            console.error("Error fetching suggestions:", err);
        }
    }

    function renderSuggestions(data, suggestionsBox) {
        suggestionsBox.innerHTML = "";
        if (!data.items || data.items.length === 0) return;

        const topResults = data.items.slice(0, 5);
        topResults.forEach(game => {
            const item = document.createElement("div");
            item.className = "suggestion-item";

            const priceText = game.price
                ? (game.price.final === 0 ? "Free" : `$${(game.price.final / 100).toFixed(2)}`)
                : "N/A";

            item.innerHTML = `
                <img src="${game.tiny_image}" alt="${game.name}">
                <div class="suggestion-info">
                    <span class="suggestion-name">${game.name}</span>
                    <span class="suggestion-dev">${priceText}</span>
                </div>
            `;

            item.addEventListener("click", () => {
                suggestionsBox.innerHTML = "";
                window.searchGame(game.name);
            });

            suggestionsBox.appendChild(item);
        });
    }

    // ------------------------------------------------------------
    // REVEAL — wires the shared .reveal entrance-motion utility
    // (see static/css/style.css) to every top-level homepage
    // section. Reused as-is by home-rows.js when lazy feed rows
    // (Biggest Deals, Action) get injected later.
    // ------------------------------------------------------------
    function initReveal(root) {
        const targets = (root || document).querySelectorAll(".reveal:not(.in-view)");
        if (!targets.length) return;
        if (!("IntersectionObserver" in window)) {
            targets.forEach(el => el.classList.add("in-view"));
            return;
        }
        const io = new IntersectionObserver((entries, obs) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    entry.target.classList.add("in-view");
                    obs.unobserve(entry.target);
                }
            });
        }, { rootMargin: "0px 0px -60px 0px", threshold: 0.1 });
        targets.forEach(el => io.observe(el));
    }

    document.addEventListener("DOMContentLoaded", () => initReveal(document));
    window.NimlyxReveal = { init: initReveal };
})();