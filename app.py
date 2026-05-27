import os
from flask import Flask, request, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, join_room
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev_key')

# Fix Render DB URL
db_url = os.environ.get('DATABASE_URL')
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url or 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# ================= MODELS =================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

class Email(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender = db.Column(db.String(80), nullable=False)
    recipient = db.Column(db.String(80), nullable=False)
    subject = db.Column(db.String(200))
    body = db.Column(db.Text)
    is_read = db.Column(db.Boolean, default=False)

# ================= AUTH APIs =================

@app.route('/api/signup', methods=['POST'])
def signup():
    data = request.json
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({'error': 'Missing fields'}), 400

    if User.query.filter_by(username=username).first():
        return jsonify({'error': 'User exists'}), 400

    hashed_pw = generate_password_hash(password)

    user = User(username=username, password=hashed_pw)
    db.session.add(user)
    db.session.commit()

    session['username'] = username
    return jsonify({'message': 'Signup success'})

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    user = User.query.filter_by(username=data.get('username')).first()

    if user and check_password_hash(user.password, data.get('password')):
        session['username'] = user.username
        return jsonify({'message': 'Login success'})

    return jsonify({'error': 'Invalid credentials'}), 401

@app.route('/api/logout', methods=['POST'])
def logout():
    session.pop('username', None)
    return jsonify({'message': 'Logged out'})

# ================= EMAIL APIs =================

@app.route('/api/emails', methods=['GET'])
def get_emails():
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    folder = request.args.get('folder', 'inbox')

    if folder == 'sent':
        emails = Email.query.filter_by(sender=session['username']).all()
    else:
        emails = Email.query.filter_by(recipient=session['username']).all()

    return jsonify([
        {
            'id': e.id,
            'sender': e.sender,
            'recipient': e.recipient,
            'subject': e.subject,
            'body': e.body,
            'is_read': e.is_read,
            'timestamp': str(e.id)  # simple fallback
        } for e in emails
    ])

@app.route('/api/emails', methods=['POST'])
def send_email():
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.json

    if not User.query.filter_by(username=data['recipient']).first():
        return jsonify({'error': 'Recipient not found'}), 400

    email = Email(
        sender=session['username'],
        recipient=data['recipient'],
        subject=data['subject'],
        body=data['body']
    )

    db.session.add(email)
    db.session.commit()

    # 🔥 Send only to recipient room
    socketio.emit('new_email', {
        'sender': email.sender,
        'subject': email.subject,
        'body': email.body
    }, room=email.recipient)

    return jsonify({'message': 'Sent'})

@app.route('/api/emails/<int:id>', methods=['DELETE'])
def delete_email(id):
    email = Email.query.get(id)
    if email:
        db.session.delete(email)
        db.session.commit()
    return jsonify({'message': 'Deleted'})

@app.route('/api/emails/<int:id>/read', methods=['PUT'])
def mark_read(id):
    email = Email.query.get(id)
    if email:
        email.is_read = True
        db.session.commit()
    return jsonify({'message': 'Updated'})

# ================= SOCKET.IO =================

@socketio.on('connect')
def handle_connect():
    if 'username' in session:
        join_room(session['username'])  # user-specific room

# ================= RUN =================

if __name__ == '__main__':
    with app.app_context():
        db.create_all()

    socketio.run(app)
