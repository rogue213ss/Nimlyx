/* ==========================================================
   REGION / CURRENCY PICKER
   Auto-detected via IP on the backend; this lets the user override
   it. "Auto" always maps back to whatever the backend detects.
========================================================== */

async function initRegionPicker() {
    const picker = document.getElementById("regionPicker");
    const trigger = document.getElementById("regionTrigger");
    const triggerLabel = document.getElementById("regionTriggerLabel");
    const menu = document.getElementById("regionMenu");
    if (!picker || !trigger || !menu) return;

    let currentValue = "auto";

    async function applyChoice(choice) {
        try {
            if (choice === "auto") {
                await fetch("/api/region/reset", { method: "POST" });
            } else {
                await fetch(`/api/region/${choice}`, { method: "POST" });
            }
            location.reload();
        } catch (error) {
            console.error("Error setting region:", error);
        }
    }

    function renderMenu(data) {
        currentValue = data.is_manual ? data.active : "auto";

        const autoItem = {
            value: "auto",
            label: `Auto-detect (${data.detected})`
        };
        const items = [autoItem, ...(data.options || [])];

        menu.innerHTML = items.map((opt, i) => `
            ${i === 1 ? '<div class="region-picker__divider"></div>' : ""}
            <div class="region-picker__item ${opt.value === currentValue || opt.code === currentValue ? "is-active" : ""}"
                 role="option" data-value="${opt.value || opt.code}">
                ${opt.label}
            </div>
        `).join("");

        const activeItem = items.find(o => (o.value || o.code) === currentValue);
        triggerLabel.textContent = activeItem ? activeItem.label : "Region";

        menu.querySelectorAll(".region-picker__item").forEach(item => {
            item.addEventListener("click", () => {
                closeMenu();
                applyChoice(item.dataset.value);
            });
        });
    }

    function openMenu() {
        picker.classList.add("is-open");
        trigger.setAttribute("aria-expanded", "true");
    }
    function closeMenu() {
        picker.classList.remove("is-open");
        trigger.setAttribute("aria-expanded", "false");
    }

    trigger.addEventListener("click", (e) => {
        e.stopPropagation();
        picker.classList.contains("is-open") ? closeMenu() : openMenu();
    });
    document.addEventListener("click", (e) => {
        if (!picker.contains(e.target)) closeMenu();
    });
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") closeMenu();
    });

    try {
        const res = await fetch("/api/region");
        const data = await res.json();
        renderMenu(data);
    } catch (error) {
        console.error("Error loading region options:", error);
        triggerLabel.textContent = "Region";
    }
}

initRegionPicker();

/* ==========================================================
   SEARCH BAR + SUGGESTIONS (reused Nimlyx logic)
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

    const searchBtnEl = document.getElementById("searchBtn");
    if (searchBtnEl) {
        searchBtnEl.addEventListener("click", (e) => {
            if (isMobileViewport()) {
                if (e) e.preventDefault();
                if (window.location.pathname !== "/search" || window.location.search !== "") {
                    window.location.href = "/search";
                }
                return;
            }
            const gameName = document.getElementById("gameInput").value.trim();
            if (!gameName) return;
            window.searchGame(gameName);
        });
    }

    let debounceTimer;
    let activeSuggestionIndex = -1;

    const searchGameInputEl = document.getElementById("gameInput");
    if (searchGameInputEl) {
        const redirectIfMobile = (e) => {
            if (isMobileViewport()) {
                if (e) e.preventDefault();
                searchGameInputEl.blur();
                const suggestionsBox = document.getElementById("suggestions");
                if (suggestionsBox) suggestionsBox.innerHTML = "";
                if (window.location.pathname !== "/search" || window.location.search !== "") {
                    window.location.href = "/search";
                }
                return true;
            }
            return false;
        };

        searchGameInputEl.addEventListener("focus", redirectIfMobile);
        searchGameInputEl.addEventListener("click", redirectIfMobile);

        searchGameInputEl.addEventListener("input", (e) => {
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

        searchGameInputEl.addEventListener("keydown", (e) => {
            if (isMobileViewport()) {
                if (e.key === "Enter") {
                    e.preventDefault();
                    if (window.location.pathname !== "/search" || window.location.search !== "") {
                        window.location.href = "/search";
                    }
                }
                return;
            }

            const suggestionsBox = document.getElementById("suggestions");
            const items = suggestionsBox ? suggestionsBox.querySelectorAll(".suggestion-item") : [];

            if (items.length === 0) {
                if (e.key === "Enter" && searchBtnEl) searchBtnEl.click();
                return;
            }

            if (e.key === "ArrowDown") {
                e.preventDefault();
                activeSuggestionIndex = (activeSuggestionIndex + 1) % items.length;
                updateActiveSuggestion(items);
            }

            if (e.key === "ArrowUp") {
                e.preventDefault();
                activeSuggestionIndex = (activeSuggestionIndex - 1 + items.length) % items.length;
                updateActiveSuggestion(items);
            }

            if (e.key === "Enter") {
                if (activeSuggestionIndex >= 0 && items[activeSuggestionIndex]) {
                    items[activeSuggestionIndex].click();
                } else if (searchBtnEl) {
                    searchBtnEl.click();
                }
            }
        });
    }

    function updateActiveSuggestion(items) {
        items.forEach(item => item.classList.remove("active-suggestion"));
        if (activeSuggestionIndex >= 0) {
            items[activeSuggestionIndex].classList.add("active-suggestion");
            items[activeSuggestionIndex].scrollIntoView({ block: "nearest" });
        }
    }

    const suggestionCache = new Map();

    async function fetchSuggestions(query) {
        activeSuggestionIndex = -1;
        
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

        data.items.slice(0, 5).forEach(game => {
            const item = document.createElement("div");
            item.className = "suggestion-item";

            const priceText = game.price
                ? (game.price.final === 0 ? "Free" : `$${(game.price.final / 100).toFixed(2)}`)
                : "N/A";

            item.innerHTML = `
                <img src="${game.tiny_image}" alt="${game.name}" loading="lazy">
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

    // ==========================================================
    // DEDICATED SEARCH LANDING INPUT AUTOCOMPLETE
    // ==========================================================
    const landingInputEl = document.getElementById("landingGameInput");
    const landingSuggestionsBox = document.getElementById("landingSuggestions");
    let landingDebounceTimer;
    let landingActiveIndex = -1;

    if (landingInputEl && landingSuggestionsBox) {
        landingInputEl.addEventListener("input", (e) => {
            clearTimeout(landingDebounceTimer);
            const query = e.target.value.trim();

            if (query.length < 2) {
                landingSuggestionsBox.innerHTML = "";
                return;
            }

            landingDebounceTimer = setTimeout(() => {
                fetchLandingSuggestions(query);
            }, 400);
        });

        landingInputEl.addEventListener("keydown", (e) => {
            const items = landingSuggestionsBox.querySelectorAll(".suggestion-item");

            if (items.length === 0) {
                return;
            }

            if (e.key === "ArrowDown") {
                e.preventDefault();
                landingActiveIndex = (landingActiveIndex + 1) % items.length;
                updateLandingActiveSuggestion(items);
            }

            if (e.key === "ArrowUp") {
                e.preventDefault();
                landingActiveIndex = (landingActiveIndex - 1 + items.length) % items.length;
                updateLandingActiveSuggestion(items);
            }

            if (e.key === "Enter") {
                if (landingActiveIndex >= 0 && items[landingActiveIndex]) {
                    e.preventDefault();
                    items[landingActiveIndex].click();
                }
            }

            if (e.key === "Escape") {
                landingSuggestionsBox.innerHTML = "";
            }
        });

        document.addEventListener("click", (e) => {
            if (!landingInputEl.contains(e.target) && !landingSuggestionsBox.contains(e.target)) {
                landingSuggestionsBox.innerHTML = "";
            }
        });
    }

    function updateLandingActiveSuggestion(items) {
        items.forEach(item => item.classList.remove("active-suggestion"));
        if (landingActiveIndex >= 0 && items[landingActiveIndex]) {
            items[landingActiveIndex].classList.add("active-suggestion");
            items[landingActiveIndex].scrollIntoView({ block: "nearest" });
        }
    }

    async function fetchLandingSuggestions(query) {
        landingActiveIndex = -1;
        if (!landingSuggestionsBox) return;

        if (suggestionCache.has(query)) {
            renderLandingSuggestions(suggestionCache.get(query));
            return;
        }

        try {
            const response = await fetch(`/api/search/${encodeURIComponent(query)}`);
            const data = await response.json();
            suggestionCache.set(query, data);
            renderLandingSuggestions(data);
        } catch (err) {
            console.error("Error fetching landing suggestions:", err);
        }
    }

    function renderLandingSuggestions(data) {
        landingSuggestionsBox.innerHTML = "";
        if (!data.items || data.items.length === 0) return;

        data.items.slice(0, 5).forEach(game => {
            const item = document.createElement("div");
            item.className = "suggestion-item";

            const priceText = game.price
                ? (game.price.final === 0 ? "Free" : `$${(game.price.final / 100).toFixed(2)}`)
                : "N/A";

            item.innerHTML = `
                <img src="${game.tiny_image}" alt="${game.name}" loading="lazy">
                <div class="suggestion-info">
                    <span class="suggestion-name">${game.name}</span>
                    <span class="suggestion-dev">${priceText}</span>
                </div>
            `;

            item.addEventListener("click", () => {
                landingSuggestionsBox.innerHTML = "";
                window.searchGame(game.name);
            });

            landingSuggestionsBox.appendChild(item);
        });
    }
})();

/* ==========================================================
   LOAD REAL GAME DATA FROM NIMLYX BACKEND
========================================================== */

const params = new URLSearchParams(window.location.search);
const appIdParam = params.get("app_id");
// Present only when the visitor originally clicked a Steam package
// ("sub" search result, e.g. a Complete/GOTY/Deluxe Edition) that got
// resolved to this app_id -- see the package-aware game page feature.
// Absent for ordinary app clicks, and build_game_detail's own app_id
// output is completely unaffected by it either way.
const packageIdParam = params.get("package_id");
const gameName = params.get("q");
document.getElementById("gameInput").value = gameName || "";

const searchResultsView = document.getElementById("searchResultsView");
const gameDetailView = document.getElementById("gameDetailView");
const searchLandingView = document.getElementById("searchLandingView");
const gameDetailSkeleton = document.getElementById("gameDetailSkeleton");
const searchResultsSkeleton = document.getElementById("searchResultsSkeleton");
const searchListRows = document.getElementById("searchListRows");
const searchFilterSidebar = document.getElementById("searchFilterSidebar");
const searchResultsTitle = document.getElementById("searchResultsTitle");

// Both skeletons are hidden together everywhere a real view or the
// error state takes over -- callers never need to know which one (if
// either) was showing, same reasoning as the existing pattern below
// where every show*View() function blindly hides the other two views
// rather than checking which was active first.
function hideSkeletons() {
    if (gameDetailSkeleton) gameDetailSkeleton.classList.add("is-hidden");
    if (searchResultsSkeleton) searchResultsSkeleton.classList.add("is-hidden");
}

function showDetailView() {
    hideSkeletons();
    if (searchLandingView) searchLandingView.classList.add("is-hidden");
    if (searchResultsView) searchResultsView.classList.add("is-hidden");
    if (gameDetailView) gameDetailView.classList.remove("is-hidden");
    const errorState = document.getElementById("gameErrorState");
    if (errorState) errorState.style.display = "none";
}

function showResultsView() {
    hideSkeletons();
    if (searchLandingView) searchLandingView.classList.add("is-hidden");
    if (gameDetailView) gameDetailView.classList.add("is-hidden");
    if (searchResultsView) searchResultsView.classList.remove("is-hidden");
    const errorState = document.getElementById("gameErrorState");
    if (errorState) errorState.style.display = "none";
}

// Bare /search -- no ?q= or ?app_id=. Previously nothing in loadGame()
// handled this case at all, so whatever #gameDetailView happened to
// look like by default (an empty shell -- see the HTML comment there)
// is what showed up. Now explicit, same pattern as the other two views.
function showLandingView() {
    hideSkeletons();
    if (searchResultsView) searchResultsView.classList.add("is-hidden");
    if (gameDetailView) gameDetailView.classList.add("is-hidden");
    if (searchLandingView) searchLandingView.classList.remove("is-hidden");
    const errorState = document.getElementById("gameErrorState");
    if (errorState) errorState.style.display = "none";

    // Wire SSR trending carousel once
    const landingTrendingSection = document.getElementById("landingTrendingSection");
    if (landingTrendingSection && !landingTrendingSection.dataset.wired) {
        // wireCarouselScroll handles null checks internally if the elements are missing
        wireCarouselScroll("landingTrendingScroll", "landingTrendingPrev", "landingTrendingNext");
        landingTrendingSection.dataset.wired = "true";
    }
}

/** Canonical loader — always by app_id. Used for /search?app_id=
 *  URLs directly, and internally once a name query has been resolved
 *  to an app_id (exact match, or a GameGrid card click). */
