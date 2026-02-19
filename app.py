import os
import subprocess
import threading
import time
import re
from datetime import datetime
from flask import Flask, render_template, redirect, url_for, request, flash, jsonify, send_from_directory
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash

from extensions import db, login_manager
from models import User, Video, Playlist, Comment, ViewAnalytics, Notification, playlist_videos, Quiz, Question, QuizResult, SiteSettings, Classroom, student_classes, ChatMessage, Attendance

# Config
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
HLS_FOLDER = os.path.join(BASE_DIR, 'static', 'hls')
ALLOWED_EXTENSIONS = {'mp4', 'mov', 'avi', 'mkv'}
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

app = Flask(__name__)
app.config['SECRET_KEY'] = 'dev-secret-key-change-this'
# Use forward slashes for Windows compatibility in SQLite URI
db_path = os.path.join(BASE_DIR, 'app.db').replace('\\', '/')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'connect_args': {'check_same_thread': False}
}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['HLS_FOLDER'] = HLS_FOLDER

# Initialize Extensions
db.init_app(app)
login_manager.init_app(app)
login_manager.login_view = 'login'

# Ensure directories exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(HLS_FOLDER, exist_ok=True)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ---- Utilities ----
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def allowed_image_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS

def get_video_duration(input_path):
    """Get video duration using ffprobe."""
    try:
        cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', input_path]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        return float(result.stdout.strip())
    except:
        return 0

def process_video_background(app, video_id, input_path):
    """Background task to convert video to HLS and update progress."""
    with app.app_context():
        video = Video.query.get(video_id)
        if not video: return

        try:
            video.status = 'processing'
            video.processing_progress = 5
            db.session.commit()

            duration = get_video_duration(input_path)
            
            output_dir = app.config['HLS_FOLDER']
            video_hls_dir = os.path.join(output_dir, str(video_id))
            os.makedirs(video_hls_dir, exist_ok=True)
            output_playlist = os.path.join(video_hls_dir, 'master.m3u8')
            
            # Use Popen to track progress
            # Added -y for overwrite, explicit codecs for better compatibility, and -preset fast
            cmd = [
                'ffmpeg', '-y', '-i', input_path,
                '-c:v', 'libx264', '-profile:v', 'baseline', '-level', '3.0',
                '-c:a', 'aac', '-ac', '2', '-b:a', '128k',
                '-start_number', '0', '-hls_time', '10', '-hls_list_size', '0',
                '-f', 'hls', output_playlist
            ]
            
            # Using stdbuf or similar is hard on Windows, so we rely on -progress if needed, 
            # but standard pipe might be okay if we read chunks.
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, universal_newlines=True)
            
            # Simple progress parsing - handling both \r and \n
            while True:
                line = ""
                # Read char by char to handle \r
                while True:
                    char = process.stdout.read(1)
                    if not char: break
                    if char in ['\r', '\n']: break
                    line += char
                
                if not char and not line: break
                
                if duration > 0:
                    # Look for time=00:00:00.00
                    match = re.search(r"time=(\d+):(\d+):(\d+\.\d+)", line)
                    if match:
                        hours, mins, secs = match.groups()
                        elapsed = int(hours) * 3600 + int(mins) * 60 + float(secs)
                        progress = min(98, int((elapsed / duration) * 100))
                        if progress > video.processing_progress:
                            video.processing_progress = progress
                            # Don't commit EVERY time to avoid DB locks
                            if progress % 5 == 0:
                                db.session.commit()

            process.wait()

            if process.returncode == 0:
                # Generate thumbnail
                thumbnail_path = os.path.join(video_hls_dir, 'thumbnail.jpg')
                thumb_cmd = ['ffmpeg', '-y', '-i', input_path, '-ss', '00:00:05', '-vframes', '1', thumbnail_path]
                subprocess.run(thumb_cmd, capture_output=True)
                
                # Check if file exists
                if os.path.exists(output_playlist):
                    video.hls_playlist_path = f'hls/{video_id}/master.m3u8'
                
                if os.path.exists(thumbnail_path):
                    video.thumbnail_path = f'hls/{video_id}/thumbnail.jpg'
                
                video.status = 'completed'
                video.processing_progress = 100
                
                # Award XP
                uploader = User.query.get(video.uploader_id)
                if uploader:
                    uploader.xp += 50
                
                db.session.commit()
                print(f"Video {video_id} processed successfully.")

                # Delete original video AFTER successful commit
                try:
                    if os.path.exists(input_path):
                        os.remove(input_path)
                except Exception as e:
                    print(f"Error deleting original video: {e}")
            else:
                print(f"FFmpeg failed with return code {process.returncode}")
                video.status = 'failed'
                db.session.commit()

        except Exception as e:
            print(f"Background processing error: {e}")
            video.status = 'failed'
            db.session.commit()

