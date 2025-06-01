from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_mail import Mail, Message
import psycopg2
import psycopg2.extras
import json
import uuid
import bcrypt
from datetime import datetime, timedelta, timezone
from pytz import timezone as pytz_timezone
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import os
import logging
from flask import send_from_directory
import requests

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', '')
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.filters['loads'] = json.loads

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DATABASE_URL = os.environ.get('DATABASE_URL')

def get_db_connection():
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.DictCursor)
        return conn
    except Exception as e:
        logging.error(f"Database connection error: {e}")
        return None

def format_datetime(iso_string):
    try:
        dt = datetime.fromisoformat(iso_string.replace('Z', '+00:00')).astimezone(pytz_timezone('Asia/Ho_Chi_Minh'))
        return dt.strftime('%a, %d %b %y | %H:%M:%S')
    except (ValueError, TypeError):
        return iso_string
    
def verify_recaptcha(response):
    secret_key = os.environ.get('RECAPTCHA_SECRET_KEY', '')  # Replace with your actual secret key
    data = {"secret": secret_key, "response": response}
    r = requests.post("https://www.google.com/recaptcha/api/siteverify", data=data)
    return r.json().get("success", False)

app.jinja_env.filters['format_datetime'] = format_datetime

app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', '')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', '')
mail = Mail(app)