async function loadGameById(appId, packageId) {
    try {
        const url = packageId
            ? `/api/game-detail/${appId}?package_id=${encodeURIComponent(packageId)}`
            : `/api/game-detail/${appId}`;
        const response = await fetch(url);
        if (!response.ok) throw new Error(`Game detail request failed (${response.status})`);
        const game = await response.json();
        showDetailView();
        renderGame(game);
    } catch (error) {
        console.error("Error loading game:", error);
        showGameError("This game may have been delisted, region-restricted, or the link may be broken.");
    }
}

// Previously this failure path only logged to console -- the page was
// left exactly as it was (usually still on the loading skeleton),
// with nothing telling the person anything went wrong. Reuses the
// same .discover-empty-state component Discover's own empty results
// use, rather than a page-specific error block.
function showGameError(message) {
    hideSkeletons();
    if (searchLandingView) searchLandingView.classList.add("is-hidden");
    if (searchResultsView) searchResultsView.classList.add("is-hidden");
    if (gameDetailView) gameDetailView.classList.add("is-hidden");
    const errorState = document.getElementById("gameErrorState");
    const errorText = document.getElementById("gameErrorText");
    if (errorText && message) errorText.textContent = message;
    if (errorState) errorState.style.display = "";
}

/** Legacy path — resolves a free-text query into either a direct
 *  redirect (exact match, e.g. "Portal 2") or a GameGrid of results
 *  (ambiguous query, e.g. "portal"), matching the search behavior of
 *  Steam/Amazon/IMDb rather than showing a one-item results page. */
async function loadGameByQuery(query) {
    try {
        const response = await fetch(`/api/search-results/${encodeURIComponent(query)}`);
        const data = await response.json();

        if (data.exact_match_app_id) {
            // Redirect internally to app_id-based loading -- the URL
            // becomes canonical without a full page reload. If the
            // matched row was itself a Steam package (steam_type ==
            // "sub", e.g. "The Witcher 3 Complete Edition") that got
            // resolved to this app_id, carry its steam_id along as
            // package_id so the resulting game page can still show
            // the package the visitor actually clicked.
            const matchedRow = (data.results || []).find(r => r.app_id === data.exact_match_app_id);
            const packageId = (matchedRow && matchedRow.steam_type === "sub") ? matchedRow.steam_id : null;

            const newUrl = packageId
                ? `/search?app_id=${encodeURIComponent(data.exact_match_app_id)}&package_id=${encodeURIComponent(packageId)}`
                : `/search?app_id=${encodeURIComponent(data.exact_match_app_id)}`;
            history.replaceState(null, "", newUrl);
            await loadGameById(data.exact_match_app_id, packageId);
            return;
        }

        if (searchResultsTitle) {
            searchResultsTitle.textContent = `Results for "${query}"`;
        }
        showResultsView();
        initSearchList({
            container: searchListRows,
            sidebar: searchFilterSidebar,
            rows: data.results,
            hasMore: data.has_more,
            nextOffset: data.next_offset,
            // SearchList doesn't own fetch/query-string details --
            // it just calls this when "Load more" is clicked and
            // expects the same {results, has_more, next_offset} shape
            // this endpoint already returns for the first page.
            fetchMore: async (offset) => {
                const res = await fetch(`/api/search-results/${encodeURIComponent(query)}?offset=${offset}`);
                return res.json();
            },
        });
    } catch (error) {
        console.error("Error loading search results:", error);
        showGameError("Something went wrong loading search results. Please try again.");
    }
}

async function loadGame() {
    if (appIdParam) {
        // Shown synchronously, before the fetch in loadGameById() goes
        // out -- this is exactly the "blank page for a few seconds"
        // gap that was reported (nothing rendered between the page
        // shell and the real hero appearing).
        if (gameDetailSkeleton) gameDetailSkeleton.classList.remove("is-hidden");
        await loadGameById(appIdParam, packageIdParam);
    } else if (gameName) {
        if (searchResultsSkeleton) searchResultsSkeleton.classList.remove("is-hidden");
        await loadGameByQuery(gameName);
    } else {
        // Bare /search has nothing to fetch before its first paint --
        // showLandingView() runs synchronously below, so there's no
        // gap for a skeleton to fill here.
        // Trending Games are now server-side rendered (SSR) directly into search.html
        // so we just show the landing view immediately.
        showLandingView();
    }
}

loadGame();

/* ==========================================================
   SEARCH LANDING — TRENDING GAMES
   Reuses buildTrendingStyleCard() / wireCarouselScroll() / 
   renderCarouselSection() below. The trending list itself is now
   rendered server-side into search.html to eliminate a client round-trip.
========================================================== */

/* ==========================================================
   MASTER RENDER
========================================================== */

function renderGame(game) {
    renderHero(game);
    renderAbout(game);
    renderMedia(game);
    renderNimlyxAnalysis(game);
    renderPurchaseOptions(game);
    renderCredits(game);
    renderStats(game);
    renderRequirements(game);
    initCompatibility(game);
    renderDeveloperGames(game);
    renderPublisherGames(game);
    initScrollReveal();
}

/* ---------------- CAROUSELS (Sprint 4 Phase 3) ----------------
   "More From Developer" / "More From Publisher".

   Deliberately NOT a new component -- reuses the homepage's own
   Trending Today card shape and arrow-scroll behavior exactly
   (.trending-card / .trending-scroll / .trending-arrow, all styled
   in style.css, already loaded here) instead of a page-specific
   carousel, so this doesn't read as something bolted onto the game
   page. The scroll-by-arrow logic below is the same approach
   trending.js uses on the homepage, just generalized to run against
   whichever scroller/prev/next triple is passed in, since this page
   has two of these carousels instead of one. */

// Same fallback artwork Discover's cards use (see discover.js) --
// kept as an identical local copy since the two pages don't share a
// module system. header_image is guaranteed by the backend in
// practice (see formatters.to_discover_card), so this is a
// defensive last resort, not an expected path.
const FALLBACK_IMAGE = "data:image/svg+xml;utf8," + encodeURIComponent(`
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300">
        <rect width="400" height="300" fill="#131318"/>
        <g transform="translate(200,150)" fill="none" stroke="#5c5b64" stroke-width="6" stroke-linecap="round" stroke-linejoin="round" opacity="0.55">
            <path d="M-60,-10 h120 a30,30 0 0 1 30,30 v10 a20,20 0 0 1 -35,14 l-14,-14 h-82 l-14,14 a20,20 0 0 1 -35,-14 v-10 a30,30 0 0 1 30,-30 z"/>
            <line x1="-38" y1="8" x2="-38" y2="24"/>
            <line x1="-46" y1="16" x2="-30" y2="16"/>
            <circle cx="34" cy="6" r="4" fill="#5c5b64" stroke="none"/>
            <circle cx="50" cy="20" r="4" fill="#5c5b64" stroke="none"/>
        </g>
    </svg>
`.replace(/\s+/g, " ").trim());

function carouselCardPrice(g) {
    const priceLabel = (g.price === 0 || g.price === "0" || g.price == null)
        ? "Free"
        : `$${(Number(g.price) / 100).toFixed(2)}`;
    return g.discount > 0 ? `-${g.discount}% \u00b7 ${priceLabel}` : priceLabel;
}

function buildTrendingStyleCard(g) {
    const card = document.createElement("a");
    card.className = "trending-card";
    card.href = g.app_id ? `/search?app_id=${encodeURIComponent(g.app_id)}` : "#";
    card.innerHTML = `
        <div class="trending-media">
            <img src="${g.header_image || FALLBACK_IMAGE}" alt="${g.name || ""}" loading="lazy">
            <div class="trending-media-overlay"></div>
        </div>
        <div class="trending-info">
            <h3 class="trending-title">${g.name || ""}</h3>
            <span class="trending-price">${carouselCardPrice(g)}</span>
        </div>
    `;

    // Recovery chain, not just a single fallback: if the guaranteed
    // header_image still fails to load, try each of image_candidates
    // in turn (which now includes this game's own same-family
    // large_image -- see related_games.py) before finally giving up
    // to the SVG placeholder. image-upgrade.js doesn't help here: it
    // only ever tries to do BETTER than an already-working image, it
    // has no path for "the base image itself is broken."
    const img = card.querySelector(".trending-media img");
    const retryQueue = Array.isArray(g.image_candidates) ? g.image_candidates.filter(Boolean) : [];
    img.addEventListener("error", function onImgError() {
        const next = retryQueue.shift();
        if (next && next !== img.src) {
            img.src = next;
        } else if (img.src !== FALLBACK_IMAGE) {
            img.removeEventListener("error", onImgError);
            img.src = FALLBACK_IMAGE;
        }
    });

    return card;
}

// Same arrow-driven scroll behavior as trending.js on the homepage,
// generalized to any scroller/prev/next triple so it can run twice
// on this page without duplicating the wiring logic itself.
function wireCarouselScroll(scrollerId, prevId, nextId) {
    const scroller = document.getElementById(scrollerId);
    const prevBtn = document.getElementById(prevId);
    const nextBtn = document.getElementById(nextId);
    if (!scroller || !prevBtn || !nextBtn) return;

    function scrollStep() {
        const card = scroller.querySelector(".trending-card");
        const cardWidth = card ? card.getBoundingClientRect().width : 340;
        return cardWidth + 18; // card width + gap, matches .trending-scroll's gap
    }

    function updateArrowState() {
        const maxScroll = scroller.scrollWidth - scroller.clientWidth;
        prevBtn.disabled = scroller.scrollLeft <= 4;
        nextBtn.disabled = scroller.scrollLeft >= maxScroll - 4;
    }

    prevBtn.addEventListener("click", () => {
        scroller.scrollBy({ left: -scrollStep(), behavior: "smooth" });
    });
    nextBtn.addEventListener("click", () => {
        scroller.scrollBy({ left: scrollStep(), behavior: "smooth" });
    });
    scroller.addEventListener("scroll", updateArrowState, { passive: true });
    window.addEventListener("resize", updateArrowState);

    updateArrowState();
}

// Shared by both carousels below -- hides the whole panel (heading
// included) rather than rendering an empty strip when the backend
// found nothing, same "never render an empty section" rule the
// screenshots panel already follows.
function renderCarouselSection(sectionId, carouselId, prevId, nextId, games, eyebrowId, titleId, name) {
    const section = document.getElementById(sectionId);
    const carousel = document.getElementById(carouselId);
    if (!games || !games.length) {
        if (section) section.style.display = "none";
        return;
    }
    if (section) section.style.display = "";
    if (eyebrowId) document.getElementById(eyebrowId).textContent = `More from ${name}`;
    if (titleId) document.getElementById(titleId).textContent = `More Games From ${name}`;
    carousel.innerHTML = "";
    games.forEach(g => carousel.appendChild(buildTrendingStyleCard(g)));
    wireCarouselScroll(carouselId, prevId, nextId);
}

function renderDeveloperGames(game) {
    const name = (game.developers || [])[0] || "this developer";
    renderCarouselSection(
        "developerGamesSection", "developerGamesCarousel", "developerGamesPrev", "developerGamesNext",
        game.developer_games, "developerGamesEyebrow", "developerGamesTitle", name
    );
}

function renderPublisherGames(game) {
    const name = (game.publishers || [])[0] || "this publisher";
    renderCarouselSection(
        "publisherGamesSection", "publisherGamesCarousel", "publisherGamesPrev", "publisherGamesNext",
        game.publisher_games, "publisherGamesEyebrow", "publisherGamesTitle", name
    );
}

/* ---------------- HERO ---------------- */

function renderHero(game) {
    document.getElementById("heroBg").src = game.header_image || "";
    document.getElementById("heroBg").alt = game.name || "";

    document.getElementById("heroKicker").textContent = game.genres.join(" · ");
    document.getElementById("heroTitle").textContent = game.name;

    // Dev/publisher credit line intentionally removed from the hero --
    // Quick Stats (further down the page) already shows Developer and
    // Publisher, so repeating it here right under the title was
    // redundant clutter rather than a second useful signal. #heroCredits
    // stays in the DOM (search.html) but is always hidden now.
    const heroCredits = document.getElementById("heroCredits");
    if (heroCredits) heroCredits.style.display = "none";

    const scoreClass = game.metacritic >= 75 ? "is-good" : game.metacritic >= 50 ? "is-mid" : "is-low";

    const platformNames = Object.keys(game.platforms)
        .filter(p => game.platforms[p])
        .map(p => p.charAt(0).toUpperCase() + p.slice(1));

    // Discount chip -- only the % off, not also a separate original-
    // price chip. The price chip right next to it already IS the
    // discounted price, so a discount% + that price is the complete,
    // uncluttered answer ("-80%, $7.99") without a third redundant
    // number crowding the row. Only shown for an actual live discount
    // (0 is the "not on sale" case, same convention build_game_detail
    // uses) -- when there's no discount, the price chip alone already
    // covers it.
    const hasDiscount = game.discount > 0;
    const discountChip = hasDiscount
        ? `<span class="meta-chip meta-chip--discount"><i class="fa-solid fa-arrow-down"></i>-${game.discount}%</span>`
        : "";

    document.getElementById("heroMeta").innerHTML = `
        <span class="meta-chip meta-chip--price"><i class="fa-solid fa-tag"></i>${game.price}</span>
        ${discountChip}
        <span class="meta-chip"><i class="fa-regular fa-calendar"></i>${game.release_date || "TBA"}</span>
        ${game.metacritic ? `<span class="meta-chip meta-chip--score ${scoreClass}"><i class="fa-solid fa-star"></i>${game.metacritic} Metacritic</span>` : ""}
        <span class="meta-chip"><i class="fa-solid fa-users"></i>${game.total_reviews.toLocaleString()} Reviews</span>
        <span class="meta-chip"><i class="fa-solid fa-desktop"></i>${platformNames.join(" / ")}</span>
    `;

    const steamLink = document.getElementById("steamLink");
    if (steamLink) {
        // Sprint 3: a real per-app store link, not a generic name
        // search -- game.app_id is always present now that both
        // /api/game-detail/<app_id> and /api/find/<name> resolve
        // through the same build_game_detail() helper.
        steamLink.href = game.app_id
            ? `https://store.steampowered.com/app/${game.app_id}/`
            : `https://store.steampowered.com/search/?term=${encodeURIComponent(game.name)}`;
    }
}