# Old convert_to_hls is no longer needed but kept as stub or removed.
# I will replace it with the new async logic in upload_video.

# ---- Routes ----

@app.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            return redirect(url_for('admin_dashboard'))
        elif current_user.role == 'teacher':
            return redirect(url_for('teacher_dashboard'))
        elif current_user.role == 'student':
            return redirect(url_for('student_dashboard'))
    return render_template('ads.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        role = request.form.get('role') # User selects role or system infers? Prompt says "Login will have three types" impling selection or separate tabs? Or just username based? Let's assume username uniqueness handles it, but maybe UI has tabs. Let's rely on username lookup.
        
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            # Optional: Enforce role check if UI had a dropdown
            if role and user.role != role.lower():
                 flash('Invalid role selected for this user.', 'error')
                 return render_template('login.html')

            login_user(user)
            if user.role == 'admin':
                return redirect(url_for('admin_dashboard'))
            elif user.role == 'teacher':
                return redirect(url_for('teacher_dashboard'))
            elif user.role == 'student':
                return redirect(url_for('student_dashboard'))
        else:
            flash('Invalid username or password.', 'error')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

# ---- Admin Routes ----
@app.route('/admin')
@login_required
def admin_dashboard():
    if current_user.role != 'admin':
        return redirect(url_for('index'))
    teachers = User.query.filter_by(role='teacher').all()
    teacher_count = User.query.filter_by(role='teacher').count()
    student_count = User.query.filter_by(role='student').count()
    settings = SiteSettings.query.first()
    return render_template('admin_dashboard.html', teachers=teachers, teacher_count=teacher_count, student_count=student_count, settings=settings)

@app.route('/admin/add_teacher', methods=['POST'])
@login_required
def add_teacher():
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    
    username = request.form.get('username')
    password = request.form.get('password')
    
    if User.query.filter_by(username=username).first():
        flash('Username already exists.', 'error')
    else:
        new_teacher = User(username=username, role='teacher')
        new_teacher.set_password(password)
        db.session.add(new_teacher)
        db.session.commit()
        flash('Teacher added successfully.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/change_teacher_password', methods=['POST'])
@login_required
def change_teacher_password():
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    
    user_id = request.form.get('user_id')
    new_password = request.form.get('new_password')
    
    teacher = User.query.get(user_id)
    if teacher and teacher.role == 'teacher':
        teacher.set_password(new_password)
        db.session.commit()
        flash('Password updated successfully.', 'success')
    else:
        flash('Error updating password.', 'error')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete_teacher/<int:user_id>', methods=['POST'])
@login_required
def delete_teacher(user_id):
    if current_user.role != 'admin': return 'Unauthorized', 403
    teacher = User.query.get_or_404(user_id)
    if teacher.role == 'teacher':
        db.session.delete(teacher)
        db.session.commit()
        flash('Teacher deleted.', 'success')
    return redirect(url_for('admin_dashboard'))

# ---- Teacher Routes ----
@app.route('/teacher')
@login_required
def teacher_dashboard():
    if current_user.role != 'teacher':
        return redirect(url_for('index'))
    videos = Video.query.filter_by(uploader_id=current_user.id).all()
    playlists = Playlist.query.filter_by(creator_id=current_user.id).all()
    students = User.query.filter_by(role='student').all()
    unread_count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
    classes = Classroom.query.filter_by(teacher_id=current_user.id).all()
    quizzes = Quiz.query.filter_by(teacher_id=current_user.id).all()
    chat_count = ChatMessage.query.filter_by(user_id=current_user.id).count()
    
    # Teacher action stats for points display
    teacher_stats = {
        'videos': len(videos),
        'playlists': len(playlists),
        'quizzes': len(quizzes),
        'classes': len(classes),
        'students_added': len(students),
        'chat_messages': chat_count,
        'total_xp': current_user.xp
    }
    
    return render_template('teacher_dashboard.html', videos=videos, playlists=playlists,
        students=students, unread_count=unread_count, classes=classes, quizzes=quizzes,
        teacher_stats=teacher_stats, now_date=datetime.utcnow().date())

@app.route('/notifications')
@login_required
def view_notifications():
    notifications = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).all()
    unread_count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
    return render_template('notifications.html', notifications=notifications, unread_count=unread_count)

@app.route('/api/notifications/mark_read', methods=['POST'])
@login_required
def mark_notifications_read():
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({'is_read': True})
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/notifications/mark_one_read/<int:notification_id>', methods=['POST'])
@login_required
def mark_one_notification_read(notification_id):
    notif = Notification.query.get(notification_id)
    if notif and notif.user_id == current_user.id:
        notif.is_read = True
        db.session.commit()
    return jsonify({'success': True})

