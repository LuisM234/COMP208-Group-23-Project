/**
 * decks.js
 * Connects my_decks.html to the FastAPI backend (decks.py)
 * Mirrors the pattern used in app.js — JWT token from localStorage,
 * all API calls go to http://localhost:8000/decks/
 */

const API_BASE = 'http://localhost:8000';

// Helpers 

// Returns the Authorization header using the JWT saved by app.js on login.
 
function authHeaders() {
    const token = localStorage.getItem('token');
    return {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        ...(token ? { 'Authorization': `Bearer ${token}` } : {})
    };
}

//Reads ?deck_id=<n> from the URL so this page knows which deck to load.

function getDeckIdFromUrl() {
    const params = new URLSearchParams(window.location.search);
    return params.get('deck_id') ? parseInt(params.get('deck_id')) : null;
}

//API calls 

// GET /decks/{deck_id} 
async function fetchDeck(deckId) {
    const response = await fetch(`${API_BASE}/decks/${deckId}`, {
        method: 'GET',
        headers: authHeaders()
    });
    if (!response.ok) throw new Error(`Failed to load deck (${response.status})`);
    return response.json(); // { id, title, description }
}

//GET /decks/ — returns all decks for the logged-in user 
async function fetchAllDecks() {
    const response = await fetch(`${API_BASE}/decks/`, {
        method: 'GET',
        headers: authHeaders()
    });
    if (!response.ok) throw new Error(`Failed to load decks (${response.status})`);
    return response.json(); // [{ id, title, description }, ...]
}

//PUT /decks/{deck_id} 
async function updateDeck(deckId, title, description) {
    const response = await fetch(`${API_BASE}/decks/${deckId}`, {
        method: 'PUT',
        headers: authHeaders(),
        body: JSON.stringify({ title, description })
    });
    if (!response.ok) throw new Error(`Failed to save deck (${response.status})`);
    return response.json();
}

// DELETE /decks/{deck_id} 
async function deleteDeck(deckId) {
    const response = await fetch(`${API_BASE}/decks/${deckId}`, {
        method: 'DELETE',
        headers: authHeaders()
    });
    if (!response.ok) throw new Error(`Failed to delete deck (${response.status})`);
    // 204 No Content, no body to parse
}

// POST /decks/ 
async function createDeck(title, description) {
    const response = await fetch(`${API_BASE}/decks/`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ title, description })
    });
    if (!response.ok) throw new Error(`Failed to create deck (${response.status})`);
    return response.json(); // { id, title, description }
}

//DOM helpers

function showError(msg) {
    // Reuse existing error-message element if present, otherwise console.error
    const el = document.getElementById('error-message');
    if (el) {
        el.innerText = msg;
    } else {
        console.error(msg);
    }
}

//Populate the Deck Settings card with data from the API.
 
function populateDeckSettings(deck) {
    const nameInput = document.getElementById('deck-name');
    const descInput = document.getElementById('deck-description');

    if (nameInput) nameInput.value = deck.title;
    if (descInput) descInput.value = deck.description;

    // Update the page title to reflect the deck name
    document.title = `ReviseWise – ${deck.title}`;
}

//Save Changes button 

//Injects a "Save Changes" button below the Deck Settings card if one doesn't already exist in the HTML, then wires it up.
 