/* ---------------- ABOUT ---------------- */

function renderAbout(game) {
    document.getElementById("aboutText").innerHTML = `<p>${game.short_description || "No description available."}</p>`;
}

/* ---------------- SCREENSHOTS ---------------- */

/* ---------------- MEDIA (screenshots + trailer merged) ----------------
   Trailer, if available, is item 0 and is what's featured on load --
   matching Steam's own product page (video first, not buried below
   the fold). Screenshots fill the rest of the strip. No trailer just
   falls back to exactly the old screenshots-only behavior. */

/* ---------------- MEDIA (screenshots + trailers merged) ----------------
   Sprint 4 Media Enhancement Pass. Every trailer in game.movies gets
   its own thumbnail (not just the first one) -- but which one is
   FEATURED on load follows Steam's own highlight signal, falling
   back to movies[0] only when nothing is highlighted. Screenshots
   fill the rest of the strip, same as before. No trailers at all
   falls back to exactly the old screenshots-only behavior. */

function pluralize(count, singular, plural) {
    return `${count} ${count === 1 ? singular : plural}`;
}

function renderMedia(game) {
    const featuredImg = document.getElementById("featuredImg");
    const featuredVideo = document.getElementById("featuredVideo");
    const featuredQualityWrap = document.getElementById("featuredQualityWrap");
    const featuredQualityBtn = document.getElementById("featuredQualityBtn");
    const featuredQualityMenu = document.getElementById("featuredQualityMenu");
    const featuredQualityList = document.getElementById("featuredQualityList");
    const thumbStrip = document.getElementById("thumbStrip");
    const wrap = document.querySelector(".featured-wrap");
    const panelTitle = document.getElementById("mediaPanelTitle");
    const panelCounts = document.getElementById("mediaPanelCounts");

    const shots = game.screenshots || [];
    // A movie with no hls_url (see _build_movie_entry in
    // routes/game.py -- Steam's current schema only exposes
    // dash_av1/dash_h264/hls_h264, and Nimlyx only wires up hls_h264)
    // isn't something this page can actually play -- excluded here
    // rather than producing a thumbnail that does nothing when clicked.
    const movies = (game.movies || []).filter(m => m.hls_url);

    const mediaItems = [];
    movies.forEach(movie => mediaItems.push({ type: "video", movie }));
    shots.forEach(url => mediaItems.push({ type: "image", url }));

    if (mediaItems.length === 0) {
        if (wrap) wrap.style.display = "none";
        return;
    }
    if (wrap) wrap.style.display = "";
    if (panelTitle) panelTitle.textContent = "Media";

    // Media Panel Counts -- e.g. "12 Screenshots • 3 Trailers", with
    // correct singular/plural and either half omitted when zero
    // (never "0 Trailers").
    if (panelCounts) {
        const parts = [];
        if (shots.length > 0) parts.push(pluralize(shots.length, "Screenshot", "Screenshots"));
        if (movies.length > 0) parts.push(pluralize(movies.length, "Trailer", "Trailers"));
        panelCounts.textContent = parts.join(" • ");
    }

    // Highlight-Aware Featured Trailer Selection: Steam's own
    // highlight flag wins when present; multiple highlighted entries
    // (shouldn't normally happen, but Steam's data isn't a contract)
    // resolve to whichever comes first in movies[]; no highlighted
    // entry at all preserves the previous behavior of using
    // movies[0]. Missing highlight metadata (undefined/false) never
    // breaks this -- it just falls through to the movies[0] default.
    const highlightedMovie = movies.find(m => m.highlight);
    const featuredMovie = highlightedMovie || movies[0];
    const initialIndex = featuredMovie
        ? mediaItems.findIndex(item => item.type === "video" && item.movie === featuredMovie)
        : 0;

    // Nimlyx Tradition: Steam's movies[] no longer ships flat mp4/webm
    // files (see _build_movie_entry in routes/game.py) -- only DASH and
    // HLS adaptive-streaming manifests. hls.js plays hls_url via Media
    // Source Extensions in Chrome/Firefox/Edge; Safari plays the same
    // .m3u8 natively off .src, no library involved. One Hls instance is
    // tracked here so switching trailers (or media items) always tears
    // the old one down first -- letting instances pile up across clicks
    // leaks buffered segments and eventually stalls playback.
    function resetQualitySelector() {
        if (featuredQualityWrap) {
            featuredQualityWrap.style.display = "none";
            featuredQualityMenu.style.display = "none";
            featuredQualityList.innerHTML = "";
            featuredQualityBtn.onclick = null;
        }
    }

    let currentHls = null;
    function destroyCurrentHls() {
        if (currentHls) {
            currentHls.destroy();
            currentHls = null;
        }
        resetQualitySelector();
    }

    // QA Pass: hls.js/Safari's native HLS were both playing correctly
    // once loaded, but nothing handled the load actually failing --
    // an expired signed CDN URL (Steam's hls_h264 links carry a `t=`
    // token), a network blip, or a browser with neither hls.js support
    // nor native HLS left the poster frame sitting there indefinitely
    // with no indication anything was wrong. This shows an honest
    // failure state with a real fallback instead.
    const errorBox = document.getElementById("featuredMediaError");
    const errorLink = document.getElementById("featuredMediaErrorLink");
    const playOverlay = document.getElementById("featuredPlayOverlay");
    const expandBtnEl = document.getElementById("featuredExpandBtn");
    const controlbarEl = document.getElementById("playerControlbar");

    function showMediaError() {
        destroyCurrentHls();
        if (playOverlay) playOverlay.style.display = "none";
        if (controlbarEl) controlbarEl.style.display = "none";
        const shotEl = document.getElementById("featuredShot");
        if (shotEl) shotEl.classList.remove("is-idle");
        if (errorLink) {
            errorLink.href = game.app_id
                ? `https://store.steampowered.com/app/${game.app_id}/`
                : `https://store.steampowered.com/search/?term=${encodeURIComponent(game.name || "")}`;
        }
        if (errorBox) errorBox.style.display = "";
        featuredVideo.style.display = "none";
        featuredImg.style.display = "none";
    }

    function clearMediaError() {
        if (errorBox) errorBox.style.display = "none";
    }

    function showFeaturedMedia(item) {
        clearMediaError();

        if (item.type === "video") {
            destroyCurrentHls();
            featuredVideo.poster = item.movie.thumbnail || "";

            if (window.Hls && Hls.isSupported()) {
                currentHls = new Hls();
                // hls.js already retries plenty of non-fatal hiccups
                // (a dropped segment, a stalled fragment load) on its
                // own -- only `fatal` errors reach here. One retry per
                // failure class before giving up: startLoad() for a
                // network failure (covers a manifest request that
                // failed transiently), recoverMediaError() for a
                // decode/buffer-append failure. A second fatal error of
                // the same kind, or anything outside those two known-
                // recoverable categories, goes straight to the error
                // state rather than retrying forever.
                let networkRetried = false;
                let mediaRetried = false;
                currentHls.on(Hls.Events.ERROR, (event, data) => {
                    if (!data.fatal) return;
                    if (data.type === Hls.ErrorTypes.NETWORK_ERROR && !networkRetried) {
                        networkRetried = true;
                        currentHls.startLoad();
                    } else if (data.type === Hls.ErrorTypes.MEDIA_ERROR && !mediaRetried) {
                        mediaRetried = true;
                        currentHls.recoverMediaError();
                    } else {
                        showMediaError();
                    }
                });

                currentHls.on(Hls.Events.MANIFEST_PARSED, (event, data) => {
                    if (!featuredQualityWrap || !data.levels || data.levels.length <= 1) return;
                    
                    const uniqueHeights = new Map();
                    data.levels.forEach((level, index) => {
                        if (level.height && !uniqueHeights.has(level.height)) {
                            uniqueHeights.set(level.height, index);
                        }
                    });
                    
                    if (uniqueHeights.size <= 1) return;

                    const sortedLevels = Array.from(uniqueHeights.entries()).sort((a, b) => b[0] - a[0]);

                    let html = '<button type="button" class="featured-quality-item is-active" data-val="-1">Auto</button>';
                    sortedLevels.forEach(([height, originalIndex]) => {
                        html += `<button type="button" class="featured-quality-item" data-val="${originalIndex}">${height}p</button>`;
                    });
                    
                    featuredQualityList.innerHTML = html;
                    featuredQualityWrap.style.display = "";
                    
                    featuredQualityBtn.onclick = (e) => {
                        e.stopPropagation();
                        featuredQualityMenu.style.display = featuredQualityMenu.style.display === "none" ? "flex" : "none";
                    };
                    
                    // Close menu when clicking outside
                    const closeMenu = (e) => {
                        if (featuredQualityMenu.style.display !== "none" && !featuredQualityWrap.contains(e.target)) {
                            featuredQualityMenu.style.display = "none";
                        }
                    };
                    document.addEventListener("click", closeMenu);
                    
                    // Cleanup listener when destroyed
                    const oldDestroy = currentHls.destroy.bind(currentHls);
                    currentHls.destroy = () => {
                        document.removeEventListener("click", closeMenu);
                        oldDestroy();
                    };

                    Array.from(featuredQualityList.children).forEach(btn => {
                        btn.onclick = (e) => {
                            e.stopPropagation();
                            if (currentHls) {
                                currentHls.currentLevel = parseInt(btn.dataset.val, 10);
                                Array.from(featuredQualityList.children).forEach(b => b.classList.remove("is-active"));
                                btn.classList.add("is-active");
                            }
                            featuredQualityMenu.style.display = "none";
                        };
                    });
                });

                currentHls.loadSource(item.movie.hls_url);
                currentHls.attachMedia(featuredVideo);
            } else if (featuredVideo.canPlayType("application/vnd.apple.mpegurl")) {
                // Safari: native HLS support built into the <video>
                // element itself -- setting .src directly is enough,
                // hls.js would be redundant here. crossOrigin is set
                // first (harmless if Steam's CDN doesn't send matching
                // CORS headers -- the ambient glow sampler just detects
                // that itself and quietly gives up) in case it does,
                // since it's required for canvas frame-sampling to work
                // on a cross-origin video. Property assignment (not
                // addEventListener) for onerror so re-running this
                // branch on a later trailer switch replaces the handler
                // instead of stacking a new one underneath it.
                featuredVideo.crossOrigin = "anonymous";
                featuredVideo.onerror = () => showMediaError();
                featuredVideo.src = item.movie.hls_url;
            } else {
                // Neither hls.js nor native HLS available -- this browser
                // genuinely cannot play the trailer, full stop. Used to
                // leave the poster frame sitting there looking clickable
                // with nothing playable behind it; now it says so.
                showMediaError();
                return;
            }

            featuredVideo.style.display = "";
            featuredImg.style.display = "none";
            // Player-Redesign: fullscreen for the trailer lives in the
            // control bar now (#playerFullscreenBtn) -- the top-corner
            // expand button stays reserved for the screenshot lightbox
            // so there aren't two overlapping fullscreen affordances.
            if (expandBtnEl) expandBtnEl.style.display = "none";
            if (controlbarEl) controlbarEl.style.display = "";
        } else {
            destroyCurrentHls();
            featuredVideo.pause();
            featuredVideo.removeAttribute("src");
            featuredVideo.onerror = null;
            featuredVideo.style.display = "none";
            featuredImg.style.display = "";
            featuredImg.src = item.url;
            if (expandBtnEl) expandBtnEl.style.display = "";
            if (controlbarEl) controlbarEl.style.display = "none";
            const shotEl = document.getElementById("featuredShot");
            if (shotEl) shotEl.classList.remove("is-idle");
        }
    }

    showFeaturedMedia(mediaItems[initialIndex]);

    thumbStrip.innerHTML = mediaItems.map((item, i) => {
        const isVideo = item.type === "video";
        // Multiple trailers now get their own real name in the thumb's
        // label/tooltip ("Gameplay Trailer" vs "Launch Trailer")
        // instead of every video thumb just saying "Trailer" --
        // otherwise a game with 3 trailers shows 3 identical-looking,
        // identically-labeled thumbs with no way to tell them apart
        // before clicking.
        const label = isVideo ? (item.movie.name || "Trailer") : `Screenshot ${i + 1}`;
        return `
        <button class="thumb ${isVideo ? "thumb--video" : ""} ${i === initialIndex ? "is-active" : ""}"
                data-index="${i}" aria-label="${label}" title="${label}">
            <img src="${isVideo ? item.movie.thumbnail : item.url}" alt="" loading="lazy">
            ${isVideo ? '<span class="thumb-play"><i class="fa-solid fa-play"></i></span>' : ""}
        </button>
    `;
    }).join("");

    // Duplicate-listener guard: renderMedia() rebuilds thumbStrip's
    // innerHTML above (so its CHILD .thumb buttons never carry stale
    // listeners), but thumbStrip/stripPrev/stripNext/watchBtn
    // themselves are the same persistent DOM nodes across any repeat
    // renderMedia() call, and innerHTML replacement doesn't touch
    // listeners already attached to the container/buttons themselves.
    // Same class of bug already fixed elsewhere in this file (see the
    // screenshot lightbox / tap-to-toggle "wired exactly once"
    // comments below) -- this is the one site that pattern was never
    // applied to. Cloning-and-replacing right before each attachment
    // strips any listener from a prior call in one line, without
    // touching the closures below (showFeaturedMedia, mediaItems,
    // etc. keep working exactly as they already do) -- not currently
    // reachable under today's all-full-page-reload navigation, but
    // matches this file's own established convention rather than
    // leaving the one site it was missed.
    const freshThumbStrip = thumbStrip.cloneNode(true);
    thumbStrip.replaceWith(freshThumbStrip);

    freshThumbStrip.addEventListener("click", (e) => {
        const btn = e.target.closest(".thumb");
        if (!btn) return;
        const index = Number(btn.dataset.index);
        const item = mediaItems[index];

        showFeaturedMedia(item);
        if (item.type === "image") {
            featuredImg.style.animation = "none";
            featuredImg.offsetHeight;
            featuredImg.style.animation = "";
        }

        freshThumbStrip.querySelectorAll(".thumb").forEach(t => t.classList.remove("is-active"));
        btn.classList.add("is-active");
    });

    const freshStripPrev = document.getElementById("stripPrev").cloneNode(true);
    document.getElementById("stripPrev").replaceWith(freshStripPrev);
    freshStripPrev.addEventListener("click", () => freshThumbStrip.scrollBy({ left: -320, behavior: "smooth" }));

    const freshStripNext = document.getElementById("stripNext").cloneNode(true);
    document.getElementById("stripNext").replaceWith(freshStripNext);
    freshStripNext.addEventListener("click", () => freshThumbStrip.scrollBy({ left: 320, behavior: "smooth" }));

    const watchBtnEl = document.getElementById("watchTrailerBtn");
    if (watchBtnEl) {
        const freshWatchBtn = watchBtnEl.cloneNode(true);
        watchBtnEl.replaceWith(freshWatchBtn);
        freshWatchBtn.style.display = movies.length > 0 ? "" : "none";
        freshWatchBtn.addEventListener("click", () => {
            document.getElementById("mediaSection").scrollIntoView({ behavior: "smooth", block: "center" });
        });
    }
}

