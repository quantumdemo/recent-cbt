import os
import psycopg2
import psycopg2.extras
import json
import pandas as pd
from datetime import datetime, timedelta
import secrets
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, make_response, session
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from database import get_db_connection, init_db
from models import User
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_mail import Mail, Message
from fpdf import FPDF
import xlsxwriter
from io import BytesIO
import click
import random
import requests
from google.oauth2 import credentials
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from google_auth_oauthlib.flow import Flow
from cachecontrol import CacheControl

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your_secret_key')
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True) # Create upload folder if it doesn't exist
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30) # Session timeout

# Mail configuration
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'True').lower() in ['true', 'on', '1']
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_USERNAME')

# Google OAuth Configuration
app.config['GOOGLE_CLIENT_ID'] = os.environ.get('GOOGLE_CLIENT_ID', 'YOUR_GOOGLE_CLIENT_ID')
app.config['GOOGLE_CLIENT_SECRET'] = os.environ.get('GOOGLE_CLIENT_SECRET', 'YOUR_GOOGLE_CLIENT_SECRET')
app.config['REDIRECT_URI'] = '/google/callback'

# Allow insecure transport for development only.
if os.environ.get('FLASK_DEBUG') == '1':
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

mail = Mail(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'student_login'

def from_json(value):
    return json.loads(value)
app.jinja_env.filters['fromjson'] = from_json

@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT id, fullname, email, role FROM users WHERE id = %s", (user_id,))
    user_data = cur.fetchone()
    if user_data:
        return User(id=user_data['id'], fullname=user_data['fullname'], email=user_data['email'], role=user_data['role'])
    return None

@app.before_request
def before_request():
    session.permanent = True
    app.permanent_session_lifetime = timedelta(minutes=30)
    session.modified = True

@app.cli.command('initdb')
def initdb_command():
    """Initializes the database."""
    init_db()
    print('Initialized the database.')

@app.cli.command('create-admin')
@click.argument('name')
@click.argument('email')
@click.argument('password')
def create_admin_command(name, email, password):
    """Creates a new admin user."""
    conn = get_db_connection()
    cur = conn.cursor()
    password_hash = generate_password_hash(password)
    try:
        cur.execute(
            "INSERT INTO users (fullname, email, password_hash, role, status) VALUES (%s, %s, %s, 'admin', 'approved')",
            (name, email, password_hash)
        )
        conn.commit()
        print(f'Admin user {name} created successfully.')
    except psycopg2.IntegrityError:
        print(f'Error: Admin user with email {email} already exists.')
    finally:
        cur.close()
        conn.close()

@app.route('/')
def index():
    return render_template('index.html')

def send_email(subject, recipients, body):
    msg = Message(subject, recipients=recipients)
    msg.body = body
    try:
        mail.send(msg)
    except Exception as e:
        print(f"Error sending email: {e}")

# Teacher routes
@app.route('/teacher/login', methods=['GET', 'POST'])
def teacher_login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("SELECT * FROM users WHERE email = %s AND role = 'teacher' AND status = 'approved'", (email,))
        user_data = cur.fetchone()
        cur.close()
        conn.close()

        if user_data and check_password_hash(user_data['password_hash'], password):
            user = User(id=user_data['id'], fullname=user_data['fullname'], email=user_data['email'], role=user_data['role'])
            login_user(user)
            return redirect(url_for('teacher_dashboard'))
        else:
            flash('Invalid email or password, or account not approved.')

    return render_template('teacher_login.html')

@app.route('/teacher/register', methods=['GET', 'POST'])
def teacher_register():
    if request.method == 'POST':
        fullname = request.form['fullname']
        email = request.form['email']
        password = request.form['password']
        gender = request.form['gender']

        password_hash = generate_password_hash(password)

        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO users (fullname, email, password_hash, role, gender, status) VALUES (%s, %s, %s, 'teacher', %s, 'pending')",
                (fullname, email, password_hash, gender)
            )
            conn.commit()
            flash('Registration successful. Please wait for admin approval.')
            return redirect(url_for('teacher_login'))
        except psycopg2.IntegrityError:
            flash('Email already registered.')
        finally:
            cur.close()
            conn.close()

    return render_template('teacher_register.html')

