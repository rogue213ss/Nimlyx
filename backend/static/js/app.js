/* ==========================================================
   HELPER — search a game (used everywhere a card is clicked)
========================================================== */

function searchGame(name) {
    window.location.href = `/search?q=${encodeURIComponent(name)}`;
}
/* ==========================================================
   GAME DETAILS CARD (full search result)
========================================================== */

function displayGame(game) {
    const gameSection = document.getElementById("gameSection");
    gameSection.innerHTML = "";

    const genreBadges = game.genres
        .map(genre => `<span class="badge">${genre}</span>`)
        .join("");

    const platformBadges = Object.keys(game.platforms)
        .filter(platform => game.platforms[platform] === true)
        .map(platform => `<span class="badge">${platform}</span>`)
        .join("");

    const card = document.createElement("div");
    card.className = "game-card";

    card.innerHTML = `
        <img src="${game.header_image}" alt="${game.name}" class="game-header-img">

        <div class="game-card-header">
            <h2>${game.name}</h2>
            <i class="fa-regular fa-copy"></i>
        </div>

        <div class="game-info-list">
            <div class="info-row">
                <span class="info-label">Price</span>
                <span class="info-value">${game.price}</span>
            </div>
            <div class="info-row">
                <span class="info-label">Reviews</span>
                <span class="info-value">${game.total_reviews.toLocaleString()}</span>
            </div>
            <div class="info-row">
                <span class="info-label">Metacritic</span>
                <span class="info-value">${game.metacritic ?? "N/A"}</span>
            </div>
            <div class="info-row">
                <span class="info-label">Platforms</span>
                <span class="info-value">${platformBadges}</span>
            </div>
            <div class="info-row">
                <span class="info-label">Genres</span>
                <span class="info-value">${genreBadges}</span>
            </div>
        </div>
    `;

    gameSection.appendChild(card);
}

/* ==========================================================
   SEARCH BUTTON
========================================================== */

document.getElementById("searchBtn").addEventListener("click", () => {
    const gameName = document.getElementById("gameInput").value.trim();
    console.log("Button clicked, value is:", gameName);
    if (!gameName) return;
    window.location.href = `/search?q=${encodeURIComponent(gameName)}`;
});
/* ==========================================================
   SEARCH SUGGESTIONS (debounced)
========================================================== */

let debounceTimer;

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

async function fetchSuggestions(query) {
    const response = await fetch(`/api/search/${query}`);
    const data = await response.json();

    const suggestionsBox = document.getElementById("suggestions");
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
            searchGame(game.name);
        });

        suggestionsBox.appendChild(item);
    });
}

/* ==========================================================
   HOMEPAGE — FEATURED GAMES
========================================================== */

async function loadFeatured() {
    try {
        const [topSellers, specials, newReleases] = await Promise.all([
            fetch("/api/browse/topsellers").then(r => r.json()),
            fetch("/api/browse/specials").then(r => r.json()),
            fetch("/api/browse/popularnew").then(r => r.json())
        ]);
 console.log("SPECIALS:", specials);
        console.log("NEW RELEASES:", newReleases);
        renderTopSellers(topSellers);
        renderSpecials(specials);
        renderNewReleases(newReleases);
    } catch (error) {
        console.error("Error loading featured games:", error);
    }
}

loadFeatured();

/* ==========================================================
   HOMEPAGE CARD BUILDER (shared by all 3 render functions)
========================================================== */

function buildHomeCard({ image, name, badgeHtml = "", priceHtml = "" }) {
    const card = document.createElement("div");
    card.className = "game-home-card";

    card.innerHTML = `
        <img src="${image}" alt="${name}">
        ${badgeHtml}
        <div class="card-content">
            <div class="card-title">${name}</div>
            ${priceHtml}
        </div>
    `;

    card.addEventListener("click", () => searchGame(name));

    return card;
}

/* ==========================================================
   TOP SELLERS
========================================================== */

function renderTopSellers(games) {
    const container = document.getElementById("topSellers");
    container.innerHTML = "";

    games.forEach(game => {
        const badgeHtml = `<div class="top-badge">🔥 Top Seller</div>`;
        const card = buildHomeCard({
            image: game.image,
            name: game.name,
            badgeHtml
        });
        container.appendChild(card);
    });
}

/* ==========================================================
   SPECIALS
========================================================== */

function renderSpecials(games) {
    const container = document.getElementById("specials");
    container.innerHTML = "";

    games.forEach(game => {
        const finalCents = Number(game.final_price);
        const final = finalCents > 0 ? `$${(finalCents / 100).toFixed(2)}` : "Free";
        const original = game.original_price || "";

        const priceHtml = `
            <div class="card-bottom">
                <div>
                    ${original ? `<span class="old-price">${original}</span>` : ""}
                    <span class="new-price">${final}</span>
                </div>
                ${game.discount_percent ? `<span class="discount">${game.discount_percent}</span>` : ""}
            </div>
        `;

        const card = buildHomeCard({ image: game.image, name: game.name, priceHtml });
        container.appendChild(card);
    });
}
/* ==========================================================
   NEW RELEASES
========================================================== */

function renderNewReleases(games) {
    const container = document.getElementById("newReleases");
    container.innerHTML = "";

    games.forEach(game => {
        const finalCents = Number(game.final_price);
        const price = finalCents > 0 ? `$${(finalCents / 100).toFixed(2)}` : "Free";

        const priceHtml = `<div class="card-bottom"><span class="new-price">${price}</span></div>`;

        const card = buildHomeCard({ image: game.image, name: game.name, priceHtml });
        container.appendChild(card);
    });
}

/* ==========================================================
   TOP SELLERS SCROLL BUTTONS
========================================================== */

document.getElementById("scrollLeft").addEventListener("click", () => {
    document.getElementById("topSellers").scrollBy({ left: -300, behavior: "smooth" });
});

document.getElementById("scrollRight").addEventListener("click", () => {
    document.getElementById("topSellers").scrollBy({ left: 300, behavior: "smooth" });
});