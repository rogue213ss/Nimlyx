/* ==========================================================
   SEARCHLIST — query-based search results (Sprint 3 refinement)

   Distinct from GameGrid on purpose: GameGrid is Discover's card
   layout (Discover is browsing-by-filters, so a visual grid fits).
   Search is query-based -- a person typed something specific and
   wants to scan real detail fast, so this uses a row layout
   (thumbnail left, name/genres/platforms/price right) instead, plus
   a collapsible sidebar to filter results down further. Both
   components share the same click destination: /search?app_id=<id>.

   Usage:
     initSearchList({
       container: document.getElementById("searchListRows"),
       sidebar: document.getElementById("searchFilterSidebar"),
       rows: data.results,   // from /api/search-results/<query>
       hasMore: data.has_more,
       nextOffset: data.next_offset,
       fetchMore: async (offset) => { ... return {results, has_more, next_offset} ... },
     });
========================================================== */

const SearchList = (function () {

    // Navigation is now a plain <a href="/search?app_id=..."> on each
    // row (see rowHtml) -- no JS-driven navigation helper needed.

    let allRows = [];
    let containerEl = null;
    let seenAppIds = new Set();

    // Load-more state -- undefined fetchMore (old call sites that
    // don't pass it) just means the button never renders, so this is
    // backward compatible with any other future caller of initSearchList.
    let hasMoreState = false;
    let nextOffsetState = null;
    let fetchMoreFn = null;
    let loadingMore = false;

    /* ------------------------------------------------------------
       FILTER STATE
    ------------------------------------------------------------ */
    const filterState = {
        freeOnly: false,
        maxPrice: null,      // dollars, null = no cap
        genres: new Set(),   // selected genre names
        platforms: new Set(), // selected of: windows, mac, linux
    };

    function escapeListHtml(str) {
        const div = document.createElement("div");
        div.textContent = str ?? "";
        return div.innerHTML;
    }

    function rowMatchesFilters(row) {
        if (filterState.freeOnly && !row.is_free) return false;

        if (filterState.maxPrice !== null && !row.is_free) {
            const dollars = (row.price_cents || 0) / 100;
            if (dollars > filterState.maxPrice) return false;
        }

        if (filterState.genres.size > 0) {
            const rowGenres = row.genres || [];
            const hasMatch = rowGenres.some(g => filterState.genres.has(g));
            if (!hasMatch) return false;
        }

        if (filterState.platforms.size > 0) {
            const platforms = row.platforms || {};
            const hasMatch = [...filterState.platforms].some(p => platforms[p]);
            if (!hasMatch) return false;
        }

        return true;
    }

    /* ------------------------------------------------------------
       ROW RENDERING
    ------------------------------------------------------------ */
    function platformIcons(platforms) {
        if (!platforms) return "";
        const icons = [];
        if (platforms.windows) icons.push('<i class="fa-brands fa-windows" title="Windows"></i>');
        if (platforms.mac) icons.push('<i class="fa-brands fa-apple" title="macOS"></i>');
        if (platforms.linux) icons.push('<i class="fa-brands fa-linux" title="Linux"></i>');
        return icons.join("");
    }

    function rowHtml(row) {
        const hasDiscount = row.discount && row.discount > 0;
        const genres = (row.genres || []).slice(0, 4);

        // A row whose Steam result was a package ("sub" -- Complete/
        // GOTY/Deluxe Edition, etc) still links to its resolved base
        // app, but carries steam_id along as package_id so the game
        // page can show what was actually clicked -- see the
        // package-aware game page feature.
        const href = row.steam_type === "sub"
            ? `/search?app_id=${encodeURIComponent(row.app_id)}&package_id=${encodeURIComponent(row.steam_id)}`
            : `/search?app_id=${encodeURIComponent(row.app_id)}`;

        return `
            <a class="search-list-row" data-app-id="${row.app_id}" href="${href}">
                <div class="search-list-row__thumb-wrap">
                    <img class="search-list-row__thumb" src="${row.header_image || ""}" alt="${escapeListHtml(row.name)}" loading="lazy">
                </div>
                <div class="search-list-row__body">
                    <div class="search-list-row__top">
                        <span class="search-list-row__name">${escapeListHtml(row.name)}</span>
                        <span class="search-list-row__platforms">${platformIcons(row.platforms)}</span>
                    </div>
                    ${genres.length ? `
                        <div class="search-list-row__genres">
                            ${genres.map(g => `<span class="search-list-row__genre-pill">${escapeListHtml(g)}</span>`).join("")}
                        </div>` : ""}
                </div>
                <div class="search-list-row__price-col">
                    ${hasDiscount ? `<span class="search-list-row__discount">-${row.discount}%</span>` : ""}
                    <span class="search-list-row__price">${row.price || ""}</span>
                </div>
            </a>
        `;
    }

    function renderRows() {
        if (!containerEl) return;
        const filtered = allRows.filter(rowMatchesFilters);

        if (filtered.length === 0) {
            containerEl.innerHTML = `<div class="search-list-empty">No games match these filters.</div>`;
            return;
        }

        // Rows are real <a href="/search?app_id=..."> anchors now (not
        // buttons with a JS click handler), so left click, right-click
        // "Open in new tab", middle-click, and Ctrl/Cmd-click all work
        // as native browser link behavior -- nothing to wire up here.
        containerEl.innerHTML = filtered.map(rowHtml).join("");

        // "Load more" only makes sense when the visible list isn't
        // already being narrowed by a filter -- Steam has more pages
        // of the RAW search to fetch, not more matches for whatever
        // genre/price/platform filter is currently active. Filtering
        // stays entirely client-side over whatever's already been
        // fetched, same as before this feature existed.
        const noFilterActive = filtered.length === allRows.length;
        if (hasMoreState && fetchMoreFn && noFilterActive) {
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "search-list-load-more";
            btn.textContent = loadingMore ? "Loading…" : "Load more results";
            btn.disabled = loadingMore;
            btn.addEventListener("click", handleLoadMore);
            containerEl.appendChild(btn);
        }
    }

    async function handleLoadMore() {
        if (loadingMore || !fetchMoreFn || nextOffsetState == null) return;
        loadingMore = true;
        renderRows(); // swap the button to its disabled "Loading…" state

        try {
            const data = await fetchMoreFn(nextOffsetState);
            const newRows = (data.results || []).filter(row => !seenAppIds.has(row.app_id));
            newRows.forEach(row => seenAppIds.add(row.app_id));
            allRows = allRows.concat(newRows);

            hasMoreState = Boolean(data.has_more);
            nextOffsetState = data.next_offset ?? null;

            if (chipsContainerEl) buildFilterGroups(); // pick up any new genres from the appended rows
        } catch (error) {
            console.error("Error loading more search results:", error);
            hasMoreState = false; // don't leave a dead "Load more" button behind on failure
        } finally {
            loadingMore = false;
            renderRows();
        }
    }

    /* ------------------------------------------------------------
       SIDEBAR
       Deliberately reuses Discover's own sidebar markup/classes
       (.discover-sidebar-panel, .selected-preferences-chips,
       .preference-chip, .filter-compact-*, .filter-add-*) instead of
       a lookalike, so Search's filter UI is styled and behaves
       identically to Discover's -- all of it comes from discover.css,
       already loaded on this page. See search_list.css for the one
       small addition (a "Clear filters" link) Discover's sidebar has
       no equivalent of.
    ------------------------------------------------------------ */
    function collectAvailableGenres() {
        const set = new Set();
        allRows.forEach(row => (row.genres || []).forEach(g => set.add(g)));
        return [...set].sort();
    }

    const BUDGET_OPTIONS = [
        { value: "free", label: "Free" },
        { value: "under-10", label: "Under $10" },
        { value: "under-20", label: "Under $20" },
        { value: "under-40", label: "Under $40" },
        { value: "any-price", label: "Any Price" },
    ];
    const PLATFORM_OPTIONS = [
        { value: "windows", label: "Windows" },
        { value: "mac", label: "macOS" },
        { value: "linux", label: "Linux" },
    ];

    // Mirrors discover.js's QUESTIONS config. "budget" is single-select
    // (one answer, like Discover's own budget question); genre/platform
    // are multi-select, since search results usually want to narrow by
    // more than one genre or platform at once.
    let filterGroups = [];
    function buildFilterGroups() {
        filterGroups = [
            { key: "budget", label: "Budget", type: "single", options: BUDGET_OPTIONS },
            { key: "genre", label: "Genre", type: "multi", options: collectAvailableGenres().map(g => ({ value: g, label: g })) },
            { key: "platform", label: "Platform", type: "multi", options: PLATFORM_OPTIONS },
        ];
    }

    // selections.budget is a single {value,label} or null; genre/platform
    // are Map<value,label> so multiple chips can render per group.
    const selections = { budget: null, genre: new Map(), platform: new Map() };

    let chipsContainerEl, addFilterBtnEl, addFilterPanelEl, addFilterPanelInnerEl;

    function applySelectionsToFilterState() {
        filterState.freeOnly = selections.budget?.value === "free";
        const priceCap = { "under-10": 10, "under-20": 20, "under-40": 40 };
        filterState.maxPrice = selections.budget ? (priceCap[selections.budget.value] ?? null) : null;
        filterState.genres = new Set(selections.genre.keys());
        filterState.platforms = new Set(selections.platform.keys());
    }

    function groupHasSelection(group) {
        return group.type === "single" ? Boolean(selections[group.key]) : selections[group.key].size > 0;
    }

    function renderChips() {
        if (!chipsContainerEl) return;
        chipsContainerEl.innerHTML = "";

        const answeredGroups = filterGroups.filter(groupHasSelection);

        if (answeredGroups.length === 0) {
            const empty = document.createElement("p");
            empty.className = "discover-sidebar-empty";
            empty.id = "sidebarEmptyState";
            empty.textContent = "No filters selected yet — pick any filter below, in any order.";
            chipsContainerEl.appendChild(empty);
            return;
        }

        answeredGroups.forEach(group => {
            const entries = group.type === "single"
                ? [[selections[group.key].value, selections[group.key].label]]
                : [...selections[group.key].entries()];

            const groupEl = document.createElement("div");
            groupEl.className = "filter-compact-group";

            const label = document.createElement("span");
            label.className = "filter-compact-group-label";
            label.textContent = group.label;

            const chipRow = document.createElement("div");
            chipRow.className = "filter-compact-chips";

            entries.forEach(([value, text]) => {
                const chip = document.createElement("span");
                chip.className = "preference-chip";

                const textEl = document.createElement("span");
                textEl.className = "preference-chip-text";
                textEl.textContent = text;

                const removeBtn = document.createElement("button");
                removeBtn.type = "button";
                removeBtn.className = "preference-chip-remove";
                removeBtn.setAttribute("aria-label", `Remove ${text} filter`);
                removeBtn.innerHTML = "&times;";
                removeBtn.addEventListener("click", () => removeSelection(group.key, value));

                chip.appendChild(textEl);
                chip.appendChild(removeBtn);
                chipRow.appendChild(chip);
            });

            groupEl.appendChild(label);
            groupEl.appendChild(chipRow);
            chipsContainerEl.appendChild(groupEl);
        });
    }

    function removeSelection(groupKey, value) {
        if (groupKey === "budget") selections.budget = null;
        else selections[groupKey].delete(value);

        applySelectionsToFilterState();
        renderChips();
        renderRows();
        if (addFilterPanelEl && addFilterPanelEl.classList.contains("is-open")) {
            renderAddFilterPanel();
        }
    }

    function selectOption(group, option) {
        if (group.type === "single") {
            selections.budget = (selections.budget?.value === option.value) ? null : option;
        } else {
            selections[group.key].set(option.value, option.label);
        }

        applySelectionsToFilterState();
        renderChips();
        renderRows();
        closeAddFilterPanel();
    }

    function renderAddFilterPanel() {
        if (!addFilterPanelInnerEl) return;
        addFilterPanelInnerEl.innerHTML = "";

        const groupsWithRemaining = filterGroups
            .map(group => {
                if (group.type === "single") {
                    return groupHasSelection(group) ? null : group;
                }
                const remaining = group.options.filter(o => !selections[group.key].has(o.value));
                return remaining.length ? { ...group, options: remaining } : null;
            })
            .filter(Boolean);

        if (groupsWithRemaining.length === 0) {
            const done = document.createElement("p");
            done.className = "filter-add-popover-empty";
            done.textContent = "Every filter is already set.";
            addFilterPanelInnerEl.appendChild(done);
            return;
        }

        groupsWithRemaining.forEach(group => {
            const section = document.createElement("div");
            section.className = "filter-add-popover-group";

            const label = document.createElement("span");
            label.className = "filter-add-popover-group-label";
            label.textContent = group.label;
            section.appendChild(label);

            const optionsRow = document.createElement("div");
            optionsRow.className = "filter-add-popover-options";

            group.options.forEach(option => {
                const btn = document.createElement("button");
                btn.type = "button";
                btn.className = "filter-add-popover-option";
                btn.textContent = option.label;
                btn.addEventListener("click", () => selectOption(group, option));
                optionsRow.appendChild(btn);
            });

            section.appendChild(optionsRow);
            addFilterPanelInnerEl.appendChild(section);
        });
    }

    function toggleAddFilterPanel() {
        if (!addFilterPanelEl) return;
        if (addFilterPanelEl.classList.contains("is-open")) {
            closeAddFilterPanel();
        } else {
            renderAddFilterPanel();
            addFilterPanelEl.classList.add("is-open");
            if (addFilterBtnEl) addFilterBtnEl.setAttribute("aria-expanded", "true");
        }
    }

    function closeAddFilterPanel() {
        if (!addFilterPanelEl) return;
        addFilterPanelEl.classList.remove("is-open");
        if (addFilterBtnEl) addFilterBtnEl.setAttribute("aria-expanded", "false");
    }

    function clearAllSelections() {
        selections.budget = null;
        selections.genre.clear();
        selections.platform.clear();
        applySelectionsToFilterState();
        renderChips();
        renderRows();
        if (addFilterPanelEl && addFilterPanelEl.classList.contains("is-open")) {
            renderAddFilterPanel();
        }
    }

    function sidebarShellHtml() {
        return `
            <div class="discover-sidebar-panel">
                <div class="discover-sidebar-head">
                    <h2 class="discover-sidebar-title">Filters</h2>
                    <p class="discover-sidebar-hint">Pick any filter and it'll show up here — remove it any time to revisit that choice.</p>
                </div>

                <div class="selected-preferences-chips" id="searchSelectedChips"></div>

                <button type="button" class="search-filter-clear-link" id="searchFilterClearLink">Clear filters</button>

                <div class="filter-add-wrap">
                    <button type="button" class="filter-add-btn" id="searchFilterAddBtn" aria-expanded="false" aria-controls="searchFilterAddPanel">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                        Add Filter
                    </button>
                    <div class="filter-add-panel" id="searchFilterAddPanel"><div class="filter-add-panel-inner" id="searchFilterAddPanelInner"></div></div>
                </div>
            </div>
        `;
    }

    function wireSidebar(sidebarEl) {
        buildFilterGroups();
        sidebarEl.innerHTML = sidebarShellHtml();

        chipsContainerEl = document.getElementById("searchSelectedChips");
        addFilterBtnEl = document.getElementById("searchFilterAddBtn");
        addFilterPanelEl = document.getElementById("searchFilterAddPanel");
        addFilterPanelInnerEl = document.getElementById("searchFilterAddPanelInner");

        addFilterBtnEl.addEventListener("click", toggleAddFilterPanel);

        // Same outside-click-closes-popover behavior as Discover's Add
        // Filter panel.
        document.addEventListener("click", (event) => {
            if (!addFilterPanelEl.classList.contains("is-open")) return;
            const wrap = event.target.closest(".filter-add-wrap");
            if (!wrap) closeAddFilterPanel();
        });

        document.getElementById("searchFilterClearLink").addEventListener("click", clearAllSelections);

        applySelectionsToFilterState();
        renderChips();
    }

    /* ------------------------------------------------------------
       PUBLIC INIT
    ------------------------------------------------------------ */
    function init({ container, sidebar, rows, hasMore, nextOffset, fetchMore }) {
        containerEl = container;
        allRows = rows || [];
        seenAppIds = new Set(allRows.map(r => r.app_id));
        hasMoreState = Boolean(hasMore);
        nextOffsetState = nextOffset ?? null;
        fetchMoreFn = fetchMore || null;
        loadingMore = false;

        filterState.freeOnly = false;
        filterState.maxPrice = null;
        filterState.genres = new Set();
        filterState.platforms = new Set();

        if (sidebar) wireSidebar(sidebar);
        renderRows();
    }

    return { init };
})();

function initSearchList(options) {
    SearchList.init(options);
}
