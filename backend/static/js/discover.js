/* ==========================================================
   NIMLYX — DISCOVER FILTERS
   Version 1 rework: every filter is independent (you can apply
   just one, or five, in any order), results update live as you
   change anything (debounced, not on a button click), and the
   current filter state is mirrored into the browser's own URL so a
   filtered view is bookmarkable/shareable and restores itself on
   reload. None of this needed backend changes — /api/discover
   already treats genre/playWith/budget/platform as fully optional
   (see routes/discover.py + steam.fetch_discover_games); the old
   "answer all 5 questions before Find Games unlocks" gate was a
   frontend-only restriction that contradicted that.
========================================================== */

(function () {

    /* ------------------------------------------------------------
       CONFIG — maps each question section to a state key and the
       label shown in its preference chip.
    ------------------------------------------------------------ */
    const QUESTIONS = [
        { id: "question-1", key: "genre", label: "Genre" },
        { id: "question-2", key: "playWith", label: "Playing With" },
        { id: "question-3", key: "budget", label: "Budget" },
        { id: "question-4", key: "reviewScore", label: "Review Score" },
        { id: "question-5", key: "platform", label: "Platform" }
    ];

    const LIVE_UPDATE_DEBOUNCE_MS = 350;

    const state = {};
    let isFetching = false;
    let liveUpdateTimer = null;

    // Discards stale fetches that resolve out of order (e.g. the user
    // flips two filters in quick succession) — every fetch captures
    // its own token and checks it's still current before touching the DOM.
    let requestToken = 0;

    /* Pagination — offset-based infinite scroll. currentSearchParams
       holds the filters as sent on the last live-search fetch;
       loadMoreGames() reuses it with a bumped offset so scrolling
       further never re-runs the filter logic, just asks for the next
       page of the same query. */
    let currentSearchParams = null;
    let currentOffset = 0;
    let hasMoreResults = false;
    let isLoadingMore = false;
    let loadMoreObserver = null;

    let wizardEl, chipsContainer, clearFiltersBtn, resultsGrid, resultsSubtitle;
    let resultsSection, resultsCount, resultsLoaderEl;

    /* ------------------------------------------------------------
       INIT
    ------------------------------------------------------------ */
    function init() {
        wizardEl = document.getElementById("discoverWizard");
        chipsContainer = document.getElementById("selectedPreferencesChips");
        clearFiltersBtn = document.getElementById("findGamesBtn");
        resultsGrid = document.getElementById("discoverResultsGrid");
        resultsSubtitle = document.querySelector(".discover-results-subtitle");
        resultsSection = document.getElementById("discoverResults");
        resultsCount = document.getElementById("discoverResultsCount");
        resultsLoaderEl = document.querySelector(".discover-results-loader");

        if (!wizardEl) return;

        QUESTIONS.forEach((question) => {
            const questionEl = document.getElementById(question.id);
            if (!questionEl) return;

            const options = questionEl.querySelectorAll(".wizard-option");
            options.forEach((option) => {
                option.addEventListener("click", () => selectOption(question, questionEl, option));
            });
        });

        if (clearFiltersBtn) {
            clearFiltersBtn.addEventListener("click", clearAllFilters);
        }

        restoreStateFromUrl();
        renderChips();
        updateClearButtonState();

        // Live from the moment the page loads — even with zero filters
        // selected, /api/discover happily returns an unfiltered browse
        // of everything, so there's no reason to make someone pick a
        // genre before they see anything.
        runLiveSearch();
    }

    /* ------------------------------------------------------------
       URL <-> STATE
       Reads ?genre=...&budget=... etc. on load so a shared/bookmarked
       link restores the exact same filters, and writes the current
       state back into the address bar (without adding a history
       entry per keystroke/click) every time it changes.
    ------------------------------------------------------------ */
    function restoreStateFromUrl() {
        const params = new URLSearchParams(window.location.search);

        QUESTIONS.forEach((question) => {
            const value = params.get(question.key);
            if (!value) return;

            const questionEl = document.getElementById(question.id);
            if (!questionEl) return;

            const option = questionEl.querySelector(`.wizard-option[data-value="${cssEscape(value)}"]`);
            if (!option) return; // unrecognized value in a hand-edited/stale URL — ignore rather than guess

            const titleEl = option.querySelector(".wizard-option-title");
            state[question.key] = {
                value,
                label: titleEl ? titleEl.textContent.trim() : value,
                questionKey: question.key,
                questionLabel: question.label
            };
            option.classList.add("is-selected");
        });
    }

    function syncStateToUrl() {
        const params = new URLSearchParams();
        QUESTIONS.forEach((question) => {
            const answer = state[question.key];
            if (answer) params.set(question.key, answer.value);
        });

        const query = params.toString();
        const newUrl = query ? `${window.location.pathname}?${query}` : window.location.pathname;
        window.history.replaceState(null, "", newUrl);
    }

    // Minimal CSS.escape fallback — data-value strings here are all
    // simple slugs (letters/digits/hyphens) generated by us, but this
    // guards against a stale/hand-edited URL containing something
    // that would otherwise break the attribute selector.
    function cssEscape(value) {
        return String(value).replace(/["\\\]]/g, "\\$&");
    }

    /* ------------------------------------------------------------
       OPTION SELECTION — every question is independent: picking one
       has no effect on any other question, and any subset (including
       none) is a valid filter state.
    ------------------------------------------------------------ */
    function selectOption(question, questionEl, option) {
        const options = questionEl.querySelectorAll(".wizard-option");
        const alreadySelected = option.classList.contains("is-selected");

        options.forEach((btn) => btn.classList.remove("is-selected"));

        if (alreadySelected) {
            // Clicking the currently-selected option again clears that
            // question entirely — filters should be as easy to remove
            // as they are to apply, not just via the sidebar chip.
            delete state[question.key];
        } else {
            option.classList.add("is-selected");
            const titleEl = option.querySelector(".wizard-option-title");
            state[question.key] = {
                value: option.dataset.value,
                label: titleEl ? titleEl.textContent.trim() : option.dataset.value,
                questionKey: question.key,
                questionLabel: question.label
            };
        }

        renderChips();
        updateClearButtonState();
        scheduleLiveUpdate();
    }

    /* ------------------------------------------------------------
       SELECTED PREFERENCES — CHIPS
    ------------------------------------------------------------ */
    function renderChips() {
        if (!chipsContainer) return;
        chipsContainer.innerHTML = "";

        const answered = QUESTIONS.filter((question) => state[question.key]);

        if (answered.length === 0) {
            const empty = document.createElement("p");
            empty.className = "discover-sidebar-empty";
            empty.id = "sidebarEmptyState";
            empty.textContent = "No preferences selected yet — pick any filter on the right, in any order.";
            chipsContainer.appendChild(empty);
            return;
        }

        answered.forEach((question) => {
            const answer = state[question.key];

            const chip = document.createElement("span");
            chip.className = "preference-chip";
            chip.dataset.questionKey = question.key;

            const text = document.createElement("span");
            text.className = "preference-chip-text";
            text.textContent = `${answer.questionLabel}: ${answer.label}`;

            const removeBtn = document.createElement("button");
            removeBtn.type = "button";
            removeBtn.className = "preference-chip-remove";
            removeBtn.setAttribute("aria-label", `Remove ${answer.questionLabel} preference`);
            removeBtn.innerHTML = "&times;";
            removeBtn.addEventListener("click", () => removeAnswer(question.key));

            chip.appendChild(text);
            chip.appendChild(removeBtn);
            chipsContainer.appendChild(chip);
        });
    }

    function removeAnswer(key) {
        delete state[key];

        const question = QUESTIONS.find((q) => q.key === key);
        if (question) {
            const questionEl = document.getElementById(question.id);
            if (questionEl) {
                questionEl.querySelectorAll(".wizard-option").forEach((btn) => {
                    btn.classList.remove("is-selected");
                });
            }
        }

        renderChips();
        updateClearButtonState();
        scheduleLiveUpdate();
    }

    function clearAllFilters() {
        QUESTIONS.forEach((question) => {
            delete state[question.key];
            const questionEl = document.getElementById(question.id);
            if (questionEl) {
                questionEl.querySelectorAll(".wizard-option").forEach((btn) => {
                    btn.classList.remove("is-selected");
                });
            }
        });

        renderChips();
        updateClearButtonState();
        scheduleLiveUpdate();
    }

    /* ------------------------------------------------------------
       CLEAR-ALL BUTTON STATE
       Purely a convenience action now (bulk-remove every chip at
       once) — it never gates whether filtering/results work, unlike
       the old "disabled until all 5 answered" Find Games button.
    ------------------------------------------------------------ */
    function updateClearButtonState() {
        if (!clearFiltersBtn) return;
        const anyAnswered = QUESTIONS.some((question) => Boolean(state[question.key]));
        clearFiltersBtn.disabled = !anyAnswered;
        clearFiltersBtn.textContent = "✨ Clear All Filters";
    }

    /* ------------------------------------------------------------
       LIVE FILTERING
       Debounced so rapidly clicking through several filters doesn't
       fire a request per click — only once things settle for
       LIVE_UPDATE_DEBOUNCE_MS.
    ------------------------------------------------------------ */
    function scheduleLiveUpdate() {
        if (liveUpdateTimer) clearTimeout(liveUpdateTimer);
        liveUpdateTimer = setTimeout(runLiveSearch, LIVE_UPDATE_DEBOUNCE_MS);
    }

    async function runLiveSearch() {
        const token = ++requestToken;
        isFetching = true;

        teardownInfiniteScroll();
        currentOffset = 0;
        hasMoreResults = false;

        if (resultsSection) resultsSection.classList.add("is-loading");
        if (resultsSubtitle) resultsSubtitle.textContent = "Applying filters…";

        syncStateToUrl();

        const params = new URLSearchParams();
        QUESTIONS.forEach((question) => {
            const answer = state[question.key];
            if (answer) params.set(question.key, answer.value);
        });
        currentSearchParams = params;

        try {
            const response = await fetch(`/api/discover?${params.toString()}`);
            const data = await response.json();
            if (token !== requestToken) return; // a newer filter change superseded this one

            const games = Array.isArray(data.games) ? data.games : [];

            renderResults(games);

            currentOffset = typeof data.next_offset === "number" ? data.next_offset : games.length;
            hasMoreResults = Boolean(data.has_more);

            if (resultsCount && typeof data.total_matches === "number") {
                resultsCount.textContent = `${data.total_matches} game${data.total_matches === 1 ? "" : "s"} matched.`;
            }

            if (hasMoreResults) {
                setupInfiniteScroll();
            }
        } catch (error) {
            if (token !== requestToken) return;
            console.error("Error fetching discover results:", error);
            renderResults([]);
            if (resultsSubtitle) {
                resultsSubtitle.textContent = "Something went wrong while finding games. Please try again.";
            }
        } finally {
            if (token === requestToken) {
                isFetching = false;
                if (resultsSection) resultsSection.classList.remove("is-loading");
            }
        }
    }

    /* ------------------------------------------------------------
       LOAD MORE — infinite scroll
       Triggered by an IntersectionObserver watching the loader
       element already sitting in the markup right after the grid
       (see .discover-results-loader in discover.html/discover.css).
       Reuses currentSearchParams so it never re-runs the filter
       logic; only the offset changes between pages.
    ------------------------------------------------------------ */
    async function loadMoreGames() {
        if (isLoadingMore || !hasMoreResults || !currentSearchParams) return;

        isLoadingMore = true;
        if (resultsSection) resultsSection.classList.add("is-loading");

        const params = new URLSearchParams(currentSearchParams);
        params.set("offset", String(currentOffset));

        try {
            const response = await fetch(`/api/discover?${params.toString()}`);
            const data = await response.json();
            const games = Array.isArray(data.games) ? data.games : [];

            games.forEach((game) => {
                resultsGrid.appendChild(createGameCard(game));
            });

            currentOffset = typeof data.next_offset === "number" ? data.next_offset : currentOffset + games.length;
            hasMoreResults = Boolean(data.has_more);

            if (!hasMoreResults) {
                teardownInfiniteScroll();
                if (resultsSubtitle) {
                    resultsSubtitle.textContent = "You've reached the end of your matches.";
                }
            }
        } catch (error) {
            console.error("Error loading more games:", error);
            // Leave hasMoreResults untouched — the observer stays attached
            // so scrolling can simply retry rather than getting stuck.
        } finally {
            isLoadingMore = false;
            if (resultsSection) resultsSection.classList.remove("is-loading");
        }
    }

    function setupInfiniteScroll() {
        teardownInfiniteScroll();
        if (!resultsLoaderEl || !("IntersectionObserver" in window)) return;

        loadMoreObserver = new IntersectionObserver((entries) => {
            entries.forEach((entry) => {
                if (entry.isIntersecting) loadMoreGames();
            });
        }, { root: null, rootMargin: "400px 0px", threshold: 0 });

        loadMoreObserver.observe(resultsLoaderEl);
    }

    function teardownInfiniteScroll() {
        if (loadMoreObserver) {
            loadMoreObserver.disconnect();
            loadMoreObserver = null;
        }
    }

    const FALLBACK_IMAGE = "/static/images/game-placeholder.png";

    function createGameCard(game) {
    const card = document.createElement("a");
    card.className = "home-card";
    card.href = game.analyze_url || "#";

    // header_image is guaranteed by the backend (Steam's own scraped
    // thumbnail or the CDN-convention header.jpg — never a guessed
    // URL that might 404). It renders immediately. Anything sharper
    // (game.image_candidates) is only ever swapped in client-side,
    // after a real successful Image() load — see image-upgrade.js.
    card.innerHTML = `
        <div class="home-card-media">
            <img src="${game.header_image || FALLBACK_IMAGE}" alt="${game.name || ""}" loading="lazy">
        </div>
        <div class="home-card-body">
            <h3 class="home-card-title">${game.name || ""}</h3>
            <div class="home-card-divider"></div>
            <div class="home-card-footer">
                <span class="home-card-footer-left">${game.footer_left || ""}</span>
                <span class="home-card-footer-right">${game.footer_right || ""}</span>
            </div>
        </div>
    `;

    const img = card.querySelector(".home-card-media img");

    // Last-resort safety net only — the guaranteed header_image
    // should always load. If it somehow doesn't (network hiccup,
    // ad-blocker, etc.), fall back once to the static placeholder
    // rather than showing a broken image icon.
    img.addEventListener("error", () => {
        if (img.src !== FALLBACK_IMAGE) img.src = FALLBACK_IMAGE;
    }, { once: true });

    if (window.NimlyxImageUpgrade && Array.isArray(game.image_candidates) && game.image_candidates.length) {
        window.NimlyxImageUpgrade.upgradeImg(img, game.image_candidates);
    }

    return card;
}

    function renderEmptyState() {
        resultsGrid.innerHTML = "";

        const emptyState = document.createElement("div");
        emptyState.className = "discover-results-empty";
        emptyState.innerHTML = `
            <span class="discover-results-empty-icon" aria-hidden="true">🎮</span>
            <p class="discover-results-empty-title">No games matched your preferences.</p>
            <p class="discover-results-empty-text">Try removing a filter — every filter here is optional.</p>
        `;
        resultsGrid.appendChild(emptyState);
    }

    function renderResults(games) {
        if (!resultsGrid) return;
        resultsGrid.innerHTML = "";

        const anyFilters = QUESTIONS.some((question) => Boolean(state[question.key]));

        if (games.length === 0) {
            if (resultsSubtitle) {
                resultsSubtitle.textContent = "No games matched yet. Try adjusting or removing a filter.";
            }
            renderEmptyState();
            return;
        }

        if (resultsSubtitle) {
            resultsSubtitle.textContent = anyFilters
                ? "Based on what you picked, here's what fits."
                : "Showing everything — add a filter to narrow these down.";
        }

        games.forEach((game) => {
            resultsGrid.appendChild(createGameCard(game));
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }

})();