@app.route('/teacher/upload', methods=['POST'])
@login_required
def upload_video():
    if current_user.role != 'teacher': return jsonify({'error': 'Unauthorized'}), 403
    
    file = request.files.get('video_file')
    title = request.form.get('title')
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        save_name = f"{timestamp}_{filename}"
        input_path = os.path.join(app.config['UPLOAD_FOLDER'], save_name)
        file.save(input_path)
        
        new_video = Video(
            title=title, 
            filename=save_name, 
            uploader_id=current_user.id,
            status='processing',
            processing_progress=0
        )
        db.session.add(new_video)
        db.session.commit()
        
        # Start background processing
        thread = threading.Thread(target=process_video_background, args=(app, new_video.id, input_path))
        thread.start()
        
        return jsonify({
            'success': True, 
            'video_id': new_video.id,
            'message': 'Upload successful. Processing started.'
        })
            
    return jsonify({'error': 'Invalid file type'}), 400

@app.route('/api/video_status/<int:video_id>')
@login_required
def get_video_status(video_id):
    video = Video.query.get_or_404(video_id)
    if video.uploader_id != current_user.id and current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    
    return jsonify({
        'status': video.status,
        'progress': video.processing_progress,
        'title': video.title
    })

@app.route('/api/teacher/processing_videos')
@login_required
def get_processing_videos():
    """Get all videos currently being processed for the teacher."""
    videos = Video.query.filter(
        Video.uploader_id == current_user.id,
        Video.status.in_(['pending', 'processing'])
    ).all()
    
    return jsonify([{
        'id': v.id,
        'title': v.title,
        'status': v.status,
        'progress': v.processing_progress
    } for v in videos])

# ---- Site Settings & Features ----
@app.route('/admin/settings', methods=['POST'])
@login_required
def admin_settings():
    if current_user.role != 'admin': return 'Unauthorized', 403
    
    lock_speed = request.form.get('lock_speed') == 'on'
    lock_skipping = request.form.get('lock_skipping') == 'on'
    
    settings = SiteSettings.query.first()
    if not settings:
        settings = SiteSettings()
        db.session.add(settings)
    
    settings.lock_video_speed = lock_speed
    settings.lock_video_skipping = lock_skipping
    
    # Global Playlist Thumbnail
    thumb = request.files.get('global_thumbnail')
    if thumb and allowed_image_file(thumb.filename):
        filename = secure_filename(thumb.filename)
        save_name = f"global_thumb_{filename}"
        path = os.path.join(app.config['UPLOAD_FOLDER'], save_name)
        thumb.save(path)
        settings.global_playlist_thumbnail = f'uploads/{save_name}'
        
    db.session.commit()
    flash('Settings updated.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/levels_pdf')
@login_required
def levels_pdf():
    if current_user.role != 'admin': return 'Unauthorized', 403
    teachers = User.query.filter_by(role='teacher').order_by(User.xp.desc()).all()
    students = User.query.filter_by(role='student').order_by(User.xp.desc()).all()
    settings = SiteSettings.query.first()
    return render_template('levels_pdf.html', teachers=teachers, students=students, datetime=datetime, settings=settings)

# ---- Quiz Routes ----
@app.route('/teacher/create_quiz', methods=['GET', 'POST'])
@login_required
def create_quiz():
    if current_user.role != 'teacher': return 'Unauthorized', 403
    
    if request.method == 'POST':
        title = request.form.get('title')
        video_id = request.form.get('video_id') or None
        classroom_id = request.form.get('classroom_id') or None
        
        quiz = Quiz(title=title, teacher_id=current_user.id)
        if video_id: quiz.video_id = int(video_id)
        if classroom_id: quiz.classroom_id = int(classroom_id)
        
        db.session.add(quiz)
        current_user.xp += 25
        db.session.commit()
        flash('Quiz created. +25 XP!', 'success')
        
        return redirect(url_for('edit_quiz', quiz_id=quiz.id))
        
    videos = Video.query.filter_by(uploader_id=current_user.id).all()
    classes = Classroom.query.filter_by(teacher_id=current_user.id).all()
    return render_template('create_quiz.html', videos=videos, classes=classes)

@app.route('/teacher/edit_quiz/<int:quiz_id>', methods=['GET', 'POST'])
@login_required
def edit_quiz(quiz_id):
    if current_user.role != 'teacher': return 'Unauthorized', 403
    quiz = Quiz.query.get_or_404(quiz_id)
    if quiz.teacher_id != current_user.id: return 'Unauthorized', 403
    
    if request.method == 'POST':
        # Add a question
        text = request.form.get('text')
        op_a = request.form.get('option_a')
        op_b = request.form.get('option_b')
        op_c = request.form.get('option_c')
        op_d = request.form.get('option_d')
        correct = request.form.get('correct_option')
        
        q = Question(quiz_id=quiz.id, text=text, option_a=op_a, option_b=op_b, option_c=op_c, option_d=op_d, correct_option=correct)
        db.session.add(q)
        db.session.commit()
        flash('Question added.', 'success')
        
    return render_template('edit_quiz.html', quiz=quiz)