/* ---------------- SCREENSHOT LIGHTBOX ----------------
   Reuses the .shot-lightbox / .shot-lightbox__img / .shot-lightbox__close
   styling in search.css, which existed before this fix but was never
   wired to anything (the expand button was a "coming soon" no-op and
   clicking the screenshot itself did nothing).

   Wired exactly ONCE, at script load, rather than inside renderMedia().
   #featuredImg and the expand button are the same DOM nodes for the
   lifetime of the page, so binding here can't produce duplicate
   listeners on repeated renders, and doesn't need to be re-run when
   renderMedia() runs again. (#thumbStrip itself now clones-and-
   replaces its own node on each renderMedia() call specifically so
   ITS listeners can't duplicate either -- see the comment at that
   call site -- but #featuredImg/the expand button never needed that,
   since they're never rebuilt.)
   The expand button now branches on which media is actually showing:
   screenshot -> lightbox, trailer -> fullscreen the video itself. It
   used to always open the lightbox and silently no-op on video (the
   lightbox only knows how to show #featuredImg), on the assumption
   that "the video already has native fullscreen via its own controls"
   covered it -- true for the controls bar, but the corner expand
   button itself did nothing while a trailer was playing. */
// Safari (desktop and iOS) doesn't implement the standard
// requestFullscreen() on <video>/other elements the same way -- iOS
// Safari specifically only exposes the older webkitEnterFullscreen()
// on the video element itself. Trying the standard API first and
// falling back covers both without needing separate browser-sniffing.
// Module-level (not nested in initScreenshotLightbox()) so both the
// screenshot lightbox's corner-button fallback path and the new
// #playerFullscreenBtn in the control bar (initPlayerControlbar())
// share one implementation instead of two copies drifting apart.
function requestVideoFullscreen() {
    const featuredVideo = document.getElementById("featuredVideo");
    if (!featuredVideo) return;
    if (featuredVideo.requestFullscreen) {
        featuredVideo.requestFullscreen();
    } else if (featuredVideo.webkitRequestFullscreen) {
        featuredVideo.webkitRequestFullscreen();
    } else if (featuredVideo.webkitEnterFullscreen) {
        featuredVideo.webkitEnterFullscreen();
    }
}

function initScreenshotLightbox() {
    const featuredImg = document.getElementById("featuredImg");
    const featuredVideo = document.getElementById("featuredVideo");
    const expandBtn = document.getElementById("featuredExpandBtn");
    const lightbox = document.getElementById("shotLightbox");
    const lightboxImg = document.getElementById("shotLightboxImg");
    const closeBtn = document.getElementById("shotLightboxClose");
    if (!featuredImg || !lightbox || !lightboxImg) return;

    function openLightbox() {
        if (featuredImg.style.display === "none" || !featuredImg.src) return;
        lightboxImg.src = featuredImg.src;
        lightboxImg.alt = featuredImg.alt || "";
        lightbox.classList.add("is-open");
        document.body.style.overflow = "hidden";
    }

    function closeLightbox() {
        lightbox.classList.remove("is-open");
        document.body.style.overflow = "";
    }

    function handleExpandClick() {
        if (featuredVideo && featuredVideo.style.display !== "none") {
            requestVideoFullscreen();
        } else {
            openLightbox();
        }
    }

    featuredImg.addEventListener("click", openLightbox);
    if (expandBtn) expandBtn.addEventListener("click", handleExpandClick);
    if (closeBtn) closeBtn.addEventListener("click", closeLightbox);

    // Backdrop click: only when the click lands on the lightbox
    // backdrop itself, not the image or close button inside it.
    lightbox.addEventListener("click", (e) => {
        if (e.target === lightbox) closeLightbox();
    });

    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && lightbox.classList.contains("is-open")) closeLightbox();
    });
}

initScreenshotLightbox();

/* ---------------- AMBIENT TRAILER GLOW ----------------
   Trailer playing -> sample the current video frame -> average its
   colors -> push that color into a CSS var -> .featured-shot's own
   box-shadow (see search.css) reads that var to glow in the trailer's
   own palette instead of a fixed brand color.

   Wired exactly ONCE at script load, same reasoning as
   initScreenshotLightbox() above: #featuredVideo is the same DOM node
   for the page's lifetime, renderMedia() only ever swaps what's
   playing inside it, so binding play/pause/ended here can't produce
   duplicate listeners across repeated renderMedia() calls. */
function initMediaGlow() {
    const featuredVideo = document.getElementById("featuredVideo");
    const featuredImg = document.getElementById("featuredImg");
    if (!featuredVideo) return;

    // Downscaled way below the video's real resolution on purpose --
    // this is sampled for an average color, not viewed, so a tiny
    // canvas keeps drawImage/getImageData cheap enough to run on an
    // interval without competing with actual video decode/render.
    const canvas = document.createElement("canvas");
    canvas.width = 32;
    canvas.height = 18;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });

    let intervalId = null;
    // Cross-origin video frames (Safari's native-HLS path hitting
    // Steam's CDN directly, without permissive CORS headers) taint the
    // canvas -- getImageData throws a SecurityError. Ambient glow is a
    // nice-to-have layered on top of trailer playback, not a
    // requirement for it, so one thrown error latches this off for
    // good instead of retrying (and failing, and logging) every tick.
    let broken = false;

    function setGlow(r, g, b) {
        const wrap = document.querySelector(".featured-shot");
        if (!wrap) return;
        if (r === null) {
            wrap.style.setProperty("--media-glow-color", "transparent");
            wrap.style.setProperty("--media-glow-color-soft", "transparent");
            return;
        }
        // Two alphas backing the two box-shadow layers in search.css:
        // a tighter, more saturated ring right against the panel edge,
        // and a much softer, larger wash further out. Bumped up from
        // the original single 0.35-alpha layer, which read as barely
        // there against the page's dark background.
        wrap.style.setProperty("--media-glow-color", `rgba(${r}, ${g}, ${b}, 0.65)`);
        wrap.style.setProperty("--media-glow-color-soft", `rgba(${r}, ${g}, ${b}, 0.4)`);
    }

    function sample() {
        if (broken || !ctx) return;
        try {
            ctx.drawImage(featuredVideo, 0, 0, canvas.width, canvas.height);
            const { data } = ctx.getImageData(0, 0, canvas.width, canvas.height);
            let r = 0, g = 0, b = 0, n = 0;
            for (let i = 0; i < data.length; i += 4) {
                // Near-black/near-white pixels (letterbox bars, blown-out
                // highlights) get skipped so they don't wash the average
                // toward grey -- the glow should read as "this trailer's
                // color", not a muddy average of its darkest and
                // brightest frames.
                const lum = (data[i] + data[i + 1] + data[i + 2]) / 3;
                if (lum < 12 || lum > 245) continue;
                r += data[i]; g += data[i + 1]; b += data[i + 2]; n++;
            }
            if (n === 0) return;
            r = Math.round(r / n); g = Math.round(g / n); b = Math.round(b / n);
            setGlow(r, g, b);
        } catch (err) {
            broken = true;
            stop();
        }
    }

    function start() {
        if (broken) return;
        stop();
        sample();
        intervalId = setInterval(sample, 500);
    }

    function stop() {
        if (intervalId) {
            clearInterval(intervalId);
            intervalId = null;
        }
    }

    featuredVideo.addEventListener("play", start);
    featuredVideo.addEventListener("pause", stop);
    featuredVideo.addEventListener("ended", stop);

    // Switching to the featured screenshot (thumb-strip click) doesn't
    // fire the video's own pause/ended -- showFeaturedMedia() calls
    // .pause() on it, which does fire "pause", so this is mostly a
    // belt-and-suspenders reset for the glow fading back out cleanly
    // whenever the image is what's actually on screen.
    if (featuredImg) {
        featuredImg.addEventListener("load", () => {
            if (featuredVideo.style.display === "none") {
                stop();
                setGlow(null, null, null);
            }
        });
    }
}

initMediaGlow();

/* ---------------- FEATURED PLAY OVERLAY ----------------
   A poster frame alone doesn't read as "this is a video" at a glance
   -- easy to mistake for just another screenshot until you notice the
   scrubber at the bottom. This puts a centered play button over
   #featuredVideo whenever it's the active media and paused, and hides
   it the instant playback actually starts.

   Wired exactly once at script load, same reasoning as
   initScreenshotLightbox()/initMediaGlow() above: #featuredVideo and
   #featuredPlayOverlay are the same DOM nodes for the page's
   lifetime, so binding here can't duplicate listeners across repeated
   renderMedia() calls. */
