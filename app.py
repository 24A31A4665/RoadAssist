from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from supabase import create_client
import smtplib
from email.mime.text import MIMEText
import random, hashlib
from datetime import datetime, timedelta, timezone
from functools import wraps

app = Flask(__name__)
app.secret_key = 'roadassist-secret-2025'

SUPABASE_URL   = "https://kjyactgzdjqgkydapntj.supabase.co"
SUPABASE_KEY   = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImtqeWFjdGd6ZGpxZ2t5ZGFwbnRqIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3NDcwOTAxNCwiZXhwIjoyMDkwMjg1MDE0fQ.bBGIFf4RMPAlO14YnpmDDiRxoVvBA4IwUcvA9pbjBYc"
GMAIL          = "d35001122@gmail.com"
GMAIL_PASSWORD = "jizq ouay ttev iyeq"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def send_otp_email(email, otp):
    body = f"""Hi,

Your Road Assist verification code is: {otp}

Valid for 10 minutes. Do not share this with anyone.

— Road Assist Team"""
    msg = MIMEText(body)
    msg['Subject'] = "Your Road Assist OTP"
    msg['From']    = GMAIL
    msg['To']      = email
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(GMAIL, GMAIL_PASSWORD)
        smtp.sendmail(GMAIL, email, msg.as_string())


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated


def role_required(role):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('index'))
            if session.get('user', {}).get('role') != role:
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return decorated
    return decorator


# ─────────────────────────────────────────
# PAGE ROUTES
# ─────────────────────────────────────────

@app.route('/')
def index():
    if 'user_id' in session:
        role = session.get('user', {}).get('role')
        if role == 'mechanic':
            return redirect(url_for('mechanic_dashboard'))
        elif role == 'admin':
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('user_dashboard'))
    return render_template('login.html')


@app.route('/dashboard')
@login_required
def user_dashboard():
    return render_template('dashboard.html', user=session.get('user'))


# BUG FIX 3 — role_required('mechanic') added so normal users cannot access
@app.route('/mechanic')
@role_required('mechanic')
def mechanic_dashboard():
    return render_template('mechanic_dashboard.html', user=session.get('user'))


@app.route('/request-service')
@login_required
def request_service():
    return render_template('request_service.html', user=session.get('user'))


@app.route('/track/<request_id>')
@login_required
def track(request_id):
    return render_template('track.html', user=session.get('user'), request_id=request_id)


@app.route('/admin')
@role_required('admin')
def admin_dashboard():
    return render_template('admin.html', user=session.get('user'))


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


# ─────────────────────────────────────────
# AUTH — SIGNUP
# ─────────────────────────────────────────

@app.route('/signup', methods=['POST'])
def signup():
    data      = request.json
    full_name = data.get('full_name', '').strip()
    email     = data.get('email', '').strip().lower()
    phone     = data.get('phone', '').strip()
    password  = data.get('password', '')
    role      = data.get('role', 'user')

    if not all([full_name, email, phone, password]):
        return jsonify({'error': 'All fields are required'}), 400
    if len(password) < 8:
        return jsonify({'error': 'Password must be at least 8 characters'}), 400

    if supabase.table('users').select('id').eq('email', email).execute().data:
        return jsonify({'error': 'Email already registered. Please login.'}), 400
    if supabase.table('users').select('id').eq('phone', phone).execute().data:
        return jsonify({'error': 'Phone number already registered.'}), 400

    # Insert user and capture result
    result = supabase.table('users').insert({
        'full_name':     full_name,
        'email':         email,
        'phone':         phone,
        'password_hash': hash_password(password),
        'role':          role,
        'is_verified':   False
    }).execute()

    # BUG FIX 1 — auto create mechanics table row when role is mechanic
    if role == 'mechanic' and result.data:
        user_id = result.data[0]['id']
        supabase.table('mechanics').insert({
            'user_id':       user_id,
            'is_available':  False,
            'rating':        0.0,
            'service_types': ['tyre', 'battery', 'fuel', 'mechanic', 'towing', 'accident']
        }).execute()

    # BUG FIX 2 — use timezone-aware datetime
    otp        = str(random.randint(100000, 999999))
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()

    supabase.table('otp_verifications').insert({
        'email':      email,
        'otp_code':   otp,
        'is_used':    False,
        'expires_at': expires_at
    }).execute()

    try:
        send_otp_email(email, otp)
    except Exception as e:
        return jsonify({'error': f'Failed to send OTP: {str(e)}'}), 500

    return jsonify({'message': 'OTP sent to your email.'}), 200


