function displayGame(game) {
    const gameSection = document.getElementById("gameSection");
    gameSection.innerHTML = "";

    const genreBadges = game.genres.map(genre => `<span class="badge">${genre}</span>`).join("");

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

document.getElementById("searchBtn").addEventListener("click", async () => {
    const gameName = document.getElementById("gameInput").value;
    try {
        const response = await fetch(`http://127.0.0.1:5000/api/find/${gameName}`);
        const data = await response.json();
        console.log(data);
        displayGame(data);
    } catch (error) {
        console.error("Error connecting to backend:", error);
    }
});
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
    const response = await fetch(`http://127.0.0.1:5000/api/search/${query}`);
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
        document.getElementById("gameInput").value = game.name;
        suggestionsBox.innerHTML = "";
        document.getElementById("searchBtn").click();
    });
    suggestionsBox.appendChild(item);
});
}