function setupSaveButton(deckId) {
    let saveBtn = document.getElementById('save-deck-btn');

    if (!saveBtn) {
        // Create and inject the button dynamically
        saveBtn = document.createElement('button');
        saveBtn.id = 'save-deck-btn';
        saveBtn.className = 'btn btn-primary';
        saveBtn.style.cssText = 'margin-top: 16px; align-self: flex-end;';
        saveBtn.innerHTML = `
            <svg viewBox="0 0 24 24" style="width:14px;height:14px;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round">
                <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>
                <polyline points="17 21 17 13 7 13 7 21"/>
                <polyline points="7 3 7 8 15 8"/>
            </svg>
            Save Changes`;

        // Append it inside the first .card (Deck Settings)
        const settingsCard = document.querySelector('.card');
        if (settingsCard) settingsCard.appendChild(saveBtn);
    }

    saveBtn.addEventListener('click', async () => {
        const title = document.getElementById('deck-name')?.value?.trim();
        const description = document.getElementById('deck-description')?.value?.trim();

        if (!title) {
            showError('Deck name cannot be empty.');
            return;
        }

        saveBtn.disabled = true;
        saveBtn.innerText = 'Saving…';

        try {
            await updateDeck(deckId, title, description);
            saveBtn.innerText = 'Saved ✓';
            setTimeout(() => {
                saveBtn.disabled = false;
                saveBtn.innerHTML = `
                    <svg viewBox="0 0 24 24" style="width:14px;height:14px;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round">
                        <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>
                        <polyline points="17 21 17 13 7 13 7 21"/>
                        <polyline points="7 3 7 8 15 8"/>
                    </svg>
                    Save Changes`;
            }, 2000);
        } catch (err) {
            showError(err.message);
            saveBtn.disabled = false;
            saveBtn.innerText = 'Save Changes';
        }
    });
}

// Delete Deck button 

//Wire up a "Delete Deck" button (add it if not already in HTML).

function setupDeleteDeckButton(deckId) {
    let deleteBtn = document.getElementById('delete-deck-btn');

    if (!deleteBtn) {
        deleteBtn = document.createElement('button');
        deleteBtn.id = 'delete-deck-btn';
        deleteBtn.className = 'btn';
        deleteBtn.style.cssText = 'margin-top: 16px; margin-left: 8px; align-self: flex-end; color: var(--danger); border-color: var(--danger);';
        deleteBtn.innerHTML = `
            <svg viewBox="0 0 24 24" style="width:14px;height:14px;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round">
                <polyline points="3 6 5 6 21 6"/>
                <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>
                <path d="M10 11v6"/><path d="M14 11v6"/>
                <path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>
            </svg>
            Delete Deck`;

        const settingsCard = document.querySelector('.card');
        if (settingsCard) settingsCard.appendChild(deleteBtn);
    }

    deleteBtn.addEventListener('click', async () => {
        if (!confirm('Are you sure you want to delete this deck? This cannot be undone.')) return;

        deleteBtn.disabled = true;
        deleteBtn.innerText = 'Deleting…';

        try {
            await deleteDeck(deckId);
            // Redirect back to the decks list after deletion
            window.location.href = 'dashboard.html';
        } catch (err) {
            showError(err.message);
            deleteBtn.disabled = false;
            deleteBtn.innerText = 'Delete Deck';
        }
    });
}

//"New Deck" flow (for pages that list all decks)

//If there's a #new-deck-btn on the page, wire it up to POST /decks/ and then redirect to my_decks.html?deck_id=<newId>

function setupNewDeckButton() {
    const newBtn = document.getElementById('new-deck-btn');
    if (!newBtn) return;

    newBtn.addEventListener('click', async () => {
        const title = prompt('New deck name:');
        if (!title?.trim()) return;

        try {
            const deck = await createDeck(title.trim(), '');
            window.location.href = `my_decks.html?deck_id=${deck.id}`;
        } catch (err) {
            showError(err.message);
        }
    });
}

//Page init 

async function init() {
    const deckId = getDeckIdFromUrl();

    if (deckId) {
        // Single deck view (my_decks.html?deck_id=42) 
        try {
            const deck = await fetchDeck(deckId);
            populateDeckSettings(deck);
            setupSaveButton(deckId);
            setupDeleteDeckButton(deckId);
        } catch (err) {
            showError(`Could not load deck: ${err.message}`);
        }
    } else {
        // All-decks list view (no deck_id in URL)
        try {
            const decks = await fetchAllDecks();
            console.log('All decks:', decks);
            // If your page has a deck list container, populate it here. e.g. renderDeckList(decks);
        } catch (err) {
            showError(`Could not load decks: ${err.message}`);
        }
    }

    // Wire up optional new-deck button
    setupNewDeckButton();
}

document.addEventListener('DOMContentLoaded', init);
