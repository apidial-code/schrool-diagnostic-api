"""
Schrool Diagnostic Tests Backend - Final Clean Production Version v2
print("🔥 THIS IS THE ACTIVE APP.PY 🔥")
Features:
- Brevo email delivery
- Explicit CORS allowlist for Schrool frontend domains
- SQLite persistence for first/second test flow
- Tokenized continuation links for emailed second-test path
- /api/continue endpoint for restoring student/session identity
- First test email, combined results email, and follow-up email
"""
from flask import Flask, request, jsonify
from flask_cors import CORS, cross_origin
import os
from datetime import datetime, timedelta
import requests
import sqlite3
import secrets
from contextlib import contextmanager

def singapore_level_label(curriculum, grade):
    try:
        grade_num = int(str(grade).strip())
    except:
        return f"Year {grade}"

    if str(curriculum).strip().lower() == "singapore":
        if grade_num <= 6:
            return f"Primary {grade_num}"
        return f"Secondary {grade_num - 6}"

    return f"Year {grade_num}"
def singapore_file_label(filename, fallback_curriculum, fallback_grade):
    filename = str(filename or "").lower()
    curriculum = str(fallback_curriculum or "").strip().lower()

    if curriculum != "singapore":
        return singapore_level_label(fallback_curriculum, fallback_grade)

    if "singapore-primary" in filename:
        grade = filename.split("singapore-primary")[1].split("-")[0]
        return f"Primary {grade}"

    if "singapore-sec" in filename:
        grade = filename.split("singapore-sec")[1].split("-")[0]
        return f"Secondary {grade}"

    return singapore_level_label(fallback_curriculum, fallback_grade)

app = Flask(__name__)
# ============================================================================
# FLASK APP INITIALIZATION
# ============================================================================

from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)

DB_PATH = "/tmp/test_results.db"

CORS(app, resources={
    r"/api/*": {
        "origins": [
            "https://test.schrool.net",
            "http://test.schrool.net",
            "https://schrool.net",
            "http://schrool.net",
            "http://localhost:3000",
            "http://127.0.0.1:5500"
        ],
        "allow_headers": ["Content-Type", "Authorization"],
        "methods": ["GET", "POST", "OPTIONS"],
        "supports_credentials": True
    }
})

# ============================================================================
# CONFIGURATION
# ============================================================================

BREVO_API_KEY = os.environ.get("BREVO_API_KEY")
BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"

SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "diagnostics@schrool.com")
SENDER_NAME = os.environ.get("SENDER_NAME", "Schrool Diagnostics")

FRONTEND_URL = os.environ.get("FRONTEND_URL", "https://test.schrool.net").rstrip("/")

DATABASE_PATH = os.environ.get("DATABASE_PATH", "/tmp/test_results.db")

# In-memory token store for continuation links
continuation_tokens = {}

# ============================================================================
# DATABASE MANAGEMENT
# ============================================================================

