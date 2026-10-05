const API_BASE = "";

const headerStatus =
    document.getElementById("headerStatus");

const connectionIndicator =
    document.getElementById("connectionIndicator");

const messages =
    document.getElementById("messages");

const welcome =
    document.getElementById("welcome");

const chatForm =
    document.getElementById("chatForm");

const questionInput =
    document.getElementById("questionInput");

const sendButton =
    document.getElementById("sendButton");

const newChatButton =
    document.getElementById("newChatButton");

const analysisStatusLabel =
    document.getElementById("analysisStatusLabel");

const analysisStatusContext =
    document.getElementById("analysisStatusContext");


/* =========================================================
   APPLICATION STATE
   ========================================================= */

let asking = false;

let sessionId = getOrCreateSessionId();


/* =========================================================
   SESSION
   ========================================================= */

function getOrCreateSessionId() {
    const storageKey = "database_ai_session_id";

    try {
        const existing =
            sessionStorage.getItem(storageKey);

        if (existing) {
            return existing;
        }

        const id = createSessionId();

        sessionStorage.setItem(
            storageKey,
            id
        );

        return id;

    } catch (_) {
        return createSessionId();
    }
}


function createSessionId() {
    if (
        typeof crypto !== "undefined" &&
        typeof crypto.randomUUID === "function"
    ) {
        return crypto.randomUUID();
    }

    return (
        "session_" +
        Date.now().toString(36) +
        "_" +
        Math.random()
            .toString(36)
            .slice(2)
    );
}


function startNewSession() {
    sessionId = createSessionId();

    try {
        sessionStorage.setItem(
            "database_ai_session_id",
            sessionId
        );
    } catch (_) {
        // Session storage is optional.
    }
}


/* =========================================================
   CONNECTION STATUS
   ========================================================= */

function setConnectionStatus(
    label,
    state = "ready"
) {
    if (!connectionIndicator) {
        return;
    }

    connectionIndicator.dataset.state =
        state;

    connectionIndicator.innerHTML = `
        <span></span>
        ${escapeHtml(label)}
    `;
}


/* =========================================================
   ANALYSIS STATUS
   ========================================================= */

function setAnalysisStatus(
    label,
    context = ""
) {
    if (analysisStatusLabel) {
        analysisStatusLabel.textContent =
            label;
    }

    if (analysisStatusContext) {
        analysisStatusContext.textContent =
            context;
    }
}


/* =========================================================
   ASK QUESTION
   ========================================================= */

chatForm.addEventListener(
    "submit",
    async event => {

        event.preventDefault();

        const question =
            questionInput.value.trim();

        if (
            !question ||
            asking
        ) {
            return;
        }

        addMessage(
            "user",
            question
        );

        questionInput.value = "";

        resizeTextarea();

        asking = true;

        updateInteractionState();

        headerStatus.textContent =
            "Analyzing your question...";

        setAnalysisStatus(
            "ANALYZING",
            "Processing your database query."
        );

        setConnectionStatus(
            "Analyzing",
            "processing"
        );

        const loading =
            addLoadingMessage();

        try {

            const response =
                await fetch(
                    `${API_BASE}/ask/database`,
                    {
                        method: "POST",

                        headers: {
                            "Content-Type":
                                "application/json"
                        },

                        body: JSON.stringify({
                            question,
                            session_id: sessionId
                        })
                    }
                );

            if (!response.ok) {

                let detail = "";

                try {

                    const errorData =
                        await response.json();

                    if (errorData?.detail) {
                        detail =
                            `: ${errorData.detail}`;
                    }

                } catch (_) {
                    // Ignore invalid error response.
                }

                throw new Error(
                    `Request failed (${response.status})${detail}`
                );
            }

            const data =
                await response.json();

            const answer =
                extractAnswer(data);

            replaceLoadingMessage(
                loading,
                answer
            );

            headerStatus.textContent =
                "Analysis complete.";

            setAnalysisStatus(
                "DATABASE READY",
                "Ask another question to continue the analysis."
            );

            setConnectionStatus(
                "Ready",
                "ready"
            );

        } catch (error) {

            replaceLoadingMessage(
                loading,
                `I could not process that question: ${error.message}`
            );

            headerStatus.textContent =
                "The analysis could not be completed.";

            setAnalysisStatus(
                "ANALYSIS ERROR",
                "The database query could not be completed."
            );

            setConnectionStatus(
                "Error",
                "error"
            );

        } finally {

            asking = false;

            updateInteractionState();

            questionInput.focus();
        }
    }
);


/* =========================================================
   SUGGESTIONS
   ========================================================= */

document
    .querySelectorAll(
        "[data-question]"
    )
    .forEach(button => {

        button.addEventListener(
            "click",
            () => {

                if (asking) {
                    return;
                }

                questionInput.value =
                    button.dataset.question || "";

                resizeTextarea();

                updateInteractionState();

                questionInput.focus();
            }
        );
    });


/* =========================================================
   NEW ANALYSIS
   ========================================================= */