@app.route('/student/quizzes')
@login_required
def student_quizzes():
    if current_user.role != 'student': return redirect(url_for('index'))
    # Only show quizzes assigned to the student's enrolled classes
    enrolled_class_ids = [c.id for c in current_user.enrolled_classes]
    quizzes = Quiz.query.filter(
        (Quiz.classroom_id.in_(enrolled_class_ids)) | (Quiz.classroom_id == None)
    ).all()
    taken_ids = [r.quiz_id for r in QuizResult.query.filter_by(student_id=current_user.id).all()]
    return render_template('student_quizzes.html', quizzes=quizzes, taken_ids=taken_ids)

@app.route('/student/quiz/<int:quiz_id>', methods=['GET', 'POST'])
@login_required
def take_quiz(quiz_id):
    if current_user.role != 'student': return 'Unauthorized', 403
    quiz = Quiz.query.get_or_404(quiz_id)
    
    # Enforce: student must be in the assigned class (if quiz has a class)
    if quiz.classroom_id:
        enrolled_class_ids = [c.id for c in current_user.enrolled_classes]
        if quiz.classroom_id not in enrolled_class_ids:
            flash('You are not enrolled in the class for this quiz.', 'error')
            return redirect(url_for('student_quizzes'))
    
    if request.method == 'POST':
        score = 0
        total = len(quiz.questions)
        for q in quiz.questions:
            selected = request.form.get(f'q_{q.id}')
            if selected == q.correct_option:
                score += 1
        
        result = QuizResult(quiz_id=quiz.id, student_id=current_user.id, score=score, total_questions=total)
        db.session.add(result)
        
        if total > 0 and (score / total) >= 0.5:
            current_user.xp += 100
            flash(f'Quiz submitted. Score: {score}/{total}. +100 XP!', 'success')
        else:
            flash(f'Quiz submitted. Score: {score}/{total}.', 'info')
            
        db.session.commit()
        return redirect(url_for('student_quizzes'))
        
    return render_template('take_quiz.html', quiz=quiz)

# ---- AI Assistant ----
@app.route('/ai_assistant')
@login_required
def ai_assistant():
    return render_template('ai_assistant.html')

@app.route('/api/ai_chat', methods=['POST'])
@login_required
def ai_chat():
    data = request.json
    message = data.get('message', '').lower()
    
    # Simple rule-based response for demo
    # In production, this would call an LLM API
    response = "I am an AI assistant. I can help with your studies."
    
    if 'hello' in message or 'hi' in message:
        response = "Hello! How can I help you with your coursework today?"
    elif 'doubts' in message or 'problem' in message:
        response = "I can help solve your doubts. Please describe the specific problem you are facing in the video."
    elif 'quiz' in message:
        response = "Quizzes are mandatory for students. Check the 'Quizzes' tab to see pending assessments."
    elif 'video' in message:
        response = "Videos are uploaded by your teachers. You earn XP by watching them!"
        
    return jsonify({'response': response})


@app.route('/teacher/add_student', methods=['POST'])
@login_required
def add_student():
    if current_user.role != 'teacher': return 'Unauthorized', 403
    username = request.form.get('username')
    password = request.form.get('password')
    
    if User.query.filter_by(username=username).first():
        flash('Username already exists.', 'error')
    else:
        new_student = User(username=username, role='student')
        new_student.set_password(password)
        db.session.add(new_student)
        current_user.xp += 20
        db.session.commit()
        flash('Student added successfully. +20 XP!', 'success')
    return redirect(url_for('teacher_dashboard'))

@app.route('/teacher/change_student_password', methods=['POST'])
@login_required
def change_student_password():
    if current_user.role != 'teacher': return 'Unauthorized', 403
    
    student_id = request.form.get('student_id')
    new_password = request.form.get('new_password')
    
    student = User.query.get(student_id)
    if student and student.role == 'student':
        student.set_password(new_password)
        db.session.commit()
        flash('Student password updated successfully.', 'success')
    else:
        flash('Error updating student password.', 'error')
    return redirect(url_for('teacher_dashboard'))

@app.route('/teacher/create_playlist', methods=['POST'])
@login_required
def create_playlist():
    if current_user.role != 'teacher': return 'Unauthorized', 403
    title = request.form.get('title')
    new_playlist = Playlist(title=title, creator_id=current_user.id)
    db.session.add(new_playlist)
    current_user.xp += 30
    db.session.commit()
    flash('Playlist created. +30 XP!', 'success')
    return redirect(url_for('teacher_dashboard'))