def init_db():
    conn = get_db_connection()
    if not conn:
        logging.error("Failed to connect to database during init_db")
        return
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        ftu_email TEXT UNIQUE,
        name TEXT,
        password TEXT,
        verified BOOLEAN,
        gender TEXT,
        age INTEGER,
        location TEXT,
        sports JSONB,
        skill_levels JSONB,
        preferences JSONB,
        description TEXT,
        time_slots JSONB,
        recurring_slots JSONB,
        profile_complete BOOLEAN DEFAULT FALSE,
        class TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS matches (
        id SERIAL PRIMARY KEY,
        user1_id INTEGER,
        user2_id INTEGER,
        status TEXT,
        timestamp TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS requests (
        id SERIAL PRIMARY KEY,
        sender_id INTEGER,
        receiver_id INTEGER,
        status TEXT,
        timestamp TEXT,
        selected_time_slot TEXT,
        selected_sport TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS verification_tokens (
        token TEXT PRIMARY KEY,
        user_id INTEGER,
        email TEXT,
        name TEXT,
        password TEXT,
        created_at TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS messages (
        id SERIAL PRIMARY KEY,
        sender_id INTEGER,
        receiver_id INTEGER,
        content TEXT,
        timestamp TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS likes (
        id SERIAL PRIMARY KEY,
        sender_id INTEGER,
        receiver_id INTEGER,
        timestamp TEXT,
        UNIQUE(sender_id, receiver_id)
    )''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_requests_status ON requests(status)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_matches_status ON matches(status)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_likes_sender_receiver ON likes(sender_id, receiver_id)')
    
    hcm_tz = pytz_timezone('Asia/Ho_Chi_Minh')
    test_users = [
        ('test1@ftu.edu.vn', 'Test User 1', bcrypt.hashpw('testpass1'.encode('utf-8'), bcrypt.gensalt()).decode('utf-8'), True, 'female', 22, 'Bình Thạnh',
         json.dumps(['badminton', 'gym', 'swimming', 'football']), json.dumps({'gym': 'intermediate', 'football': 'beginner', 'swimming': 'beginner', 'badminton': 'beginner'}),
         json.dumps({'same_gender': False, 'motivation': 'high'}), 'Morning workouts are my jam!',
         json.dumps([datetime(2025, 5, 26, 7, 0, tzinfo=hcm_tz).isoformat(), datetime(2025, 5, 27, 11, 0, tzinfo=hcm_tz).isoformat()]),
         json.dumps({'Monday': ['07:00'], 'Friday': ['15:00']}), True),
        ('test2@ftu.edu.vn', 'Test User 2', bcrypt.hashpw('testpass2'.encode('utf-8'), bcrypt.gensalt()).decode('utf-8'), True, 'male', 23, 'Bình Thạnh',
         json.dumps(['badminton', 'football']), json.dumps({'badminton': 'intermediate', 'football': 'beginner'}),
         json.dumps({'same_gender': False, 'motivation': 'medium'}), 'Evening vibes for sports.',
         json.dumps([datetime(2025, 5, 26, 18, 0, tzinfo=hcm_tz).isoformat()]), json.dumps({'Monday': ['18:00']}), True)
    ]
    for user in test_users:
        c.execute('INSERT INTO users (ftu_email, name, password, verified, gender, age, location, sports, skill_levels, preferences, description, time_slots, recurring_slots, profile_complete) '
                  'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) '
                  'ON CONFLICT (ftu_email) DO NOTHING', user)
    c.execute('SELECT COUNT(*) FROM users')
    count = c.fetchone()['count']
    logging.info(f"Inserted test users, total users: {count}")
    
    conn.commit()
    conn.close()

def generate_recurring_time_slots(recurring_slots, start_date, end_date):
    if not recurring_slots:
        return []
    try:
        recurring = recurring_slots if isinstance(recurring_slots, dict) else json.loads(recurring_slots)
    except (json.JSONDecodeError, TypeError):
        logging.error(f"Invalid recurring_slots: {recurring_slots}")
        return []
    
    hcm_tz = pytz_timezone('Asia/Ho_Chi_Minh')
    time_slots = []
    current_date = start_date.astimezone(hcm_tz).replace(hour=0, minute=0, second=0, microsecond=0)
    end_date = end_date.astimezone(hcm_tz)
    while current_date <= end_date:
        day_name = current_date.strftime('%A')
        if day_name in recurring:
            for time_str in recurring.get(day_name, []):
                try:
                    hour, minute = map(int, time_str.split(':'))
                    slot_time = current_date.replace(hour=hour, minute=minute)
                    time_slots.append(slot_time.isoformat())
                except (ValueError, TypeError):
                    logging.error(f"Invalid time format in recurring_slots: {time_str}")
        current_date += timedelta(days=1)
    return sorted(time_slots)

def calculate_match_score(user1, user2):
    hcm_tz = pytz_timezone('Asia/Ho_Chi_Minh')
    try:
        sports1 = user1['sports'] if isinstance(user1['sports'], list) else json.loads(user1['sports']) if user1['sports'] else []
        sports2 = user2['sports'] if isinstance(user2['sports'], list) else json.loads(user2['sports']) if user2['sports'] else []
        time_slots1 = (user1['time_slots'] if isinstance(user1['time_slots'], list) else json.loads(user1['time_slots']) if user1['time_slots'] else []) + \
                      generate_recurring_time_slots(user1.get('recurring_slots'), datetime.now(hcm_tz), datetime.now(hcm_tz) + timedelta(weeks=2))
        time_slots2 = (user2['time_slots'] if isinstance(user2['time_slots'], list) else json.loads(user2['time_slots']) if user2['time_slots'] else []) + \
                      generate_recurring_time_slots(user2.get('recurring_slots'), datetime.now(hcm_tz), datetime.now(hcm_tz) + timedelta(weeks=2))
        skill_levels1 = user1['skill_levels'] if isinstance(user1['skill_levels'], dict) else json.loads(user1['skill_levels']) if user1['skill_levels'] else {}
        skill_levels2 = user2['skill_levels'] if isinstance(user2['skill_levels'], dict) else json.loads(user2['skill_levels']) if user2['skill_levels'] else {}
        preferences1 = user1['preferences'] if isinstance(user1['preferences'], dict) else json.loads(user1['preferences']) if user1['preferences'] else {'same_gender': False, 'motivation': 'medium'}
        preferences2 = user2['preferences'] if isinstance(user2['preferences'], dict) else json.loads(user2['preferences']) if user2['preferences'] else {'same_gender': False, 'motivation': 'medium'}
        gender1 = user1['gender'] or ''
        gender2 = user2['gender'] or ''
        desc1 = user1['description'] or ''
        desc2 = user2['description'] or ''
        location1 = user1['location'] or ''
        location2 = user2['location'] or ''
        age1 = user1['age'] or 0
        age2 = user2['age'] or 0
    except (TypeError, json.JSONDecodeError) as e:
        logging.error(f"JSON parsing error: {e}, user1_id={user1['id']}, user2_id={user2['id']}")
        return 0

    sports_score = len(set(sports1) & set(sports2)) / max(len(sports1), len(sports2), 1) * 0.35 if sports1 and sports2 else 0
    
    time_score = 0
    if time_slots1 and time_slots2:
        try:
            slots1 = {datetime.fromisoformat(slot.replace('Z', '+00:00')).astimezone(hcm_tz) for slot in time_slots1}
            slots2 = {datetime.fromisoformat(slot.replace('Z', '+00:00')).astimezone(hcm_tz) for slot in time_slots2}
            common_slots = slots1 & slots2
            time_score = len(common_slots) / max(len(slots1), len(slots2), 1) * 0.25
            logging.info(f"Time slots: user1={len(slots1)}, user2={len(slots2)}, common={len(common_slots)}")
        except Exception as e:
            logging.error(f"Time slot parsing error: {e}")
        
    skill_score = 0
    for sport in set(sports1) & set(sports2):
        level1 = skill_levels1.get(sport, 'beginner')
        level2 = skill_levels2.get(sport, 'beginner')
        levels = ['beginner', 'intermediate', 'advanced']
        diff = abs(levels.index(level1) - levels.index(level2))
        skill_score += (1 - diff / 2) / max(len(sports1), len(sports2), 1)
    skill_score *= 0.15
    
    pref_score = 0
    if preferences1['same_gender'] and gender1 == gender2:
        pref_score += 0.5
    elif not preferences1['same_gender']:
        pref_score += 0.5
    if preferences2['same_gender'] and gender1 == gender2:
        pref_score += 0.5
    elif not preferences2['same_gender']:
        pref_score += 0.5
    motivation_levels = {'low': 0, 'medium': 1, 'high': 2}
    motivation_diff = abs(motivation_levels[preferences1['motivation']] - motivation_levels[preferences2['motivation']])
    pref_score += (1 - motivation_diff / 2) * 0.5
    pref_score *= 0.1
    
    desc_score = 0
    if desc1 and desc2:
        vectorizer = TfidfVectorizer()
        vectors = vectorizer.fit_transform([desc1, desc2])
        desc_score = cosine_similarity(vectors[0:1], vectors[1:2])[0][0] * 0.1
    
    location_score = 1.0 if location1 and location2 and location1 == location2 else 0.5
    location_score *= 0.1
    
    age_diff = abs(age1 - age2)
    age_score = max(0, 1 - age_diff / 20) * 0.05

    total_score = sports_score + time_score + skill_score + pref_score + desc_score + location_score + age_score
    logging.info(f"Score components for user1_id={user1['id']}, user2_id={user2['id']}: "
                 f"sports={sports_score:.3f}, time={time_score:.3f}, skill={skill_score:.3f}, "
                 f"pref={pref_score:.3f}, desc={desc_score:.3f}, location={location_score:.3f}, "
                 f"age={age_score:.3f}, total={total_score:.3f}")
    return total_score

@app.route('/', methods=['GET', 'POST'])
def landing():
    if request.method == 'POST':
        email = request.form.get('email')
        website = request.form.get('website')
        if website:
            flash('Suspicious activity detected.', 'error')
            return redirect(url_for('landing'))
        if not email:
            flash('Email is required.', 'error')
            return redirect(url_for('landing'))
        if not email.endswith('@ftu.edu.vn'):
            flash('Please use an FTU email address.', 'error')
            return redirect(url_for('landing'))
        conn = get_db_connection()
        if not conn:
            flash('Database error. Please try again later.', 'error')
            return redirect(url_for('landing'))
        c = conn.cursor()
        c.execute('SELECT * FROM users WHERE ftu_email = %s', (email,))
        user = c.fetchone()
        conn.close()
        session['signup_email'] = email
        if user:
            return redirect(url_for('signin'))
        return redirect(url_for('signup'))
    return render_template('landing.html')

@app.route('/signin', methods=['GET', 'POST'])
def signin():
    email = session.get('signup_email', '')
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        website = request.form.get('website')
        recaptcha_response = request.form.get('g-recaptcha-response')
        if website:
            flash('Suspicious activity detected.', 'error')
            return redirect(url_for('signin'))
        if not verify_recaptcha(recaptcha_response):
            flash('reCAPTCHA verification failed.', 'error')
            return redirect(url_for('signin'))
        if not email or not password:
            flash('Email and password are required.', 'error')
            return redirect(url_for('signin'))
        if not email.endswith('@ftu.edu.vn'):
            flash('Please use an FTU email address.', 'error')
            return redirect(url_for('signin'))
        conn = get_db_connection()
        if not conn:
            flash('Database error. Please try again later.', 'error')
            return redirect(url_for('signin'))
        c = conn.cursor()
        c.execute('SELECT * FROM users WHERE ftu_email = %s', (email,))
        user = c.fetchone()
        if not user:
            flash('Email not registered. Please sign up.', 'error')
            conn.close()
            return redirect(url_for('signup'))
        if not bcrypt.checkpw(password.encode('utf-8'), user['password'].encode('utf-8')):
            flash('Invalid password.', 'error')
            conn.close()
            return redirect(url_for('signin'))
        if not user['verified']:
            flash('Please verify your email.', 'error')
            conn.close()
            return redirect(url_for('signin'))
        session['user_id'] = user['id']
        session.pop('signup_email', None)
        flash(f'Welcome back, {user["name"]}!', 'success')
        conn.close()
        return redirect(url_for('dashboard', user_id=user['id']))
    return render_template('signin.html', email=email)

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    email = session.get('signup_email', '')
    if request.method == 'POST':
        logging.info(f"Signup form data: {request.form}")
        email = request.form.get('email')
        password = request.form.get('password')
        name = request.form.get('name')
        website = request.form.get('website')
        recaptcha_response = request.form.get('g-recaptcha-response')
        if website:
            flash('Suspicious activity detected.', 'error')
            return redirect(url_for('signup'))
        if not verify_recaptcha(recaptcha_response):
            flash('reCAPTCHA verification failed.', 'error')
            return redirect(url_for('signup'))
        if not email or not password or not name:
            flash('Email, password, and name are required.', 'error')
            return redirect(url_for('signup'))
        if not email.endswith('@ftu.edu.vn'):
            flash('Please use an FTU email address.', 'error')
            return redirect(url_for('signup'))
        conn = get_db_connection()
        if not conn:
            flash('Database error. Please try again later.', 'error')
            return redirect(url_for('signup'))
        c = conn.cursor()
        c.execute('SELECT * FROM users WHERE ftu_email = %s', (email,))
        existing_user = c.fetchone()
        if existing_user:
            session.pop('signup_email', None)
            flash('Email already registered. Please sign in.', 'error')
            conn.close()
            return redirect(url_for('signin'))
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        import random
        token = f"{random.randint(0, 9999):04d}"  # Use random 4-digit code
        hcm_tz = pytz_timezone('Asia/Ho_Chi_Minh')
        created_at = datetime.now(hcm_tz).isoformat(timespec='microseconds')
        c.execute('DELETE FROM verification_tokens WHERE email = %s', (email,))  # Clean up old tokens
        c.execute('INSERT INTO verification_tokens (token, email, name, password, created_at) VALUES (%s, %s, %s, %s, %s)',
                  (token, email, name, hashed_password, created_at))
        conn.commit()
        logging.info(f"Sending verification email to {email} with token {token}")
        msg = Message('Xác Minh Tài Khoản Fi+Uni Của Bạn', sender=app.config['MAIL_USERNAME'], recipients=[email])
        msg.body = f"""Xin chào {name},

Cảm ơn bạn đã đăng ký Fi+Uni – nền tảng kết nối bạn với những người bạn tập luyện lý tưởng tại FTU! Để hoàn tất đăng ký, hãy sử dụng mã xác minh bên dưới:

Mã xác minh: {token}

Vui lòng nhập mã này trong vòng 1 giờ để kích hoạt tài khoản. Bắt đầu hành trình rèn luyện sức khỏe và kết nối cộng đồng ngay tại đây: {url_for('verify', email=email, _external=True)}

Nếu bạn không đăng ký, vui lòng bỏ qua email này.

Trân trọng,  
Đội ngũ Fi+Uni
-----------------
Liên hệ:
Nền tảng Fi+Uni
Trường Đại học Ngoại thương - Cơ sở II
Địa chỉ: 15 D5, Phường 25, Bình Thạnh, TP. Hồ Chí Minh"""
        try:
            mail.send(msg)
            flash('Verification code sent to your email.', 'success')
        except Exception as e:
            flash(f'Failed to send verification email: {str(e)}', 'error')
            logging.error(f"Failed to send verification email: {str(e)}")
        session.pop('signup_email', None)
        conn.close()
        return redirect(url_for('verify', email=email))
    return render_template('signup.html', email=email)

@app.route('/verify/<email>', methods=['GET', 'POST'])
def verify(email):
    if request.method == 'POST':
        code = request.form.get('code').strip()  # Strip whitespace
        website = request.form.get('website')
        if website:
            flash('Suspicious activity detected.', 'error')
            return redirect(url_for('verify', email=email))
        conn = get_db_connection()
        if not conn:
            flash('Database error. Please try again later.', 'error')
            return redirect(url_for('verify', email=email))
        c = conn.cursor()
        hcm_tz = pytz_timezone('Asia/Ho_Chi_Minh')
        one_hour_ago = datetime.now(hcm_tz) - timedelta(hours=1)
        c.execute('SELECT * FROM verification_tokens WHERE token = %s AND email = %s AND created_at > %s',
                  (code, email, one_hour_ago.isoformat(timespec='microseconds')))
        token = c.fetchone()
        if token:
            c.execute('INSERT INTO users (ftu_email, name, password, verified) VALUES (%s, %s, %s, %s) RETURNING id',
                      (token['email'], token['name'] or None, token['password'], True))
            user_id = c.fetchone()['id']
            c.execute('DELETE FROM verification_tokens WHERE token = %s', (code,))
            conn.commit()
            session['user_id'] = user_id
            flash('Verification successful! Complete your profile.', 'success')
            conn.close()
            return redirect(url_for('profile', user_id=user_id))
        else:
            flash('Invalid or expired verification code.', 'error')
        conn.close()
    return render_template('verify.html', email=email)

@app.route('/profile/<int:user_id>', methods=['GET', 'POST'])
def profile(user_id):
    if 'user_id' not in session or session['user_id'] != user_id:
        flash('Please sign in.', 'error')
        return redirect(url_for('signin'))
    conn = get_db_connection()
    if not conn:
        flash('Database error. Please try again later.', 'error')
        return redirect(url_for('signin'))
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE id = %s', (user_id,))
    user = c.fetchone()
    
    user_dict = dict(user)
    user_dict['sports'] = user['sports'] if isinstance(user['sports'], list) else json.loads(user['sports']) if user['sports'] else []
    user_dict['time_slots'] = user['time_slots'] if isinstance(user['time_slots'], list) else json.loads(user['time_slots']) if user['time_slots'] else []
    user_dict['recurring_slots'] = user['recurring_slots'] if isinstance(user['recurring_slots'], dict) else json.loads(user['recurring_slots']) if user['recurring_slots'] else {}
    user_dict['skill_levels'] = user['skill_levels'] if isinstance(user['skill_levels'], dict) else json.loads(user['skill_levels']) if user['skill_levels'] else {}
    user_dict['preferences'] = user['preferences'] if isinstance(user['preferences'], dict) else json.loads(user['preferences']) if user['preferences'] else {'same_gender': False, 'motivation': 'medium'}

    hcm_tz = pytz_timezone('Asia/Ho_Chi_Minh')
    today = datetime.now(hcm_tz)
    # Modified: Start available_dates from start of today to include all slots, even past ones
    start_date = today.replace(hour=0, minute=0, second=0, microsecond=0)
    available_dates = []
    for day_offset in range(14):
        date = start_date + timedelta(days=day_offset)
        date_str = date.strftime('%Y-%m-%d')
        day_name = date.strftime('%A')
        slots = []
        for hour in range(6, 22):
            slot_time = date.replace(hour=hour, minute=0, second=0, microsecond=0).isoformat()
            slots.append({'time': slot_time, 'display': f'{hour:02d}:00'})
        available_dates.append({'date': date_str, 'day': day_name, 'slots': slots})

    if request.method == 'POST':
        name = request.form.get('name')
        gender = request.form.get('gender')
        age = request.form.get('age')
        location = request.form.get('location')
        sports = request.form.getlist('sports')
        time_slots = request.form.getlist('time_slots')
        recurring_slots = request.form.getlist('recurring_slots')
        description = request.form.get('description')
        class_value = request.form.get('class')
        website = request.form.get('website')

        if website:
            flash('Suspicious activity detected.', 'error')
            return render_template('profile.html', user=user_dict, form_data=request.form, available_dates=available_dates)

        form_data = {
            'name': name or '',
            'gender': gender or '',
            'age': age or '',
            'location': location or '',
            'sports': sports or [],
            'description': description or '',
            'time_slots': time_slots or [],
            'recurring_slots': recurring_slots or [],
            'motivation': request.form.get('motivation', 'medium'),
            'same_gender': 'same_gender' in request.form,
            'class': class_value or ''
        }

        errors = []
        if not name:
            errors.append('Name is required.')
        if not gender:
            errors.append('Gender is required.')
        if not age or not age.isdigit() or int(age) < 16 or int(age) > 100:
            errors.append('Valid age (16-100) is required.')
        if not location:
            errors.append('Location is required.')
        if not sports:
            errors.append('Please select at least one sport.')
        if not description or len(description.strip()) < 10:
            errors.append('Description must be at least 10 characters.')
        if not class_value or not class_value.strip():
            errors.append('Class (Khóa lớp) is required.')

        cleaned_slots = []
        max_date = (today + timedelta(weeks=2)).replace(hour=23, minute=59, second=59)
        # Modified: Removed min_date to allow past slots; use start_date for range check
        for slot in time_slots:
            try:
                slot_date = datetime.fromisoformat(slot.replace('Z', '+00:00')).astimezone(hcm_tz)
                if slot_date > max_date:
                    errors.append(f'Time slot {slot} is beyond 2 weeks.')
                elif slot_date < start_date:
                    errors.append(f'Time slot {slot} is before today.')
                elif slot_date.hour < 6 or slot_date.hour >= 22:
                    errors.append(f'Time slot {slot} is outside 6 AM–10 PM.')
                else:
                    cleaned_slots.append(slot_date.isoformat())
            except (ValueError, TypeError):
                errors.append(f'Invalid time slot format: {slot}')

        cleaned_recurring = {}
        for slot in recurring_slots:
            try:
                day, time = slot.split('-')
                if day not in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']:
                    errors.append(f'Invalid day: {day}')
                    continue
                hour, minute = map(int, time.split(':'))
                if hour < 6 or hour >= 22:
                    errors.append(f'Recurring time {time} is outside 6 AM–10 PM.')
                    continue
                if day not in cleaned_recurring:
                    cleaned_recurring[day] = []
                if time not in cleaned_recurring[day]:
                    cleaned_recurring[day].append(time)
            except (ValueError, TypeError):
                errors.append(f'Invalid recurring slot format: {slot}')

        generated_slots = generate_recurring_time_slots(cleaned_recurring, start_date, max_date)
        all_slots = sorted(list(set(cleaned_slots + generated_slots)))

        if len(all_slots) < 2:
            errors.append('Please select at least two time slots (one-time or recurring).')

        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('profile.html', user=user_dict, form_data=form_data, available_dates=available_dates)

        skill_levels = {sport: request.form.get(f'skill_{sport}', 'beginner') for sport in sports}
        preferences = {
            'same_gender': 'same_gender' in request.form,
            'motivation': request.form.get('motivation', 'medium')
        }
        c.execute('''UPDATE users SET name = %s, gender = %s, age = %s, location = %s, sports = %s, skill_levels = %s, 
                    preferences = %s, description = %s, time_slots = %s, recurring_slots = %s, profile_complete = %s, class = %s WHERE id = %s''',
                  (name, gender, int(age), location, json.dumps(sports), json.dumps(skill_levels), 
                   json.dumps(preferences), description, json.dumps(all_slots), json.dumps(cleaned_recurring), True, class_value, user_id))
        conn.commit()
        flash('Profile updated successfully!', 'success')
        conn.close()
        return redirect(url_for('dashboard', user_id=user_id))
    conn.close()
    return render_template('profile.html', user=user_dict, form_data={}, available_dates=available_dates)

@app.route('/find_instructor/<int:user_id>')
def find_instructor(user_id):
    if 'user_id' not in session or session['user_id'] != user_id:
        flash('Please sign in.', 'error')
        return redirect(url_for('signin'))
    return render_template('find_instructor.html', user_id=user_id)

@app.route('/bookings/<int:user_id>')
def bookings(user_id):
    if 'user_id' not in session or session['user_id'] != user_id:
        flash('Please sign in.', 'error')
        return redirect(url_for('signin'))
    conn = get_db_connection()
    if not conn:
        flash('Database error. Please try again later.', 'error')
        return redirect(url_for('signin'))
    c = conn.cursor()
    
    logging.info(f"Registered Jinja2 filters: {list(app.jinja_env.filters.keys())}")
    
    c.execute('''SELECT r.*, u.name, u.gender, u.sports, u.description 
                 FROM requests r 
                 JOIN users u ON (r.sender_id = u.id AND r.receiver_id = %s) OR (r.receiver_id = u.id AND r.sender_id = %s)
                 WHERE r.status = %s''', 
              (user_id, user_id, 'pending'))
    pending_requests = c.fetchall()
    
    parsed_pending_requests = []
    for req in pending_requests:
        req_dict = dict(req)
        try:
            req_dict['sports'] = req['sports'] if isinstance(req['sports'], list) else json.loads(req['sports']) if req['sports'] else []
        except (json.JSONDecodeError, TypeError):
            req_dict['sports'] = [req['sports']] if req['sports'] else []
        parsed_pending_requests.append(req_dict)
    logging.info(f"Pending requests for user_id={user_id}: {len(parsed_pending_requests)}")
    
    c.execute('''SELECT m.*, u.name, u.gender, u.sports, r.selected_sport, r.selected_time_slot
                 FROM matches m 
                 JOIN users u ON (u.id = m.user2_id OR u.id = m.user1_id)
                 JOIN requests r ON ((r.sender_id = m.user1_id AND r.receiver_id = m.user2_id) OR (r.sender_id = m.user2_id AND r.receiver_id = m.user1_id))
                 WHERE (m.user1_id = %s OR m.user2_id = %s) AND m.status = %s AND u.id != %s AND r.status = %s''',
              (user_id, user_id, 'accepted', user_id, 'accepted'))
    confirmed_matches = c.fetchall()
    
    parsed_confirmed_matches = []
    for match in confirmed_matches:
        match_dict = dict(match)
        try:
            match_dict['sports'] = match['sports'] if isinstance(match['sports'], list) else json.loads(match['sports']) if match['sports'] else []
        except (json.JSONDecodeError, TypeError):
            req_dict['sports'] = [req['sports']] if req['sports'] else []
        match_dict['selected_sport'] = match['selected_sport'] or 'Not specified'
        match_dict['selected_time_slot'] = match['selected_time_slot'] or 'Not specified'
        parsed_confirmed_matches.append(match_dict)
    logging.info(f"Confirmed matches for user_id={user_id}: {len(parsed_confirmed_matches)}")
    
    conn.close()
    return render_template('bookings.html', user_id=user_id, pending_requests=parsed_pending_requests, confirmed_matches=parsed_confirmed_matches)

@app.route('/dashboard/<int:user_id>')
def dashboard(user_id):
    if 'user_id' not in session or session['user_id'] != user_id:
        flash('Please sign in.', 'error')
        return redirect(url_for('signin'))
    conn = get_db_connection()
    if not conn:
        flash('Database error. Please try again later.', 'error')
        return redirect(url_for('signin'))
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE id = %s', (user_id,))
    user = c.fetchone()
    if not user:
        flash('User not found.', 'error')
        conn.close()
        return redirect(url_for('signin'))
    
    c.execute('SELECT r.*, u.name, u.gender, u.sports, u.description FROM requests r JOIN users u ON r.sender_id = u.id WHERE r.receiver_id = %s AND r.status = %s', 
              (user_id, 'pending'))
    incoming_requests = c.fetchall()
    
    c.execute('SELECT r.*, u.name, u.gender, u.sports, u.description FROM requests r JOIN users u ON r.receiver_id = u.id WHERE r.sender_id = %s AND r.status = %s', 
              (user_id, 'pending'))
    outgoing_requests = c.fetchall()
    
    potential_matches = []
    liked_user_ids = []
    if user['profile_complete']:
        c.execute('SELECT receiver_id FROM likes WHERE sender_id = %s', (user_id,))
        liked_user_ids = [row['receiver_id'] for row in c.fetchall()]
        
        c.execute('SELECT * FROM users WHERE id != %s AND verified = %s AND profile_complete = %s', (user_id, True, True))
        other_users = c.fetchall()
        matches_with_scores = []
        for other in other_users:
            if other['id'] not in liked_user_ids:
                score = calculate_match_score(user, other)
                logging.info(f"Match score: user_id={user['id']}, other_id={other['id']}, score={score:.3f}")
                if score > 0.5:
                    matches_with_scores.append((other, score))
        matches_with_scores.sort(key=lambda x: x[1], reverse=True)
        potential_matches = matches_with_scores[:10]
    
    conn.close()
    return render_template('dashboard.html', user=user, incoming_requests=incoming_requests, outgoing_requests=outgoing_requests, 
                          potential_matches=potential_matches, liked_user_ids=liked_user_ids)

@app.route('/notify_like', methods=['POST'])
def notify_like():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Please sign in.'}), 401
    
    data = request.get_json()
    user_id = data.get('user_id')
    receiver_id = data.get('receiver_id')
    
    if not user_id or not receiver_id:
        return jsonify({'success': False, 'error': 'Invalid user or receiver ID.'}), 400
    
    if user_id != session['user_id']:
        return jsonify({'success': False, 'error': 'Unauthorized action.'}), 403
    
    conn = get_db_connection()
    if not conn:
        return jsonify({'success': False, 'error': 'Database error.'}), 500
    
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE id = %s', (user_id,))
    sender = c.fetchone()
    c.execute('SELECT * FROM users WHERE id = %s', (receiver_id,))
    receiver = c.fetchone()
    
    if not sender or not receiver:
        conn.close()
        return jsonify({'success': False, 'error': 'User not found.'}), 404
    
    c.execute('SELECT * FROM likes WHERE sender_id = %s AND receiver_id = %s', (user_id, receiver_id))
    if c.fetchone():
        conn.close()
        return jsonify({'success': False, 'error': 'You have already liked this user.'}), 400
    
    hcm_tz = pytz_timezone('Asia/Ho_Chi_Minh')
    c.execute('INSERT INTO likes (sender_id, receiver_id, timestamp) VALUES (%s, %s, %s) RETURNING id',
              (user_id, receiver_id, datetime.now(hcm_tz).isoformat()))
    like_id = c.fetchone()['id']
    conn.commit()
    
    msg = Message('Có Người Quan Tâm Đến Bạn Trên Fi+Uni!', sender=app.config['MAIL_USERNAME'], recipients=[receiver['ftu_email']])
    msg.body = f"""Xin chào {receiver['name']},

Tin vui đây! {sender['name']} vừa bày tỏ sự quan tâm đến bạn trên Fi+Uni! Họ muốn mời bạn cùng tập luyện và kết nối để có những buổi tập đầy năng lượng.

Hãy kiểm tra hồ sơ của họ và gửi yêu cầu tập luyện ngay hôm nay! Truy cập mục "Tìm Bạn Tập" để xem chi tiết:

Xem ngay: {url_for('dashboard', user_id=receiver['id'], _external=True)}

Cùng nhau xây dựng một cộng đồng khỏe mạnh hơn!

Trân trọng,  
Đội ngũ Fi+Uni 
----------------- 
Liên hệ:
Nền tảng Fi+Uni
Trường Đại học Ngoại thương - Cơ sở II
Địa chỉ: 15 D5, Phường 25, Bình Thạnh, TP. Hồ Chí Minh
You are receiving this email because you signed up for Fi+Uni or someone expressed interest in you on our platform"""
    try:
        mail.send(msg)
        logging.info(f"Like notification sent: like_id={like_id}, sender_id={user_id}, receiver_id={receiver_id}")
        conn.close()
        return jsonify({'success': True, 'message': 'Like sent successfully!'})
    except Exception as e:
        logging.error(f"Failed to send like notification: like_id={like_id}, error={str(e)}")
        conn.close()
        return jsonify({'success': False, 'error': f'Failed to send email: {str(e)}'}), 500

@app.route('/notify_chat', methods=['POST'])
def notify_chat():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Please sign in.'}), 401
    
    data = request.get_json()
    user_id = data.get('user_id')
    receiver_id = data.get('receiver_id')
    
    if not user_id or not receiver_id:
        return jsonify({'success': False, 'error': 'Invalid user or receiver ID.'}), 400
    
    if user_id != session['user_id']:
        return jsonify({'success': False, 'error': 'Unauthorized action.'}), 403
    
    conn = get_db_connection()
    if not conn:
        return jsonify({'success': False, 'error': 'Database error.'}), 500
    
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE id = %s', (user_id,))
    sender = c.fetchone()
    c.execute('SELECT * FROM users WHERE id = %s', (receiver_id,))
    receiver = c.fetchone()
    
    if not sender or not receiver:
        conn.close()
        return jsonify({'success': False, 'error': 'User not found.'}), 404
    
    msg = Message('Tin Nhắn Mới Trên Fi+Uni!', sender=app.config['MAIL_USERNAME'], recipients=[receiver['ftu_email']])
    msg.body = f"""Xin chào {receiver['name']},

Bạn vừa nhận được một tin nhắn mới từ {sender['name']} trên Fi+Uni! Đây là cơ hội để bắt đầu một cuộc trò chuyện và lên kế hoạch cho những buổi tập luyện cùng nhau.

Hãy kiểm tra hộp thư đến của bạn trên Fi+Uni để trả lời và kết nối:

Trò chuyện ngay: {url_for('chat', user_id=receiver['id'], other_user_id=user_id, _external=True)}

Cùng nhau xây dựng một cộng đồng năng động hơn!

Trân trọng,  
Đội ngũ Fi+Uni 
----------------- 
Liên hệ:
Nền tảng Fi+Uni
Trường Đại học Ngoại thương - Cơ sở II
Địa chỉ: 15 D5, Phường 25, Bình Thạnh, TP. Hồ Chí Minh
You are receiving this email because you signed up for Fi+Uni or someone initiated a chat with you on our platform"""
    try:
        mail.send(msg)
        logging.info(f"Chat notification sent: sender_id={user_id}, receiver_id={receiver_id}")
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        logging.error(f"Failed to send chat notification: {str(e)}")
        conn.close()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/find_match/<int:user_id>', defaults={'receiver_id': None}, methods=['GET', 'POST'])
@app.route('/find_match/<int:user_id>/<int:receiver_id>', methods=['GET', 'POST'])
def find_match(user_id, receiver_id):
    if 'user_id' not in session or session['user_id'] != user_id:
        flash('Please sign in.', 'error')
        return redirect(url_for('signin'))
    conn = get_db_connection()
    if not conn:
        flash('Database error. Please try again later.', 'error')
        return redirect(url_for('signin'))
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE id = %s AND verified = %s AND profile_complete = %s', (user_id, True, True))
    current_user = c.fetchone()
    if not current_user:
        flash('Please complete your profile first.', 'error')
        conn.close()
        return redirect(url_for('profile', user_id=user_id))
    
    c.execute('SELECT COUNT(*) FROM requests WHERE sender_id = %s AND status = %s', (user_id, 'pending'))
    pending_count = c.fetchone()['count']
    if pending_count >= 2 and (not receiver_id or not c.execute('SELECT 1 FROM requests WHERE sender_id = %s AND receiver_id = %s AND status = %s', (user_id, receiver_id, 'pending')).fetchone()):
        flash('You have reached the limit of 2 pending requests. Please wait for responses or recall a request.', 'error')
        conn.close()
        return redirect(url_for('dashboard', user_id=user_id))
    
    c.execute('SELECT * FROM matches WHERE (user1_id = %s OR user2_id = %s) AND status = %s', (user_id, user_id, 'pending'))
    if c.fetchone():
        flash('You have a pending match. Please confirm or reject it.', 'error')
        conn.close()
        return redirect(url_for('dashboard', user_id=user_id))
    
    if receiver_id:
        c.execute('SELECT * FROM users WHERE id = %s AND verified = %s AND profile_complete = %s', (receiver_id, True, True))
        best_match = c.fetchone()
        if not best_match:
            flash('Invalid user selected.', 'error')
            conn.close()
            return redirect(url_for('dashboard', user_id=user_id))
        c.execute('SELECT * FROM requests WHERE sender_id = %s AND receiver_id = %s AND status = %s', (user_id, receiver_id, 'pending'))
        if c.fetchone():
            flash('You already have a pending request to this user.', 'error')
            conn.close()
            return redirect(url_for('dashboard', user_id=user_id))
    else:
        c.execute('SELECT * FROM users WHERE id != %s AND verified = %s AND profile_complete = %s', (user_id, True, True))
        other_users = c.fetchall()
        matches_with_scores = []
        for other in other_users:
            score = calculate_match_score(current_user, other)
            if score > 0.6:
                matches_with_scores.append((other, score))
        matches_with_scores.sort(key=lambda x: x[1], reverse=True)
        if not matches_with_scores:
            flash('No suitable matches found. Try updating your profile.', 'error')
            conn.close()
            return redirect(url_for('dashboard', user_id=user_id))
        best_match = matches_with_scores[0][0]
    
    user_slots = current_user['time_slots'] if isinstance(current_user['time_slots'], list) else json.loads(current_user['time_slots']) if current_user['time_slots'] else []
    match_slots = best_match['time_slots'] if isinstance(best_match['time_slots'], list) else json.loads(best_match['time_slots']) if best_match['time_slots'] else []
    user_sports = current_user['sports'] if isinstance(current_user['sports'], list) else json.loads(current_user['sports']) if current_user['sports'] else []
    match_sports = best_match['sports'] if isinstance(best_match['sports'], list) else json.loads(best_match['sports']) if best_match['sports'] else []
    
    hcm_tz = pytz_timezone('Asia/Ho_Chi_Minh')
    shared_slots = sorted(list(set(user_slots) & set(match_slots)))
    shared_sports = sorted(list(set(user_sports) & set(match_sports)))
    
    if request.method == 'POST':
        selected_time_slot = request.form.get('time_slot')
        selected_sport = request.form.get('sport')
        other_sport = request.form.get('other_sport', '').strip()
        
        if not selected_time_slot:
            flash('Please select a time slot.', 'error')
            return render_template('select_workout.html', user_id=user_id, receiver_id=best_match['id'], 
                                 shared_slots=shared_slots, shared_sports=shared_sports, 
                                 current_user=current_user, best_match=best_match)
        
        if not selected_sport:
            flash('Please select or specify a sport.', 'error')
            return render_template('select_workout.html', user_id=user_id, receiver_id=best_match['id'], 
                                 shared_slots=shared_slots, shared_sports=shared_sports, 
                                 current_user=current_user, best_match=best_match)
        
        if selected_sport == 'Khác' and not other_sport:
            flash('Please specify the sport when selecting "Other".', 'error')
            return render_template('select_workout.html', user_id=user_id, receiver_id=best_match['id'], 
                                 shared_slots=shared_slots, shared_sports=shared_sports, 
                                 current_user=current_user, best_match=best_match)
        
        final_sport = other_sport if selected_sport == 'Khác' else selected_sport
        
        if selected_time_slot not in shared_slots and shared_slots:
            flash('Invalid time slot selected.', 'error')
            return render_template('select_workout.html', user_id=user_id, receiver_id=best_match['id'], 
                                 shared_slots=shared_slots, shared_sports=shared_sports, 
                                 current_user=current_user, best_match=best_match)
        
        c.execute('DELETE FROM requests WHERE status = %s AND timestamp < %s', 
                  ('pending', (datetime.now(hcm_tz) - timedelta(days=7)).isoformat()))
        conn.commit()
        
        c.execute('INSERT INTO requests (sender_id, receiver_id, status, timestamp, selected_time_slot, selected_sport) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id',
                  (user_id, best_match['id'], 'pending', datetime.now(hcm_tz).isoformat(), selected_time_slot, final_sport))
        request_id = c.fetchone()['id']
        conn.commit()
        logging.info(f"Inserted request: id={request_id}, sender_id={user_id}, receiver_id={best_match['id']}, time_slot={selected_time_slot}, sport={final_sport}")
        
        msg = Message('Yêu Cầu Tập Luyện Mới Từ Fi+Uni!', sender=app.config['MAIL_USERNAME'], recipients=[best_match['ftu_email']])
        vn_time = datetime.fromisoformat(selected_time_slot.replace('Z', '+00:00')).astimezone(hcm_tz)
        formatted_time_slot_vn = vn_time.strftime('%a, %d %b %y | %H:%M:%S (GMT+7)')
        msg.body = f"""Xin chào {best_match['name']},

Tin vui đây! {current_user['name']} muốn trở thành bạn tập luyện của bạn trên Fi+Uni! Đây là cơ hội để cùng nhau chinh phục mục tiêu sức khỏe và tận hưởng những buổi tập đầy năng lượng.

Mã yêu cầu: {request_id}
Thời gian đề xuất: {formatted_time_slot_vn}
Môn thể thao: {final_sport}

Hãy kiểm tra mục "Bookings" trên Fi+Uni để xác nhận hoặc từ chối yêu cầu này. Đừng bỏ lỡ cơ hội kết nối với một người bạn tập tuyệt vời!

Kiểm tra ngay: {url_for('bookings', user_id=best_match['id'], _external=True)}

Cùng nhau, chúng ta xây dựng một cộng đồng khỏe mạnh hơn!

Trân trọng,  
Đội ngũ Fi+Uni 
----------------- 
Liên hệ:
Nền tảng Fi+Uni
Trường Đại học Ngoại thương - Cơ sở II
Địa chỉ: 15 D5, Phường 25, Bình Thạnh, TP. Hồ Chí Minh
You are receiving this email because you signed up for Fi+Uni or a workout request was sent/accepted on our platform"""
        try:
            mail.send(msg)
            flash('Request sent successfully!', 'success')
        except Exception as e:
            flash(f'Failed to send request email: {str(e)}', 'error')
            logging.error(f"Failed to send request email: {str(e)}")
        conn.close()
        return redirect(url_for('dashboard', user_id=user_id))
    
    conn.close()
    return render_template('select_workout.html', user_id=user_id, receiver_id=best_match['id'], 
                          shared_slots=shared_slots, shared_sports=shared_sports, 
                          current_user=current_user, best_match=best_match)

@app.route('/request_action/<int:user_id>/<int:request_id>/<action>')
def request_action(user_id, request_id, action):
    if 'user_id' not in session or session['user_id'] != user_id:
        flash('Please sign in.', 'error')
        return redirect(url_for('signin'))
    if action not in ['accept', 'reject']:
        flash('Invalid action.', 'error')
        return redirect(url_for('dashboard', user_id=user_id))
    conn = get_db_connection()
    if not conn:
        flash('Database error. Please try again later.', 'error')
        return redirect(url_for('dashboard', user_id=user_id))
    c = conn.cursor()
    c.execute('SELECT * FROM requests WHERE id = %s AND receiver_id = %s AND status = %s', (request_id, user_id, 'pending'))
    req = c.fetchone()
    if not req:
        flash('Request not found or already processed.', 'error')
        conn.close()
        return redirect(url_for('dashboard', user_id=user_id))
    
    c.execute('SELECT * FROM users WHERE id = %s', (req['sender_id'],))
    sender = c.fetchone()
    c.execute('SELECT * FROM users WHERE id = %s', (user_id,))
    receiver = c.fetchone()
    
    hcm_tz = pytz_timezone('Asia/Ho_Chi_Minh')
    if action == 'accept':
        c.execute('UPDATE requests SET status = %s WHERE id = %s', ('accepted', request_id))
        c.execute('INSERT INTO matches (user1_id, user2_id, status, timestamp) VALUES (%s, %s, %s, %s)',
                  (req['sender_id'], user_id, 'accepted', datetime.now(hcm_tz).isoformat()))
        conn.commit()
        msg = Message('Yêu Cầu Tập Luyện Được Chấp Nhận Trên Fi+Uni!', sender=app.config['MAIL_USERNAME'], recipients=[sender['ftu_email']])
        formatted_time_slot = datetime.fromisoformat(req['selected_time_slot'].replace('Z', '+00:00')).astimezone(hcm_tz).strftime('%a, %d %b %y | %H:%M:%S')
        msg.body = f"""Xin chào {sender['name']},

Tuyệt vời! {receiver['name']} đã chấp nhận yêu cầu tập luyện của bạn trên Fi+Uni! Hãy sẵn sàng cho những buổi tập đầy năng lượng cùng nhau.

Mã yêu cầu: {request_id}
Thời gian: {formatted_time_slot}
Môn thể thao: {req['selected_sport']}

Hãy kiểm tra mục "Bookings" để xem chi tiết và bắt đầu liên lạc với bạn tập của bạn:

Kiểm tra ngay: {url_for('bookings', user_id=sender['id'], _external=True)}

Cùng nhau xây dựng một cộng đồng khỏe mạnh hơn!

Trân trọng,  
Đội ngũ Fi+Uni 
----------------- 
Liên hệ:
Nền tảng Fi+Uni
Trường Đại học Ngoại thương - Cơ sở II
Địa chỉ: 15 D5, Phường 25, Bình Thạnh, TP. Hồ Chí Minh
You are receiving this email because you signed up for Fi+Uni or a workout request was sent/accepted on our platform"""
        try:
            mail.send(msg)
            flash('Request accepted! You can now chat with your match.', 'success')
        except Exception as e:
            flash(f'Failed to send acceptance email: {str(e)}', 'error')
            logging.error(f"Failed to send acceptance email: {str(e)}")
    else:
        c.execute('UPDATE requests SET status = %s WHERE id = %s', ('rejected', request_id))
        conn.commit()
        flash('Request rejected.', 'success')
    
    conn.close()
    return redirect(url_for('dashboard', user_id=user_id))

@app.route('/recall_request/<int:user_id>/<int:request_id>')
def recall_request(user_id, request_id):
    if 'user_id' not in session or session['user_id'] != user_id:
        flash('Please sign in.', 'error')
        return redirect(url_for('signin'))
    conn = get_db_connection()
    if not conn:
        flash('Database error. Please try again later.', 'error')
        return redirect(url_for('dashboard', user_id=user_id))
    c = conn.cursor()
    c.execute('SELECT * FROM requests WHERE id = %s AND sender_id = %s AND status = %s', (request_id, user_id, 'pending'))
    req = c.fetchone()
    if not req:
        flash('Request not found or cannot be recalled.', 'error')
        conn.close()
        return redirect(url_for('dashboard', user_id=user_id))
    
    c.execute('DELETE FROM requests WHERE id = %s', (request_id,))
    conn.commit()
    flash('Request recalled successfully.', 'success')
    conn.close()
    return redirect(url_for('dashboard', user_id=user_id))

@app.route('/chat/<int:user_id>/<int:other_user_id>', methods=['GET', 'POST'])
def chat(user_id, other_user_id):
    if 'user_id' not in session or session['user_id'] != user_id:
        flash('Please sign in.', 'error')
        return redirect(url_for('signin'))
    conn = get_db_connection()
    if not conn:
        flash('Database error. Please try again later.', 'error')
        return redirect(url_for('dashboard', user_id=user_id))
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE id = %s', (user_id,))
    user = c.fetchone()
    c.execute('SELECT * FROM users WHERE id = %s', (other_user_id,))
    other_user = c.fetchone()
    if not user or not other_user:
        flash('User not found.', 'error')
        conn.close()
        return redirect(url_for('dashboard', user_id=user_id))
    
    c.execute('SELECT COUNT(*) FROM messages WHERE (sender_id = %s AND receiver_id = %s) OR (sender_id = %s AND receiver_id = %s)',
              (user_id, other_user_id, other_user_id, user_id))
    message_count = c.fetchone()['count']
    is_new_chat = message_count == 0
    
    c.execute('SELECT * FROM messages WHERE (sender_id = %s AND receiver_id = %s) OR (sender_id = %s AND receiver_id = %s) ORDER BY timestamp',
              (user_id, other_user_id, other_user_id, user_id))
    messages = c.fetchall()
    
    if request.method == 'POST':
        content = request.form.get('content').strip()
        website = request.form.get('website')
        if website:
            flash('Suspicious activity detected.', 'error')
            conn.close()
            return redirect(url_for('chat', user_id=user_id, other_user_id=other_user_id))
        if not content:
            flash('Message cannot be empty.', 'error')
            conn.close()
            return redirect(url_for('chat', user_id=user_id, other_user_id=other_user_id))
        
        hcm_tz = pytz_timezone('Asia/Ho_Chi_Minh')
        c.execute('INSERT INTO messages (sender_id, receiver_id, content, timestamp) VALUES (%s, %s, %s, %s)',
                  (user_id, other_user_id, content, datetime.now(hcm_tz).isoformat()))
        conn.commit()
        
        if is_new_chat:
            msg = Message('Tin Nhắn Mới Trên Fi+Uni!', sender=app.config['MAIL_USERNAME'], recipients=[other_user['ftu_email']])
            msg.body = f"""Xin chào {other_user['name']},

Bạn vừa nhận được một tin nhắn mới từ {user['name']} trên Fi+Uni! Đây là cơ hội để bắt đầu một cuộc trò chuyện và lên kế hoạch cho những buổi tập luyện cùng nhau.

Hãy kiểm tra hộp thư đến của bạn trên Fi+Uni để trả lời và kết nối:

Trò chuyện ngay: {url_for('chat', user_id=other_user['id'], other_user_id=user_id, _external=True)}

Cùng nhau xây dựng một cộng đồng năng động hơn!

Trân trọng,  
Đội ngũ Fi+Uni 
----------------- 
Liên hệ:
Nền tảng Fi+Uni
Trường Đại học Ngoại thương - Cơ sở II
Địa chỉ: 15 D5, Phường 25, Bình Thạnh, TP. Hồ Chí Minh
You are receiving this email because you signed up for Fi+Uni or someone initiated a chat with you on our platform"""
            try:
                mail.send(msg)
                logging.info(f"Chat notification sent: sender_id={user_id}, receiver_id={other_user_id}")
            except Exception as e:
                logging.error(f"Failed to send chat notification: {str(e)}")
        
        conn.close()
        flash('Message sent!', 'success')
        return redirect(url_for('chat', user_id=user_id, other_user_id=other_user_id))
    
    conn.close()
    return render_template('chat.html', user=user, other_user=other_user, messages=messages)

@app.route('/send_message/<int:user_id>/<int:other_user_id>', methods=['POST'])
def send_message(user_id, other_user_id):
    if 'user_id' not in session or session['user_id'] != user_id:
        flash('Please sign in.', 'error')
        return redirect(url_for('signin'))
    conn = get_db_connection()
    if not conn:
        flash('Database error. Please try again later.', 'error')
        return redirect(url_for('chat', user_id=user_id, other_user_id=other_user_id))
    c = conn.cursor()
    
    content = request.form.get('content').strip()
    website = request.form.get('website')
    if website:
        flash('Suspicious activity detected.', 'error')
        conn.close()
        return redirect(url_for('chat', user_id=user_id, other_user_id=other_user_id))
    if not content:
        flash('Message cannot be empty.', 'error')
        conn.close()
        return redirect(url_for('chat', user_id=user_id, other_user_id=other_user_id))
    
    c.execute('SELECT COUNT(*) FROM messages WHERE (sender_id = %s AND receiver_id = %s) OR (sender_id = %s AND receiver_id = %s)',
              (user_id, other_user_id, other_user_id, user_id))
    message_count = c.fetchone()['count']
    is_new_chat = message_count == 0
    
    hcm_tz = pytz_timezone('Asia/Ho_Chi_Minh')
    c.execute('INSERT INTO messages (sender_id, receiver_id, content, timestamp) VALUES (%s, %s, %s, %s)',
              (user_id, other_user_id, content, datetime.now(hcm_tz).isoformat()))
    conn.commit()
    
    if is_new_chat:
        c.execute('SELECT * FROM users WHERE id = %s', (user_id,))
        sender = c.fetchone()
        c.execute('SELECT * FROM users WHERE id = %s', (other_user_id,))
        receiver = c.fetchone()
        
        if sender and receiver:
            msg = Message('Tin Nhắn Mới Trên Fi+Uni!', sender=app.config['MAIL_USERNAME'], recipients=[receiver['ftu_email']])
            msg.body = f"""Xin chào {receiver['name']},

Bạn vừa nhận được một tin nhắn mới từ {sender['name']} trên Fi+Uni! Đây là cơ hội để bắt đầu một cuộc trò chuyện và lên kế hoạch cho những buổi tập luyện cùng nhau.

Hãy kiểm tra hộp thư đến của bạn trên Fi+Uni để trả lời và kết nối:

Trò chuyện ngay: {url_for('chat', user_id=receiver['id'], other_user_id=user_id, _external=True)}

Cùng nhau xây dựng một cộng đồng năng động hơn!

Trân trọng,  
Đội ngũ Fi+Uni 
----------------- 
Liên hệ:
Nền tảng Fi+Uni
Trường Đại học Ngoại thương - Cơ sở II
Địa chỉ: 15 D5, Phường 25, Bình Thạnh, TP. Hồ Chí Minh
You are receiving this email because you signed up for Fi+Uni or someone initiated a chat with you on our platform"""
            try:
                mail.send(msg)
                logging.info(f"Chat notification sent: sender_id={user_id}, receiver_id={other_user_id}")
            except Exception as e:
                logging.error(f"Failed to send chat notification: {str(e)}")
    
    conn.close()
    flash('Message sent!', 'success')
    return redirect(url_for('chat', user_id=user_id, other_user_id=other_user_id))

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('signup_email', None)
    flash('Logged out successfully.', 'success')
    return redirect(url_for('landing'))

@app.route('/terms')
def terms():
    return render_template('terms.html')

@app.route('/privacy')
def privacy():
    return render_template('privacy.html')

@app.route('/ads.txt')
def ads_txt():
    return send_from_directory('.', 'ads.txt')

@app.route('/sitemap.xml')
def sitemap():
    return send_from_directory('.', 'sitemap.xml')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)