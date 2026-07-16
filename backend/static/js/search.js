const params = new URLSearchParams(window.location.search);
const gameName = params.get("q");

document.getElementById("gameInput").value = gameName || "";

document.getElementById("searchBtn").addEventListener("click", () => {
    const newQuery = document.getElementById("gameInput").value.trim();
    if (!newQuery) return;
    window.location.href = `/search?q=${encodeURIComponent(newQuery)}`;
});

async function loadGame() {
    if (!gameName) return;

    try {
        const response = await fetch(`/api/find/${gameName}`);
        const game = await response.json();
        displayGame(game);
    } catch (error) {
        console.error("Error loading game:", error);
    }
}

function displayGame(game) {
    renderHero(game);
    renderMedia(game);
    renderAbout(game);
    renderTags(game);
    renderStats(game);
}
function renderHero(game) {
    const hero = document.getElementById("heroSection");
    hero.innerHTML = `
        <img src="${game.header_image}" alt="${game.name}" class="hero-bg">
        <div class="hero-overlay">
            <h1 class="hero-title">${game.name}</h1>
            <div class="hero-meta">
                <span>${game.price}</span>
                <span>•</span>
                <span>${game.metacritic ? "⭐ " + game.metacritic : "No score"}</span>
                <span>•</span>
                <span>${game.release_date}</span>
            </div>
        </div>
    `;
}

function renderAbout(game) {
    const about = document.getElementById("aboutSection");
    about.innerHTML = `
        <h2>About</h2>
        <p>${game.short_description}</p>
    `;
}

function renderTags(game) {
    const tags = document.getElementById("tagsSection");
    const genreBadges = game.genres.map(g => `<span class="badge">${g}</span>`).join("");
    tags.innerHTML = `
        <h2>Genres</h2>
        <div class="genre-badges">${genreBadges}</div>
    `;
}


function renderMedia(game) {
    const media = document.getElementById("mediaSection");

    if (!game.screenshots || game.screenshots.length === 0) {
        media.innerHTML = "";
        return;
    }

    const screenshotHtml = game.screenshots
        .map(url => `<img src="${url}" class="screenshot-thumb" alt="${game.name} screenshot">`)
        .join("");

    media.innerHTML = `
        <h2>Screenshots</h2>
        <div class="screenshot-gallery">${screenshotHtml}</div>
    `;
}
function renderStats(game) {
    const stats = document.getElementById("statsSection");
    const platformBadges = Object.keys(game.platforms)
        .filter(p => game.platforms[p])
        .map(p => `<span class="badge">${p}</span>`)
        .join("");

    stats.innerHTML = `
        <h3>Quick Stats</h3>
        <div class="info-row"><span class="info-label">Price</span><span class="info-value">${game.price}</span></div>
        <div class="info-row"><span class="info-label">Metacritic</span><span class="info-value">${game.metacritic ?? "N/A"}</span></div>
        <div class="info-row"><span class="info-label">Reviews</span><span class="info-value">${game.total_reviews.toLocaleString()}</span></div>
        <div class="info-row"><span class="info-label">Platforms</span><span class="info-value">${platformBadges}</span></div>
        <div class="info-row"><span class="info-label">Developer</span><span class="info-value">${game.developers.join(", ")}</span></div>
    `;
}
loadGame();
console.log("search.js loaded");