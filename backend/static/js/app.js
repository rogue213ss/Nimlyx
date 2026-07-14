function displayGame(game) {
    const gameSection = document.getElementById("gameSection");
    gameSection.innerHTML = "";

    const genreBadges = game.genres.map(genre => `<span class="badge">${genre}</span>`).join("");

    const card = document.createElement("div");
    card.className = "game-card";

    card.innerHTML = `
        <img src="${game.header_image}" alt="${game.name}">
        <div class="game-info">
            <h2>${game.name}</h2>
            <div class="genre-badges">${genreBadges}</div>
            <p class="price">${game.price}</p>
            <p>${game.developers.join(", ")} | ${game.publishers.join(", ")}</p>
            <p>Released: ${game.release_date}</p>
            ${game.metacritic ? `<p class="metacritic">Metacritic: ${game.metacritic}</p>` : ""}
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