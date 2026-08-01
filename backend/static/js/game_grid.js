/* ==========================================================
   GAMEGRID — shared results-grid component (Sprint 3)

   Deliberately named GameGrid, not SearchResults: Search and
   Discover both funnel into this same card renderer, and future
   "recommended for you" style surfaces can reuse it too. One card
   system, one destination (a game's canonical /search?app_id=<id>
   page) -- see routes/game.py's /api/search-results and
   /api/discover for the two producers of this card shape today.

   Card shape (matches Sprint 3 spec):
     { app_id, name, header_image, price, discount,
       review_percentage, review_count, genres }

   Usage:
     renderGameGrid(containerEl, cards);
========================================================== */

function gameGridCardHtml(game) {
    const hasDiscount = game.discount && game.discount > 0;
    const hasReview = game.review_percentage !== null && game.review_percentage !== undefined;
    const genres = (game.genres || []).slice(0, 3);

    return `
        <button class="game-grid-card" data-app-id="${game.app_id}" type="button">
            <div class="game-grid-card__image-wrap">
                <img class="game-grid-card__image" src="${game.header_image || ""}" alt="${escapeGridHtml(game.name)}" loading="lazy">
                ${hasDiscount ? `<span class="game-grid-card__discount">-${game.discount}%</span>` : ""}
            </div>
            <div class="game-grid-card__body">
                <div class="game-grid-card__name">${escapeGridHtml(game.name)}</div>
                ${genres.length ? `
                    <div class="game-grid-card__genres">
                        ${genres.map(g => `<span class="game-grid-card__genre-pill">${escapeGridHtml(g)}</span>`).join("")}
                    </div>` : ""}
                <div class="game-grid-card__footer">
                    ${hasReview ? `
                        <span class="game-grid-card__review">
                            ${game.review_percentage}% Positive
                            ${game.review_count ? `<span class="game-grid-card__review-count">(${game.review_count.toLocaleString()})</span>` : ""}
                        </span>` : "<span></span>"}
                    <span class="game-grid-card__price">${game.price || ""}</span>
                </div>
            </div>
        </button>
    `;
}

function escapeGridHtml(str) {
    const div = document.createElement("div");
    div.textContent = str ?? "";
    return div.innerHTML;
}

/**
 * Renders a list of GameGrid cards into containerEl and wires up
 * click-through navigation. Click behavior is always the same,
 * regardless of caller (Search vs Discover): navigate to the
 * canonical app_id-based game page.
 */
function renderGameGrid(containerEl, games) {
    if (!containerEl) return;

    if (!games || games.length === 0) {
        containerEl.innerHTML = `<div class="game-grid-empty">No games found.</div>`;
        return;
    }

    containerEl.innerHTML = games.map(gameGridCardHtml).join("");

    containerEl.querySelectorAll(".game-grid-card").forEach(card => {
        card.addEventListener("click", () => {
            const appId = card.dataset.appId;
            if (appId) goToGamePage(appId);
        });
    });
}

/** Canonical navigation target for any card, anywhere GameGrid is used. */
function goToGamePage(appId) {
    window.location.href = `/search?app_id=${encodeURIComponent(appId)}`;
}
