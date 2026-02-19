from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db

# Association table for Playlist-Video
playlist_videos = db.Table('playlist_videos',
    db.Column('playlist_id', db.Integer, db.ForeignKey('playlist.id'), primary_key=True),
    db.Column('video_id', db.Integer, db.ForeignKey('video.id'), primary_key=True)
)

# Association table for Student-Classroom
student_classes = db.Table('student_classes',
    db.Column('student_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('classroom_id', db.Integer, db.ForeignKey('classroom.id'), primary_key=True)
)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 'admin', 'teacher', 'student'
    xp = db.Column(db.Integer, default=0)
    parent_email = db.Column(db.String(150))
    parent_name = db.Column(db.String(150))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships with cascades for clean deletions
    videos = db.relationship('Video', backref='uploader', lazy=True, cascade="all, delete-orphan")
    playlists = db.relationship('Playlist', backref='creator', lazy=True, cascade="all, delete-orphan")
    comments = db.relationship('Comment', backref='author', lazy=True, cascade="all, delete-orphan")
    views = db.relationship('ViewAnalytics', backref='viewer', lazy=True, cascade="all, delete-orphan")
    received_notifications = db.relationship('Notification', backref='recipient', lazy=True, cascade="all, delete-orphan")
    
    # Class relationships
    created_classes = db.relationship('Classroom', backref='teacher', lazy=True, cascade="all, delete-orphan")
    enrolled_classes = db.relationship('Classroom', secondary='student_classes', backref=db.backref('students', lazy='dynamic'))
    attendance_records = db.relationship('Attendance', backref='student', lazy=True, cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Video(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    filename = db.Column(db.String(300), nullable=False)  # Original filename
    hls_playlist_path = db.Column(db.String(500))  # Path to master.m3u8
    thumbnail_path = db.Column(db.String(500))
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)
    uploader_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    classroom_id = db.Column(db.Integer, db.ForeignKey('classroom.id'), nullable=True)
    
    # New fields for progress tracking
    status = db.Column(db.String(20), default='pending')  # 'pending', 'uploading', 'processing', 'completed', 'failed'
    processing_progress = db.Column(db.Integer, default=0)
    
    comments = db.relationship('Comment', backref='video', lazy=True, cascade="all, delete-orphan")
    analytics = db.relationship('ViewAnalytics', backref='video', lazy=True, cascade="all, delete-orphan")
    notifications = db.relationship('Notification', backref='video', lazy=True, cascade="all, delete-orphan")

class Playlist(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    thumbnail_path = db.Column(db.String(500))  # Custom or global thumbnail
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    videos = db.relationship('Video', secondary=playlist_videos, lazy='subquery',
        backref=db.backref('playlists', lazy=True))

class Classroom(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    start_time = db.Column(db.String(5), default="09:10") # HH:MM format
    
    # Relationships
    videos = db.relationship('Video', backref='classroom', lazy=True)

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    video_id = db.Column(db.Integer, db.ForeignKey('video.id'), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('comment.id'), nullable=True)
    replies = db.relationship('Comment', backref=db.backref('parent', remote_side=[id]), lazy=True)

class ViewAnalytics(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    video_id = db.Column(db.Integer, db.ForeignKey('video.id'), nullable=False)
    start_time = db.Column(db.DateTime, default=datetime.utcnow)
    end_time = db.Column(db.DateTime)
    duration_seconds = db.Column(db.Integer, default=0)
    percent_watched = db.Column(db.Float, default=0.0)
    completed = db.Column(db.Boolean, default=False)

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)  # Teacher who receives
    message = db.Column(db.Text, nullable=False)
    video_id = db.Column(db.Integer, db.ForeignKey('video.id'), nullable=True)
    comment_id = db.Column(db.Integer, db.ForeignKey('comment.id'), nullable=True)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    comment = db.relationship('Comment', backref=db.backref('notification', lazy=True))

class SiteSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # 0 = unlocked, 1 = locked
    lock_video_speed = db.Column(db.Boolean, default=False)
    lock_video_skipping = db.Column(db.Boolean, default=False)
    global_playlist_thumbnail = db.Column(db.String(500), nullable=True)

class Quiz(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    teacher_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    video_id = db.Column(db.Integer, db.ForeignKey('video.id'), nullable=True) # Optional link to video
    classroom_id = db.Column(db.Integer, db.ForeignKey('classroom.id'), nullable=True) # Optional link to class
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    questions = db.relationship('Question', backref='quiz', lazy=True, cascade="all, delete-orphan")
    results = db.relationship('QuizResult', backref='quiz', lazy=True, cascade="all, delete-orphan")

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey('quiz.id'), nullable=False)
    text = db.Column(db.Text, nullable=False)
    option_a = db.Column(db.String(200), nullable=False)
    option_b = db.Column(db.String(200), nullable=False)
    option_c = db.Column(db.String(200), nullable=False)
    option_d = db.Column(db.String(200), nullable=False)
    correct_option = db.Column(db.String(1), nullable=False) # 'A', 'B', 'C', 'D'

class QuizResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey('quiz.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    score = db.Column(db.Integer, nullable=False)
    total_questions = db.Column(db.Integer, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    classroom_id = db.Column(db.Integer, db.ForeignKey('classroom.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref=db.backref('chat_messages', lazy=True))
    classroom = db.relationship('Classroom', backref=db.backref('messages', lazy='dynamic', cascade="all, delete-orphan"))

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    classroom_id = db.Column(db.Integer, db.ForeignKey('classroom.id'), nullable=False)
    date = db.Column(db.Date, default=datetime.utcnow().date)
    status = db.Column(db.String(20), default='Absent') # 'Present', 'Late', 'Absent'
    arrival_time = db.Column(db.DateTime)
    
    # Backrefs
    # student backref via User.attendance_records
    classroom_rel = db.relationship('Classroom', backref=db.backref('attendance_history', lazy=True))
