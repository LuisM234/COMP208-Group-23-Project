/**
 * param @username
 * param @password 
 * returns login data to front end 
 * method checks if login is valid - JWT ticket saved if it is if not error appears.
 */ 

// --- DOM Elements ---
const tabLogin = document.getElementById('tab-login');
const tabSignup = document.getElementById('tab-signup');
const authForm = document.getElementById('auth-form');
const submitBtn = document.getElementById('submit-btn');
const forgotPasswordLink = document.getElementById('forgot-password');
const errorMessage = document.getElementById('error-message');

const loginPage = document.getElementById('login-page');
const dashboardPage = document.getElementById('dashboard-page');

// NEW: Grab the username group and input
const usernameGroup = document.getElementById('username-group');
const usernameInput = document.getElementById('username');

// --- State Tracker ---
let isLoginMode = true;

// --- Tab Switching Logic ---
tabLogin.addEventListener('click', () => {
    isLoginMode = true;
    tabLogin.classList.add('active');
    tabSignup.classList.remove('active');
    
    submitBtn.innerText = "Sign in";
    forgotPasswordLink.classList.remove('hidden');
    errorMessage.innerText = ""; 
    
    // Hide username field and remove requirement
    usernameGroup.classList.add('hidden');
    usernameInput.required = false;
});

tabSignup.addEventListener('click', () => {
    isLoginMode = false;
    tabSignup.classList.add('active');
    tabLogin.classList.remove('active');
    
    submitBtn.innerText = "Create Account";
    forgotPasswordLink.classList.add('hidden');
    errorMessage.innerText = "";
    
    // Show username field and make it required
    usernameGroup.classList.remove('hidden');
    usernameInput.required = true;
});

// --- Form Submission Logic ---
authForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const emailValue = document.getElementById('email').value;
    const passwordValue = document.getElementById('password').value;
    const usernameValue = document.getElementById('username') ? document.getElementById('username').value : "";
    
    const endpoint = isLoginMode ? 'http://localhost:8000/auth/login' : 'http://localhost:8000/auth/signup';
    
    // Create the exact object the backend expects
    let payload;
    if (isLoginMode) {
        payload = {
            email: emailValue,
            password: passwordValue
        };
    } else {
        payload = {
            username: usernameValue,
            email: emailValue,
            password: passwordValue
        };
    }
    
    try {
        const response = await fetch(endpoint, {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            },
            body: JSON.stringify(payload) 
        });

        const data = await response.json();

        if (response.ok) {
            localStorage.setItem('token', data.access_token);
            window.location.href = 'my_decks.html';
        } else {
            console.error("Validation Error:", data);
            errorMessage.innerText = data.detail[0].msg || "Check your input fields.";
        }
    } catch (error) {
        errorMessage.innerText = "Connection error.";
    }
});