@app.route('/teacher/add_to_playlist', methods=['POST'])
@login_required
def add_to_playlist():
    if current_user.role != 'teacher': return 'Unauthorized', 403
    playlist_id = request.form.get('playlist_id')
    video_id = request.form.get('video_id')
    
    playlist = Playlist.query.get(playlist_id)
    video = Video.query.get(video_id)
    
    if playlist and video and playlist.creator_id == current_user.id:
        if video not in playlist.videos:
            playlist.videos.append(video)
            db.session.commit()
            flash('Video added to playlist.', 'success')
    return redirect(url_for('teacher_dashboard'))

@app.route('/teacher/delete_video/<int:video_id>', methods=['POST'])
@login_required
def delete_video(video_id):
    if current_user.role != 'teacher': return 'Unauthorized', 403
    video = Video.query.get_or_404(video_id)
    if video.uploader_id == current_user.id:
        # Delete files as well
        try:
            input_path = os.path.join(app.config['UPLOAD_FOLDER'], video.filename)
            if os.path.exists(input_path): os.remove(input_path)
            # HLS segments
            # ... simple cleanup:
            import shutil
            hls_dir = os.path.join(app.config['HLS_FOLDER'], str(video.id))
            if os.path.exists(hls_dir): shutil.rmtree(hls_dir)
        except Exception as e:
            print(f"File deletion error: {e}")
            
        db.session.delete(video)
        db.session.commit()
        flash('Video deleted successfully.', 'success')
    return redirect(url_for('teacher_dashboard'))

@app.route('/teacher/delete_playlist/<int:playlist_id>', methods=['POST'])
@login_required
def delete_playlist(playlist_id):
    if current_user.role != 'teacher': return 'Unauthorized', 403
    playlist = Playlist.query.get_or_404(playlist_id)
    if playlist.creator_id == current_user.id:
        db.session.delete(playlist)
        db.session.commit()
        flash('Playlist deleted successfully.', 'success')
    return redirect(url_for('teacher_dashboard'))

@app.route('/teacher/analytics')
@login_required
def analytics():
    if current_user.role != 'teacher': return redirect(url_for('index'))
    # Get all videos by this teacher
    videos = Video.query.filter_by(uploader_id=current_user.id).all()
    # For each video, get view data
    data = []
    for video in videos:
        views = ViewAnalytics.query.filter_by(video_id=video.id).all()
        for v in views:
            viewer = User.query.get(v.user_id)
            data.append({
                'video_title': video.title,
                'student_name': viewer.username if viewer else 'Unknown',
                'start_time': v.start_time,
                'duration': v.duration_seconds
            })
    return render_template('analytics.html', analytics_data=data)


# ---- Student and Watch Routes ----
@app.route('/student')
@login_required
def student_dashboard():
    if current_user.role != 'student':
        return redirect(url_for('index'))
    
    # Students search teacher playlists
    query = request.args.get('q')
    if query:
        playlists = Playlist.query.filter(Playlist.title.contains(query)).all()
        videos = Video.query.filter(Video.title.contains(query), Video.status=='completed').all()
    else:
        playlists = Playlist.query.all()
        videos = Video.query.filter_by(status='completed').order_by(Video.upload_date.desc()).limit(20).all()
        
    unread_count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
    settings = SiteSettings.query.first()
    enrolled_classes = current_user.enrolled_classes
    
    # Calculate real attendance percentage
    total_records = len(current_user.attendance_records) if current_user.attendance_records else 0
    present_records = len([r for r in current_user.attendance_records if r.status in ['Present', 'Late']]) if total_records > 0 else 0
    attendance_pct = int((present_records / total_records) * 100) if total_records > 0 else 0
    
    return render_template('student_dashboard.html', playlists=playlists, videos=videos, 
        search_query=query, unread_count=unread_count, settings=settings, 
        enrolled_classes=enrolled_classes, now_date=datetime.utcnow().date(),
        attendance_pct=attendance_pct)

@app.route('/playlist/<int:playlist_id>')
@login_required
def view_playlist(playlist_id):
    playlist = Playlist.query.get_or_404(playlist_id)
    return render_template('playlist_view.html', playlist=playlist)

@app.route('/watch/<int:video_id>')
@login_required
def watch_video(video_id):
    video = Video.query.get_or_404(video_id)
    
    # Simple recommendation logic (videos from same uploader)
    related_videos = Video.query.filter(Video.uploader_id == video.uploader_id, Video.id != video.id).limit(5).all()
    
    # Top-level comments
    top_level_comments = Comment.query.filter_by(video_id=video_id, parent_id=None).order_by(Comment.timestamp.desc()).all()
    
    settings = SiteSettings.query.first()
    return render_template('video_player.html', video=video, related_videos=related_videos, comments=top_level_comments, settings=settings)