function initFeaturedPlayOverlay() {
    const featuredVideo = document.getElementById("featuredVideo");
    const featuredImg = document.getElementById("featuredImg");
    const overlay = document.getElementById("featuredPlayOverlay");
    if (!featuredVideo || !overlay) return;

    const overlayIcon = overlay.querySelector('i');
    let overlayHideTimer = null;

    function updateOverlayState() {
        if (featuredVideo.paused) {
            overlayIcon.className = "fa-solid fa-play";
            overlay.className = "featured-play-overlay is-play";
            overlay.style.display = "";
            clearTimeout(overlayHideTimer);
        } else {
            overlayIcon.className = "fa-solid fa-pause";
            overlay.className = "featured-play-overlay is-pause";
            overlay.style.display = "none";
            clearTimeout(overlayHideTimer);
        }
    }

    function show() { overlay.style.display = ""; }
    function hide() { overlay.style.display = "none"; }

    function togglePlayPause(e) {
        if (e && e.clientY) {
            const rect = featuredVideo.getBoundingClientRect();
            const NATIVE_CONTROLS_BAR_HEIGHT = 44;
            if (e.clientY > rect.bottom - NATIVE_CONTROLS_BAR_HEIGHT) return;
        }
        if (featuredVideo.paused) {
            featuredVideo.play().catch(() => {});
        } else {
            featuredVideo.pause();
        }
    }

    let lastNativeStateChange = 0;
    featuredVideo.addEventListener("loadstart", updateOverlayState);
    featuredVideo.addEventListener("play", () => { lastNativeStateChange = Date.now(); updateOverlayState(); });
    featuredVideo.addEventListener("pause", () => { lastNativeStateChange = Date.now(); updateOverlayState(); });
    featuredVideo.addEventListener("ended", updateOverlayState);

    overlay.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (featuredVideo.paused) {
            featuredVideo.play().catch(() => {});
        } else {
            featuredVideo.pause();
        }
    });

    // Clicking the video canvas directly toggles play/pause.
    // We bind to pointerdown and preventDefault to completely suppress
    // Chromium's native click-to-pause behavior, ensuring we only toggle once.
    featuredVideo.addEventListener("pointerdown", (e) => {
        // Pointer coarse (mobile touch) handles single vs double tap separately below
        if (window.matchMedia("(pointer: coarse)").matches) return;
        if (e.pointerType !== "mouse") return;
        
        // Exclude the bottom 44px where native controls live
        const rect = featuredVideo.getBoundingClientRect();
        const NATIVE_CONTROLS_BAR_HEIGHT = 44;
        if (e.clientY > rect.bottom - NATIVE_CONTROLS_BAR_HEIGHT) return;

        // Prevent native browser behavior (e.g., Chrome double toggle)
        e.preventDefault();
        
        togglePlayPause(e);
    });

    // Switching to the featured screenshot needs the overlay gone too
    if (featuredImg) {
        featuredImg.addEventListener("load", () => {
            if (featuredVideo.style.display === "none") hide();
        });
    }

    // Mobile touch interaction: single tap toggles play/pause,
    // double-tap on left/right half seeks -5s/+5s (YouTube-style)
    if (window.matchMedia("(pointer: coarse)").matches) {
        const seekBack = document.getElementById("featuredSeekBack");
        const seekFwd = document.getElementById("featuredSeekFwd");
        const SEEK_SECONDS = 5;
        const DOUBLE_TAP_WINDOW_MS = 300;
        let lastTapAt = 0;
        let tapTimer = null;

        function flashSeek(el) {
            if (!el) return;
            el.classList.add("is-active");
            clearTimeout(el._flashTimer);
            el._flashTimer = setTimeout(() => el.classList.remove("is-active"), 450);
        }

        featuredVideo.addEventListener("pointerup", (e) => {
            if (e.pointerType === "mouse") return;

            const rect = featuredVideo.getBoundingClientRect();
            const NATIVE_CONTROLS_BAR_HEIGHT = 44;
            if (e.clientY > rect.bottom - NATIVE_CONTROLS_BAR_HEIGHT) return;

            const now = Date.now();
            const isDoubleTap = now - lastTapAt < DOUBLE_TAP_WINDOW_MS;
            lastTapAt = now;

            if (isDoubleTap) {
                clearTimeout(tapTimer);
                lastTapAt = 0;
                const isLeftHalf = (e.clientX - rect.left) < rect.width / 2;
                if (isLeftHalf) {
                    featuredVideo.currentTime = Math.max(0, featuredVideo.currentTime - SEEK_SECONDS);
                    flashSeek(seekBack);
                } else {
                    const duration = featuredVideo.duration || Infinity;
                    featuredVideo.currentTime = Math.min(duration, featuredVideo.currentTime + SEEK_SECONDS);
                    flashSeek(seekFwd);
                }
            } else {
                clearTimeout(tapTimer);
                tapTimer = setTimeout(() => {
                    lastTapAt = 0;
                    // Mobile Requirement: Tapping the video itself must NOT pause playback natively.
                    // The tap natively reveals the existing controls, but we also want to show our 
                    // custom large center PAUSE button temporarily if playing.
                    if (!featuredVideo.paused) {
                        overlayIcon.className = "fa-solid fa-pause";
                        overlay.className = "featured-play-overlay is-pause";
                        overlay.style.display = "";
                        
                        clearTimeout(overlayHideTimer);
                        overlayHideTimer = setTimeout(() => {
                            overlay.style.display = "none";
                        }, 3000);
                    }
                }, DOUBLE_TAP_WINDOW_MS);
            }
        });
    }
}

initFeaturedPlayOverlay();

/* ---------------- PLAYER CONTROL BAR (Player-Redesign) ----------------
   YouTube-style bottom bar layered on top of the existing playback
   system -- does not replace it. #featuredVideo, the HLS setup in
   showFeaturedMedia(), the center #featuredPlayOverlay, and the
   mobile double-tap-seek gesture in initFeaturedPlayOverlay() above
   are all untouched; this only adds a timeline/time/fullscreen row
   and auto-hide behavior, and keeps the play button here in sync
   with the same video element both of those already drive.

   Wired exactly once at script load -- #featuredVideo/#playerControlbar
   and their children are the same persistent DOM nodes for the page's
   lifetime (only what showFeaturedMedia() loads into the video
   changes), matching every other init*() in this file. */
function initPlayerControlbar() {
    const shot = document.getElementById("featuredShot");
    const video = document.getElementById("featuredVideo");
    const bar = document.getElementById("playerControlbar");
    const playBtn = document.getElementById("playerPlayBtn");
    const playIcon = playBtn ? playBtn.querySelector("i") : null;
    const timeEl = document.getElementById("playerTime");
    const timeline = document.getElementById("playerTimeline");
    const buffered = document.getElementById("playerBuffered");
    const played = document.getElementById("playerPlayed");
    const handle = document.getElementById("playerHandle");
    const fullscreenBtn = document.getElementById("playerFullscreenBtn");
    const loading = document.getElementById("playerLoading");
    if (!shot || !video || !bar || !playBtn || !timeline) return;

    function fmt(seconds) {
        if (!isFinite(seconds) || seconds < 0) return "0:00";
        const m = Math.floor(seconds / 60);
        const s = Math.floor(seconds % 60).toString().padStart(2, "0");
        return `${m}:${s}`;
    }

    function updatePlayIcon() {
        if (!playIcon) return;
        const playing = !video.paused && !video.ended;
        playIcon.className = playing ? "fa-solid fa-pause" : "fa-solid fa-play";
        playBtn.setAttribute("aria-label", playing ? "Pause" : "Play");
    }

    function updateTime() {
        const duration = video.duration || 0;
        if (timeEl) timeEl.textContent = `${fmt(video.currentTime)} / ${fmt(duration)}`;
        if (!duration || isScrubbing) return;
        const pct = Math.min(100, Math.max(0, (video.currentTime / duration) * 100));
        played.style.width = pct + "%";
        handle.style.left = pct + "%";
        timeline.setAttribute("aria-valuenow", Math.round(pct));
    }

    function updateBuffered() {
        const duration = video.duration || 0;
        if (!duration || !video.buffered || video.buffered.length === 0) return;
        const end = video.buffered.end(video.buffered.length - 1);
        buffered.style.width = Math.min(100, (end / duration) * 100) + "%";
    }

    // ---- Play/pause button ----
    playBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        if (video.paused) video.play().catch(() => {}); else video.pause();
    });
    ["play", "pause", "ended", "loadstart"].forEach(evt => video.addEventListener(evt, updatePlayIcon));

    // ---- Time / progress ----
    video.addEventListener("timeupdate", updateTime);
    video.addEventListener("loadedmetadata", () => { updateTime(); updateBuffered(); });
    video.addEventListener("durationchange", updateTime);
    video.addEventListener("progress", updateBuffered);

    // ---- Timeline scrub (click + drag), desktop and touch alike.
    // stopPropagation throughout: the timeline sits as a sibling over
    // the video, not a video descendant, so it can't natively bubble
    // into #featuredVideo's own pointerdown/pointerup handlers -- but
    // it CAN bubble up into #featuredShot's own activity listeners
    // (which is fine/wanted) and into the document-level quality-menu
    // closeMenu listener (which would otherwise flash-close an open
    // quality menu on every seek). Only ever calls play()/pause()
    // implicitly through scrubbing, never toggles playback state. ----
    let isScrubbing = false;

    function pctFromEvent(e) {
        const rect = timeline.getBoundingClientRect();
        const x = (e.clientX ?? (e.touches && e.touches[0] && e.touches[0].clientX)) - rect.left;
        return Math.min(1, Math.max(0, x / rect.width));
    }

    function scrubTo(e) {
        const duration = video.duration || 0;
        if (!duration) return;
        const pct = pctFromEvent(e);
        played.style.width = (pct * 100) + "%";
        handle.style.left = (pct * 100) + "%";
        timeline.setAttribute("aria-valuenow", Math.round(pct * 100));
        video.currentTime = pct * duration;
    }

    timeline.addEventListener("pointerdown", (e) => {
        e.stopPropagation();
        isScrubbing = true;
        timeline.classList.add("is-scrubbing");
        try { timeline.setPointerCapture(e.pointerId); } catch (err) {}
        scrubTo(e);
        showControls();
    });
    timeline.addEventListener("pointermove", (e) => {
        if (!isScrubbing) return;
        e.stopPropagation();
        scrubTo(e);
    });
    ["pointerup", "pointercancel"].forEach(evt => {
        timeline.addEventListener(evt, (e) => {
            if (!isScrubbing) return;
            e.stopPropagation();
            isScrubbing = false;
            timeline.classList.remove("is-scrubbing");
        });
    });
    timeline.addEventListener("click", (e) => e.stopPropagation());
    timeline.addEventListener("keydown", (e) => {
        const duration = video.duration || 0;
        if (!duration) return;
        if (e.key === "ArrowLeft") { video.currentTime = Math.max(0, video.currentTime - 5); showControls(); }
        else if (e.key === "ArrowRight") { video.currentTime = Math.min(duration, video.currentTime + 5); showControls(); }
    });

    // ---- Fullscreen ----
    if (fullscreenBtn) {
        fullscreenBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            requestVideoFullscreen();
        });
    }

    // ---- Loading indicator: hls.js's own load/decode retries (see
    // showFeaturedMedia) are separate from this -- purely cosmetic,
    // keyed off the native media events so it can't get out of sync
    // with what's actually happening. ----
    function showLoading() { if (loading) loading.style.display = ""; }
    function hideLoading() { if (loading) loading.style.display = "none"; }
    video.addEventListener("waiting", showLoading);
    video.addEventListener("seeking", showLoading);
    video.addEventListener("playing", hideLoading);
    video.addEventListener("canplay", hideLoading);
    video.addEventListener("pause", hideLoading);
    video.addEventListener("ended", hideLoading);
    video.addEventListener("loadstart", hideLoading);

    // ---- Auto-hide: controls fade out ~3s after the last interaction
    // while the video is actually playing; any interaction, or pausing,
    // or an open quality menu, brings them straight back. ----
    let idleTimer = null;
    const IDLE_MS = 3000;

    function showControls() {
        shot.classList.remove("is-idle");
        clearTimeout(idleTimer);
        const qualityMenu = document.getElementById("featuredQualityMenu");
        const menuOpen = qualityMenu && qualityMenu.style.display !== "none";
        if (!video.paused && !video.ended && !isScrubbing && !menuOpen) {
            idleTimer = setTimeout(() => {
                const stillMenuOpen = qualityMenu && qualityMenu.style.display !== "none";
                if (!video.paused && !video.ended && !isScrubbing && !stillMenuOpen) {
                    shot.classList.add("is-idle");
                }
            }, IDLE_MS);
        }
    }

    ["mousemove", "pointermove", "touchstart", "click", "keydown"].forEach(evt => {
        shot.addEventListener(evt, () => { if (video.style.display !== "none") showControls(); }, { passive: true });
    });
    video.addEventListener("play", showControls);
    video.addEventListener("pause", () => { shot.classList.remove("is-idle"); clearTimeout(idleTimer); });
    video.addEventListener("ended", () => { shot.classList.remove("is-idle"); clearTimeout(idleTimer); });

    updatePlayIcon();
}

initPlayerControlbar();

/* ---------------- NIMLYX ANALYSIS ----------------
   One premium dashboard, not six independent cards (Sprint 2 spec).
   Every sub-block is driven by real backend data and hidden --
   never rendered with a placeholder -- when that data is null:
     - nimlyx_score            -> the visual anchor of this dashboard;
                                   Quick Stats no longer duplicates it
     - reputation_trajectory   -> null unless statistically valid
                                   (see reputation_trajectory.py)
     - community_pulse         -> null if no real signal in the last
                                   100 reviews; positives/concerns
                                   each capped to 5 topics here
     - review_preview          -> up to 10 real Steam reviews total
                                   (see spotlight_reviews.compute_
                                   review_preview), pre-split into
                                   .positive/.negative arrays -- each
                                   independently empty if that game
                                   has no reviews in that direction
------------------------------------------------------------------ */

const NIMLYX_TOPIC_EMOJI = {
    combat: "⚔️",
    soundtrack: "🎵",
    story: "📖",
    ending: "🎬",
    servers: "🌐",
    performance: "🖥️",
    replayability: "🔁",
    grinding: "⛏️",
};

function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str ?? "";
    return div.innerHTML;
}

