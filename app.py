import os
import base64
import hashlib
import requests
import urllib.parse
from flask import Flask, session, redirect, url_for, request, render_template, flash, jsonify
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
SCOPE = 'user_data vehicle_device_data'  # Minimum scopes for user info
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

@app.route('/vehicles')
def get_vehicles():
    # Check access token
    access_token = session.get('access_token')
    if not access_token:
        return {"error": "Access token not found."}, 401

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
    }

    # Get vehicles
    vehicle_url = f'{API_BASE_URL}/api/1/vehicles'
    response = requests.get(vehicle_url, headers=headers)

    print(f'Vehicle response: {response.status_code}, {response.text}')

    if response.status_code != 200:
        return {"error": "Error retrieving vehicles.", "details": response.text}, response.status_code

    return response.json()

@app.route('/vehicle_options/<vin>')
def get_vehicle_options(vin):
    # Check access token
    access_token = session.get('access_token')
    if not access_token:
        return {"error": "Access token not found."}, 401

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
    }

    # Get vehicle options
    options_url = f'{API_BASE_URL}/api/1/dx/vehicles/options'
    params = {'vin': vin}
    response = requests.get(options_url, headers=headers, params=params)

    if response.status_code != 200:
        return {"error": "Error retrieving vehicle options.", "details": response.text}, response.status_code

    return response.json()

# 차량 이미지를 생성하는 엔드포인트
@app.route('/generate_image/<vin>/<model_letter>/<option_codes>')
def generate_vehicle_image(vin, model_letter, option_codes):
    # 옵션 코드 문자열을 리스트로 변환
    option_codes_list = option_codes.split(',')
    
    # Tesla 이미지 URL 생성
    image_urls = generate_tesla_images(model_letter, option_codes_list)
    
    return jsonify({'urls': image_urls})

def generate_tesla_images(model_letter, option_codes):
    # Tesla 이미지 베이스 URL
    base_url = "https://static-assets.tesla.com/configurator/compositor"

    # 이미지 각도 옵션 설정
    view_angles = [ 'STUD_3QTR', 'STUD_SIDE', 'STUD_3QTR_V2', 'STUD_SEAT_V2']

    # 배경 설정 (0: 흰색 배경, 1: 투명 배경)
    bkba_opt = 1

    # 이미지 URL 생성 (각각의 뷰 앵글에 대해 생성)
    image_urls = [
        f"{base_url}?&options={','.join(option_codes)}&view={view}&model=m{model_letter}&size=1441&bkba_opt={bkba_opt}&version=v0027d202003051352"
        for view in view_angles
    ]

    return image_urls

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.')
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3000)
