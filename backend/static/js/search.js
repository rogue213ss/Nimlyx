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

function searchGame(name) {
    window.location.href = `/search?q=${encodeURIComponent(name)}`;
}

document.getElementById("searchBtn").addEventListener("click", () => {
    const gameName = document.getElementById("gameInput").value.trim();
    if (!gameName) return;
    searchGame(gameName);
});

let debounceTimer;
let activeSuggestionIndex = -1;

document.getElementById("gameInput").addEventListener("input", (e) => {
    clearTimeout(debounceTimer);
    const query = e.target.value;

    if (query.length < 2) {
        document.getElementById("suggestions").innerHTML = "";
        return;
    }

    debounceTimer = setTimeout(() => {
        fetchSuggestions(query);
    }, 400);
});

document.getElementById("gameInput").addEventListener("keydown", (e) => {
    const suggestionsBox = document.getElementById("suggestions");
    const items = suggestionsBox.querySelectorAll(".suggestion-item");

    if (items.length === 0) {
        if (e.key === "Enter") document.getElementById("searchBtn").click();
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
        if (activeSuggestionIndex >= 0) {
            items[activeSuggestionIndex].click();
        } else {
            document.getElementById("searchBtn").click();
        }
    }
});

function updateActiveSuggestion(items) {
    items.forEach(item => item.classList.remove("active-suggestion"));
    if (activeSuggestionIndex >= 0) {
        items[activeSuggestionIndex].classList.add("active-suggestion");
        items[activeSuggestionIndex].scrollIntoView({ block: "nearest" });
    }
}

async function fetchSuggestions(query) {
    activeSuggestionIndex = -1;
    const response = await fetch(`/api/search/${query}`);
    const data = await response.json();

    const suggestionsBox = document.getElementById("suggestions");
    suggestionsBox.innerHTML = "";

    if (!data.items || data.items.length === 0) return;

    data.items.slice(0, 5).forEach(game => {
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
            searchGame(game.name);
        });

        suggestionsBox.appendChild(item);
    });
}

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
const searchListRows = document.getElementById("searchListRows");
const searchFilterSidebar = document.getElementById("searchFilterSidebar");
const searchResultsTitle = document.getElementById("searchResultsTitle");

function showDetailView() {
    if (searchResultsView) searchResultsView.classList.add("is-hidden");
    if (gameDetailView) gameDetailView.classList.remove("is-hidden");
    const errorState = document.getElementById("gameErrorState");
    if (errorState) errorState.style.display = "none";
}

function showResultsView() {
    if (gameDetailView) gameDetailView.classList.add("is-hidden");
    if (searchResultsView) searchResultsView.classList.remove("is-hidden");
    const errorState = document.getElementById("gameErrorState");
    if (errorState) errorState.style.display = "none";
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
        });
    } catch (error) {
        console.error("Error loading search results:", error);
        showGameError("Something went wrong loading search results. Please try again.");
    }
}

async function loadGame() {
    if (appIdParam) {
        await loadGameById(appIdParam, packageIdParam);
    } else if (gameName) {
        await loadGameByQuery(gameName);
    }
}

loadGame();

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