function renderNimlyxAnalysis(game) {
    const hasScore = !!game.nimlyx_score;
    const hasTrajectory = !!game.reputation_trajectory;
    const hasLoved = !!(game.community_pulse && game.community_pulse.positives && game.community_pulse.positives.length);
    const hasMentioned = !!(game.community_pulse && game.community_pulse.concerns && game.community_pulse.concerns.length);
    const hasPositiveReview = !!(game.review_preview && game.review_preview.positive && game.review_preview.positive.length);
    const hasNegativeReview = !!(game.review_preview && game.review_preview.negative && game.review_preview.negative.length);

    const hasAnything = hasScore || hasTrajectory || hasLoved || hasMentioned || hasPositiveReview || hasNegativeReview;

    const emptyEl = document.getElementById("nimlyxEmpty");
    const rowIds = ["nimlyxScore", "nimlyxRep", "nimlyxTopics", "nimlyxReviews"];
    const dividerIds = ["nimlyxTopicsDivider", "nimlyxReviewsDivider"];

    if (!hasAnything) {
        // Not one field to show -- a bare panel header with nothing
        // under it reads as broken, not "nothing to say yet". Show a
        // single honest message instead, and make sure nothing else
        // in the dashboard is left rendered underneath it.
        emptyEl.classList.remove("is-hidden");
        [...rowIds, ...dividerIds].forEach(id => document.getElementById(id).classList.add("is-hidden"));
        document.querySelector(".nimlyx-row--anchor").classList.add("is-hidden");
        return;
    }

    emptyEl.classList.add("is-hidden");
    renderNimlyxScoreAndReputation(game);
    renderNimlyxTopics(game);
    renderNimlyxReviews(game);
}

function renderNimlyxScoreAndReputation(game) {
    const scoreEl = document.getElementById("nimlyxScore");
    const repEl = document.getElementById("nimlyxRep");
    const score = game.nimlyx_score;
    const trajectory = game.reputation_trajectory;

    if (score) {
        const scoreClass = score.value >= 75 ? "is-good" : score.value >= 50 ? "is-mid" : "is-low";
        scoreEl.innerHTML = `
            <div class="nimlyx-score__value ${scoreClass}">${score.value}<span>/ 100</span></div>
            <div class="nimlyx-score__meta">
                <div class="nimlyx-score__verdict">${escapeHtml(score.verdict)}</div>
                <div class="nimlyx-score__note">Based on ${score.total_reviews.toLocaleString()}+ Steam reviews</div>
            </div>
        `;
        scoreEl.classList.remove("is-hidden");
    } else {
        scoreEl.classList.add("is-hidden");
    }

    // Data Rules: only render a trend claim when it's statistically
    // valid (reputation_trajectory.py already enforces this
    // server-side); otherwise hide the block entirely rather than
    // invent a "Stable Reputation" label the backend never computed.
    if (trajectory) {
        const isUp = trajectory.direction === "up";
        repEl.innerHTML = `
            <div class="nimlyx-rep__icon">${isUp ? "📈" : "📉"}</div>
            <div>
                <div class="nimlyx-rep__label ${isUp ? "is-up" : "is-down"}">${escapeHtml(trajectory.label)}</div>
                <div class="nimlyx-rep__note">${escapeHtml(trajectory.note)}</div>
            </div>
        `;
        repEl.classList.remove("is-hidden");
    } else {
        repEl.classList.add("is-hidden");
    }

    // If NEITHER half of the anchor row has anything to show, hide
    // the divider that would otherwise sit under an empty row.
    const anchorRow = document.querySelector(".nimlyx-row--anchor");
    if (!score && !trajectory) {
        anchorRow.classList.add("is-hidden");
    } else {
        anchorRow.classList.remove("is-hidden");
    }
}

function renderNimlyxTopicGroup(topics, iconClass, label) {
    if (!topics || topics.length === 0) return null;

    const pills = topics.slice(0, 5).map(t => {
        const emoji = NIMLYX_TOPIC_EMOJI[t.topic_id] || "•";
        return `
            <span class="nimlyx-topic-pill">
                <span class="nimlyx-topic-pill__emoji">${emoji}</span>${escapeHtml(t.label)}
            </span>
        `;
    }).join("");

    return `
        <div class="nimlyx-topic-group">
            <div class="nimlyx-topic-group__label"><i class="fa-solid ${iconClass}"></i>${label}</div>
            <div class="nimlyx-topic-list">${pills}</div>
        </div>
    `;
}

function renderNimlyxTopics(game) {
    const topicsEl = document.getElementById("nimlyxTopics");
    const dividerEl = document.getElementById("nimlyxTopicsDivider");
    const pulse = game.community_pulse;

    const lovedHtml = pulse ? renderNimlyxTopicGroup(pulse.positives, "fa-heart", "Players Loved") : null;
    const mentionedHtml = pulse ? renderNimlyxTopicGroup(pulse.concerns, "fa-triangle-exclamation", "Players Mentioned") : null;

    if (!lovedHtml && !mentionedHtml) {
        topicsEl.classList.add("is-hidden");
        dividerEl.classList.add("is-hidden");
        return;
    }

    topicsEl.innerHTML = (lovedHtml || "") + (mentionedHtml || "");
    topicsEl.classList.remove("is-hidden");
    dividerEl.classList.remove("is-hidden");
}

function renderNimlyxQuote(review, kind, steamReviewsUrl) {
    if (!review) return "";

    const isPositive = kind === "positive";
    const voteWord = review.votes_up === 1 ? "player" : "players";

    return `
        <div class="nimlyx-quote nimlyx-quote--${kind}" data-sentiment="${kind}">
            <div class="nimlyx-quote__label">
                <i class="fa-solid ${isPositive ? "fa-thumbs-up" : "fa-thumbs-down"}"></i>
                ${isPositive ? "Recommended" : "Not Recommended"}
            </div>
            <div class="nimlyx-quote__body">&ldquo;${escapeHtml(review.quote)}&rdquo;</div>
            <div class="nimlyx-quote__footer">
                <span class="nimlyx-quote__helpful">
                    <i class="fa-solid ${isPositive ? "fa-thumbs-up" : "fa-thumbs-down"}"></i>
                    Found helpful by ${review.votes_up.toLocaleString()} ${voteWord}
                </span>
                <a class="nimlyx-quote__link" href="${steamReviewsUrl}" target="_blank" rel="noopener">Read on Steam →</a>
            </div>
        </div>
    `;
}

/* Interleaves the positive/negative arrays for the "All" view so the
   default list isn't just every positive review followed by every
   negative one -- alternates sides, then appends whatever's left
   over on the longer side. Order within each side (Steam's own
   helpfulness ranking) is preserved either way. */
function interleaveReviews(positive, negative) {
    const merged = [];
    const max = Math.max(positive.length, negative.length);
    for (let i = 0; i < max; i++) {
        if (positive[i]) merged.push({ review: positive[i], kind: "positive" });
        if (negative[i]) merged.push({ review: negative[i], kind: "negative" });
    }
    return merged;
}

function renderNimlyxReviews(game) {
    const reviewsEl = document.getElementById("nimlyxReviews");
    const dividerEl = document.getElementById("nimlyxReviewsDivider");
    const filterEl = document.getElementById("nimlyxReviewFilter");
    const filterEmptyEl = document.getElementById("nimlyxReviewFilterEmpty");
    const headingEl = document.getElementById("nimlyxReviewsHeading");
    const ctaEl = document.getElementById("nimlyxReviewsCta");
    const preview = game.review_preview;

    const positive = (preview && preview.positive) || [];
    const negative = (preview && preview.negative) || [];

    if (!positive.length && !negative.length) {
        // Clear out any previous game's cards -- reviewsEl.innerHTML
        // is only ever swapped below, never appended to, but this
        // guards against stale nodes lingering when a new game
        // simply has no reviews at all.
        reviewsEl.innerHTML = "";
        reviewsEl.classList.add("is-hidden");
        dividerEl.classList.add("is-hidden");
        if (filterEl) filterEl.classList.add("is-hidden");
        if (filterEmptyEl) filterEmptyEl.classList.add("is-hidden");
        if (headingEl) headingEl.classList.add("is-hidden");
        if (ctaEl) ctaEl.classList.add("is-hidden");
        return;
    }

    // Cache the current game's shaped review data + sentiment counts
    // on the row element itself so applyNimlyxReviewFilter() (called
    // both here and from the click handler) can re-render per
    // sentiment without re-deriving anything or touching `game`
    // again -- avoids stale-closure bugs when the user switches games
    // between clicks.
    reviewsEl.dataset.steamReviewsUrl = game.steam_reviews_url || "";
    reviewsEl._nimlyxReviewData = { positive, negative };

    if (headingEl) {
        const total = game.total_reviews;
        headingEl.textContent = total ? `${total.toLocaleString()} reviews` : "Reviews";
        headingEl.classList.remove("is-hidden");
    }

    if (ctaEl && game.steam_reviews_url) {
        ctaEl.href = game.steam_reviews_url;
        ctaEl.classList.remove("is-hidden");
    } else if (ctaEl) {
        ctaEl.classList.add("is-hidden");
    }

    dividerEl.classList.remove("is-hidden");

    // Sentiment Filter: game.review_preview is already sentiment-split
    // by the backend and already fully present in `game` -- no
    // separate fetch, no pagination, nothing to recalculate. Reset to
    // "All" on every render (new game, or a repeat render of the same
    // one) so switching games never leaves a stale Positive/Negative
    // selection, and never leaves the previous game's cards behind.
    if (filterEl) filterEl.classList.remove("is-hidden");
    applyNimlyxReviewFilter("all");
}

/* ---------------- REVIEW SENTIMENT FILTER ----------------
   Toggles which of the two already-rendered .nimlyx-quote cards
   (#nimlyxReviews, built by renderNimlyxReviews() above) are visible,
   using the existing .is-hidden convention already defined for them
   in search.css. No new sentiment classification and no separate
   review fetch -- "positive"/"negative" here are exactly
   game.review_preview.positive/.negative, unchanged.

   Click handling is wired exactly ONCE at script load, same pattern
   as initMediaGlow()/initScreenshotLightbox() above: #nimlyxReviewFilter
   and its three buttons are the same persistent DOM nodes for the
   page's lifetime (renderNimlyxReviews() only ever swaps what's
   inside #nimlyxReviews, never rebuilds the filter itself), so this
   can't produce duplicate listeners/duplicate handling across repeat
   renders. */
function initNimlyxReviewFilter() {
    const filterEl = document.getElementById("nimlyxReviewFilter");
    if (!filterEl) return;

    filterEl.addEventListener("click", (e) => {
        const btn = e.target.closest("[data-sentiment]");
        if (!btn) return;
        applyNimlyxReviewFilter(btn.dataset.sentiment);
    });
}

initNimlyxReviewFilter();

function applyNimlyxReviewFilter(sentiment) {
    const filterEl = document.getElementById("nimlyxReviewFilter");
    const emptyEl = document.getElementById("nimlyxReviewFilterEmpty");
    const reviewsEl = document.getElementById("nimlyxReviews");
    if (!filterEl || !reviewsEl) return;

    // Re-render (not toggle) the up-to-10 cards for the selected
    // sentiment from the data cached on #nimlyxReviews by
    // renderNimlyxReviews() -- data.positive/.negative are the same
    // arrays every time, so switching tabs never appends onto
    // whatever was there before and never leaves duplicate/stale
    // nodes behind (see task note on avoiding stale DOM on filter
    // switches and on game-to-game navigation).
    const data = reviewsEl._nimlyxReviewData || { positive: [], negative: [] };
    const steamReviewsUrl = reviewsEl.dataset.steamReviewsUrl || "";

    let cards;
    if (sentiment === "positive") {
        cards = data.positive.map(r => ({ review: r, kind: "positive" }));
    } else if (sentiment === "negative") {
        cards = data.negative.map(r => ({ review: r, kind: "negative" }));
    } else {
        cards = interleaveReviews(data.positive, data.negative);
    }

    reviewsEl.innerHTML = cards.map(c => renderNimlyxQuote(c.review, c.kind, steamReviewsUrl)).join("");
    reviewsEl.classList.toggle("is-hidden", cards.length === 0);

    // Empty state: only when the selected sentiment genuinely has no
    // reviews in this game's preview (e.g. only positive reviews
    // exist and "Negative" is selected) -- "All" can never hit this,
    // since renderNimlyxReviews() already hides the whole section
    // (filter included) when the preview is empty on both sides.
    if (emptyEl) {
        if (cards.length === 0) {
            emptyEl.textContent = `No ${sentiment} reviews found.`;
            emptyEl.classList.remove("is-hidden");
        } else {
            emptyEl.classList.add("is-hidden");
        }
    }

    filterEl.querySelectorAll("[data-sentiment]").forEach(btn => {
        const active = btn.dataset.sentiment === sentiment;
        btn.classList.toggle("is-active", active);
        btn.setAttribute("aria-selected", active ? "true" : "false");
    });
}

/* ---------------- PURCHASE OPTIONS ----------------
   "Which version should I buy?" -- every way to buy this game
   (base game, Complete/GOTY/Deluxe editions, bundles), sourced
   straight from Steam's own package_groups data (see
   build_purchase_options in steam.py). The base game itself is
   always game.purchase_options[0] (is_base_game: true), matching
   Steam's own ordering.

   Purely additive, same as the card this replaced: the rest of the
   page (hero/about/media/reviews/genres) always describes the
   resolved base app_id regardless of what's in this list. Hidden
   entirely (not rendered empty) whenever purchase_options is empty
   -- e.g. many F2P titles genuinely have nothing else to show here. */

