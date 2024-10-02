import os
import base64
import hashlib
import requests
import urllib.parse
import cv2
from PIL import Image
from collections import Counter
from flask import Flask, session, redirect, url_for, request, render_template, flash, jsonify, send_from_directory
from dotenv import load_dotenv
from datetime import datetime, timedelta

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

# Cache settings
CACHE_DIR = 'cache'
CACHE_DURATION = timedelta(hours=720)

# Create cache directory if not exists
if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

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
    
    # 이미지 다운로드 및 캐싱
    cached_images = cache_images(image_urls, vin, model_letter, option_codes_list)
    
    return jsonify({'urls': cached_images})

def generate_tesla_images(model_letter, option_codes):
    # Tesla 이미지 베이스 URL
    base_url = "https://static-assets.tesla.com/configurator/compositor"

    # 이미지 각도 옵션 설정
    view_angles = [ 'STUD_FRONT34', 'STUD_SIDEVIEW', 'STUD_REAR34', 'STUD_RIMCLOSEUP', 'STUD_INTERIOR']

    # 배경 설정 (0: 흰색 배경, 1: 투명 배경)
    bkba_opt = 1

    # 이미지 URL 생성 (각각의 뷰 앵글에 대해 생성)
    image_urls = [
        f"{base_url}?&context=design_studio_2&options={','.join(option_codes)}&view={view}&model=m{model_letter}&size=1920&bkba_opt={bkba_opt}&crop=0,0,0,0&"
        for view in view_angles
    ]

    return image_urls

def cache_images(image_urls, vin, model_letter, option_codes):
    cached_image_paths = []
    view_index = 0  # 뷰 각도마다 고유한 파일명을 생성하기 위한 인덱스
    
    for url in image_urls:
        view_index += 1  # 다음 뷰 각도를 처리하기 위한 인덱스 증가
        # 파일명 생성: 뷰를 구분하여 각 뷰의 이미지를 고유하게 저장
        view_angle = url.split('&view=')[1].split('&')[0]  # URL에서 view 각도 추출
        file_name = f"{view_index}-{vin}_{model_letter}_{'_'.join(option_codes)}_{view_angle}.jpg".replace('/', '_')
        file_path = os.path.join(CACHE_DIR, file_name)
        
        # 파일이 이미 캐시되어 있고 24시간 내 생성되었다면 기존 파일을 사용
        if os.path.exists(file_path):
            file_mod_time = datetime.fromtimestamp(os.path.getmtime(file_path))
            if datetime.now() - file_mod_time < CACHE_DURATION:
                if view_index == 1:
                    cartoon_file_name = f"6-{vin}_{model_letter}_cartoon.png"
                    cached_image_paths.append(f"/cached_image/{cartoon_file_name}")
                cached_image_paths.append(f"/cached_image/{file_name}")
                continue
            else:
                # 캐시 시간이 초과되면 파일을 삭제
                os.remove(file_path)

        # 새로운 파일 다운로드
        response = requests.get(url, stream=True)
        if response.status_code == 200:
            with open(file_path, 'wb') as file:
                file.write(response.content)

            if view_index == 1:
                cartoon_file_name = f"6-{vin}_{model_letter}_cartoon.png"
                create_cartoon_image(file_path, cartoon_file_name)
                cached_image_paths.append(f"/cached_image/{cartoon_file_name}")

            cached_image_paths.append(f"/cached_image/{file_name}")


    return cached_image_paths

def create_cartoon_image(input_image_path, output_image_name):
    img = cv2.imread(input_image_path)

    # Convert image to RGB
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    # Apply bilateral filter
    for _ in range(7):
        img_rgb = cv2.bilateralFilter(img_rgb, d=9, sigmaColor=75, sigmaSpace=75)

    # Edge detection
    img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    img_blur = cv2.medianBlur(img_gray, 7)
    edges = cv2.adaptiveThreshold(img_blur, 255, 
                                  cv2.ADAPTIVE_THRESH_MEAN_C, 
                                  cv2.THRESH_BINARY, 
                                  blockSize=9, C=2)

    # Combine color and edges
    edges_colored = cv2.cvtColor(edges, cv2.COLOR_GRAY2RGB)
    cartoon = cv2.bitwise_and(img_rgb, edges_colored)

    # Reduce color depth
    img_pil = Image.fromarray(cartoon)
    img_pil = img_pil.convert('P', palette=Image.ADAPTIVE, colors=256)

    # Convert to RGBA to add transparency
    img_pil = img_pil.convert('RGBA')

    # Get the data of the image
    datas = list(img_pil.getdata())

    # Get the most common color in the first 1-1000 pixels
    common_color = Counter(datas[:min(1000, len(datas))]).most_common(1)[0][0]

    # Replace the most common color with transparent
    new_data = []
    for item in datas:
        # Check if the item matches the most common color
        if item[:3] == common_color[:3]:  # Compare only RGB channels
            # Change to transparent
            new_data.append((255, 255, 255, 0))
        else:
            new_data.append(item)

    # Update image data
    img_pil.putdata(new_data)

    # Save the cartoon effect image as PNG to support transparency
    output_image_name = os.path.splitext(output_image_name)[0] + ".png"
    img_pil.save(os.path.join(CACHE_DIR, output_image_name))

@app.route('/cached_image/<filename>')
def serve_cached_image(filename):
    # 캐시 디렉터리에서 이미지 파일 반환
    return send_from_directory(CACHE_DIR, filename)

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.')
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3000)