@app.route('/teacher/dashboard')
@login_required
def teacher_dashboard():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    # Fetch exams for the main list
    cur.execute("""
        SELECT
            e.id, e.title, e.class, e.duration, e.start_time, e.end_time,
            COUNT(s.id) AS submission_count
        FROM exams e
        LEFT JOIN exam_submissions s ON e.id = s.exam_id
        WHERE e.teacher_id = %s
        GROUP BY e.id
        ORDER BY e.created_at DESC
    """, (current_user.id,))
    exams_data = cur.fetchall()

    now = datetime.utcnow()
    exams = []
    for exam_data in exams_data:
        exam = dict(exam_data)
        start_time = exam.get('start_time')
        end_time = exam.get('end_time')
        is_active = False
        if start_time and end_time:
            is_active = start_time <= now <= end_time
        elif start_time:
            is_active = start_time <= now
        exam['is_active'] = is_active

        # Calculate completion rate for each exam
        cur.execute("SELECT COUNT(id) FROM users WHERE role = 'student' AND class = %s", (exam['class'],))
        total_students_in_class = cur.fetchone()[0]

        completion_rate = 0
        if total_students_in_class > 0:
            completion_rate = (exam['submission_count'] / total_students_in_class) * 100
        exam['completion_rate'] = completion_rate

        exams.append(exam)

    # --- DYNAMIC ACTIVITY FEED LOGIC ---
    activities = []

    # 1. Fetch recent exam creations
    cur.execute("SELECT title, created_at FROM exams WHERE teacher_id = %s ORDER BY created_at DESC LIMIT 5", (current_user.id,))
    for exam in cur.fetchall():
        activities.append({
            'type': 'exam_created',
            'title': f"New exam created: {exam['title']}",
            'time': exam['created_at'],
            'icon': '📝'
        })

    # 2. Fetch recent student submissions for this teacher's exams
    cur.execute("""
        SELECT u.fullname, e.title, s.end_time
        FROM exam_submissions s
        JOIN users u ON s.student_id = u.id
        JOIN exams e ON s.exam_id = e.id
        WHERE e.teacher_id = %s AND s.status = 'submitted'
        ORDER BY s.end_time DESC
        LIMIT 5
    """, (current_user.id,))
    for submission in cur.fetchall():
        activities.append({
            'type': 'submission',
            'title': f"{submission['fullname']} completed the exam: {submission['title']}",
            'time': submission['end_time'],
            'icon': '📊'
        })

    # 3. (Optional) Fetch new student registrations in the teacher's classes.
    # This is a bit more complex as we need to infer the teacher's classes.
    cur.execute("SELECT DISTINCT class FROM exams WHERE teacher_id = %s", (current_user.id,))
    teacher_classes = [row['class'] for row in cur.fetchall()]

    if teacher_classes:
        cur.execute("""
            SELECT fullname, created_at
            FROM users
            WHERE role = 'student' AND class IN %s
            ORDER BY created_at DESC
            LIMIT 5
        """, (tuple(teacher_classes),))
        for student in cur.fetchall():
            activities.append({
                'type': 'new_student',
                'title': f"New student registered: {student['fullname']}",
                'time': student['created_at'],
                'icon': '👤'
            })

    # Sort all activities by time and take the most recent 5
    activities.sort(key=lambda x: x['time'], reverse=True)
    recent_activities = activities[:5]
    # --- END ACTIVITY FEED LOGIC ---

    cur.close()
    conn.close()
    return render_template('teacher_dashboard.html', exams=exams, activities=recent_activities)

@app.route('/teacher/exam/create', methods=['GET', 'POST'])
@login_required
def create_exam():
    if request.method == 'POST':
        title = request.form['title']
        exam_class = request.form['class']
        duration = request.form['duration']
        description = request.form['description']
        start_time = request.form.get('start_time') or None
        end_time = request.form.get('end_time') or None
        randomize_questions = 'randomize_questions' in request.form
        delay_results = 'delay_results' in request.form

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO exams (title, class, duration, description, teacher_id, start_time, end_time, randomize_questions, delay_results) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (title, exam_class, duration, description, current_user.id, start_time, end_time, randomize_questions, delay_results)
        )
        exam_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()

        flash('Exam created successfully. Now add questions.')
        return redirect(url_for('manage_exam', exam_id=exam_id))

    return render_template('create_exam.html')