function renderPurchaseOptions(game) {
    const section = document.getElementById("purchasePanel");
    const container = document.getElementById("purchaseOptions");
    if (!section || !container) return;

    const options = game.purchase_options || [];
    if (!options.length) {
        section.classList.add("is-hidden");
        container.innerHTML = "";
        return;
    }

    // The package the visitor actually clicked to land here (a
    // Complete/GOTY/Deluxe Edition search result) -- see
    // highlighted_package_id in routes/game.py. Absent for anyone who
    // came in through the base game directly.
    const highlightId = game.highlighted_package_id ? String(game.highlighted_package_id) : null;

    container.innerHTML = options.map(opt => {
        const hasDiscount = opt.discount > 0 && opt.original_price;
        const includedApps = (opt.included_apps || []).filter(a => a.name);
        const isHighlighted = highlightId && String(opt.package_id) === highlightId;

        return `
            <div class="purchase-option${isHighlighted ? " is-highlighted" : ""}">
                <div class="purchase-option__main">
                    <div class="purchase-option__tags">
                        ${opt.is_base_game ? `<span class="purchase-option__tag">Base Game</span>` : ""}
                        ${hasDiscount ? `<span class="purchase-option__discount"><i class="fa-solid fa-arrow-down"></i>-${opt.discount}%</span>` : ""}
                    </div>
                    <div class="purchase-option__name">${escapeHtml(opt.name || "Steam Package")}</div>
                    ${includedApps.length ? `
                        <div class="purchase-option__included">
                            Includes ${includedApps.map(a => escapeHtml(a.name)).join(", ")}
                        </div>
                    ` : ""}
                </div>
                <div class="purchase-option__side">
                    <div class="purchase-option__price">
                        ${hasDiscount ? `<span class="purchase-option__price-original">${opt.original_price}</span>` : ""}
                        <span class="purchase-option__price-current">${opt.price || ""}</span>
                    </div>
                    <a class="home-btn home-btn-ghost purchase-option__cta" href="${opt.steam_url || "#"}" target="_blank" rel="noopener">
                        <i class="fa-solid fa-arrow-up-right-from-square"></i> View on Steam
                    </a>
                </div>
            </div>
        `;
    }).join("");

    section.classList.remove("is-hidden");
}

/* ---------------- CREDITS ---------------- */

function renderCredits(game) {
    document.getElementById("devValue").textContent = (game.developers || []).join(", ") || "Unknown";
    document.getElementById("pubValue").textContent = (game.publishers || []).join(", ") || "Unknown";
}

/* ---------------- QUICK STATS ---------------- */

function renderStats(game) {
    const scoreClass = game.metacritic >= 75 ? "is-good" : game.metacritic >= 50 ? "is-mid" : "is-low";

    const platformNames = Object.keys(game.platforms)
        .filter(p => game.platforms[p])
        .map(p => p.charAt(0).toUpperCase() + p.slice(1));

    document.getElementById("statsRows").innerHTML = `
        <div class="info-row">
            <span class="info-row__label"><i class="fa-solid fa-tag"></i>Price</span>
            <span class="info-row__value">${game.discount > 0 ? `<span class="stat-discount">-${game.discount}%</span> ${game.price}` : game.price}</span>
        </div>
        ${game.review_score_desc ? `
        <div class="info-row">
            <span class="info-row__label"><i class="fa-solid fa-comment"></i>Review Score</span>
            <span class="info-row__value">${game.review_score_desc}</span>
        </div>` : ""}
        ${game.metacritic ? `
        <div class="info-row">
            <span class="info-row__label"><i class="fa-solid fa-star"></i>Metacritic</span>
            <span class="info-row__value ${scoreClass === "is-good" ? "is-good" : ""}">${game.metacritic} / 100</span>
        </div>` : ""}
        <div class="info-row">
            <span class="info-row__label"><i class="fa-solid fa-users"></i>Reviews</span>
            <span class="info-row__value">${game.total_reviews.toLocaleString()}</span>
        </div>
        <div class="info-row">
            <span class="info-row__label"><i class="fa-solid fa-desktop"></i>Platforms</span>
            <span class="info-row__value">${platformNames.map(p => `<span class="mini-badge">${p}</span>`).join("")}</span>
        </div>
        <div class="info-row">
            <span class="info-row__label"><i class="fa-solid fa-tags"></i>Genres</span>
            <span class="info-row__value">${(game.genres || []).map(g => `<span class="mini-badge">${g}</span>`).join("") || "—"}</span>
        </div>
        <div class="info-row">
            <span class="info-row__label"><i class="fa-regular fa-calendar"></i>Release</span>
            <span class="info-row__value">${game.release_date || "TBA"}</span>
        </div>
    `;
}

/* ---------------- SYSTEM REQUIREMENTS (Sprint 5) ----------------
   game.requirements is already normalized by the backend --
   {minimum: {os,cpu,gpu,ram,storage}, recommended: {...}} -- see
   services/game/requirements.py. This function only renders it; no
   HTML parsing happens client-side, per the Sprint 5 spec. */

const REQUIREMENT_FIELD_ORDER = [
    { key: "os", label: "OS", icon: "fa-solid fa-desktop" },
    { key: "cpu", label: "Processor", icon: "fa-solid fa-microchip" },
    { key: "gpu", label: "Graphics", icon: "fa-solid fa-tv" },
    { key: "ram", label: "Memory", icon: "fa-solid fa-memory" },
    { key: "storage", label: "Storage", icon: "fa-solid fa-hard-drive" },
];

function _renderRequirementTier(tier, title, modifier) {
    const rows = REQUIREMENT_FIELD_ORDER
        .filter(f => tier[f.key])
        .map(f => `
            <div class="info-row">
                <span class="info-row__label"><i class="${f.icon}"></i>${f.label}</span>
                <span class="info-row__value">${tier[f.key]}</span>
            </div>
        `).join("");

    if (!rows) return "";

    // modifier ("is-minimum" / "is-recommended") drives the visual
    // split between the two tiers -- see .requirements-tier--* in
    // search.css. Without this the two columns were styled
    // identically and only distinguishable by small label text,
    // which read as "8 identical cards" rather than two tiers.
    const icon = modifier === "is-recommended" ? "fa-solid fa-circle-check" : "fa-regular fa-circle";

    return `
        <div class="requirements-tier ${modifier}">
            <h3 class="requirements-tier__title"><i class="${icon}"></i>${title}</h3>
            <div class="stats-grid">${rows}</div>
        </div>
    `;
}

function renderRequirements(game) {
    const panel = document.getElementById("requirementsPanel");
    const requirements = game.requirements;

    if (!requirements) {
        panel.classList.add("is-hidden");
        return;
    }

    const minimumHtml = _renderRequirementTier(requirements.minimum || {}, "Minimum", "is-minimum");
    const recommendedHtml = _renderRequirementTier(requirements.recommended || {}, "Recommended", "is-recommended");

    // No usable fields in EITHER tier -- Steam had no parseable
    // requirements for this game (see requirements.py Case 3/4).
    // Nothing honest to show, so the whole panel stays hidden rather
    // than rendering an empty shell.
    if (!minimumHtml && !recommendedHtml) {
        panel.classList.add("is-hidden");
        return;
    }

    document.getElementById("requirementsGrid").innerHTML = minimumHtml + recommendedHtml;
    panel.classList.remove("is-hidden");
}

/* ==========================================================
   SCROLL REVEAL
========================================================== */

function initScrollReveal() {
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!reduceMotion && "IntersectionObserver" in window) {
        const io = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    entry.target.classList.add("in-view");
                    io.unobserve(entry.target);
                }
            });
        }, { threshold: 0.12 });
        document.querySelectorAll(".reveal").forEach(el => io.observe(el));
    } else {
        document.querySelectorAll(".reveal").forEach(el => el.classList.add("in-view"));
    }
}

/* ==========================================================
   COMPATIBILITY CHECK (new feature)
   Backend: services/hardware/compatibility.py +
   requirement_matching.py + ram_parsing.py + rankings_loader.py,
   exposed via POST /api/game/<app_id>/compatibility. CPU/GPU
   selector options come from GET /api/hardware/catalog (same
   validated ranking catalog the engine itself reads).

   This block owns exactly one section (#compatibilityPanel) and
   touches nothing else on the page -- same isolation as
   renderRequirements() above. All comparison logic is server-side;
   this only sends the user's selection and renders whatever the API
   returns, verbatim (including null/"unable to determine" states --
   never guessed into a pass or fail on the client).
========================================================== */

let _compatCatalogPromise = null;

/** Fetches /api/hardware/catalog once per page load and caches the
 * promise -- reused across every game the user views in this SPA
 * session (the catalog itself doesn't change per-game), and dedupes
 * concurrent callers so a fast game-to-game navigation can't fire it
 * twice. */
function getHardwareCatalog() {
    if (!_compatCatalogPromise) {
        _compatCatalogPromise = fetch("/api/hardware/catalog")
            .then(res => {
                if (!res.ok) throw new Error(`Hardware catalog request failed (${res.status})`);
                return res.json();
            })
            .catch(error => {
                // Reset so a later retry (e.g. next game page visit)
                // gets a fresh attempt instead of a cached failure.
                _compatCatalogPromise = null;
                throw error;
            });
    }
    return _compatCatalogPromise;
}

/* ----------------------------------------------------------------
   Searchable CPU/GPU combobox
   Replaces the old native <select> (which had to render every one of
   the ~418 CPU / ~2,627 GPU catalog rows as an <option>). The catalog
   itself and the API contract are unchanged -- this is purely a
   client-side search/filter layer over the same GET
   /api/hardware/catalog payload, writing the chosen external_id into
   the existing hidden #compatCpuSelect / #compatGpuSelect inputs so
   _runCompatibilityCheck() needs no changes at all.

   Matching is deliberately more lenient than the backend's
   requirement_matching.py (which must stay exact-key-only so it
   never guesses a Steam requirement's identity) -- here the user is
   explicitly picking their OWN hardware from a visible list, so a
   forgiving "every typed word appears somewhere in vendor+name"
   substring match is the right trade-off: it's what makes bare
   numbers ("2600"), missing vendor prefixes ("RX 5600 XT" without
   "AMD"), and missing brand words ("NVIDIA RTX 5050" without
   "GeForce") all find the right rows, while the user still confirms
   the exact match themselves before it's submitted.
---------------------------------------------------------------- */

const COMPAT_SEARCH_DEBOUNCE_MS = 120;
const COMPAT_SEARCH_MAX_RESULTS = 50;