@app.route('/api/comment', methods=['POST'])
@login_required
def post_comment():
    data = request.json
    video_id = data.get('video_id')
    content = data.get('content')
    parent_id = data.get('parent_id') # Optional
    
    new_comment = Comment(content=content, user_id=current_user.id, video_id=video_id, parent_id=parent_id)
    db.session.add(new_comment)
    db.session.commit()
    
    video = Video.query.get(video_id)
    
    if parent_id:
        # It's a reply: Notify the author of the parent comment
        parent_comment = Comment.query.get(parent_id)
        if parent_comment and parent_comment.user_id != current_user.id:
            role_label = "Teacher" if current_user.role == 'teacher' else current_user.username
            notification_msg = f'{role_label} replied to your comment: "{content[:100]}"'
            notif = Notification(
                user_id=parent_comment.user_id,
                message=notification_msg,
                video_id=video_id,
                comment_id=new_comment.id
            )
            db.session.add(notif)
    else:
        # It's a top-level comment: Notify the teacher who uploaded this video
        if video and video.uploader_id != current_user.id:
            notification_msg = f'{current_user.username} commented on your video "{video.title}": "{content[:100]}"'
            notif = Notification(
                user_id=video.uploader_id,
                message=notification_msg,
                video_id=video_id,
                comment_id=new_comment.id
            )
            db.session.add(notif)
            
    db.session.commit()
    return jsonify({'success': True, 'username': current_user.username, 'content': content})

@app.route('/api/analytics/start', methods=['POST'])
@login_required
def track_start():
    data = request.json
    video_id = data.get('video_id')
    
    new_view = ViewAnalytics(user_id=current_user.id, video_id=video_id)
    db.session.add(new_view)
    db.session.commit()
    return jsonify({'view_id': new_view.id})

@app.route('/api/analytics/update', methods=['POST'])
@login_required
def track_update():
    data = request.json
    view_id = data.get('view_id')
    curr_time = data.get('duration') # current time in seconds
    total_duration = data.get('total_duration') # video total length
    
    view = ViewAnalytics.query.get(view_id)
    if view and view.user_id == current_user.id:
        view.duration_seconds = curr_time
        view.end_time = datetime.utcnow()
        
        if total_duration and total_duration > 0:
            view.percent_watched = (curr_time / total_duration) * 100
            if view.percent_watched >= 90:
                view.completed = True
        
        # Gamification: Award XP
        if current_user.role == 'student':
            current_user.xp += 1
            
        db.session.commit()
    return jsonify({'success': True})

# ---- Class Management Routes ----
@app.route('/teacher/create_class', methods=['POST'])
@login_required
def create_class():
    if current_user.role != 'teacher': return 'Unauthorized', 403
    name = request.form.get('name')
    if name:
        new_class = Classroom(name=name, teacher_id=current_user.id)
        db.session.add(new_class)
        current_user.xp += 40
        db.session.commit()
        flash(f'Class "{name}" created. +40 XP!', 'success')
    return redirect(url_for('teacher_dashboard'))

@app.route('/teacher/add_student_to_class', methods=['POST'])
@login_required
def add_student_to_class():
    if current_user.role != 'teacher': return 'Unauthorized', 403
    student_id = request.form.get('student_id')
    class_id = request.form.get('class_id')
    student = User.query.get(student_id)
    classroom = Classroom.query.get(class_id)
    if student and classroom and classroom.teacher_id == current_user.id:
        if student not in classroom.students:
            classroom.students.append(student)
            current_user.xp += 15
            db.session.commit()
            flash(f'Added {student.username} to {classroom.name}. +15 XP!', 'success')
        else:
            flash(f'{student.username} is already in {classroom.name}.', 'info')
    else:
        flash('Invalid student or class.', 'error')
    return redirect(url_for('teacher_dashboard'))

@app.route('/teacher/remove_student_from_class', methods=['POST'])
@login_required
def remove_student_from_class():
    if current_user.role != 'teacher': return 'Unauthorized', 403
    student_id = request.form.get('student_id')
    class_id = request.form.get('class_id')
    student = User.query.get(student_id)
    classroom = Classroom.query.get(class_id)
    if student and classroom and classroom.teacher_id == current_user.id:
        if student in classroom.students:
            classroom.students.remove(student)
            db.session.commit()
            flash(f'Removed {student.username} from class {classroom.name}.', 'success')
    return redirect(url_for('teacher_dashboard'))

@app.route('/teacher/delete_student/<int:student_id>', methods=['POST'])
@login_required
def delete_student(student_id):
    if current_user.role != 'teacher': return 'Unauthorized', 403
    student = User.query.get_or_404(student_id)
    if student.role == 'student':
        db.session.delete(student)
        db.session.commit()
        flash('Student account deleted.', 'success')
    else:
        flash('Cannot delete non-students.', 'error')
    return redirect(url_for('teacher_dashboard'))

