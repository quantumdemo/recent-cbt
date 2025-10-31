import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

def get_db_connection():
    conn = psycopg2.connect(os.environ['DATABASE_URL'])
    return conn

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()

    # Users table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        fullname VARCHAR(100) NOT NULL,
        email VARCHAR(100) UNIQUE NOT NULL,
        password_hash VARCHAR(255) NOT NULL,
        role VARCHAR(10) NOT NULL CHECK (role IN ('student', 'teacher', 'admin')),
        gender VARCHAR(10),
        class VARCHAR(50),
        status VARCHAR(10) DEFAULT 'approved',
        profile_image VARCHAR(255),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Exams table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS exams (
        id SERIAL PRIMARY KEY,
        title VARCHAR(255) NOT NULL,
        description TEXT,
        duration INTEGER NOT NULL, -- in minutes
        start_time TIMESTAMP,
        end_time TIMESTAMP,
        teacher_id INTEGER REFERENCES users(id),
        class VARCHAR(50),
        randomize_questions BOOLEAN DEFAULT FALSE,
        elay_results BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Questions table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS questions (
        id SERIAL PRIMARY KEY,
        exam_id INTEGER REFERENCES exams(id) ON DELETE CASCADE,
        question_text TEXT NOT NULL,
        question_image VARCHAR(255),
        question_type VARCHAR(20) NOT NULL CHECK (question_type IN ('single-choice', 'multiple-choice', 'short-answer')),
        options JSONB,
        correct_answer TEXT
    );
    """)

    # Exam Submissions table to track student attempts
    cur.execute("""
    CREATE TABLE IF NOT EXISTS exam_submissions (
        id SERIAL PRIMARY KEY,
        student_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
        exam_id INTEGER REFERENCES exams(id) ON DELETE CASCADE,
        start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        end_time TIMESTAMP,
        score INTEGER,
        status VARCHAR(20) DEFAULT 'in-progress' NOT NULL, -- e.g., in-progress, submitted
        UNIQUE(student_id, exam_id) -- A student can only take an exam once
    );
    """)

    # Student Answers table to store individual answers
    cur.execute("""
    CREATE TABLE IF NOT EXISTS student_answers (
        id SERIAL PRIMARY KEY,
        submission_id INTEGER REFERENCES exam_submissions(id) ON DELETE CASCADE,
        question_id INTEGER REFERENCES questions(id) ON DELETE CASCADE,
        answer_text TEXT
    );
    """)

    # Password Reset Tokens table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS password_reset_tokens (
        id SERIAL PRIMARY KEY,
        user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
        token VARCHAR(255) UNIQUE NOT NULL,
        expires_at TIMESTAMP NOT NULL
    );
    """)

    conn.commit()
    cur.close()
    conn.close()

if __name__ == '__main__':
    init_db()