function _compactUpper(text) {
    return (text || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
}

/** Every typed word (split on whitespace) must appear somewhere in
 * the item's "vendor + name" compact haystack -- order-independent,
 * so "AMD 2600", "Ryzen 5 2600", and "2600" all match "AMD Ryzen 5
 * 2600", and "NVIDIA RTX 5050" matches "GeForce RTX 5050" (vendor
 * NVIDIA) even though the word "NVIDIA" never appears in the name
 * itself. */
function _filterHardwareItems(items, query, vendorKey) {
    const tokens = query.trim().split(/\s+/).filter(Boolean).map(_compactUpper).filter(Boolean);
    if (!tokens.length) return [];

    const scored = [];
    for (const item of items) {
        const haystack = _compactUpper((item[vendorKey] || "") + item.name);
        if (tokens.every(t => haystack.includes(t))) {
            // Rough relevance: shorter names and earlier match
            // position surface more specific/likely matches first
            // without needing a real ranking algorithm.
            const firstIdx = haystack.indexOf(tokens[0]);
            scored.push({ item, score: firstIdx * 1000 + item.name.length });
        }
    }
    scored.sort((a, b) => a.score - b.score);
    return scored.slice(0, COMPAT_SEARCH_MAX_RESULTS).map(s => s.item);
}

/** Wires one combobox (CPU or GPU) up to search/select/keyboard-nav
 * behavior. `items` is the full catalog array for that hardware type
 * (already fetched via getHardwareCatalog()); `vendorKey` is
 * "manufacturer" for CPUs or "vendor" for GPUs, matching the shape
 * /api/hardware/catalog already returns. Returns a `reset()` function
 * so initCompatibility() can clear the field when the user navigates
 * to a different game. */
function _initHardwareCombobox({ inputId, listboxId, clearBtnId, hiddenId, items, vendorKey, placeholder }) {
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

// VRAM is GPU-only, catalog-provided (vram_gb), display-only context --
// never sent to the backend, never used in matching. Shown "where
// possible": only when the catalog actually has a value for this record,
// never fabricated for records with missing data. Whole-GB values print
// without a decimal ("4GB"), fractional ones keep one decimal ("1.5GB").
function _vramLabel(item) {
    const vram = item && item.vram_gb;
    if (vram === null || vram === undefined || Number.isNaN(Number(vram))) return "";
    const num = Number(vram);
    const formatted = Number.isInteger(num) ? String(num) : num.toFixed(1);
    return `${formatted}GB`;
}

function _displayHardwareName(item, vendorKey) {
    // Some catalog names already include the vendor (CPU
    // model_name is always "Intel ..."/"AMD ..."), others don't (GPU
    // name is "Radeon RX 590", not "AMD Radeon RX 590"). Only
    // prepend the vendor when the name doesn't already start with it,
    // so the display never doubles up ("AMD AMD Ryzen 5 2600").
    const vendor = (item[vendorKey] || "").trim();
    const name = (item.name || "").trim();
    const base = (!vendor || name.toUpperCase().startsWith(vendor.toUpperCase()))
        ? name
        : `${vendor} ${name}`;
    const vramLabel = _vramLabel(item);
    // Skip appending if the catalog name already spells out the VRAM
    // (e.g. "GeForce GTX 1060 6 GB") to avoid a redundant "...6 GB (6GB)".
    if (!vramLabel || base.toUpperCase().includes(vramLabel.toUpperCase())) return base;
    return `${base} (${vramLabel})`;
}

    function selectItem(item) {
        hidden.value = item.external_id;
        input.value = _displayHardwareName(item, vendorKey);
        clearBtn.classList.remove("is-hidden");
        closeListbox();
    }

    function clearSelection({ focus = true } = {}) {
        hidden.value = "";
        input.value = "";
        clearBtn.classList.add("is-hidden");
        closeListbox();
        if (focus) input.focus();
    }

    function renderResults(query) {
        const matches = _filterHardwareItems(items, query, vendorKey);
        currentResults = matches;
        highlightedIndex = matches.length ? 0 : -1;

        if (!matches.length) {
            listbox.innerHTML = `<li class="compat-combobox__empty">No hardware found for "${query.replace(/</g, "&lt;")}"</li>`;
            listbox.classList.remove("is-hidden");
            input.setAttribute("aria-expanded", "true");
            return;
        }

        listbox.innerHTML = matches.map((item, i) => {
            // Only show the vendor tag when the name doesn't already
            // start with it (see _displayHardwareName) -- avoids a
            // redundant "AMD | AMD Ryzen 5 2600" row for CPUs, while
            // GPUs (name has no vendor prefix) still get the tag.
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
        // Typing invalidates any prior selection until a new one is
        // explicitly confirmed -- matches the spec's "allow
        // clearing/changing the selection" requirement.
        if (hidden.value) {
            hidden.value = "";
            clearBtn.classList.add("is-hidden");
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

    listbox.addEventListener("click", (e) => {
        const optionEl = e.target.closest(".compat-combobox__option");
        if (!optionEl) return;
        const idx = Number(optionEl.dataset.index);
        if (currentResults[idx]) selectItem(currentResults[idx]);
    });

    clearBtn.addEventListener("click", () => clearSelection());

    document.addEventListener("click", (e) => {
        if (!combobox.contains(e.target)) closeListbox();
    });

    return {
        reset() { clearSelection({ focus: false }); },
    };
}

let _compatChecking = false; // request-guard -- prevents duplicate in-flight checks

function _setCompatLoading(isLoading) {
    const btn = document.getElementById("compatCheckBtn");
    const icon = document.getElementById("compatCheckBtnIcon");
    const label = document.getElementById("compatCheckBtnText");
    if (!btn) return;

    _compatChecking = isLoading;
    btn.disabled = isLoading;
    if (icon) {
        icon.className = isLoading
            ? "fa-solid fa-spinner fa-spin"
            : "fa-solid fa-magnifying-glass-chart";
    }
    if (label) label.textContent = isLoading ? "Checking\u2026" : "Check Compatibility";
}

function _showCompatError(message) {
    const errorEl = document.getElementById("compatError");
    const resultEl = document.getElementById("compatResult");
    if (resultEl) resultEl.classList.add("is-hidden");
    if (errorEl) {
        errorEl.innerHTML = `<i class="fa-solid fa-triangle-exclamation"></i><span>${message}</span>`;
        errorEl.classList.remove("is-hidden");
    }
}

function _clearCompatError() {
    const errorEl = document.getElementById("compatError");
    if (errorEl) errorEl.classList.add("is-hidden");
}

const COMPAT_VERDICT_META = {
    runs_well: { icon: "fa-solid fa-circle-check", cls: "is-good", emoji: "\u{1F7E2}", title: "Runs Well", subtitle: "This hardware meets or exceeds the recommended specs." },
    playable: { icon: "fa-solid fa-triangle-exclamation", cls: "is-mid", emoji: "\u{1F7E1}", title: "Playable", subtitle: "This hardware meets the minimum requirements, but not every recommended spec." },
    not_recommended: { icon: "fa-solid fa-circle-xmark", cls: "is-low", emoji: "\u{1F534}", title: "Not Recommended", subtitle: "This hardware falls below the minimum requirements for at least one component." },
};

const COMPAT_COMPONENT_META = {
    cpu: { label: "CPU", icon: "fa-solid fa-microchip" },
    gpu: { label: "GPU", icon: "fa-solid fa-tv" },
    ram: { label: "RAM", icon: "fa-solid fa-memory" },
};

/** One meets_minimum/meets_recommended -> {icon, cls, text} row.
 * `null` is ALWAYS rendered as a neutral, non-failure state -- this
 * is the client-side half of the same rule the backend's
 * compatibility engine enforces (see compatibility.py's module
 * docstring on preserving uncertainty rather than guessing). Worded
 * as "Unable to compare" (not "Unable to determine") specifically so
 * it doesn't read as a hardware failure -- it's a statement about
 * what Nimlyx could match, not about the user's PC. */
function _compatRowState(value, passLabel, failLabel) {
    if (value === true) return { cls: "is-pass", icon: "fa-solid fa-check", text: passLabel };
    if (value === false) return { cls: "is-fail", icon: "fa-solid fa-xmark", text: failLabel };
    return {
        cls: "is-unknown", icon: "fa-solid fa-question", text: "Unable to compare",
        note: "Nimlyx couldn't confidently match this requirement to its hardware database.",
    };
}

function _renderCompatComponent(componentResult) {
    const meta = COMPAT_COMPONENT_META[componentResult.component] || { label: componentResult.component, icon: "fa-solid fa-circle" };
    const minState = _compatRowState(componentResult.meets_minimum, "Meets minimum", "Below minimum");
    const recState = _compatRowState(componentResult.meets_recommended, "Meets recommended", "Below recommended");
    const minNote = minState.note ? `<div class="compat-component__note">${minState.note}</div>` : "";
    const recNote = recState.note ? `<div class="compat-component__note">${recState.note}</div>` : "";

    return `
        <div class="compat-component">
            <div class="compat-component__label"><i class="${meta.icon}"></i>${meta.label}</div>
            <div class="compat-component__row ${minState.cls}"><i class="${minState.icon}"></i>${minState.text}</div>
            ${minNote}
            <div class="compat-component__row ${recState.cls}"><i class="${recState.icon}"></i>${recState.text}</div>
            ${recNote}
        </div>
    `;
}

function _renderCompatResult(result) {
    const resultEl = document.getElementById("compatResult");
    if (!resultEl) return;

    // Malformed-response guard -- if the API ever returns something
    // that doesn't match the expected contract, fail into the error
    // state rather than throwing mid-render or silently showing a
    // blank/broken panel.
    if (!result || typeof result.verdict !== "string" || !Array.isArray(result.components)) {
        _showCompatError("Nimlyx received an unexpected response while checking compatibility. Please try again.");
        return;
    }

    const verdictMeta = COMPAT_VERDICT_META[result.verdict];
    if (!verdictMeta) {
        _showCompatError("Nimlyx received an unrecognized compatibility result. Please try again.");
        return;
    }

    const componentOrder = ["cpu", "gpu", "ram"];
    const byComponent = new Map(result.components.map(c => [c.component, c]));
    const componentsHtml = componentOrder
        .filter(key => byComponent.has(key))
        .map(key => _renderCompatComponent(byComponent.get(key)))
        .join("");

    const notes = Array.isArray(result.notes) ? result.notes.filter(Boolean) : [];
    const notesHtml = notes.length ? `
        <div class="compat-notes">
            <div class="compat-notes__title"><i class="fa-solid fa-circle-info"></i>Nimlyx notes</div>
            <ul class="compat-notes__list">
                ${notes.map(n => `<li>${n}</li>`).join("")}
            </ul>
        </div>
    ` : "";

    resultEl.innerHTML = `
        <div class="compat-verdict ${verdictMeta.cls}">
            <div class="compat-verdict__icon"><i class="${verdictMeta.icon}"></i></div>
            <div>
                <div class="compat-verdict__title">${verdictMeta.emoji} ${verdictMeta.title}</div>
                <div class="compat-verdict__subtitle">${verdictMeta.subtitle}</div>
            </div>
        </div>
        <div class="compat-components">${componentsHtml}</div>
        ${notesHtml}
    `;
    resultEl.classList.remove("is-hidden");
}

async function _runCompatibilityCheck(appId) {
    if (_compatChecking) return; // duplicate-click guard

    _clearCompatError();
    _setCompatLoading(true);

    try {
        const cpuId = document.getElementById("compatCpuSelect")?.value || null;
        const gpuId = document.getElementById("compatGpuSelect")?.value || null;
        const ramRaw = document.getElementById("compatRamSelect")?.value || "";
        const ramGb = ramRaw ? Number(ramRaw) : null;

        const response = await fetch(`/api/game/${encodeURIComponent(appId)}/compatibility`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                cpu_external_id: cpuId,
                gpu_external_id: gpuId,
                ram_gb: ramGb,
            }),
        });

        let data;
        try {
            data = await response.json();
        } catch {
            throw new Error("MALFORMED");
        }

        if (!response.ok) {
            const message = (data && data.error) || `Request failed (${response.status})`;
            throw new Error(message === "Game not found" ? "GAME_NOT_FOUND" : message);
        }

        _renderCompatResult(data);
    } catch (error) {
        console.error("Compatibility check failed:", error);
        if (error.message === "GAME_NOT_FOUND") {
            _showCompatError("This game's requirements couldn't be found right now. Please try again later.");
        } else if (error.message === "MALFORMED") {
            _showCompatError("Nimlyx received an unexpected response while checking compatibility. Please try again.");
        } else if (error instanceof TypeError) {
            // fetch() throws a TypeError specifically on network-level
            // failure (offline, DNS, CORS) -- distinct from a
            // non-2xx HTTP response, which is handled above instead.
            _showCompatError("Couldn't reach Nimlyx to check compatibility. Check your connection and try again.");
        } else {
            _showCompatError("Something went wrong while checking compatibility. Please try again.");
        }
    } finally {
        _setCompatLoading(false);
    }
}

let _compatCpuCombobox = null;
let _compatGpuCombobox = null;

function initCompatibility(game) {
    const panel = document.getElementById("compatibilityPanel");
    if (!panel) return;

    // Same "nothing honest to show" rule renderRequirements() above
    // already follows -- if Steam gave this game no usable
    // requirement text at all, there's nothing meaningful to check
    // against, so the section stays hidden rather than offering a
    // form that can only ever return "unable to determine" for
    // every component.
    const req = game.requirements || {};
    const min = req.minimum || {};
    const rec = req.recommended || {};
    const hasAnyRequirement = ["cpu", "gpu", "ram"].some(k => min[k] || rec[k]);
    if (!hasAnyRequirement) {
        panel.classList.add("is-hidden");
        return;
    }
    panel.classList.remove("is-hidden");

    // Reset any previous game's result/error/selection when
    // navigating game-to-game in this SPA -- otherwise a stale
    // verdict from the last game briefly shows under the new one's
    // requirements before the user does anything.
    document.getElementById("compatResult")?.classList.add("is-hidden");
    _clearCompatError();
    _setCompatLoading(false);

    // Reset any previously-typed/selected hardware from the last
    // game before this game's catalog-driven combobox is (re)wired.
    _compatCpuCombobox?.reset();
    _compatGpuCombobox?.reset();

    getHardwareCatalog()
        .then(catalog => {
            // Combobox event listeners are only bound once per page
            // load (guarded by _compatCpuCombobox/_compatGpuCombobox
            // already being set) -- same "bind once, re-target per
            // game via reset() above" pattern the Check button below
            // already uses, so re-entering this page's SPA flow for a
            // different game doesn't double-bind listeners.
            if (!_compatCpuCombobox) {
                _compatCpuCombobox = _initHardwareCombobox({
                    inputId: "compatCpuInput", listboxId: "compatCpuListbox",
                    clearBtnId: "compatCpuClear", hiddenId: "compatCpuSelect",
                    items: catalog.cpus, vendorKey: "manufacturer",
                    placeholder: "Search your CPU\u2026",
                });
            }
            if (!_compatGpuCombobox) {
                _compatGpuCombobox = _initHardwareCombobox({
                    inputId: "compatGpuInput", listboxId: "compatGpuListbox",
                    clearBtnId: "compatGpuClear", hiddenId: "compatGpuSelect",
                    items: catalog.gpus, vendorKey: "vendor",
                    placeholder: "Search your GPU\u2026",
                });
            }
        })
        .catch(error => {
            console.error("Error loading hardware catalog:", error);
            _showCompatError("Couldn't load the hardware list right now. Please refresh and try again.");
        });

    const btn = document.getElementById("compatCheckBtn");
    if (btn && !btn.dataset.compatBound) {
        // Bound once per page load (not once per game) -- app_id is
        // read fresh from the button's own dataset at click time
        // (set below on every initCompatibility() call), so a single
        // listener correctly targets whichever game is currently
        // displayed even across SPA navigations.
        btn.dataset.compatBound = "true";
        btn.addEventListener("click", () => {
            const currentAppId = btn.dataset.compatAppId;
            if (currentAppId) _runCompatibilityCheck(currentAppId);
        });
    }
    if (btn) btn.dataset.compatAppId = game.app_id;
}