newChatButton.addEventListener(
    "click",
    () => {

        if (asking) {
            return;
        }

        startNewSession();

        messages.innerHTML = "";

        messages.appendChild(
            welcome
        );

        welcome.style.display = "";

        questionInput.value = "";

        resizeTextarea();

        headerStatus.textContent =
            "New analysis started. Ask a question about the database.";

        setAnalysisStatus(
            "DATABASE READY",
            "Ask a question to begin an analysis."
        );

        setConnectionStatus(
            "Ready",
            "ready"
        );

        updateInteractionState();

        questionInput.focus();
    }
);


/* =========================================================
   INTERACTION STATE
   ========================================================= */

function updateInteractionState() {

    if (sendButton) {
        sendButton.disabled =
            asking ||
            !questionInput.value.trim();
    }

    if (questionInput) {
        questionInput.disabled =
            asking;
    }

    if (newChatButton) {
        newChatButton.disabled =
            asking;
    }
}


/* =========================================================
   QUESTION INPUT
   ========================================================= */

questionInput.addEventListener(
    "input",
    () => {

        resizeTextarea();

        updateInteractionState();
    }
);


questionInput.addEventListener(
    "keydown",
    event => {

        if (
            event.key === "Enter" &&
            !event.shiftKey
        ) {

            event.preventDefault();

            if (
                !asking &&
                questionInput.value.trim()
            ) {
                chatForm.requestSubmit();
            }
        }
    }
);


/* =========================================================
   TEXTAREA
   ========================================================= */

function resizeTextarea() {

    questionInput.style.height =
        "auto";

    questionInput.style.height =
        Math.min(
            questionInput.scrollHeight,
            150
        ) + "px";
}


/* =========================================================
   MESSAGE CREATION
   ========================================================= */

function addMessage(
    role,
    text
) {

    if (
        welcome &&
        welcome.parentElement === messages
    ) {
        welcome.style.display =
            "none";
    }

    const wrapper =
        document.createElement(
            "div"
        );

    wrapper.className =
        `message ${role}`;

    wrapper.innerHTML = `
        <div class="message-avatar">
            ${role === "user" ? "YOU" : "AI"}
        </div>

        <div class="message-body">

            <div class="message-label">
                ${role === "user"
                    ? "YOUR QUESTION"
                    : "DATABASE ANALYSIS"}
            </div>

            <div class="message-content"></div>

        </div>
    `;

    const content =
        wrapper.querySelector(
            ".message-content"
        );

    content.textContent =
        String(text ?? "");

    messages.appendChild(
        wrapper
    );

    scrollConversation();

    return wrapper;
}


/* =========================================================
   LOADING MESSAGE
   ========================================================= */

function addLoadingMessage() {

    if (
        welcome &&
        welcome.parentElement === messages
    ) {
        welcome.style.display =
            "none";
    }

    const wrapper =
        document.createElement(
            "div"
        );

    wrapper.className =
        "message ai loading";

    wrapper.innerHTML = `
        <div class="message-avatar">
            AI
        </div>

        <div class="message-body">

            <div class="message-label">
                DATABASE ANALYSIS
            </div>

            <div class="message-content">
                <span class="loading-dot"></span>
                <span class="loading-dot"></span>
                <span class="loading-dot"></span>
            </div>

        </div>
    `;

    messages.appendChild(
        wrapper
    );

    scrollConversation();

    return wrapper;
}


function replaceLoadingMessage(
    wrapper,
    text
) {

    if (!wrapper) {
        return;
    }

    wrapper.classList.remove(
        "loading"
    );

    const content =
        wrapper.querySelector(
            ".message-content"
        );

    if (content) {
        content.textContent =
            String(text ?? "");
    }

    scrollConversation();
}


/* =========================================================
   RESPONSE EXTRACTION
   ========================================================= */

function extractAnswer(data) {

    if (
        typeof data === "string"
    ) {
        return data;
    }

    if (
        !data ||
        typeof data !== "object"
    ) {
        return String(data);
    }

    if (
        typeof data.answer === "string"
    ) {
        return data.answer;
    }

    if (
        typeof data.response === "string"
    ) {
        return data.response;
    }

    if (
        typeof data.result === "string"
    ) {
        return data.result;
    }

    if (
        typeof data.message === "string"
    ) {
        return data.message;
    }

    return JSON.stringify(
        data,
        null,
        2
    );
}


/* =========================================================
   SCROLL
   ========================================================= */

function scrollConversation() {

    requestAnimationFrame(
        () => {

            messages.scrollTo({
                top:
                    messages.scrollHeight,
                behavior:
                    "smooth"
            });

        }
    );
}


/* =========================================================
   HTML ESCAPING
   ========================================================= */

function escapeHtml(
    value
) {

    return String(value)
        .replaceAll(
            "&",
            "&amp;"
        )
        .replaceAll(
            "<",
            "&lt;"
        )
        .replaceAll(
            ">",
            "&gt;"
        )
        .replaceAll(
            '"',
            "&quot;"
        )
        .replaceAll(
            "'",
            "&#039;"
        );
}


/* =========================================================
   INITIAL STATE
   ========================================================= */

setConnectionStatus(
    "Ready",
    "ready"
);

setAnalysisStatus(
    "DATABASE READY",
    "Ask a question to begin an analysis."
);

if (headerStatus) {
    headerStatus.textContent =
        "Database connected. Ask a question to explore its data.";
}

resizeTextarea();

updateInteractionState();