# ─────────────────────────────────────────
# AUTH — RESEND OTP
# ─────────────────────────────────────────

@app.route('/resend-otp', methods=['POST'])
def resend_otp():
    email = request.json.get('email', '').strip().lower()
    if not email:
        return jsonify({'error': 'Email is required'}), 400
    if not supabase.table('users').select('id').eq('email', email).execute().data:
        return jsonify({'error': 'Email not found'}), 404

    supabase.table('otp_verifications').update({'is_used': True})\
        .eq('email', email).eq('is_used', False).execute()

    otp        = str(random.randint(100000, 999999))
    # BUG FIX 2 — timezone-aware datetime
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()

    supabase.table('otp_verifications').insert({
        'email':      email,
        'otp_code':   otp,
        'is_used':    False,
        'expires_at': expires_at
    }).execute()

    try:
        send_otp_email(email, otp)
    except Exception as e:
        return jsonify({'error': f'Failed to send OTP: {str(e)}'}), 500

    return jsonify({'message': 'New OTP sent.'}), 200


# ─────────────────────────────────────────
# AUTH — VERIFY OTP
# ─────────────────────────────────────────

@app.route('/verify-otp', methods=['POST'])
def verify_otp():
    data  = request.json
    email = data.get('email', '').strip().lower()
    otp   = data.get('otp', '').strip()

    if not email or not otp:
        return jsonify({'error': 'Email and OTP are required'}), 400

    # Fetch all unused OTPs for this email — no otp filter yet
    result = supabase.table('otp_verifications').select('*')\
        .eq('email', email)\
        .eq('is_used', False)\
        .order('created_at', desc=True)\
        .limit(1)\
        .execute()

    if not result.data:
        return jsonify({'error': 'No active OTP found. Please request a new one.'}), 400

    record = result.data[0]

    # Compare OTP as string on both sides — fixes integer vs string mismatch
    if str(record['otp_code']).strip() != str(otp).strip():
        return jsonify({'error': 'Invalid OTP. Please check and try again.'}), 400

    # Check expiry safely
    try:
        expires_str = record['expires_at'].replace('Z', '+00:00')
        if '+' not in expires_str and 'T' in expires_str:
            expires_str = expires_str + '+00:00'
        expires_at = datetime.fromisoformat(expires_str)
        if datetime.now(timezone.utc) > expires_at:
            return jsonify({'error': 'OTP expired. Please request a new one.'}), 400
    except Exception as e:
        print('Expiry parse error:', e)

    # Mark OTP used
    supabase.table('otp_verifications')\
        .update({'is_used': True})\
        .eq('id', record['id'])\
        .execute()

    # Mark user verified
    supabase.table('users')\
        .update({'is_verified': True})\
        .eq('email', email)\
        .execute()

    return jsonify({'message': 'Email verified! You can now log in.'}), 200

# ─────────────────────────────────────────
# AUTH — LOGIN
# ─────────────────────────────────────────

@app.route('/login', methods=['POST'])
def login():
    data     = request.json
    email    = data.get('email', '').strip().lower()
    password = data.get('password', '')

    if not email or not password:
        return jsonify({'error': 'Email and password are required'}), 400

    result = supabase.table('users').select('*')\
        .eq('email', email).eq('password_hash', hash_password(password)).execute()

    if not result.data:
        return jsonify({'error': 'Invalid email or password'}), 401

    user = result.data[0]
    if not user['is_verified']:
        return jsonify({'error': 'Email not verified.', 'needs_verify': True, 'email': email}), 403

    session['user_id'] = user['id']
    session['user']    = {
        'id':    user['id'],
        'name':  user['full_name'],
        'email': user['email'],
        'role':  user['role']
    }

    redirect_url = '/mechanic' if user['role'] == 'mechanic' else ('/admin' if user['role'] == 'admin' else '/dashboard')
    return jsonify({'message': 'Login successful', 'user': session['user'], 'redirect': redirect_url}), 200


