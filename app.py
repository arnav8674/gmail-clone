import os
from datetime import datetime
from flask import Flask, render_template, request, jsonify, session, redirect
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates')

app = Flask(__name__, template_folder=TEMPLATE_DIR)

# --- CONFIGURATION ---
app.config['SECRET_KEY'] = 'super-secure-dev-key-12345'
app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(BASE_DIR, 'instance', 'gmailclone.db')}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# --- DATABASE MODELS ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)  # e.g., alex@gmail.com
    password_hash = db.Column(db.String(200), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Email(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender = db.Column(db.String(100), nullable=False)     # Sender username
    recipient = db.Column(db.String(100), nullable=False)  # Recipient username
    subject = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Integer, default=0) 
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "sender": self.sender,
            "recipient": self.recipient,
            "subject": self.subject,
            "body": self.body,
            "is_read": self.is_read,
            "timestamp": self.timestamp.strftime('%Y-%m-%d %H:%M:%S')
        }

# --- DB INITIALIZATION ---
with app.app_context():
    os.makedirs(os.path.join(BASE_DIR, 'instance'), exist_ok=True)
    db.create_all()

# --- WEB PAGE ROUTING ---
@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect('/auth')
    return render_template('index.html', username=session['username'])

@app.route('/auth')
def auth_page():
    if 'user_id' in session:
        return redirect('/')
    return render_template('auth.html')

# --- AUTHENTICATION API ENDPOINTS ---
@app.route('/api/signup', methods=['POST'])
def signup():
    data = request.get_json()
    username = data.get('username', '').strip().lower()
    password = data.get('password', '')

    if not username or not password:
        return jsonify({"error": "Missing credentials"}), 400
    
    if User.query.filter_by(username=username).first():
        return jsonify({"error": "Username already exists"}), 400

    new_user = User(username=username)
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()

    # Automatically sign user in post-registration
    session['user_id'] = new_user.id
    session['username'] = new_user.username
    return jsonify({"success": True}), 201

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username', '').strip().lower()
    password = data.get('password', '')

    user = User.query.filter_by(username=username).first()
    if user and user.check_password(password):
        session['user_id'] = user.id
        session['username'] = user.username
        return jsonify({"success": True}), 200
        
    return jsonify({"error": "Invalid username or password"}), 401

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({"success": True}), 200

# --- SECURED EMAIL API ENDPOINTS ---
@app.route('/api/emails', methods=['GET'])
def get_emails():
    if 'username' not in session:
        return jsonify({"error": "Unauthorized"}), 401
        
    current_user = session['username']
    folder = request.args.get('folder', 'inbox')
    
    if folder == 'sent':
        emails = Email.query.filter_by(sender=current_user).order_by(Email.timestamp.desc()).all()
    else:
        emails = Email.query.filter_by(recipient=current_user).order_by(Email.timestamp.desc()).all()
        
    return jsonify([email.to_dict() for email in emails])

@app.route('/api/emails', methods=['POST'])
def send_email():
    if 'username' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()
    recipient = data.get('recipient', '').strip().lower()
    
    # Validation check: Ensure recipient exists in our system
    if not User.query.filter_by(username=recipient).first():
        return jsonify({"error": f"User '{recipient}' does not exist."}), 404

    try:
        new_email = Email(
            sender=session['username'],
            recipient=recipient,
            subject=data.get('subject', '(No Subject)'),
            body=data.get('body', '')
        )
        db.session.add(new_email)
        db.session.commit()
        
        # Broadcast the signal to notify incoming tabs
        socketio.emit('db_changed', {'action': 'send'})
        return jsonify({"message": "Sent!"}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/api/emails/<int:email_id>/read', methods=['PUT'])
def mark_as_read(email_id):
    if 'username' not in session: return jsonify({"error": "Unauthorized"}), 401
    email = Email.query.get_or_404(email_id)
    email.is_read = 1
    db.session.commit()
    socketio.emit('db_changed', {'action': 'read'})
    return jsonify({"message": "Read"})

@app.route('/api/emails/<int:email_id>', methods=['DELETE'])
def delete_email(email_id):
    if 'username' not in session: return jsonify({"error": "Unauthorized"}), 401
    email = Email.query.get_or_404(email_id)
    db.session.delete(email)
    db.session.commit()
    socketio.emit('db_changed', {'action': 'delete'})
    return jsonify({"message": "Deleted"})

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5001, debug=True)