@contextmanager
def get_db():
    conn = sqlite3.connect(DATABASE_PATH, timeout=30)
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_database():
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS test_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_key TEXT UNIQUE NOT NULL,
                parent_email TEXT NOT NULL,
                parent_name TEXT,
                student_name TEXT NOT NULL,
                school_grade TEXT,
                test_curriculum TEXT,
                test1_name TEXT,
                test1_score INTEGER,
                test1_raw TEXT,
                test1_year INTEGER,
                expected_second_year INTEGER,
                test2_name TEXT,
                test2_score INTEGER,
                test2_raw TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_student_key
            ON test_results(student_key)
            """
        )

        seven_days_ago = (datetime.now() - timedelta(days=7)).isoformat()
        conn.execute(
            """
            DELETE FROM test_results
            WHERE created_at < ?
            """,
            (seven_days_ago,),
        )


init_database()

# ============================================================================
# DATABASE OPERATIONS
# ============================================================================

def store_first_test(student_key, data, expected_second_year):
    now = datetime.now().isoformat()
    with get_db() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO test_results (
                student_key, parent_email, parent_name, student_name,
                school_grade, test_curriculum,
                test1_name, test1_score, test1_raw, test1_year, expected_second_year,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                student_key,
                data["parent_email"],
                data.get("parent_name", "Parent"),
                data["student_name"],
                str(data.get("school_grade", "")),
                data["test_curriculum"],
                f"{data['test_curriculum']} Year {data['test_grade']}",
                int(data["percentage"]),
                f"{data['score']}/{data['total']}",
                int(data["test_grade"]),
                int(expected_second_year),
                now,
                now,
            ),
        )


def get_first_test(student_key):
    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT *
            FROM test_results
            WHERE student_key = ?
            """,
            (student_key,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def store_second_test(student_key, data):
    now = datetime.now().isoformat()
    with get_db() as conn:
        conn.execute(
            """
            UPDATE test_results
            SET test2_name = ?,
                test2_score = ?,
                test2_raw = ?,
                updated_at = ?
            WHERE student_key = ?
            """,
            (
                f"{data['test_curriculum']} Year {data['test_grade']}",
                int(data["percentage"]),
                f"{data['score']}/{data['total']}",
                now,
                student_key,
            ),
        )


def cleanup_test_data(student_key):
    with get_db() as conn:
        conn.execute(
            """
            DELETE FROM test_results
            WHERE student_key = ?
            """,
            (student_key,),
        )

# ============================================================================
# HELPERS
# ============================================================================

def normalize_student_key(parent_email, student_name):
    return f"{parent_email}_{student_name}".lower().replace(" ", "_")


def calculate_expected_second_year(student_year, first_test_year):
    difference = student_year - first_test_year
    if difference == 1:
        return student_year - 2
    if difference == 2:
        return student_year - 1
    return None


def get_interpretation(percentage):
    if percentage >= 90:
        return "Excellent! Your child demonstrates strong mastery of the concepts at this grade level."
    if percentage >= 75:
        return "Good performance! Your child has a solid understanding with some areas for improvement."
    if percentage >= 60:
        return "Fair performance. Your child understands basic concepts but needs support in several areas."
    if percentage >= 40:
        return "Your child is struggling with many concepts at this level and would benefit from targeted support."
    return "Your child needs significant support. Consider working with a tutor to build foundational skills."


def get_performance_level(percentage):
    if percentage >= 75:
        return {"level": "Strong", "color": "#059669", "description": "Excellent performance"}
    if percentage >= 60:
        return {"level": "Satisfactory", "color": "#2563eb", "description": "Good performance"}
    if percentage >= 40:
        return {"level": "Needs Improvement", "color": "#d97706", "description": "Needs more practice"}
    return {"level": "Requires Support", "color": "#dc2626", "description": "Requires immediate support"}

# ============================================================================
# HEALTH CHECK
# ============================================================================

@app.route("/")
def home():
    return jsonify({
        "status": "running",
        "service": "Schrool Diagnostic Tests API",
        "version": "3.0-TOKEN-FINAL",
        "email_service": "Brevo",
        "storage": "SQLite Database",
        "routes": [str(rule) for rule in app.url_map.iter_rules()],
        "timestamp": datetime.now().isoformat(),
    }), 200

# ============================================================================
# CONTINUATION TOKEN ENDPOINT
# ============================================================================

@app.route("/api/continue", methods=["GET"])
def continue_test():
    try:
        token = request.args.get("token")

        if not token or token not in continuation_tokens:
            return jsonify({"success": False, "error": "Invalid token"}), 400

        record = continuation_tokens[token]

        expires_at = datetime.fromisoformat(record["expires_at"])
        if datetime.now() > expires_at:
            del continuation_tokens[token]
            return jsonify({"success": False, "error": "Token expired"}), 400

        return jsonify({
            "success": True,
            "parent_email": record["parent_email"],
            "parent_name": record["parent_name"],
            "student_name": record["student_name"],
            "test_curriculum": record["test_curriculum"],
            "expected_second_year": record["expected_second_year"],
        }), 200

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ============================================================================
# EMAIL DELIVERY
# ============================================================================

def send_brevo_email(to_email, to_name, subject, html_content):
    try:
        if not BREVO_API_KEY:
            return {
                "success": False,
                "error": "BREVO_API_KEY is not set in environment variables",
            }

        payload = {
            "sender": {
                "name": SENDER_NAME,
                "email": SENDER_EMAIL,
            },
            "to": [
                {
                    "email": to_email,
                    "name": to_name,
                }
            ],
            "subject": subject,
            "htmlContent": html_content,
        }

        headers = {
            "accept": "application/json",
            "api-key": BREVO_API_KEY,
            "content-type": "application/json",
        }

        response = requests.post(BREVO_API_URL, json=payload, headers=headers, timeout=20)

        if response.status_code in [200, 201]:
            return {"success": True, "message": "Email sent successfully", "email": to_email}

        return {
            "success": False,
            "error": f"Brevo API error: {response.status_code} - {response.text}",
        }

    except Exception as e:
        return {"success": False, "error": f"Failed to send email: {str(e)}"}

# ============================================================================
# EMAIL TEMPLATES
# ============================================================================

def send_first_test_email(data):
    try:
        color = "#e74c3c"
        completed_test_label = f"Year {data.get('test_grade', '')}"
        next_test_label = "Next Test"
        interpretation = "Your child needs significant support. Consider working with a tutor to build foundational skills."
        next_test_section = ""
        student_full_name = data["student_name"]
        student_first_name = student_full_name.split()[0] if student_full_name else "Student"

        deadline = datetime.now() + timedelta(hours=48)
        deadline_str = deadline.strftime("%A, %B %d at %I:%M %p")

        token = secrets.token_urlsafe(24)

        continuation_tokens[token] = {
            "student_key": normalize_student_key(data["parent_email"], data["student_name"]),
            "parent_email": data["parent_email"],
            "parent_name": data.get("parent_name", "Parent"),
            "student_name": data["student_name"],
            "test_curriculum": data["test_curriculum"],
            "first_test_year": int(data["test_grade"]),
            "expected_second_year": int(data.get("next_test_grade") or 0),
            "expires_at": (datetime.now() + timedelta(hours=48)).isoformat(),
        }

        curriculum_slug = data["test_curriculum"].strip().lower()
        next_test_grade = int(data.get("next_test_grade") or 0)
        single_test_final = bool(data.get("single_test_final", False))
        next_test_file = data.get("next_test_file")
        if not next_test_file and next_test_grade:
            next_test_file = f"{curriculum_slug}-year{next_test_grade}-math-test.html"
            
        print("NEXT TEST FILE RECEIVED:", next_test_file)
        print("NEXT TEST GRADE RECEIVED:", next_test_grade)

        if False:
            second_test_link = None
        elif next_test_file:
            second_test_link = (
                f"{FRONTEND_URL}/schrool-fresher/"
                f"{next_test_file}"
                f"?token={token}"
            )
        else:
            if curriculum_slug == "singapore":
                if next_test_grade <= 6:
                    fallback_file = f"singapore-primary{next_test_grade}-math-test.html"
                else:
                    fallback_file = f"singapore-sec{next_test_grade - 6}-math-test.html"
            else:
                fallback_file = f"{curriculum_slug}-year{next_test_grade}-math-test.html"

            second_test_link = (
                f"{FRONTEND_URL}/schrool-fresher/"
                f"{fallback_file}"
                f"?token={token}"
            )

        interpretation = get_interpretation(int(data["percentage"]))
        performance = get_performance_level(int(data["percentage"]))
        color = performance.get("color", "#e74c3c") if isinstance(performance, dict) else "#e74c3c"

        completed_test_label = f"Year {data['test_grade']}"
        if curriculum_slug == "singapore":
            completed_test_label = singapore_level_label(data["test_curriculum"], data["test_grade"])

        next_test_label = f"Year {next_test_grade}" if next_test_grade else "Next Test"

        if curriculum_slug == "singapore":
            next_test_label = singapore_file_label(
                data.get("next_test_file"),
                data["test_curriculum"],
                next_test_grade
            )
        next_test_section = f"""
        <div style="background-color: #fef3c7; padding: 20px; border-radius: 8px; border-left: 4px solid #f59e0b; margin-bottom: 25px;">
            <h3 style="color: #92400e; margin-top: 0; font-size: 18px;">Next Test to Complete</h3>
            <p><strong>{data['test_curriculum']} {next_test_label}</strong></p>
            <p>Please complete this second test within 48 hours so we can provide a full diagnosis of your child's math situation.</p>
            <p><strong>Link expires:</strong> {deadline_str}</p>
        </div>

        <div style="text-align: center; margin: 30px 0;">
            <a href="{second_test_link}"
               style="display: inline-block; background-color: #2563eb; color: white; padding: 15px 40px; text-decoration: none; border-radius: 8px; font-size: 18px; font-weight: bold;">
                Take {data['test_curriculum']} {next_test_label} Test Now
            </a>
        </div>
        """
        html_content = f"""
        
        <!DOCTYPE html>
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; border-radius: 10px 10px 0 0; text-align: center;">
                <h1 style="color: white; margin: 0; font-size: 28px;">⏰ Test 1 Complete!</h1>
            </div>

            <div style="background-color: #f9fafb; padding: 30px; border-radius: 0 0 10px 10px;">
                <p style="font-size: 16px; margin-bottom: 20px;">Dear {data.get('parent_name', 'Parent')},</p>

                <p style="font-size: 16px; margin-bottom: 25px;">
                    <strong>{data['student_name']}</strong> has completed the first diagnostic test.
                </p>

                <div style="background-color: white; padding: 25px; border-radius: 8px; border-left: 4px solid {color}; margin-bottom: 25px;">
                    <h2 style="color: #1f2937; margin-top: 0; font-size: 20px;">First Test Results</h2>
                    <p><strong>Completed test:</strong> {data['test_curriculum']} {completed_test_label}</p>
                    <p><strong>Score:</strong> {data['score']} out of {data['total']} ({data['percentage']}%)</p>
                    <p><strong>Performance Assessment:</strong> {interpretation}</p>
                </div>

                {next_test_section if next_test_section else ""}

                <p style="font-size: 14px; color: #666;">
                    Best regards,<br>
                    <strong>Richard & The Schrool Team</strong>
                </p>
            </div>
        </body>
        </html>
        """

        subject = f"⏰ {data['test_curriculum']} Test 1 Complete - Next Test Ready"
        return send_brevo_email(
            data["parent_email"],
            data.get("parent_name", "Parent"),
            subject,
            html_content
        )
    except Exception as e:
        print("FIRST TEST EMAIL ERROR:", str(e), flush=True)
        return {"success": False, "error": f"Failed to send first test email: {str(e)}"}
def get_combined_observation(p1, p2):
    avg = (p1 + p2) / 2

    if avg < 40:
        return "Across both tests, the student is showing gaps in foundational understanding. This often happens when earlier concepts have not fully settled, making it difficult to build reliably on top."
    elif avg < 75:
        return "The student shows a developing understanding across the two levels, with some areas secure and others less consistent. This usually indicates that key concepts are partially understood but not yet fully integrated."
    else:
        return "The student demonstrates a solid grasp of the material across both levels. The next step is to confirm how this understanding holds as the level of challenge increases."

def send_consultant_booking_email(booking):
    lead_manager_email = os.environ.get("LEAD_MANAGER_EMAIL", "kineticcls@gmail.com")
    consultant_email = booking.get("consultant_email") or os.environ.get("CONSULTANT_EMAIL", "")

    recipient_email = lead_manager_email

    qa = booking.get("qualifying_answers", {})

    answer_maps = {
    "1": {
        "1": "Average performance",
        "2": "Having problems coping",
        "3": "Needs help",
        "4": "Can't do homework",
        "5": "Needs immediate help"
    },
    "2": {
        "1": "My child to be coping with school work",
        "2": "Someone to be working with my child one-on-one",
        "3": "I want my child to do homework on their own",
        "4": "To catch up with classwork"
    },
    "3": {
        "1": "Don't know where to start",
        "2": "Haven't found good tutoring options",
        "3": "Too expensive",
        "4": "No time",
        "5": "Child is resistant to help"
    },
    "4": {
        "1": "Tutoring center classes that didn't work",
        "2": "One-on-one coaching that failed to deliver",
        "3": "I have tried to teach my child myself",
        "4": "I asked my eldest child who is good at math to help",
        "5": "Haven't tried anything yet"
    },
    "5": {
        "1": "Elementary (Grades 1-5)",
        "2": "Middle School (Grades 6-8)",
        "3": "High School (Grades 9-12)",
        "4": "Other"
    },
    "6": {
        "1": "1-2 hours",
        "2": "3-5 hours",
        "3": "6-10 hours",
        "4": "As much as needed"
    },
    "7": {
        "1": "Under $100",
        "2": "$100-$300",
        "3": "$300-$500",
        "4": "$500+",
        "5": "Whatever it takes"
    },
    "8": {
        "1": "Just exploring options",
        "2": "Within the next month",
        "3": "Within the next week",
        "4": "Need help immediately"
    }
}

def qa_text(question, fallback="Not provided"):
    value = str(qa.get(question, "")).strip()
    return answer_maps.get(question, {}).get(value, value or fallback)

    parent_name = booking.get("parent_name", "Parent")
    parent_email = booking.get("parent_email", "")
    phone = booking.get("phone", "")
    student_name = booking.get("student_name", "Student")
    school_grade = booking.get("school_grade", "")
    curriculum = booking.get("test_curriculum", "")
    booking_date = booking.get("booking_date", "")
    booking_time = booking.get("booking_time", "")

    html_content = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 700px; margin: 0 auto; padding: 20px;">

        <h2 style="color:#1f2937;">New Consultation Booking</h2>

        <p>A parent has requested a call after completing the Schrool diagnostic.</p>

        <hr>

        <h3>Customer Profile</h3>

        <p><strong>Parent:</strong> {parent_name}</p>
        <p><strong>Email:</strong> {parent_email}</p>
        <p><strong>Phone:</strong> {phone}</p>
        <p><strong>Student:</strong> {student_name}</p>
        <p><strong>School Year:</strong> {school_grade}</p>
        <p><strong>Curriculum:</strong> {curriculum}</p>

        <p style="margin-top:20px;"><strong>Diagnostic Insights</strong></p>

        <p><strong>Performance:</strong> {qa_text("1")}</p>
        <p><strong>Goal (90 days):</strong> {qa_text("2")}</p>
        <p><strong>Main Obstacle:</strong> {qa_text("3")}</p>
        <p><strong>Previous Attempts:</strong> {qa_text("4")}</p>
        <p><strong>School Level:</strong> {qa_text("5")}</p>
        <p><strong>Weekly Time:</strong> {qa_text("6")}</p>
        <p><strong>Budget:</strong> {qa_text("7")}</p>
        <p><strong>Urgency:</strong> {qa_text("8")}</p>
        <p><strong>Additional Notes:</strong> {qa.get("9", "Not provided")}</p>


        <hr>

        <h3>Parent’s Situation</h3>

        <p><strong>Current performance:</strong> {booking.get("performance", "Not provided")}</p>
        <p><strong>Goal for next 90 days:</strong> {booking.get("goal", "Not provided")}</p>
        <p><strong>Main obstacle:</strong> {booking.get("obstacle", "Not provided")}</p>
        <p><strong>What they have tried:</strong> {booking.get("attempts", "Not provided")}</p>
        <p><strong>Time available weekly:</strong> {booking.get("time_commitment", "Not provided")}</p>
        <p><strong>Monthly budget:</strong> {booking.get("budget", "Not provided")}</p>
        <p><strong>Urgency:</strong> {booking.get("urgency", "Not provided")}</p>

        <hr>

        <h3>Additional Notes</h3>
        <p>{booking.get("notes", "No additional notes provided.")}</p>

        <hr>

        <h3>Booked Call</h3>
        <p><strong>Date:</strong> {booking_date}</p>
        <p><strong>Time:</strong> {booking_time}</p>

        <hr>

        <h3>Consultant Guidance</h3>
        <p>
            Focus first on the parent’s stated concern, then connect it gently to the diagnostic results.
            Avoid starting with a programme pitch. Begin by clarifying the child’s current level and the pattern shown in the results.
        </p>

    </body>
    </html>
    """

    subject = f"New Consultation Booking - {student_name}"

    return send_brevo_email(
        recipient_email,
        "Schrool System",
        subject,
        html_content
    )
def send_parent_booking_confirmation_email(booking):
    parent_email = booking.get("parent_email", "")
    parent_name = booking.get("parent_name", "Parent")
    student_name = booking.get("student_name", "your child")
    booking_date = booking.get("booking_date", "")
    booking_time = booking.get("booking_time", "")

    if not parent_email:
        return {"success": False, "error": "Parent email missing"}

    html_content = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 650px; margin: 0 auto; padding: 20px;">
        <h2 style="color:#2563eb;">Your Schrool Results Call is Confirmed</h2>

        <p>Dear {parent_name},</p>

        <p>Your call to go through {student_name}'s diagnostic results has been booked.</p>

        <div style="background:#f9fafb; border-left:4px solid #2563eb; padding:18px; border-radius:8px; margin:25px 0;">
            <p><strong>Date:</strong> {booking_date}</p>
            <p><strong>Time:</strong> {booking_time}</p>
        </div>

        <p>During the call, we will go through what the diagnostic results suggest about {student_name}'s current level and answer any questions you may have.</p>

        <p>Best regards,<br>
        <strong>Richard & The Schrool Team</strong></p>
    </body>
    </html>
    """

    subject = f"Your Schrool Results Call is Confirmed - {student_name}"

    return send_brevo_email(
        parent_email,
        parent_name,
        subject,
        html_content
    )

def send_parent_booking_reminder_email(booking):
    parent_email = booking.get("parent_email", "")
    parent_name = booking.get("parent_name", "Parent")
    student_name = booking.get("student_name", "your child")
    booking_date = booking.get("booking_date", "")
    booking_time = booking.get("booking_time", "")

    if not parent_email:
        return {"success": False, "error": "Parent email missing"}

    html_content = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 650px; margin: 0 auto; padding: 20px;">
        <h2 style="color:#2563eb;">Reminder: Your Schrool Call is Tomorrow</h2>

        <p>Dear {parent_name},</p>

        <p>This is a reminder of your scheduled call to go through {student_name}'s diagnostic results.</p>

        <div style="background:#f9fafb; border-left:4px solid #2563eb; padding:18px; border-radius:8px; margin:25px 0;">
            <p><strong>Date:</strong> {booking_date}</p>
            <p><strong>Time:</strong> {booking_time}</p>
        </div>

        <p>We look forward to speaking with you.</p>

        <p>Best regards,<br>
        <strong>Richard & The Schrool Team</strong></p>
    </body>
    </html>
    """

    subject = f"Reminder: Your Schrool Call Tomorrow - {student_name}"

    return send_brevo_email(
        parent_email,
        parent_name,
        subject,
        html_content
    )
def send_combined_results_email(first_test, second_test):
    try:
        data = {
            "parent_name": second_test.get("parent_name") or first_test.get("parent_name", "Parent"),
            "parent_email": second_test.get("parent_email") or first_test.get("parent_email"),
            "student_name": second_test.get("student_name") or first_test.get("student_name"),

            # FIRST TEST: read old stored format first, then fall back to new format
            "test1_name": first_test.get("test1_name") or f"Year {first_test.get('grade') or first_test.get('test_grade') or first_test.get('test1_year', '')}",
            "test1_score": first_test.get("test1_score", first_test.get("percentage", "N/A")),
            "test1_raw": first_test.get("test1_raw") or f"{first_test.get('score', 0)}/{first_test.get('maxScore', first_test.get('total', 0))}",

            # SECOND TEST: use live second-test payload
            "test2_name": second_test.get("test2_name") or f"Year {second_test.get('grade') or second_test.get('test_grade', '')}",
            "test2_score": second_test.get("test2_score", second_test.get("percentage", "N/A")),
            "test2_raw": second_test.get("test2_raw") or f"{second_test.get('score', 0)}/{second_test.get('maxScore', second_test.get('total', 0))}",
        }
        curriculum = (
            data.get("test_curriculum")
            or first_test.get("test_curriculum")
            or second_test.get("test_curriculum")
            or "Singapore"
        )

        completed_test_label = singapore_level_label(
            curriculum,
            first_test.get("test_grade")
            or first_test.get("grade")
            or first_test.get("test1_year")
            or first_test.get("first_test_year")
        )

        second_grade = second_test.get("test_grade") or second_test.get("grade")

        if str(curriculum).strip().lower() == "singapore":
            first_grade = (
                first_test.get("test_grade")
                or first_test.get("grade")
                or first_test.get("test1_year")
                or first_test.get("first_test_year")
            )

            if str(second_grade).isdigit() and int(second_grade) <= 4 and str(first_grade).isdigit() and int(first_grade) >= 6:
                next_test_label = f"Secondary {second_grade}"
            else:
                next_test_label = singapore_file_label(
                    second_test.get("next_test_file")
                    or second_test.get("test_file")
                    or second_test.get("test_name"),
                    curriculum,
                    second_grade
                )
        else:
            next_test_label = singapore_level_label(curriculum, second_grade)

            observation = get_combined_observation(
                float(str(data.get("test1_score", "0")).replace('%','') or 0),
                float(str(data.get("test2_score", "0")).replace('%','') or 0)
            )

            html_content = f"""
        
        <!DOCTYPE html>
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; border-radius: 10px 10px 0 0; text-align: center;">
                <h1 style="color: white; margin: 0; font-size: 28px;">🎉 Congratulations!</h1>
            </div>

            <div style="background-color: #f9fafb; padding: 30px; border-radius: 0 0 10px 10px;">
                <p style="font-size: 16px; margin-bottom: 20px;">Dear {data.get('parent_name', 'Parent')},</p>

                <p style="font-size: 16px; margin-bottom: 25px;">
                    <strong>{data['student_name']}</strong> has completed both diagnostic tests!
                </p>

                <div style="background-color: #ecfdf5; padding: 25px; border-radius: 8px; border-left: 4px solid #059669; margin-bottom: 25px;">
                    <h2 style="color: #065f46; margin-top: 0; font-size: 20px;">Complete Results Summary</h2>

                    <p><strong>Test 1:</strong> {curriculum} {completed_test_label} -
                    <strong style="color: #059669;">{data.get('test1_score')}%</strong></p>
                    <p style="font-size: 14px; color: #666; margin-left: 20px;">Raw Score: {data.get('test1_raw')}</p>

                    <p style="margin-top: 20px;"><strong>Test 2:</strong> {curriculum} {next_test_label} -
                    <strong style="color: #059669;">{data.get('test2_score')}%</strong></p>
                    <p style="font-size: 14px; color: #666; margin-left: 20px;">Raw Score: {data.get('test2_raw')}</p>
                </div>
                <div style="background-color: #f9fafb; padding: 25px; border-radius: 8px; margin-bottom: 25px; border-left: 4px solid #059669;">
    
    <h3 style="color: #065f46; margin-top: 0;">Observation</h3>
    
    <p style="font-size: 14px; color: #444;">
        {observation}
    </p>

    <br>

    <h3 style="color: #065f46;">What this means</h3>

    <p style="font-size: 14px; color: #444;">
        The results are not only a measure of performance, but an indication of how stable the underlying understanding is.
        <br><br>
        In many cases, students can appear to cope with a topic, but still rely on fragile methods that do not hold as the level increases.
    </p>

    <br>

    <p style="font-size: 14px; color: #444;">
        The purpose of this diagnostic is to identify these patterns early, before they become more difficult to address at higher levels.
    </p>

    <br>

    <p style="font-size: 14px; color: #444;">
        If you would like to understand how these results translate into your child’s current level, you can select a suitable time this week and we will go through them with you.
    </p>

    <br><br>

    <a href="https://test.schrool.net/schrool-fresher/booking.html"
       style="display:inline-block;background:#2563eb;color:#ffffff;
       padding:14px 22px;border-radius:8px;text-decoration:none;
       font-weight:bold;margin-top:10px;">
       Book a Free Diagnostic Review
   </a>

</div>

<p style="font-size: 14px; color: #666;">
    Best regards,<br>
    <strong>Richard & The Schrool Team</strong>
</p>
        </body>
        </html>
        """

        subject = f"🎉 Complete Diagnostic Results for {data['student_name']}"
        to_name = data.get("parent_name", "Parent")
        return send_brevo_email(data["parent_email"], to_name, subject, html_content)

    except Exception as e:
        return {"success": False, "error": str(e)}
def send_followup_email(data):
    try:
        test1_score = int(data.get("test1_score", 0) or 0)
        test2_score = int(data.get("test2_score", 0) or 0)

        avg_score = (test1_score + test2_score) / 2 if test1_score and test2_score else 0

        html_content = f"""
        <html>
        <body style="font-family: Arial; max-width:600px; margin:auto; padding:20px;">
            <h2>📊 Personalized Analysis</h2>
            <p>Dear {data.get('parent_name', 'Parent')},</p>
            <p>We have reviewed {data['student_name']}'s diagnostic results.</p>

            <p><strong>Average Score:</strong> {avg_score:.0f}%</p>

            <p>We will send tailored recommendations within 72 hours.</p>

            <br>
            <p>Richard & The Schrool Team</p>
        </body>
        </html>
        """

        subject = f"📊 Analysis for {data['student_name']}"

        return send_brevo_email(
            data["parent_email"],
            data.get("parent_name", "Parent"),
            subject,
            html_content
        )

    except Exception as e:
        return {"success": False, "error": str(e)}

        subject = f"📊 Analysis for {data['student_name']}"

        return send_brevo_email(
            data["parent_email"],
            data.get("parent_name", "Parent"),
            subject,
            html_content
        )

    except Exception as e:
        return {"success": False, "error": str(e)}
        subject = f"🎉 Complete Diagnostic Results for {data['student_name']}"
        to_name = data.get("parent_name", "Parent")
        return send_brevo_email(data["parent_email"], to_name, subject, html_content)

    except Exception as e:
        return {"success": False, "error": str(e)}

# ============================================================================
# MAIN API ENDPOINT
# ============================================================================

@app.route('/api/submit-test', methods=['POST', 'OPTIONS'])
def submit_test():
    if request.method == 'OPTIONS':
       
        response = jsonify({'status': 'ok'})
        response.headers.add("Access-Control-Allow-Origin", "https://test.schrool.net")
        response.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization")
        response.headers.add("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        return response, 200

    try:
        data = request.get_json(silent=True) or {}
        is_first_test = bool(data.get("is_first_test", False))
        token = data.get("token")
        school_grade_raw = data.get("school_grade")
        send_email_only = bool(data.get("send_email_only", False))
        single_test_final = bool(data.get("single_test_final", False))
        required_fields = [
            "parent_email",
            "student_name",
            "test_curriculum",
            "test_grade",
            "score",
            "total",
            "percentage",
        ]

        for field in required_fields:
            if field not in data or data[field] in (None, ""):
                return jsonify({"success": False, "error": f"Missing required field: {field}"}), 400

        parent_email = data["parent_email"]
        student_name = data["student_name"]
        student_key = normalize_student_key(parent_email, student_name)

        is_first_test = bool(data.get("is_first_test", False))
        school_grade_raw = data.get("school_grade", "")
        token = data.get("token")

        # Token override for continuation flow
        if token:
            if token not in continuation_tokens:
                return jsonify({"success": False, "error": "Invalid continuation token"}), 400

            token_record = continuation_tokens[token]
            expires_at = datetime.fromisoformat(token_record["expires_at"])
            if datetime.now() > expires_at:
                del continuation_tokens[token]
                return jsonify({"success": False, "error": "Continuation token expired"}), 400

            expected_second_year = int(token_record["expected_second_year"])
            submitted_year = int(data["test_grade"])

            if submitted_year != expected_second_year:
                return jsonify({
                    "success": False,
                    "error": f"Incorrect second test submitted. Expected Year {expected_second_year}, but received Year {submitted_year}."
                }), 400

        # only override when token is present (continuation flow)
        if token:
            is_first_test = False
            data["parent_email"] = token_record["parent_email"]
            data["parent_name"] = token_record["parent_name"]
            data["student_name"] = token_record["student_name"]
            data["test_curriculum"] = token_record["test_curriculum"]
            student_key = token_record["student_key"]

        # SEND FIRST EMAIL ONLY, used when parent clicks "Do Test Later"
        if send_email_only:
            expected_second_year = int(data.get("next_test_grade", 0) or 0)

            if not expected_second_year and not single_test_final:
                return jsonify({
                    "success": False,
                    "error": "Missing next_test_grade for email-only flow"
                }), 400

            if expected_second_year:
                data["next_test_grade"] = expected_second_year

            # store or refresh first test record before sending email
            
            store_first_test(student_key, data, expected_second_year)

            result = send_first_test_email(data)

            if result.get("success"):
                return jsonify({
                    "success": True,
                    "message": "First test email sent successfully",
                    "email": data["parent_email"],
                    "test_number": 1,
                    "email_only": True
                }), 200

            return jsonify({
                "success": False,
                "error": result.get("error", "Failed to send email"),
            }), 500

        # ACTUAL FIRST TEST SUBMISSION
        if is_first_test:
            if not school_grade_raw:
                return jsonify({
                    "success": False,
                    "error": "Missing required field: school_grade"
                }), 400

            student_year = int(school_grade_raw)
            first_test_year = int(data["test_grade"])
            expected_second_year = calculate_expected_second_year(student_year, first_test_year)

            if expected_second_year is None:
                return jsonify({
                    "success": False,
                    "error": (
                        f"Invalid test year selected. Student year is {student_year}, "
                        f"test year is {first_test_year}. Expected {student_year - 1} or {student_year - 2}."
                    ),
                }), 400

            data["next_test_grade"] = expected_second_year

            # always store first test here
            store_first_test(student_key, data, expected_second_year)

            # same-session flow: store only, do not send email yet
            if bool(data.get("store_only", False)):
                return jsonify({
                    "success": True,
                    "message": "First test stored successfully without email",
                    "email": data["parent_email"],
                    "test_number": 1,
                    "stored_only": True,
                }), 200

            # first test was stored successfully
            # do not send first email here
            return jsonify({
                "success": True,
                "message": "First test stored successfully without email",
                "email": data["parent_email"],
                "test_number": 1,
                "stored_only": True
            }), 200
        # SECOND TEST
        first_test = get_first_test(student_key)
        if not first_test:
            return jsonify({
                "success": False,
                "error": "First test record not found"
            }), 404

        second_test = {
            "grade": data["test_grade"],
            "test_grade": data["test_grade"],
            "score": data["score"],
            "maxScore": data["total"],
            "total": data["total"],
            "percentage": data["percentage"],
            "test_curriculum": data["test_curriculum"],
            "student_name": data["student_name"],
            "parent_email": data["parent_email"],
            "parent_name": data.get("parent_name", "Parent")
        }
        
        print("FIRST TEST DATA:", first_test)
        print("SECOND TEST DATA:", second_test)
        result = send_combined_results_email(first_test, second_test)
        
        if result.get("success"):
            return jsonify({
                "success": True,
                "message": "Combined results email sent successfully",
                "email": data["parent_email"],
                "test_number": 2
            }), 200

        return jsonify({
            "success": False,
            "error": result.get("error", "Failed to send combined results email"),
        }), 500

    except Exception as e:
        print(f"Error in submit_test: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.errorhandler(404)
def not_found(error):
    return jsonify({"success": False, "error": "Endpoint not found"}), 404


@app.errorhandler(500)
def internal_error(error):
    return jsonify({"success": False, "error": "Internal server error"}), 500

# ============================================================================
# APPLICATION ENTRY POINT
# ============================================================================
# ============================================================
# BOOKING SYSTEM
# ============================================================

def init_booking_table():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA busy_timeout = 30000")
    cursor = conn.cursor()


    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parent_name TEXT,
            parent_email TEXT,
            phone TEXT,
            student_name TEXT,
            school_grade TEXT,
            test_curriculum TEXT,
            booking_date TEXT,
            booking_time TEXT,
            performance TEXT,
            goal TEXT,
            obstacle TEXT,
            attempts TEXT,
            time_commitment TEXT,
            budget TEXT,
            urgency TEXT,
            notes TEXT,
            consultant_email TEXT,
            reminder_sent INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    try:
        cursor.execute("ALTER TABLE bookings ADD COLUMN reminder_sent INTEGER DEFAULT 0")
    except Exception:
        pass

    conn.commit()
    conn.close()

@app.route("/api/booking-slots", methods=["GET"])
def get_booking_slots():
    try:
        init_booking_table()

        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.execute("PRAGMA busy_timeout = 30000")
        cursor = conn.cursor()

        cursor.execute("""
            SELECT booking_date, booking_time
            FROM bookings
        """)

        rows = cursor.fetchall()
        conn.close()

        booked_slots = [
            {
                "booking_date": row[0],
                "booking_time": row[1]
            }
            for row in rows
        ]

        return jsonify({
            "success": True,
            "booked_slots": booked_slots
        }), 200

    except Exception as e:
        print("BOOKING SLOTS ERROR:", str(e), flush=True)
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/api/book-slot", methods=["POST", "OPTIONS"])
def book_slot():
    if request.method == "OPTIONS":
        return jsonify({"success": True}), 200

    try:
        init_booking_table()

        data = request.get_json() or {}

        booking_date = data.get("booking_date")
        booking_time = data.get("booking_time")

        if not booking_date or not booking_time:
            return jsonify({
                "success": False,
                "error": "Missing booking date or time"
            }), 400

        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.execute("PRAGMA busy_timeout = 30000")
        cursor = conn.cursor()

        # Prevent double booking
        cursor.execute("""
            SELECT id FROM bookings
            WHERE booking_date = ? AND booking_time = ?
        """, (booking_date, booking_time))

        existing = cursor.fetchone()

        if existing:
            conn.close()
            return jsonify({
                "success": False,
                "error": "This slot has already been booked"
            }), 409

        cursor.execute("""
            INSERT INTO bookings (
                parent_name,
                parent_email,
                phone,
                student_name,
                school_grade,
                test_curriculum,
                booking_date,
                booking_time,
                performance,
                goal,
                obstacle,
                attempts,
                time_commitment,
                budget,
                urgency,
                notes,
                consultant_email
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data.get("parent_name", ""),
            data.get("parent_email", ""),
            data.get("phone", ""),
            data.get("student_name", ""),
            data.get("school_grade", ""),
            data.get("test_curriculum", ""),
            booking_date,
            booking_time,
            data.get("performance", ""),
            data.get("goal", ""),
            data.get("obstacle", ""),
            data.get("attempts", ""),
            data.get("time_commitment", ""),
            data.get("budget", ""),
            data.get("urgency", ""),
            data.get("notes", ""),
            data.get("consultant_email", "")
        ))

        conn.commit()
        conn.close()

        send_manager_email({
    "parent_name": data.get("parent_name"),
    "parent_email": data.get("parent_email"),
    "student_name": data.get("student_name"),
    "school_grade": data.get("school_grade"),
    "test_curriculum": data.get("test_curriculum"),
    "booking_date": booking_date,
    "booking_time": booking_time,
    "performance": data.get("performance"),
    "goal": data.get("goal"),
    "obstacle": data.get("obstacle"),
    "attempts": data.get("attempts"),
    "time_commitment": data.get("time_commitment"),
    "budget": data.get("budget"),
    "urgency": data.get("urgency"),
    "notes": data.get("notes")
})


        # Send lead profile to manager or assigned consultant
        send_consultant_booking_email(data)

        # Send confirmation to parent
        send_parent_booking_confirmation_email(data)

        return jsonify({
            "success": True,
            "message": "Booking confirmed",
            "booking_date": booking_date,
            "booking_time": booking_time
        }), 200

    except Exception as e:
        print("BOOK SLOT ERROR:", str(e), flush=True)
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