@app.route('/teacher/exam/<int:exam_id>/manage')
@login_required
def manage_exam(exam_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT * FROM exams WHERE id = %s AND teacher_id = %s", (exam_id, current_user.id))
    exam = cur.fetchone()
    cur.execute("SELECT * FROM questions WHERE exam_id = %s ORDER BY id", (exam_id,))
    questions = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('manage_exam.html', exam=exam, questions=questions)

@app.route('/teacher/exam/<int:exam_id>/add_question', methods=['GET', 'POST'])
@login_required
def add_question(exam_id):
    if request.method == 'POST':
        question_text = request.form['question_text']
        question_type = request.form['question_type']

        options = None
        correct_answer = ''
        question_image = None

        if 'question_image' in request.files:
            file = request.files['question_image']
            if file.filename != '':
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                question_image = filename

        if question_type in ['single-choice', 'multiple-choice']:
            form_options = [request.form[key] for key in request.form if key.startswith('option_')]
            correct_indices = request.form.getlist('correct_option')

            options_data = [{'text': text, 'correct': str(i) in correct_indices} for i, text in enumerate(form_options)]
            options = json.dumps(options_data)
            correct_answer = json.dumps(correct_indices)

        else:
            correct_answer = request.form['correct_answer']

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO questions (exam_id, question_text, question_image, question_type, options, correct_answer) VALUES (%s, %s, %s, %s, %s, %s)",
            (exam_id, question_text, question_image, question_type, options, correct_answer)
        )
        conn.commit()
        cur.close()
        conn.close()
        flash('Question added successfully.')
        return redirect(url_for('manage_exam', exam_id=exam_id))

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT * FROM exams WHERE id = %s", (exam_id,))
    exam = cur.fetchone()
    cur.close()
    conn.close()
    return render_template('add_question.html', exam=exam)

