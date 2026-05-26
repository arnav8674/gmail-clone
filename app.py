import os
from flask import Flask, render_template, request, redirect, url_name, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit

app = Flask(__name__)

# 1. SECURE SECRET KEY: Uses Render's environment variable, falls back to dev key locally
app.secret_key = os.environ.get('SECRET_KEY', 'dev_fallback_secret_key_123')

# 2. DYNAMIC DATABASE CHANGER: Fixes Render's PostgreSQL "postgres://" vs "postgresql://" string quirk
env_db = os.environ.get('DATABASE_URL')
if env_db and env_db.startswith("postgres://"):
    env_db = env_db.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = env_db or 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# --- DATABASE MODELS ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)

class Email(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender = db.Column(db.String(80), nullable=False)
    recipient = db.Column(db.String(80), nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)

# --- ROUTES ---
@app.route('/')
def index():
    if 'username' in session:
        emails = Email.query.filter_by(recipient=session['username']).all()
        return render_template('index.html', username=session['username'], emails=emails)
    return redirect('/login')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username, password=password).first()
        if user:
            session['username'] = username
            return redirect('/')
        flash('Invalid username or password!')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if User.query.filter_by(username=username).first():
            flash('Username already exists!')
        else:
            new_user = User(username=username, password=password)
            db.session.add(new_user)
            db.session.commit()
            flash('Registration successful! Please login.')
            return redirect('/login')
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect('/login')

# --- LIVE SOCKETIO EVENTS ---
@socketio.on('send_email')
def handle_send_email(data):
    if 'username' in session:
        new_email = Email(
            sender=session['username'],
            recipient=data['recipient'],
            subject=data['subject'],
            body=data['body']
        )
        db.session.add(new_email)
        db.session.commit()
        
        # Instantly stream the email to the recipient if they are currently online
        emit('new_email', {
            'sender': new_email.sender,
            'subject': new_email.subject,
            'body': new_email.body
        }, broadcast=True)

if __name__ == '__main__':
    # Auto-creates database tables safely inside SQLite or PostgreSQL environment
    with app.app_context():
        db.create_all()
    socketio.run(app, debug=True)
