/* ==========================================================
   NIMLYX — DISCOVER WIZARD
   Drives the progressive question flow, the Selected Preferences
   chips, the Find Games CTA, and rendering of results once the
   user has answered every question.
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

    const state = {};
    let isFetching = false;

    let wizardEl, chipsContainer, findGamesBtn, resultsGrid, resultsSubtitle;

    /* ------------------------------------------------------------
       INIT
    ------------------------------------------------------------ */
    function init() {
        wizardEl = document.getElementById("discoverWizard");
        chipsContainer = document.getElementById("selectedPreferencesChips");
        findGamesBtn = document.getElementById("findGamesBtn");
        resultsGrid = document.getElementById("discoverResultsGrid");
        resultsSubtitle = document.querySelector(".discover-results-subtitle");

        if (!wizardEl) return;

        QUESTIONS.forEach((question) => {
            const questionEl = document.getElementById(question.id);
            if (!questionEl) return;

            const options = questionEl.querySelectorAll(".wizard-option");
            options.forEach((option) => {
                option.addEventListener("click", () => selectOption(question, questionEl, option));
            });
        });

        if (findGamesBtn) {
            findGamesBtn.addEventListener("click", handleFindGames);
        }
    }

    /* ------------------------------------------------------------
       OPTION SELECTION
    ------------------------------------------------------------ */
    function selectOption(question, questionEl, option) {
        const options = questionEl.querySelectorAll(".wizard-option");
        options.forEach((btn) => btn.classList.remove("is-selected"));
        option.classList.add("is-selected");

        const titleEl = option.querySelector(".wizard-option-title");
        const label = titleEl ? titleEl.textContent.trim() : option.dataset.value;

        state[question.key] = {
            value: option.dataset.value,
            label: label,
            questionKey: question.key,
            questionLabel: question.label
        };

        resetQuestionsAfter(question);
        renderChips();
        revealNextQuestion(questionEl);
        updateFindButtonState();
    }

    /* ------------------------------------------------------------
       RESET LATER QUESTIONS
       Answering (or re-answering) a question clears every question
       that comes after it — their state, their selected styles, their
       chips — and hides them again until the user reaches them.
    ------------------------------------------------------------ */
    function resetQuestionsAfter(question) {
        const currentIndex = QUESTIONS.findIndex((q) => q.key === question.key);

        QUESTIONS.slice(currentIndex + 1).forEach((laterQuestion) => {
            delete state[laterQuestion.key];

            const laterQuestionEl = document.getElementById(laterQuestion.id);
            if (!laterQuestionEl) return;

            laterQuestionEl.querySelectorAll(".wizard-option").forEach((btn) => {
                btn.classList.remove("is-selected");
            });

            laterQuestionEl.classList.add("is-hidden");
            laterQuestionEl.classList.remove("is-active");
        });
    }

    /* ------------------------------------------------------------
       REVEAL NEXT QUESTION
    ------------------------------------------------------------ */
    function revealNextQuestion(currentQuestionEl) {
        const currentIndex = QUESTIONS.findIndex((q) => q.id === currentQuestionEl.id);
        const next = QUESTIONS[currentIndex + 1];
        if (!next) return;

        const nextEl = document.getElementById(next.id);
        if (!nextEl) return;

        if (nextEl.classList.contains("is-hidden")) {
            nextEl.classList.remove("is-hidden");
            nextEl.classList.add("is-active");
            nextEl.scrollIntoView({ behavior: "smooth", block: "start" });
        }
    }

    /* ------------------------------------------------------------
       SELECTED PREFERENCES — CHIPS
    ------------------------------------------------------------ */
    function renderChips() {
        if (!chipsContainer) return;
        chipsContainer.innerHTML = "";

        QUESTIONS.forEach((question) => {
            const answer = state[question.key];
            if (!answer) return;

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
            resetQuestionsAfter(question);
        }

        renderChips();
        updateFindButtonState();
    }

    /* ------------------------------------------------------------
       FIND GAMES BUTTON STATE
    ------------------------------------------------------------ */
    function updateFindButtonState() {
        if (!findGamesBtn) return;
        const allAnswered = QUESTIONS.every((question) => Boolean(state[question.key]));
        findGamesBtn.disabled = !allAnswered;
    }

    /* ------------------------------------------------------------
       FIND GAMES — FETCH + RENDER RESULTS
    ------------------------------------------------------------ */
    async function handleFindGames() {
        if (findGamesBtn.disabled || isFetching) return;

        isFetching = true;
        const originalLabel = findGamesBtn.textContent;
        findGamesBtn.disabled = true;
        findGamesBtn.textContent = "Searching…";

        const params = new URLSearchParams();
        QUESTIONS.forEach((question) => {
            const answer = state[question.key];
            if (answer) params.set(question.key, answer.value);
        });

        try {
            const response = await fetch(`/api/discover?${params.toString()}`);
            const data = await response.json();
            renderResults(Array.isArray(data.games) ? data.games : []);
        } catch (error) {
            console.error("Error fetching discover results:", error);
            renderResults([]);
            if (resultsSubtitle) {
                resultsSubtitle.textContent = "Something went wrong while finding games. Please try again.";
            }
        } finally {
            isFetching = false;
            findGamesBtn.disabled = false;
            findGamesBtn.textContent = originalLabel;
        }
    }

    const FALLBACK_IMAGE = "/static/images/game-placeholder.png";

    function createGameCard(game) {
        const card = document.createElement("a");
        card.className = "home-card";
        card.href = game.analyze_url || "#";

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
        img.addEventListener("error", () => {
            img.src = FALLBACK_IMAGE;
        }, { once: true });

        return card;
    }

    function renderEmptyState() {
        resultsGrid.innerHTML = "";

        const emptyState = document.createElement("div");
        emptyState.className = "discover-results-empty";
        emptyState.innerHTML = `
            <span class="discover-results-empty-icon" aria-hidden="true">🎮</span>
            <p class="discover-results-empty-title">No games matched your preferences.</p>
            <p class="discover-results-empty-text">Try increasing your budget or lowering your review requirement.</p>
        `;
        resultsGrid.appendChild(emptyState);
    }

    function renderResults(games) {
        if (!resultsGrid) return;
        resultsGrid.innerHTML = "";

        if (games.length === 0) {
            if (resultsSubtitle) {
                resultsSubtitle.textContent = "No games matched your preferences yet. Try adjusting your answers above.";
            }
            renderEmptyState();
            return;
        }

        if (resultsSubtitle) {
            resultsSubtitle.textContent = "Based on what you told us, here's what fits.";
        }

        games.forEach((game) => {
            resultsGrid.appendChild(createGameCard(game));
        });

        resultsGrid.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }

})();