function renderMedia(game) {
    const featuredImg = document.getElementById("featuredImg");
    const featuredVideo = document.getElementById("featuredVideo");
    const thumbStrip = document.getElementById("thumbStrip");
    const wrap = document.querySelector(".featured-wrap");
    const panelTitle = document.getElementById("mediaPanelTitle");

    const movie = (game.movies || [])[0];
    const hasTrailer = !!(movie && movie.video_url);
    const shots = game.screenshots || [];

    const mediaItems = [];
    if (hasTrailer) {
        mediaItems.push({
            type: "video",
            video_url: movie.video_url,
            // Falls back to the first screenshot as a poster frame if
            // Steam didn't supply its own trailer thumbnail -- better
            // than a blank black box before the person hits play.
            thumbnail: movie.thumbnail || shots[0] || "",
        });
    }
    shots.forEach(url => mediaItems.push({ type: "image", url }));

    if (mediaItems.length === 0) {
        if (wrap) wrap.style.display = "none";
        return;
    }
    if (wrap) wrap.style.display = "";
    if (panelTitle) panelTitle.textContent = hasTrailer ? "Media" : "Screenshots";

    function showFeaturedMedia(item) {
        if (item.type === "video") {
            featuredVideo.innerHTML = `<source src="${item.video_url}" type="video/mp4">`;
            featuredVideo.poster = item.thumbnail || "";
            featuredVideo.style.display = "";
            featuredImg.style.display = "none";
        } else {
            featuredVideo.pause();
            featuredVideo.removeAttribute("src");
            featuredVideo.innerHTML = "";
            featuredVideo.style.display = "none";
            featuredImg.style.display = "";
            featuredImg.src = item.url;
        }
    }

    showFeaturedMedia(mediaItems[0]);

    thumbStrip.innerHTML = mediaItems.map((item, i) => `
        <button class="thumb ${item.type === "video" ? "thumb--video" : ""} ${i === 0 ? "is-active" : ""}"
                data-index="${i}" aria-label="${item.type === "video" ? "Trailer" : `Screenshot ${i + 1}`}">
            <img src="${item.type === "video" ? item.thumbnail : item.url}" alt="">
            ${item.type === "video" ? '<span class="thumb-play"><i class="fa-solid fa-play"></i></span>' : ""}
        </button>
    `).join("");

    thumbStrip.addEventListener("click", (e) => {
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

        thumbStrip.querySelectorAll(".thumb").forEach(t => t.classList.remove("is-active"));
        btn.classList.add("is-active");
    });

    document.getElementById("stripPrev").addEventListener("click", () => thumbStrip.scrollBy({ left: -320, behavior: "smooth" }));
    document.getElementById("stripNext").addEventListener("click", () => thumbStrip.scrollBy({ left: 320, behavior: "smooth" }));

    const watchBtn = document.getElementById("watchTrailerBtn");
    if (watchBtn) {
        watchBtn.style.display = hasTrailer ? "" : "none";
        watchBtn.addEventListener("click", () => {
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
   renderMedia() only ever replaces #thumbStrip's innerHTML; #featuredImg
   and the expand button are the same DOM nodes for the lifetime of the
   page, so binding here can't produce duplicate listeners on repeated
   renders, and doesn't need to be re-run when renderMedia() runs again.
   Only the featured *image* opens the lightbox -- the featured trailer
   video already has native fullscreen via its own controls. */
function initScreenshotLightbox() {
    const featuredImg = document.getElementById("featuredImg");
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

    featuredImg.addEventListener("click", openLightbox);
    if (expandBtn) expandBtn.addEventListener("click", openLightbox);
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
     - spotlight_reviews       -> positive/negative each independently
                                   null if that game has no reviews in
                                   that direction
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
    const hasPositiveReview = !!(game.spotlight_reviews && game.spotlight_reviews.positive);
    const hasNegativeReview = !!(game.spotlight_reviews && game.spotlight_reviews.negative);

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
        <div class="nimlyx-quote nimlyx-quote--${kind}">
            <div class="nimlyx-quote__label">
                <i class="fa-solid ${isPositive ? "fa-thumbs-up" : "fa-thumbs-down"}"></i>
                Most Helpful ${isPositive ? "Positive" : "Negative"} Review
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

function renderNimlyxReviews(game) {
    const reviewsEl = document.getElementById("nimlyxReviews");
    const dividerEl = document.getElementById("nimlyxReviewsDivider");
    const spotlight = game.spotlight_reviews;

    const positiveHtml = spotlight ? renderNimlyxQuote(spotlight.positive, "positive", game.steam_reviews_url) : "";
    const negativeHtml = spotlight ? renderNimlyxQuote(spotlight.negative, "negative", game.steam_reviews_url) : "";

    if (!positiveHtml && !negativeHtml) {
        reviewsEl.classList.add("is-hidden");
        dividerEl.classList.add("is-hidden");
        return;
    }

    reviewsEl.innerHTML = positiveHtml + negativeHtml;
    reviewsEl.classList.remove("is-hidden");
    dividerEl.classList.remove("is-hidden");
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
            <span class="info-row__value">${game.discount > 0 ? `<span class="is-good">-${game.discount}%</span> ${game.price}` : game.price}</span>
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