# ─────────────────────────────────────────
# SERVICE REQUESTS
# ─────────────────────────────────────────

@app.route('/api/request', methods=['POST'])
@login_required
def create_request():
    data         = request.json
    service_type = data.get('service_type')
    user_lat     = data.get('lat')
    user_lng     = data.get('lng')
    notes        = data.get('notes', '')

    if not all([service_type, user_lat, user_lng]):
        return jsonify({'error': 'Service type and location are required'}), 400

    result = supabase.table('service_requests').insert({
        'user_id':      session['user_id'],
        'service_type': service_type,
        'user_lat':     user_lat,
        'user_lng':     user_lng,
        'notes':        notes,
        'status':       'pending'
    }).execute()

    return jsonify({'message': 'Request created', 'request': result.data[0]}), 201


@app.route('/api/requests/user', methods=['GET'])
@login_required
def get_user_requests():
    result = supabase.table('service_requests').select('*')\
        .eq('user_id', session['user_id']).order('created_at', desc=True).execute()
    return jsonify(result.data), 200


@app.route('/api/requests/pending', methods=['GET'])
@login_required
def get_pending_requests():
    result = supabase.table('service_requests').select('*, users(full_name, phone)')\
        .eq('status', 'pending').order('created_at', desc=True).execute()
    return jsonify(result.data), 200


@app.route('/api/request/<request_id>/accept', methods=['POST'])
@login_required
def accept_request(request_id):
    mechanic = supabase.table('mechanics').select('id')\
        .eq('user_id', session['user_id']).execute()

    if not mechanic.data:
        return jsonify({'error': 'Mechanic profile not found. Please contact support.'}), 404

    supabase.table('service_requests').update({
        'mechanic_id': mechanic.data[0]['id'],
        'status':      'accepted'
    }).eq('id', request_id).execute()

    return jsonify({'message': 'Request accepted'}), 200


@app.route('/api/request/<request_id>/complete', methods=['POST'])
@login_required
def complete_request(request_id):
    supabase.table('service_requests').update({'status': 'completed'})\
        .eq('id', request_id).execute()
    return jsonify({'message': 'Request marked as completed'}), 200


@app.route('/api/request/<request_id>/cancel', methods=['POST'])
@login_required
def cancel_request(request_id):
    supabase.table('service_requests').update({'status': 'cancelled'})\
        .eq('id', request_id).execute()
    return jsonify({'message': 'Request cancelled'}), 200


@app.route('/api/request/<request_id>', methods=['GET'])
@login_required
def get_request(request_id):
    result = supabase.table('service_requests')\
        .select('*, users(full_name, phone), mechanics(user_id, rating)')\
        .eq('id', request_id).execute()
    if not result.data:
        return jsonify({'error': 'Request not found'}), 404
    return jsonify(result.data[0]), 200


# ─────────────────────────────────────────
# MECHANIC LOCATION UPDATE
# ─────────────────────────────────────────

@app.route('/api/mechanic/location', methods=['POST'])
@login_required
def update_mechanic_location():
    data = request.json
    lat  = data.get('lat')
    lng  = data.get('lng')

    supabase.table('mechanics').update({'latitude': lat, 'longitude': lng})\
        .eq('user_id', session['user_id']).execute()

    return jsonify({'message': 'Location updated'}), 200


@app.route('/api/mechanic/availability', methods=['POST'])
@login_required
def update_availability():
    is_available = request.json.get('is_available', True)
    supabase.table('mechanics').update({'is_available': is_available})\
        .eq('user_id', session['user_id']).execute()
    return jsonify({'message': 'Availability updated'}), 200


# Get mechanic live location + name by mechanic table id (used in track.html)
@app.route('/api/mechanic/location-by-id/<mechanic_id>', methods=['GET'])
@login_required
def get_mechanic_location(mechanic_id):
    result = supabase.table('mechanics')\
        .select('latitude, longitude, users(full_name, phone)')\
        .eq('id', mechanic_id)\
        .execute()

    if not result.data:
        return jsonify({'error': 'Mechanic not found'}), 404

    row  = result.data[0]
    user = row.get('users', {}) or {}

    return jsonify({
        'latitude':  row.get('latitude'),
        'longitude': row.get('longitude'),
        'full_name': user.get('full_name', 'Mechanic'),
        'phone':     user.get('phone', '')
    }), 200