@app.route('/teacher/quiz_report/<int:quiz_id>')
@login_required
def quiz_report(quiz_id):
    if current_user.role != 'teacher': return 'Unauthorized', 403
    quiz = Quiz.query.get_or_404(quiz_id)
    if quiz.teacher_id != current_user.id: return 'Unauthorized', 403
    results = QuizResult.query.filter_by(quiz_id=quiz.id).all()
    detailed_results = []
    for r in results:
        student = User.query.get(r.student_id)
        if student:
            detailed_results.append({
                'student': student,
                'score': r.score,
                'total': r.total_questions,
                'date': r.timestamp
            })
    return render_template('quiz_report.html', quiz=quiz, results=detailed_results, datetime=datetime)

# ---- Admin Password Change ----
@app.route('/admin/change_admin_password', methods=['POST'])
@login_required
def change_admin_password():
    if current_user.role != 'admin': return 'Unauthorized', 403
    current_password = request.form.get('current_password')
    new_password = request.form.get('new_password')
    confirm_password = request.form.get('confirm_password')
    
    if not current_user.check_password(current_password):
        flash('Current password is incorrect.', 'error')
    elif new_password != confirm_password:
        flash('New passwords do not match.', 'error')
    elif len(new_password) < 4:
        flash('Password must be at least 4 characters.', 'error')
    else:
        current_user.set_password(new_password)
        db.session.commit()
        flash('Admin password updated successfully.', 'success')
    return redirect(url_for('admin_dashboard'))

# ---- Delete Class ----
@app.route('/teacher/delete_class/<int:class_id>', methods=['POST'])
@login_required
def delete_class(class_id):
    if current_user.role != 'teacher': return 'Unauthorized', 403
    classroom = Classroom.query.get_or_404(class_id)
    if classroom.teacher_id != current_user.id: return 'Unauthorized', 403
    class_name = classroom.name
    db.session.delete(classroom)
    db.session.commit()
    flash(f'Class deleted successfully.', 'success')
    return redirect(url_for('teacher_dashboard'))

# ---- Chatroom Routes ----
@app.route('/chatroom/<int:class_id>')
@login_required
def chatroom(class_id):
    classroom = Classroom.query.get_or_404(class_id)
    # Teacher who owns the class OR student enrolled in the class
    if current_user.role == 'teacher' and classroom.teacher_id != current_user.id:
        flash('You do not own this class.', 'error')
        return redirect(url_for('teacher_dashboard'))
    if current_user.role == 'student':
        enrolled_ids = [c.id for c in current_user.enrolled_classes]
        if class_id not in enrolled_ids:
            flash('You are not enrolled in this class.', 'error')
            return redirect(url_for('student_dashboard'))
    
    messages = ChatMessage.query.filter_by(classroom_id=class_id).order_by(ChatMessage.timestamp.asc()).all()
    return render_template('chatroom.html', classroom=classroom, messages=messages)

@app.route('/api/chatroom/<int:class_id>/send', methods=['POST'])
@login_required
def send_chat_message(class_id):
    classroom = Classroom.query.get_or_404(class_id)
    # Verify access
    if current_user.role == 'teacher' and classroom.teacher_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403
    if current_user.role == 'student':
        enrolled_ids = [c.id for c in current_user.enrolled_classes]
        if class_id not in enrolled_ids:
            return jsonify({'error': 'Not enrolled'}), 403
    
    data = request.json
    content = data.get('content', '').strip()
    if not content:
        return jsonify({'error': 'Empty message'}), 400
    
    msg = ChatMessage(classroom_id=class_id, user_id=current_user.id, content=content)
    db.session.add(msg)
    if current_user.role == 'teacher':
        current_user.xp += 5
    db.session.commit()
    return jsonify({
        'success': True,
        'id': msg.id,
        'username': current_user.username,
        'role': current_user.role,
        'content': msg.content,
        'timestamp': msg.timestamp.strftime('%I:%M %p')
    })

@app.route('/api/chatroom/<int:class_id>/messages')
@login_required
def get_chat_messages(class_id):
    classroom = Classroom.query.get_or_404(class_id)
    after_id = request.args.get('after', 0, type=int)
    messages = ChatMessage.query.filter(
        ChatMessage.classroom_id == class_id,
        ChatMessage.id > after_id
    ).order_by(ChatMessage.timestamp.asc()).all()
    return jsonify({
        'messages': [{
            'id': m.id,
            'username': m.user.username,
            'role': m.user.role,
            'content': m.content,
            'timestamp': m.timestamp.strftime('%I:%M %p'),
            'user_id': m.user_id
        } for m in messages]
    })

@app.route('/api/chatroom/delete_message/<int:message_id>', methods=['POST'])
@login_required
def delete_chat_message(message_id):
    if current_user.role != 'teacher': return jsonify({'error': 'Unauthorized'}), 403
    msg = ChatMessage.query.get_or_404(message_id)
    classroom = Classroom.query.get(msg.classroom_id)
    if not classroom or classroom.teacher_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403
    db.session.delete(msg)
    db.session.commit()
    return jsonify({'success': True})

