/* ==========================================================
   HELPER — search a game (used everywhere a card is clicked)
========================================================== */

function searchGame(name) {
    window.location.href = `/search?q=${encodeURIComponent(name)}`;
}

/* ==========================================================
   HERO — FEATURED GAME SPOTLIGHT
   Isolated addition. Fetches GET /api/featured and reads the
   `hero` array only:
     [{ appid, name, header_image, short_description, price }]
========================================================== */

(function () {
    const ROTATE_MS = 10000;
    const FADE_MS = 380;

    let heroGames = [];
    let heroIndex = 0;
    let rotateTimer = null;

    async function initHero() {
        const heroSection = document.getElementById("heroSection");
        if (!heroSection) return;

        try {
            const response = await fetch("/api/featured");
            const data = await response.json();

            if (!Array.isArray(data.hero) || data.hero.length === 0) return;

            heroGames = data.hero;

            buildIndicators();
            renderSlide(0, false);
            bindInteractions();
            startRotation();
        } catch (error) {
            console.error("Error loading hero:", error);
        }
    }

    function buildIndicators() {
        const dotsContainer = document.getElementById("heroIndicators");
        dotsContainer.innerHTML = "";

        heroGames.forEach((game, i) => {
            const dot = document.createElement("button");
            dot.type = "button";
            dot.className = "hero-dot";
            dot.setAttribute("aria-label", `Show ${game.name}`);

            dot.addEventListener("click", (e) => {
                e.stopPropagation();
                if (i === heroIndex) return;
                renderSlide(i, true);
                restartRotation();
            });

            dotsContainer.appendChild(dot);
        });
    }

    function renderSlide(index, animate) {
        const game = heroGames[index];
        if (!game) return;

        const bgLayer = document.getElementById("heroBackground");
        const contentLayer = document.getElementById("heroContent");
        const titleEl = document.getElementById("heroTitle");
        const descEl = document.getElementById("heroDescription");

        const applySlideContent = () => {
            bgLayer.style.backgroundImage = `url("${game.header_image}")`;
            titleEl.textContent = game.name;
            descEl.textContent = game.short_description || "";
        };

        if (!animate) {
            applySlideContent();
        } else {
            bgLayer.classList.add("hero-fade-out");
            contentLayer.classList.add("hero-fade-out");

            setTimeout(() => {
                applySlideContent();
                bgLayer.classList.remove("hero-fade-out");
                contentLayer.classList.remove("hero-fade-out");
            }, FADE_MS);
        }

        document.querySelectorAll(".hero-dot").forEach((dot, i) => {
            dot.classList.toggle("active", i === index);
        });

        heroIndex = index;
    }

    function nextSlide() {
        const next = (heroIndex + 1) % heroGames.length;
        renderSlide(next, true);
    }

    function startRotation() {
        if (heroGames.length < 2) return;
        rotateTimer = setInterval(nextSlide, ROTATE_MS);
    }

    function restartRotation() {
        clearInterval(rotateTimer);
        startRotation();
    }

    function bindInteractions() {
        const heroSection = document.getElementById("heroSection");
        const ctaButton = document.getElementById("heroCta");

        heroSection.addEventListener("click", openGameSearch);

        ctaButton.addEventListener("click", (e) => {
            e.stopPropagation();
            openGameSearch();
        });
    }

    function openGameSearch() {
        const game = heroGames[heroIndex];
        if (!game) return;
        // Root-cause fix: /api/featured already gives us this game's
        // real Steam app_id (see routes/browse.py's featured_games_api
        // -- hero entries come straight off Steam's own top_sellers
        // list, always a genuine "app", never a DLC/sub). Routing
        // through /search?q=<name> instead of using that id directly
        // threw away a known-good app_id and forced a fresh name-based
        // resolution, which is exactly the path that can land on a
        // same-named DLC/edition instead of the base game (see
        // /api/search-results's type filtering fix). Once Nimlyx has
        // an app_id, that id is the source of truth -- never
        // re-resolve it by name.
        if (game.appid) {
            window.location.href = `/search?app_id=${encodeURIComponent(game.appid)}`;
        } else {
            // Defensive fallback only -- shouldn't happen given the
            // shape /api/featured returns, but better than a dead click.
            window.location.href = `/search?q=${encodeURIComponent(game.name)}`;
        }
    }

    initHero();
})();

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

    async function fetchSuggestions(query) {
        if (isMobileViewport()) return;
        try {
            const response = await fetch(`/api/search/${encodeURIComponent(query)}`);
            const data = await response.json();

            const suggestionsBox = document.getElementById("suggestions");
            if (!suggestionsBox) return;
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
        } catch (err) {
            console.error("Error fetching suggestions:", err);
        }
    }
})();