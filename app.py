import os
import base64
import hashlib
import requests
import urllib.parse
from flask import Flask, session, redirect, url_for, request, render_template, flash
from dotenv import load_dotenv

# Load environment variables
load_dotenv('.env.local')

# Flask application setup
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY')

# Tesla API Constants
CLIENT_ID = os.getenv('CLIENT_ID')
REDIRECT_URI = os.getenv('REDIRECT_URI')
AUTH_URL = 'https://auth.tesla.com/oauth2/v3/authorize'
TOKEN_URL = 'https://auth.tesla.com/oauth2/v3/token'
AUDIENCE = 'https://fleet-api.prd.na.vn.cloud.tesla.com'
API_BASE_URL = 'https://fleet-api.prd.na.vn.cloud.tesla.com'
SCOPE = 'user_data'  # Minimum scopes for user info
CODE_CHALLENGE_METHOD = 'S256'

# Generate PKCE code verifier and challenge
def generate_code_verifier_and_challenge():
    code_verifier = base64.urlsafe_b64encode(os.urandom(64)).rstrip(b'=').decode('utf-8')
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode('utf-8')).digest()
    ).rstrip(b'=').decode('utf-8')
    return code_verifier, code_challenge

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login')
def login():
    # Generate PKCE
    code_verifier, code_challenge = generate_code_verifier_and_challenge()
    session['code_verifier'] = code_verifier

    # Build Tesla API authorization URL
    auth_params = {
        'response_type': 'code',
        'client_id': CLIENT_ID,
        'redirect_uri': REDIRECT_URI,
        'scope': SCOPE,
        'state': os.urandom(16).hex(),
        'code_challenge': code_challenge,
        'code_challenge_method': CODE_CHALLENGE_METHOD,
    }
    auth_url = f"{AUTH_URL}?{urllib.parse.urlencode(auth_params)}"
    return redirect(auth_url)

@app.route('/api')
def callback():
    # Extract authorization code from callback
    auth_code = request.args.get('code')
    if not auth_code:
        flash('Authorization code not found.')
        return redirect(url_for('index'))

    code_verifier = session.get('code_verifier')

    # Exchange code for tokens
    token_data = {
        'grant_type': 'authorization_code',
        'client_id': CLIENT_ID,
        'code': auth_code,
        'redirect_uri': REDIRECT_URI,
        'code_verifier': code_verifier,
        'audience': AUDIENCE,
    }
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
    }
    response = requests.post(TOKEN_URL, data=token_data, headers=headers)

    # Handle token exchange errors
    if response.status_code != 200:
        flash('Error obtaining access token.')
        print(f"Error: {response.status_code}, {response.text}")
        return redirect(url_for('index'))

    tokens = response.json()
    session['access_token'] = tokens['access_token']
    session['refresh_token'] = tokens.get('refresh_token')

    return redirect(url_for('user_info'))

@app.route('/user_info')
def user_info():
    # Check access token
    access_token = session.get('access_token')
    if not access_token:
        flash('Access token not found.')
        return redirect(url_for('index'))

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
    }

    # Get user info
    user_url = f'{API_BASE_URL}/api/1/users/me'
    response = requests.get(user_url, headers=headers)

    if response.status_code != 200:
        flash('Error retrieving user information.')
        print(f"Error: {response.status_code}, {response.text}")
        return redirect(url_for('index'))

    user_data = response.json().get('response', {})
    return render_template('user_info.html', user=user_data)

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.')
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3000)
