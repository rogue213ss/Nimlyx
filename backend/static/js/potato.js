/* ==========================================================
   NIMLYX — POTATO ECOSYSTEM "VIEW MORE" PAGE

   One "Load More" button per tier (Friendly/Tweaks/Extreme), each
   independently paginating against /api/potato/<tier>?offset=N. The
   first page of each tier is already server-rendered into the grid
   by potato.html/routes/potato.py -- this script only appends
   subsequent pages, using each grid's own data-offset attribute to
   track where the next request should start (kept in the DOM rather
   than a JS-only variable so it survives independently per tier
   without needing a shared state object).

   Load More visibility: potato.html only renders a tier's
   .potato-load-more-wrap block at all if that tier started with more
   games than fit on the first page (has_more), so a tier with
   everything already shown has zero extra markup/empty space from
   the start. Once the LAST page loads here, the whole wrapper (not
   just the button) is hidden -- hiding only the button left an empty
   24px-margin gap where the button used to be.

   Renders the same card markup routes/pages.py's home() /
   templates/index.html use for these three tiers (portrait card /
   list row / extreme card), PLUS an extra real-world-evidence line
   (FPS/resolution/settings, and for Extreme, the specific tweak that
   made it playable) that only the verified Potato database provides
   -- see services/hardware/verified_potato_pool.py's
   format_evidence_for_card(). The homepage's own rows don't render
   this field even though it's present in the same card payload; this
   page is where it's surfaced.
========================================================== */

(function () {

    function escapeHtml(value) {
        const div = document.createElement("div");
        div.textContent = value == null ? "" : String(value);
        return div.innerHTML;
    }

    // Carries a card's Potato tier/badge/evidence over to the game
    // detail page as URL params, exactly matching potato.html's
    // Jinja-side query-string building (see routes/potato.py's
    // server-rendered first page) -- Load More pages built here need
    // to produce the identical link shape, or only games on page 1
    // would show their Potato verdict on the game page. Read by
    // search.js's readPotatoParamsFromUrl().
    function withPotatoParams(baseUrl, tier, badge, evidence) {
        const sep = baseUrl.indexOf("?") === -1 ? "?" : "&";
        let qs = "potato_tier=" + encodeURIComponent(tier) + "&potato_badge=" + encodeURIComponent(badge || "Pending Check");
        if (evidence && evidence.summary) qs += "&potato_summary=" + encodeURIComponent(evidence.summary);
        if (evidence && evidence.notes) qs += "&potato_notes=" + encodeURIComponent(evidence.notes);
        if (evidence && evidence.tweak) qs += "&potato_tweak=" + encodeURIComponent(evidence.tweak);
        return baseUrl + sep + qs;
    }

    function cardMarkup(tier, game) {
        const imgCandidates = escapeHtml(JSON.stringify(game.image_candidates || []));
        const badge = escapeHtml(game.hardware_badge || "Pending Check");
        const image = escapeHtml(game.header_image || "");
        const name = escapeHtml(game.name || "");
        const evidence = game.evidence || null;
        const url = escapeHtml(withPotatoParams(game.analyze_url || "#", tier, game.hardware_badge, evidence));
        const evidenceSummary = evidence && evidence.summary ? escapeHtml(evidence.summary) : "";
        const evidenceNotes = evidence && evidence.notes ? escapeHtml(evidence.notes) : "";
        const evidenceTweak = evidence && evidence.tweak ? escapeHtml(evidence.tweak) : "";

        if (tier === "friendly") {
            return (
                '<a class="nimlyx-card nimlyx-card--portrait nimlyx-card--potato-friendly" href="' + url + '">' +
                '<div class="nimlyx-card-media"><img src="' + image + '" data-img-candidates=\'' + imgCandidates + '\' loading="lazy" alt="" onerror="NimlyxImgFallback(this)"></div>' +
                '<div class="nimlyx-card-body">' +
                '<h3 class="nimlyx-card-title">' + name + '</h3>' +
                '<div class="hw-badge hw-badge--potato-friendly">' + badge + '</div>' +
                (evidenceSummary ? '<div class="potato-evidence-line" title="' + evidenceNotes + '">' + evidenceSummary + '</div>' : '') +
                '</div></a>'
            );
        }

        if (tier === "tweaks") {
            return (
                '<a class="potato-list-row" href="' + url + '">' +
                '<span class="potato-list-thumb"><img src="' + image + '" data-img-candidates=\'' + imgCandidates + '\' loading="lazy" alt="" onerror="NimlyxImgFallback(this)"></span>' +
                '<span class="potato-list-text">' +
                '<span class="potato-list-name">' + name + '</span>' +
                (evidenceSummary ? '<span class="potato-list-evidence" title="' + evidenceNotes + '">' + evidenceSummary + '</span>' : '') +
                '</span>' +
                '<span class="hw-badge hw-badge--potato-tweaks">' + badge + '</span>' +
                '<span class="potato-list-arrow" aria-hidden="true">→</span>' +
                '</a>'
            );
        }

        // extreme
        return (
            '<a class="potato-extreme-card" href="' + url + '">' +
            '<div class="potato-extreme-media">' +
            '<img src="' + image + '" data-img-candidates=\'' + imgCandidates + '\' loading="lazy" alt="" onerror="NimlyxImgFallback(this)">' +
            '<span class="potato-extreme-ribbon">Challenge</span>' +
            '</div>' +
            '<div class="potato-extreme-body"' + (evidenceNotes ? ' title="' + evidenceNotes + '"' : '') + '>' +
            '<h4 class="nimlyx-card-title">' + name + '</h4>' +
            '<div class="hw-badge hw-badge--potato-extreme">' + badge + '</div>' +
            (evidenceSummary ? '<div class="potato-extreme-evidence">' + evidenceSummary + '</div>' : '') +
            (evidenceTweak ? '<div class="potato-extreme-tweak">🔧 ' + evidenceTweak + '</div>' : '') +
            '</div></a>'
        );
    }

    function loadMore(button) {
        const tier = button.getAttribute("data-tier");
        const grid = document.getElementById("potatoGrid-" + tier);
        if (!grid || button.classList.contains("is-loading")) return;

        const offset = parseInt(grid.getAttribute("data-offset"), 10) || 0;
        button.classList.add("is-loading");
        button.textContent = "Loading…";

        fetch("/api/potato/" + encodeURIComponent(tier) + "?offset=" + offset)
            .then(function (response) { return response.json(); })
            .then(function (data) {
                const games = data.games || [];
                const html = games.map(function (game) { return cardMarkup(tier, game); }).join("");
                grid.insertAdjacentHTML("beforeend", html);

                if (typeof data.next_offset === "number") {
                    grid.setAttribute("data-offset", String(data.next_offset));
                }

                if (!data.has_more) {
                    const wrap = button.closest(".potato-load-more-wrap");
                    if (wrap) {
                        wrap.hidden = true;
                    } else {
                        button.hidden = true;
                    }
                } else {
                    button.hidden = false;
                    button.textContent = "Load More";
                }
                button.classList.remove("is-loading");
            })
            .catch(function () {
                // Never leave the button stuck saying "Loading…" -- a
                // failed request here is a normal, retryable thing
                // (matches the rest of Nimlyx's "never let one Steam
                // hiccup break the page" approach), not a reason to
                // hide the button or show an error state.
                button.classList.remove("is-loading");
                button.textContent = "Load More";
            });
    }

    document.addEventListener("DOMContentLoaded", function () {
        document.querySelectorAll(".potato-load-more-btn").forEach(function (button) {
            button.addEventListener("click", function () { loadMore(button); });
        });
    });

})();