@app.route('/api/mechanic/requests', methods=['GET'])
@login_required
def mechanic_requests():
    mechanic = supabase.table('mechanics').select('id')\
        .eq('user_id', session['user_id']).execute()
    if not mechanic.data:
        return jsonify([]), 200

    result = supabase.table('service_requests')\
        .select('*, users(full_name, phone)')\
        .eq('mechanic_id', mechanic.data[0]['id'])\
        .order('created_at', desc=True).execute()
    return jsonify(result.data), 200


# ─────────────────────────────────────────
# PAYMENTS
# ─────────────────────────────────────────

@app.route('/api/payment', methods=['POST'])
@login_required
def create_payment():
    data       = request.json
    request_id = data.get('request_id')
    amount     = data.get('amount')
    method     = data.get('method', 'upi')

    if not all([request_id, amount]):
        return jsonify({'error': 'Request ID and amount are required'}), 400

    result = supabase.table('payments').insert({
        'request_id': request_id,
        'user_id':    session['user_id'],
        'amount':     amount,
        'method':     method,
        'status':     'paid',
        'paid_at':    datetime.now(timezone.utc).isoformat()
    }).execute()

    return jsonify({'message': 'Payment recorded', 'payment': result.data[0]}), 201


# ─────────────────────────────────────────
# RATINGS
# ─────────────────────────────────────────

@app.route('/api/rating', methods=['POST'])
@login_required
def submit_rating():
    data       = request.json
    request_id = data.get('request_id')
    to_user_id = data.get('to_user_id')
    stars      = data.get('stars')
    comment    = data.get('comment', '')

    if not all([request_id, to_user_id, stars]):
        return jsonify({'error': 'All rating fields required'}), 400

    supabase.table('ratings').insert({
        'request_id':   request_id,
        'from_user_id': session['user_id'],
        'to_user_id':   to_user_id,
        'stars':        stars,
        'comment':      comment
    }).execute()

    # Recalculate and update mechanic average rating
    ratings = supabase.table('ratings').select('stars')\
        .eq('to_user_id', to_user_id).execute()
    if ratings.data:
        avg = sum(r['stars'] for r in ratings.data) / len(ratings.data)
        supabase.table('mechanics').update({'rating': round(avg, 1)})\
            .eq('user_id', to_user_id).execute()

    return jsonify({'message': 'Rating submitted'}), 201


# ─────────────────────────────────────────
# ADMIN
# ─────────────────────────────────────────

@app.route('/api/admin/stats', methods=['GET'])
@role_required('admin')
def admin_stats():
    users     = supabase.table('users').select('id', count='exact').execute()
    mechanics = supabase.table('mechanics').select('id', count='exact').execute()
    requests  = supabase.table('service_requests').select('id', count='exact').execute()
    payments  = supabase.table('payments').select('amount').execute()

    total_revenue = sum(p['amount'] for p in payments.data) if payments.data else 0

    return jsonify({
        'total_users':     users.count,
        'total_mechanics': mechanics.count,
        'total_requests':  requests.count,
        'total_revenue':   total_revenue
    }), 200


@app.route('/api/admin/requests', methods=['GET'])
@role_required('admin')
def admin_all_requests():
    result = supabase.table('service_requests')\
        .select('*, users(full_name, phone)')\
        .order('created_at', desc=True).limit(100).execute()
    return jsonify(result.data), 200


@app.route('/api/admin/users', methods=['GET'])
@role_required('admin')
def admin_all_users():
    result = supabase.table('users')\
        .select('id, full_name, email, phone, role, is_verified, created_at')\
        .order('created_at', desc=True).execute()
    return jsonify(result.data), 200


# ─────────────────────────────────────────
# RUN
# ─────────────────────────────────────────

if __name__ == '__main__':
    app.run(debug=True)