# ---- Attendance Routes ----

@app.route('/teacher/mark_attendance/<int:class_id>/<int:student_id>', methods=['POST'])
@login_required
def mark_attendance(class_id, student_id):
    if current_user.role != 'teacher': return 'Unauthorized', 403
    classroom = Classroom.query.get_or_404(class_id)
    if classroom.teacher_id != current_user.id: return 'Unauthorized', 403
    
    student = User.query.get_or_404(student_id)
    now = datetime.utcnow()
    class_start = now.replace(hour=9, minute=10, second=0, microsecond=0)

    # Logic: Present if marking early or if "force" param is used
    # In a real app, this would be strict. For simulation, we'll check if it's before 10 AM 
    # OR if the teacher clicked a specific button. 
    # But for now let's just make it easier: if it's a weekday and they mark it, it's Present 
    # unless it's genuinely late (e.g. after 9:20 AM)
    
    # FOR USER: Since you're testing now (afternoon), let's allow "Present" if marked manually.
    forced_status = request.args.get('status')
    if forced_status:
        status = forced_status
    else:
        diff = (now - class_start).total_seconds() / 60
        if diff <= 5: status = 'Present'
        elif diff <= 20: status = 'Late'
        else: status = 'Late' # Still defaults to Late if very late, but we'll add buttons for teacher.
        
    # Check if record for today already exists
    today_date = now.date()
    record = Attendance.query.filter_by(student_id=student_id, classroom_id=class_id, date=today_date).first()
    
    if not record:
        record = Attendance(student_id=student_id, classroom_id=class_id, date=today_date, status=status, arrival_time=now)
        db.session.add(record)
    else:
        record.status = status
        record.arrival_time = now
        
    db.session.commit()
    
    # Check for warnings: 3 lates in a month
    this_month = today_date.month
    lates = Attendance.query.filter(
        Attendance.student_id == student_id,
        Attendance.status == 'Late',
        db.extract('month', Attendance.date) == this_month
    ).count()
    
    if lates >= 3:
        flash(f"WARNING: Student {student.username} late {lates} times! Parent notified.", 'warning')
        
    flash(f'Attendance marked for {student.username}: {status}', 'success')
    
    # Check for continuous 3 days absence
    # We'll check the last 3 days excluding weekends? Or just last 3 records.
    last_records = Attendance.query.filter_by(student_id=student_id).order_by(Attendance.date.desc()).limit(3).all()
    absent_streak = all(r.status == 'Absent' for r in last_records) if len(last_records) >= 3 else False
    
    if absent_streak:
        flash(f"CRITICAL: Student {student.username} absent for 3 consecutive days! Parent notified for compensation warning.", 'error')
        
    return redirect(url_for('teacher_dashboard'))

@app.route('/teacher/report/struggling_topics')
@login_required
def struggling_topics_report():
    if current_user.role != 'teacher': return 'Unauthorized', 403
    stats = db.session.query(
        Video.title, 
        db.func.count(ViewAnalytics.id).label('view_count')
    ).join(ViewAnalytics).filter(Video.uploader_id == current_user.id).group_by(Video.id).order_by(db.desc('view_count')).all()
    return render_template('struggling_topics.html', stats=stats)

@app.route('/teacher/report/monthly/<int:student_id>')
@login_required
def monthly_report(student_id):
    if current_user.role != 'teacher': return 'Unauthorized', 403
    student = User.query.get_or_404(student_id)
    
    # Calculate stats for current month
    this_month = datetime.utcnow().month
    records = Attendance.query.filter(
        Attendance.student_id == student_id,
        db.extract('month', Attendance.date) == this_month
    ).all()
    
    total = len(records)
    present = len([r for r in records if r.status == 'Present'])
    late = len([r for r in records if r.status == 'Late'])
    absent = len([r for r in records if r.status == 'Absent'])
    
    attendance_pct = (present / total * 100) if total > 0 else 0
    
    # Working hours simulation (assume 6 hours per present day)
    working_hours = present * 6
    
    return render_template('monthly_report.html', 
        student=student, 
        attendance_pct=attendance_pct,
        total=total, present=present, late=late, absent=absent,
        working_hours=working_hours,
        now_date=datetime.utcnow().date())

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        # Initialize admin if not exists
        if not User.query.filter_by(role='admin').first():
            admin = User(username='admin', role='admin')
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
            print("Admin user created: admin / admin123")
            
        # Initialize settings
        if not SiteSettings.query.first():
            db.session.add(SiteSettings())
            db.session.commit()
            print("SiteSettings initialized.")
            
    app.run(debug=True, port=5000)
