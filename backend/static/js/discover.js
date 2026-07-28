/* ==========================================================
   NIMLYX — DISCOVER FILTERS

   Version 1 base: every filter is independent (apply just one, or
   five, in any order), results update live as you change anything
   (debounced), and the current filter state is mirrored into the
   browser's own URL so a filtered view is bookmarkable/shareable.

   Progressive Filter Workspace (this revision): once you pick your
   first filter, the full filter panel smoothly collapses into a
   compact list in the sidebar instead of just sitting there taking
   up scroll space — every filter stays editable from that compact
   view (via "+ Add Filter", which reuses the exact same underlying
   options rather than duplicating them) so you never have to scroll
   back up unless you want to. Selecting a filter also scrolls the
   page down to the results so the effect is immediately visible.
========================================================== */

(function () {

    /* ------------------------------------------------------------
       CONFIG
    ------------------------------------------------------------ */
    const QUESTIONS = [
        { id: "question-1", key: "genre", label: "Genre" },
        { id: "question-2", key: "playWith", label: "Playing With" },
        { id: "question-3", key: "budget", label: "Budget" },
        { id: "question-4", key: "reviewScore", label: "Review Score" },
        { id: "question-5", key: "platform", label: "Platform" }
    ];

    const LIVE_UPDATE_DEBOUNCE_MS = 350;
    const WIZARD_TRANSITION_MS = 450; // must match discover.css's .discover-wizard transition duration

    const state = {};
    let isFetching = false;
    let liveUpdateTimer = null;
    let isCompactMode = false;
    let wizardHideTimer = null;

    // Set right before a fetch that resulted from adding a NEW filter
    // (not removing one) — checked once that fetch's results are
    // actually rendered, so the auto-scroll lands on a settled page
    // rather than one still reflowing from the wizard's collapse
    // animation or the results still being skeletons.
    let shouldScrollToResultsNext = false;

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
    let resultsSection, resultsCount, resultsLoaderEl, sidebarPanelEl;
    let addFilterBtn, addFilterPanel, addFilterPanelInner;

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
        sidebarPanelEl = document.querySelector(".discover-sidebar-panel");
        addFilterBtn = document.getElementById("filterAddBtn");
        addFilterPanel = document.getElementById("filterAddPanel");
        addFilterPanelInner = document.getElementById("filterAddPanelInner");

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

        if (addFilterBtn) {
            addFilterBtn.addEventListener("click", toggleAddFilterPanel);
        }

        // Closing the Add Filter panel when clicking anywhere outside
        // it is standard popover-adjacent behavior — otherwise it'd
        // only ever close by re-clicking the same button.
        document.addEventListener("click", (event) => {
            if (!addFilterPanel || !addFilterPanel.classList.contains("is-open")) return;
            const wrap = event.target.closest(".filter-add-wrap");
            if (!wrap) closeAddFilterPanel();
        });

        restoreStateFromUrl();

        // Skip the collapse/expand ANIMATION on first load — if a
        // shared/bookmarked URL already has filters in it, the page
        // should just start in compact mode instantly, not visibly
        // play the "shrinking" transition the instant it loads.
        syncUIAfterStateChange({ instant: true });

        // Live from the moment the page loads — even with zero filters
        // selected, /api/discover happily returns an unfiltered browse
        // of everything, so there's no reason to make someone pick a
        // genre before they see anything.
        runLiveSearch();
    }

    /* ------------------------------------------------------------
       URL <-> STATE
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
            // Only ADDING a filter triggers the auto-scroll-to-results —
            // removing one (the `alreadySelected` branch above) doesn't,
            // since yanking the page down right after someone clears a
            // filter isn't what they asked for.
            shouldScrollToResultsNext = true;
        }

        syncUIAfterStateChange();
        scheduleLiveUpdate();
    }

    /* ------------------------------------------------------------
       ONE PLACE THAT KEEPS EVERY PIECE OF UI IN SYNC WITH `state`
       Called after any change to `state` — selecting, removing,
       clearing, or restoring from the URL — so no code path can
       forget to update the chips, the compact-mode toggle, the
       collapsed-row badges, or the Clear button.
    ------------------------------------------------------------ */
    function syncUIAfterStateChange(opts) {
        renderChips();
        updateQuestionSummaries();
        updateClearButtonState();
        updateFilterUIMode(opts);
    }

    /* ------------------------------------------------------------
       COMPACT MODE — the whole wizard collapses once any filter is
       active, and .discover-results (its next sibling) naturally
       rises to sit beside the sidebar as a result. Expands back only
       once every filter has been cleared.
    ------------------------------------------------------------ */
    function updateFilterUIMode(opts) {
        const instant = Boolean(opts && opts.instant);
        const anyAnswered = QUESTIONS.some((question) => Boolean(state[question.key]));

        if (anyAnswered && !isCompactMode) {
            isCompactMode = true;
            if (sidebarPanelEl) sidebarPanelEl.classList.add("is-compact");
            if (instant) {
                wizardEl.classList.add("is-collapsed");
                wizardEl.setAttribute("hidden", "");
                wizardEl.setAttribute("aria-hidden", "true");
            } else {
                collapseWizard();
            }
        } else if (!anyAnswered && isCompactMode) {
            isCompactMode = false;
            if (sidebarPanelEl) sidebarPanelEl.classList.remove("is-compact");
            closeAddFilterPanel();
            if (instant) {
                wizardEl.removeAttribute("hidden");
                wizardEl.removeAttribute("aria-hidden");
                wizardEl.classList.remove("is-collapsed");
            } else {
                expandWizard();
            }
        }
    }

    function collapseWizard() {
        if (!wizardEl || wizardEl.hasAttribute("hidden") || wizardEl.classList.contains("is-collapsed")) return;
        wizardEl.classList.add("is-collapsed");
        wizardEl.setAttribute("aria-hidden", "true");
        clearTimeout(wizardHideTimer);
        wizardHideTimer = setTimeout(() => {
            // hidden (not just visually collapsed) once the animation
            // settles, so its buttons drop out of tab order entirely —
            // pointer-events:none in CSS covers mouse/touch in the
            // meantime, this covers keyboard nav.
            if (wizardEl.classList.contains("is-collapsed")) wizardEl.setAttribute("hidden", "");
        }, WIZARD_TRANSITION_MS);
    }

    function expandWizard() {
        if (!wizardEl || !wizardEl.classList.contains("is-collapsed")) return;
        clearTimeout(wizardHideTimer);
        wizardEl.removeAttribute("hidden");
        wizardEl.removeAttribute("aria-hidden");
        // Force a reflow so the browser registers "not hidden, still
        // at max-height:0" as a real starting point before the next
        // class change — otherwise both changes can get batched into
        // one frame and the transition never plays.
        void wizardEl.offsetHeight;
        wizardEl.classList.remove("is-collapsed");
    }

    /* ------------------------------------------------------------
       SELECTED PREFERENCES — grouped by category, sidebar
    ------------------------------------------------------------ */
    function renderChips() {
        if (!chipsContainer) return;
        chipsContainer.innerHTML = "";

        const answered = QUESTIONS.filter((question) => state[question.key]);

        if (answered.length === 0) {
            const empty = document.createElement("p");
            empty.className = "discover-sidebar-empty";
            empty.id = "sidebarEmptyState";
            empty.textContent = "No preferences selected yet — pick any filter below, in any order.";
            chipsContainer.appendChild(empty);
            return;
        }

        answered.forEach((question) => {
            const answer = state[question.key];

            const group = document.createElement("div");
            group.className = "filter-compact-group";

            const label = document.createElement("span");
            label.className = "filter-compact-group-label";
            label.textContent = answer.questionLabel;

            const chipRow = document.createElement("div");
            chipRow.className = "filter-compact-chips";

            const chip = document.createElement("span");
            chip.className = "preference-chip";
            chip.dataset.questionKey = question.key;

            const text = document.createElement("span");
            text.className = "preference-chip-text";
            text.textContent = answer.label;

            const removeBtn = document.createElement("button");
            removeBtn.type = "button";
            removeBtn.className = "preference-chip-remove";
            removeBtn.setAttribute("aria-label", `Remove ${answer.questionLabel} preference`);
            removeBtn.innerHTML = "&times;";
            removeBtn.addEventListener("click", () => removeAnswer(question.key));

            chip.appendChild(text);
            chip.appendChild(removeBtn);
            chipRow.appendChild(chip);
            group.appendChild(label);
            group.appendChild(chipRow);
            chipsContainer.appendChild(group);
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

        syncUIAfterStateChange();
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

        syncUIAfterStateChange();
        scheduleLiveUpdate();
    }

    function updateClearButtonState() {
        if (!clearFiltersBtn) return;
        const anyAnswered = QUESTIONS.some((question) => Boolean(state[question.key]));
        clearFiltersBtn.disabled = !anyAnswered;
        clearFiltersBtn.textContent = "✨ Clear All Filters";
    }

    /* ------------------------------------------------------------
       COLLAPSED-ROW ANSWER BADGES (in the wizard's own accordion
       summaries — separate from the sidebar's grouped chips above,
       both are kept in sync from the same state).
    ------------------------------------------------------------ */
    function updateQuestionSummaries() {
        QUESTIONS.forEach((question) => {
            const badge = document.querySelector(`[data-question-answer="${question.id.split("-")[1]}"]`);
            if (!badge) return;
            const answer = state[question.key];
            badge.textContent = answer ? answer.label : "";
        });
    }

    /* ------------------------------------------------------------
       ADD FILTER PANEL — a second entry point into the exact same
       .wizard-option buttons already in the (possibly collapsed)
       wizard. Clicking an option here just clicks the real button,
       so there is exactly one place that owns selection logic.
    ------------------------------------------------------------ */
    function renderAddFilterPanel() {
        if (!addFilterPanelInner) return;
        addFilterPanelInner.innerHTML = "";

        const unanswered = QUESTIONS.filter((question) => !state[question.key]);

        if (unanswered.length === 0) {
            const done = document.createElement("p");
            done.className = "filter-add-popover-empty";
            done.textContent = "Every filter is already set.";
            addFilterPanelInner.appendChild(done);
            return;
        }

        unanswered.forEach((question) => {
            const questionEl = document.getElementById(question.id);
            if (!questionEl) return;

            const section = document.createElement("div");
            section.className = "filter-add-popover-group";

            const label = document.createElement("span");
            label.className = "filter-add-popover-group-label";
            label.textContent = question.label;
            section.appendChild(label);

            const optionsRow = document.createElement("div");
            optionsRow.className = "filter-add-popover-options";

            questionEl.querySelectorAll(".wizard-option").forEach((originalOption) => {
                const titleEl = originalOption.querySelector(".wizard-option-title");
                const btn = document.createElement("button");
                btn.type = "button";
                btn.className = "filter-add-popover-option";
                btn.textContent = titleEl ? titleEl.textContent.trim() : originalOption.dataset.value;
                btn.addEventListener("click", () => {
                    originalOption.click();
                    closeAddFilterPanel();
                });
                optionsRow.appendChild(btn);
            });

            section.appendChild(optionsRow);
            addFilterPanelInner.appendChild(section);
        });
    }

    function toggleAddFilterPanel() {
        if (!addFilterPanel) return;
        if (addFilterPanel.classList.contains("is-open")) {
            closeAddFilterPanel();
        } else {
            renderAddFilterPanel();
            addFilterPanel.classList.add("is-open");
            if (addFilterBtn) addFilterBtn.setAttribute("aria-expanded", "true");
        }
    }

    function closeAddFilterPanel() {
        if (!addFilterPanel) return;
        addFilterPanel.classList.remove("is-open");
        if (addFilterBtn) addFilterBtn.setAttribute("aria-expanded", "false");
    }

    /* ------------------------------------------------------------
       LIVE FILTERING
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

            // Scroll only after results are actually settled — not at
            // the moment of clicking, which would fight both the
            // wizard's collapse animation and the debounce/fetch delay.
            if (shouldScrollToResultsNext) {
                shouldScrollToResultsNext = false;
                if (resultsSection) {
                    resultsSection.scrollIntoView({ behavior: "smooth", block: "start" });
                }
            }
        } catch (error) {
            if (token !== requestToken) return;
            console.error("Error fetching discover results:", error);
            renderResults([]);
            if (resultsSubtitle) {
                resultsSubtitle.textContent = "Something went wrong while finding games. Please try again.";
            }
            shouldScrollToResultsNext = false;
        } finally {
            if (token === requestToken) {
                isFetching = false;
                if (resultsSection) resultsSection.classList.remove("is-loading");
            }
        }
    }

    /* ------------------------------------------------------------
       LOAD MORE — infinite scroll
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

    // Was a reference to /static/images/game-placeholder.png — a file
    // that was never actually created, so the "fallback" was itself
    // broken (see NIMLYX TRADITION #009 in steam.py for the matching
    // backend half of this fix). An inline SVG data URI needs no
    // separate file and can never 404: it's on-brand (matches
    // --home-bg-elevated + the muted accent tone) rather than a
    // generic broken-image icon, and renders instantly with zero
    // extra network request.
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
        // ad-blocker, etc.), fall back once to the SVG placeholder
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