@app.route('/teacher/exam/delete/<int:exam_id>')
@login_required
def delete_exam(exam_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM exams WHERE id = %s AND teacher_id = %s", (exam_id, current_user.id))
    conn.commit()
    cur.close()
    conn.close()
    flash('Exam deleted.')
    return redirect(url_for('teacher_dashboard'))

@app.route('/teacher/question/delete/<int:question_id>')
@login_required
def delete_question(question_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT q.exam_id FROM questions q JOIN exams e ON q.exam_id = e.id WHERE q.id = %s AND e.teacher_id = %s", (question_id, current_user.id))
    question_data = cur.fetchone()

    if question_data:
        exam_id = question_data['exam_id']
        cur.execute("DELETE FROM questions WHERE id = %s", (question_id,))
        conn.commit()
        flash('Question deleted.')
        cur.close()
        conn.close()
        return redirect(url_for('manage_exam', exam_id=exam_id))

    flash('Permission denied.')
    return redirect(url_for('teacher_dashboard'))

@app.route('/teacher/exam/<int:exam_id>/upload_questions', methods=['POST'])
@login_required
def upload_questions(exam_id):
    file = request.files['file']
    if file:
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        if filename.endswith('.csv'):
            df = pd.read_csv(filepath)
        else:
            df = pd.read_excel(filepath)

        conn = get_db_connection()
        cur = conn.cursor()
        for index, row in df.iterrows():
            question_text = row['question_text']
            question_type = row['question_type']
            options = None
            correct_answer = ''

            if question_type in ['single-choice', 'multiple-choice']:
                opts = []
                correct_indices = []
                for i in range(1, 5):
                    if f'option{i}' in row and pd.notna(row[f'option{i}']):
                        opts.append(row[f'option{i}'])

                options_data = [{'text': text, 'correct': str(i+1) in str(row['correct_answer']).split(',')} for i, text in enumerate(opts)]
                options = json.dumps(options_data)
                correct_answer = json.dumps(str(row['correct_answer']).split(','))
            else:
                correct_answer = row['correct_answer']

            cur.execute(
                "INSERT INTO questions (exam_id, question_text, question_type, options, correct_answer) VALUES (%s, %s, %s, %s, %s)",
                (exam_id, question_text, question_type, options, correct_answer)
            )
        conn.commit()
        cur.close()
        conn.close()
        flash('Questions uploaded successfully.')

    return redirect(url_for('manage_exam', exam_id=exam_id))

@app.route('/teacher/question/edit/<int:question_id>', methods=['GET', 'POST'])
@login_required
def edit_question(question_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT * FROM questions WHERE id = %s", (question_id,))
    question = cur.fetchone()

    if request.method == 'POST':
        question_text = request.form['question_text']

        # Handle image upload
        if 'question_image' in request.files:
            file = request.files['question_image']
            if file.filename != '':
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                cur.execute("UPDATE questions SET question_image = %s WHERE id = %s", (filename, question_id))

        if question['question_type'] in ['single-choice', 'multiple-choice']:
            form_options = [request.form[key] for key in sorted(request.form.keys()) if key.startswith('option_')]
            correct_indices = request.form.getlist('correct_option')

            options_data = [{'text': text, 'correct': str(i) in correct_indices} for i, text in enumerate(form_options)]
            options = json.dumps(options_data)
            correct_answer = json.dumps(correct_indices)

            cur.execute("UPDATE questions SET options = %s, correct_answer = %s WHERE id = %s", (options, correct_answer, question_id))
        else:
            correct_answer = request.form['correct_answer']
            cur.execute("UPDATE questions SET correct_answer = %s WHERE id = %s", (correct_answer, question_id))

        cur.execute("UPDATE questions SET question_text = %s WHERE id = %s", (question_text, question_id))
        conn.commit()

        flash('Question updated successfully.')
        cur.close()
        conn.close()
        return redirect(url_for('manage_exam', exam_id=question['exam_id']))

    cur.close()
    conn.close()
    return render_template('edit_question.html', question=question)

def calculate_score(submission_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute("""
        SELECT sa.answer_text, q.question_type, q.correct_answer
        FROM student_answers sa
        JOIN questions q ON sa.question_id = q.id
        WHERE sa.submission_id = %s
    """, (submission_id,))

    answers = cur.fetchall()
    score = 0
    total_objective_questions = 0

    for answer in answers:
        if answer['question_type'] in ['single-choice', 'multiple-choice']:
            total_objective_questions += 1
            student_answer_indices = set(answer['answer_text'].split(','))
            correct_answer_indices = set(json.loads(answer['correct_answer']))

            if student_answer_indices == correct_answer_indices:
                score += 1

    final_score = (score / total_objective_questions) * 100 if total_objective_questions > 0 else 0
    cur.execute("UPDATE exam_submissions SET score = %s WHERE id = %s", (final_score, submission_id))
    conn.commit()

    cur.close()
    conn.close()

@app.route('/student/exam/submit', methods=['POST'])
@login_required
def submit_exam_route():
    data = request.json
    submission_id = data['submission_id']

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE exam_submissions SET status = 'submitted', end_time = %s WHERE id = %s",
        (datetime.utcnow(), submission_id)
    )
    conn.commit()
    cur.close()
    conn.close()

    calculate_score(submission_id)

    flash('Exam submitted successfully!')
    return jsonify({'status': 'success'})

@app.route('/student/results/<int:submission_id>')
@login_required
def view_results(submission_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute("SELECT * FROM exam_submissions WHERE id = %s AND student_id = %s", (submission_id, current_user.id))
    submission = cur.fetchone()

    cur.execute("SELECT * FROM exams WHERE id = %s", (submission['exam_id'],))
    exam = cur.fetchone()

    cur.execute("""
        SELECT q.*, sa.answer_text
        FROM questions q
        JOIN student_answers sa ON q.id = sa.question_id
        WHERE sa.submission_id = %s
    """, (submission_id,))
    answers = cur.fetchall()

    results = []
    for answer in answers:
        is_correct = False
        if answer['question_type'] in ['single-choice', 'multiple-choice']:
            student_ans = set(answer['answer_text'].split(','))
            correct_ans = set(json.loads(answer['correct_answer']))
            if student_ans == correct_ans:
                is_correct = True
        else:
            if answer['answer_text'].lower() == answer['correct_answer'].lower():
                is_correct = True

        results.append({
            'question': answer,
            'student_answer': answer,
            'is_correct': is_correct
        })

    cur.close()
    conn.close()
    return render_template('view_results.html', exam=exam, submission=submission, results=results)

@app.route('/teacher/analytics/', defaults={'exam_id': None})
@app.route('/teacher/analytics/<int:exam_id>')
@login_required
def teacher_analytics(exam_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    if exam_id:
        cur.execute("SELECT * FROM exams WHERE id = %s AND teacher_id = %s", (exam_id, current_user.id))
        exam = cur.fetchone()
        cur.execute("""
            SELECT u.fullname, s.score
            FROM exam_submissions s
            JOIN users u ON s.student_id = u.id
            WHERE s.exam_id = %s AND s.status = 'submitted'
        """, (exam_id,))
        submissions = cur.fetchall()
    else:
        exam = None
        cur.execute("""
            SELECT u.fullname, s.score
            FROM exam_submissions s
            JOIN users u ON s.student_id = u.id
            JOIN exams e ON s.exam_id = e.id
            WHERE e.teacher_id = %s AND s.status = 'submitted'
        """, (current_user.id,))
        submissions = cur.fetchall()

    average_score = sum([s['score'] for s in submissions]) / len(submissions) if submissions else 0

    # Calculate completion rate for all exams
    cur.execute("SELECT COUNT(DISTINCT student_id) FROM exam_submissions WHERE exam_id IN (SELECT id FROM exams WHERE teacher_id = %s)", (current_user.id,))
    total_students_with_submissions = cur.fetchone()[0]

    cur.execute("SELECT COUNT(DISTINCT id) FROM users WHERE role = 'student' AND class IN (SELECT DISTINCT class FROM exams WHERE teacher_id = %s)", (current_user.id,))
    total_students_in_classes = cur.fetchone()[0]

    completion_rate = (total_students_with_submissions / total_students_in_classes) * 100 if total_students_in_classes > 0 else 0


    cur.close()
    conn.close()
    return render_template('teacher_analytics.html', exam=exam, submissions=submissions, average_score=average_score, completion_rate=completion_rate)

@app.route('/teacher/exam/<int:exam_id>/export/<format>')
@login_required
def export_results(exam_id, format):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute("SELECT * FROM exams WHERE id = %s AND teacher_id = %s", (exam_id, current_user.id))
    exam = cur.fetchone()

    cur.execute("""
        SELECT u.fullname, s.score
        FROM exam_submissions s
        JOIN users u ON s.student_id = u.id
        WHERE s.exam_id = %s AND s.status = 'submitted'
    """, (exam_id,))
    submissions = cur.fetchall()
    cur.close()
    conn.close()

    if format == 'csv':
        output = BytesIO()
        writer = pd.DataFrame(submissions).to_csv(index=False)
        output.write(writer.encode('utf-8'))
        output.seek(0)
        return make_response(output.getvalue(), 200, {'Content-Disposition': f'attachment; filename=results_{exam_id}.csv', 'Content-Type': 'text/csv'})

    elif format == 'pdf':
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font('Arial', 'B', 16)
        pdf.cell(200, 10, txt=f"UCH Staff Secondary School - {exam['title']}", ln=1, align='C')

        for sub in submissions:
            pdf.cell(200, 10, txt=f"{sub['fullname']}: {sub['score']}%", ln=1)

        output = BytesIO(pdf.output(dest='S').encode('latin-1'))
        return make_response(output.getvalue(), 200, {'Content-Disposition': f'attachment; filename=results_{exam_id}.pdf', 'Content-Type': 'application/pdf'})

    return redirect(url_for('teacher_analytics', exam_id=exam_id))

# Student routes
@app.route('/student/login', methods=['GET', 'POST'])
def student_login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("SELECT * FROM users WHERE email = %s AND role = 'student'", (email,))
        user_data = cur.fetchone()
        cur.close()
        conn.close()

        if user_data and check_password_hash(user_data['password_hash'], password):
            user = User(id=user_data['id'], fullname=user_data['fullname'], email=user_data['email'], role=user_data['role'])
            login_user(user)
            return redirect(url_for('student_dashboard'))
        else:
            flash('Invalid email or password.')

    return render_template('student_login.html')

@app.route('/student/register', methods=['GET', 'POST'])
def student_register():
    if request.method == 'POST':
        fullname = request.form['fullname']
        email = request.form['email']
        password = request.form['password']
        gender = request.form['gender']
        student_class = request.form['class']

        password_hash = generate_password_hash(password)

        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO users (fullname, email, password_hash, role, gender, class) VALUES (%s, %s, %s, 'student', %s, %s)",
                (fullname, email, password_hash, gender, student_class)
            )
            conn.commit()
            flash('Registration successful. Please login.')
            return redirect(url_for('student_login'))
        except psycopg2.IntegrityError:
            flash('Email already registered.')
        finally:
            cur.close()
            conn.close()

    return render_template('student_register.html')

@app.route('/student/dashboard')
@login_required
def student_dashboard():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    now = datetime.utcnow()

    cur.execute("""
        SELECT e.* FROM exams e
        LEFT JOIN exam_submissions s ON e.id = s.exam_id AND s.student_id = %s
        WHERE s.id IS NULL AND e.start_time <= %s AND e.end_time >= %s
    """, (current_user.id, now, now))
    available_exams = cur.fetchall()

    cur.execute("""
        SELECT e.* FROM exams e
        WHERE e.start_time > %s
    """, (now,))
    upcoming_exams = cur.fetchall()

    cur.execute("""
        SELECT e.id, e.title, e.class, s.id as submission_id, s.score, e.delay_results FROM exams e
        JOIN exam_submissions s ON e.id = s.exam_id
        WHERE s.student_id = %s AND s.status = 'submitted'
    """, (current_user.id,))
    completed_exams = cur.fetchall()

    cur.close()
    conn.close()
    return render_template('student_dashboard.html', available_exams=available_exams, upcoming_exams=upcoming_exams, completed_exams=completed_exams, now=now)

@app.route('/student/exam/start/<int:exam_id>')
@login_required
def start_exam(exam_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        cur.execute(
            "INSERT INTO exam_submissions (student_id, exam_id) VALUES (%s, %s) RETURNING id",
            (current_user.id, exam_id)
        )
        submission_id = cur.fetchone()['id']
        conn.commit()
    except psycopg2.IntegrityError:
        conn.rollback()
        cur.execute("SELECT id FROM exam_submissions WHERE student_id = %s AND exam_id = %s", (current_user.id, exam_id))
        submission_id = cur.fetchone()['id']

    cur.execute("SELECT * FROM exams WHERE id = %s", (exam_id,))
    exam = cur.fetchone()

    if exam['randomize_questions']:
        cur.execute("SELECT * FROM questions WHERE exam_id = %s ORDER BY RANDOM()", (exam_id,))
    else:
        cur.execute("SELECT * FROM questions WHERE exam_id = %s ORDER BY id", (exam_id,))
    questions = cur.fetchall()

    cur.close()
    conn.close()
    return render_template('take_exam.html', exam=exam, questions=questions, submission_id=submission_id)

@app.route('/student/exam/save_answer', methods=['POST'])
@login_required
def save_answer():
    data = request.json
    submission_id = data['submission_id']
    question_id = data['question_id']
    answer_text = data['answer_text']
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM student_answers WHERE submission_id = %s AND question_id = %s", (submission_id, question_id))
    exists = cur.fetchone()
    if exists:
        cur.execute(
            "UPDATE student_answers SET answer_text = %s WHERE id = %s",
            (answer_text, exists[0])
        )
    else:
        cur.execute(
            "INSERT INTO student_answers (submission_id, question_id, answer_text) VALUES (%s, %s, %s)",
            (submission_id, question_id, answer_text)
        )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'status': 'success'})

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('index'))

# Admin routes
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("SELECT * FROM users WHERE email = %s AND role = 'admin'", (email,))
        user_data = cur.fetchone()
        cur.close()
        conn.close()

        if user_data and check_password_hash(user_data['password_hash'], password):
            user = User(id=user_data['id'], fullname=user_data['fullname'], email=user_data['email'], role=user_data['role'])
            login_user(user)
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid email or password.')

    return render_template('admin_login.html')

@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT id, fullname, email FROM users WHERE role = 'teacher' AND status = 'pending'")
    pending_teachers = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('admin_dashboard.html', pending_teachers=pending_teachers)

@app.route('/admin/teacher/approve/<int:teacher_id>')
@login_required
def approve_teacher(teacher_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET status = 'approved' WHERE id = %s", (teacher_id,))
    conn.commit()
    cur.close()
    conn.close()
    flash('Teacher approved.')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/teacher/decline/<int:teacher_id>')
@login_required
def decline_teacher(teacher_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM users WHERE id = %s", (teacher_id,))
    conn.commit()
    cur.close()
    conn.close()
    flash('Teacher declined.')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/users')
@login_required
def manage_users():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT id, fullname, email, role FROM users")
    users = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('manage_users.html', users=users)

@app.route('/admin/analytics')
@login_required
def admin_analytics():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute("SELECT COUNT(*) as total_users FROM users")
    total_users = cur.fetchone()['total_users']

    cur.execute("SELECT COUNT(*) as total_teachers FROM users WHERE role = 'teacher'")
    total_teachers = cur.fetchone()['total_teachers']

    cur.execute("SELECT COUNT(*) as total_students FROM users WHERE role = 'student'")
    total_students = cur.fetchone()['total_students']

    cur.execute("SELECT COUNT(*) as total_exams FROM exams")
    total_exams = cur.fetchone()['total_exams']

    cur.execute("SELECT COUNT(*) as total_submissions FROM exam_submissions")
    total_submissions = cur.fetchone()['total_submissions']

    cur.execute("SELECT AVG(score) as average_score FROM exam_submissions WHERE score IS NOT NULL")
    average_score = cur.fetchone()['average_score'] or 0

    stats = {
        'total_users': total_users,
        'total_teachers': total_teachers,
        'total_students': total_students,
        'total_exams': total_exams,
        'total_submissions': total_submissions,
        'average_score': average_score
    }

    cur.close()
    conn.close()
    return render_template('admin_analytics.html', stats=stats)

@app.route('/admin/users/bulk_import', methods=['POST'])
@login_required
def bulk_import_users():
    file = request.files['file']
    if not file:
        flash('No file selected for upload.')
        return redirect(url_for('manage_users'))

    if file.filename.endswith('.xlsx'):
        df = pd.read_excel(file)
        conn = get_db_connection()
        cur = conn.cursor()

        for index, row in df.iterrows():
            password_hash = generate_password_hash(row['password'])
            try:
                cur.execute(
                    "INSERT INTO users (fullname, email, password_hash, role, gender, class) VALUES (%s, %s, %s, %s, %s, %s)",
                    (row['fullname'], row['email'], password_hash, row['role'], row['gender'], row['class'])
                )
            except psycopg2.IntegrityError:
                conn.rollback()
            else:
                conn.commit()

        cur.close()
        conn.close()
        flash('Bulk user import completed.')
    else:
        flash('Invalid file format. Please upload an Excel file (.xlsx).')

    return redirect(url_for('manage_users'))

@app.route('/admin/users/export')
@login_required
def export_users():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT fullname, email, role, gender, class FROM users")
    users = cur.fetchall()
    cur.close()
    conn.close()

    df = pd.DataFrame(users)
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='xlsxwriter')
    df.to_excel(writer, index=False, sheet_name='Users')
    writer.close()
    output.seek(0)

    return make_response(output.getvalue(), 200, {
        'Content-Disposition': 'attachment; filename=all_users.xlsx',
        'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    })

@app.route('/admin/user/edit/<int:user_id>', methods=['GET', 'POST'])
@login_required
def edit_user(user_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    if request.method == 'POST':
        fullname = request.form['fullname']
        email = request.form['email']
        role = request.form['role']
        cur.execute("UPDATE users SET fullname = %s, email = %s, role = %s WHERE id = %s",
                    (fullname, email, role, user_id))
        conn.commit()
        cur.close()
        conn.close()
        flash('User updated successfully.')
        return redirect(url_for('manage_users'))

    cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    cur.close()
    conn.close()
    return render_template('edit_user.html', user=user)

@app.route('/admin/user/reset_password/<int:user_id>')
@login_required
def admin_reset_password(user_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()

    if user:
        token = secrets.token_urlsafe(16)
        expires_at = datetime.utcnow() + timedelta(hours=1)
        cur.execute("INSERT INTO password_reset_tokens (user_id, token, expires_at) VALUES (%s, %s, %s)",
                    (user['id'], token, expires_at))
        conn.commit()

        reset_link = url_for('reset_password', token=token, _external=True)
        send_email(
            subject='Password Reset Initiated by Admin',
            recipients=[user['email']],
            body=f'An admin has initiated a password reset for your account. Click the following link to reset your password: {reset_link}'
        )
        flash(f"A password reset link has been sent to {user['email']}.")
    else:
        flash('User not found.')

    cur.close()
    conn.close()
    return redirect(url_for('manage_users'))

@app.route('/admin/user/delete/<int:user_id>')
@login_required
def delete_user(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
    conn.commit()
    cur.close()
    conn.close()
    flash('User deleted successfully.')
    return redirect(url_for('manage_users'))

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        fullname = request.form['fullname']
        email = request.form['email']

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE users SET fullname = %s, email = %s WHERE id = %s", (fullname, email, current_user.id))

        if 'profile_image' in request.files:
            file = request.files['profile_image']
            if file.filename != '':
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                cur.execute("UPDATE users SET profile_image = %s WHERE id = %s", (filename, current_user.id))

        conn.commit()
        cur.close()
        conn.close()
        flash('Profile updated successfully.')
        return redirect(url_for('profile'))

    return render_template('profile.html')

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form['email']
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cur.fetchone()

        if user:
            token = secrets.token_urlsafe(16)
            expires_at = datetime.utcnow() + timedelta(hours=1)
            cur.execute("INSERT INTO password_reset_tokens (user_id, token, expires_at) VALUES (%s, %s, %s)",
                        (user['id'], token, expires_at))
            conn.commit()

            reset_link = url_for('reset_password', token=token, _external=True)
            send_email(
                subject='Password Reset Request',
                recipients=[user['email']],
                body=f'Click the following link to reset your password: {reset_link}'
            )
            flash('A password reset link has been sent to your email.')
        else:
            flash('Email address not found.')

        cur.close()
        conn.close()
        return redirect(url_for('forgot_password'))

    return render_template('forgot_password.html')

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT * FROM password_reset_tokens WHERE token = %s AND expires_at > %s", (token, datetime.utcnow()))
    token_data = cur.fetchone()

    if not token_data:
        flash('Invalid or expired password reset link.')
        cur.close()
        conn.close()
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        if password != confirm_password:
            flash('Passwords do not match.')
            return render_template('reset_password.html', token=token)

        password_hash = generate_password_hash(password)
        cur.execute("UPDATE users SET password_hash = %s WHERE id = %s", (password_hash, token_data['user_id']))
        cur.execute("DELETE FROM password_reset_tokens WHERE token = %s", (token,))
        conn.commit()

        flash('Your password has been reset successfully.')
        cur.close()
        conn.close()
        return redirect(url_for('student_login'))

    cur.close()
    conn.close()
    return render_template('reset_password.html', token=token)

def get_google_flow():
    """Initializes and returns the Google OAuth Flow object."""
    client_secrets_file = os.path.join(os.path.dirname(__file__), 'client_secret.json')
    return Flow.from_client_secrets_file(
        client_secrets_file,
        scopes=['https://www.googleapis.com/auth/userinfo.profile', 'https://www.googleapis.com/auth/userinfo.email', 'openid'],
        redirect_uri=url_for('google_callback', _external=True)
    )

@app.route('/google/login')
def google_login():
    try:
        flow = get_google_flow()
        authorization_url, state = flow.authorization_url()
        session['state'] = state
        return redirect(authorization_url)
    except FileNotFoundError:
        flash("Google OAuth is not configured. Please add client_secret.json.")
        return redirect(url_for('student_login'))

@app.route('/google/callback')
def google_callback():
    flow = get_google_flow()
    flow.fetch_token(authorization_response=request.url)

    credentials = flow.credentials
    request_session = requests.session()
    cached_session = CacheControl(request_session)
    token_request = google_requests.Request(session=cached_session)

    id_info = id_token.verify_oauth2_token(
        id_token=credentials._id_token,
        request=token_request,
        audience=app.config['GOOGLE_CLIENT_ID']
    )

    email = id_info.get('email')
    name = id_info.get('name')

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT * FROM users WHERE email = %s", (email,))
    user_data = cur.fetchone()

    if not user_data:
        password_hash = generate_password_hash(secrets.token_hex(16))
        cur.execute("INSERT INTO users (fullname, email, password_hash, role, status) VALUES (%s, %s, %s, 'student', 'approved')",
                    (name, email, password_hash))
        conn.commit()
        cur.execute("SELECT * FROM users WHERE email = %s", (email,))
        user_data = cur.fetchone()

    user = User(id=user_data['id'], fullname=user_data['fullname'], email=user_data['email'], role=user_data['role'])
    login_user(user)

    cur.close()
    conn.close()
    return redirect(url_for('student_dashboard'))

if __name__ == '__main__':
    app.run(debug=True)