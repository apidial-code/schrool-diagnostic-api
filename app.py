"""
Schrool Diagnostic Tests Backend
Flask API for handling test submissions and email notifications using Brevo

FIXED VERSION
- Explicit CORS allowlist for Schrool frontend domains
- Proper OPTIONS preflight handling for /api/submit-test
- Cleaned route definition and removed duplicated/corrupted block
- Preserves first-test / second-test email logic
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import os
from datetime import datetime, timedelta
import requests

app = Flask(__name__)

# Explicit CORS configuration for frontend requests
CORS(
    app,
    resources={
        r"/api/*": {
            "origins": [
                "https://test.schrool.net",
                "https://schrool.com",
                "https://www.schrool.com",
            ]
        }
    },
    methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

# Brevo API Key (set in Heroku environment variables)
BREVO_API_KEY = os.environ.get("BREVO_API_KEY")
BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"

# Sender email (must be verified in Brevo)
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "diagnostics@schrool.com")
SENDER_NAME = os.environ.get("SENDER_NAME", "Schrool Diagnostics")

# In-memory storage for test results (temporary solution)
# In production, use a database like PostgreSQL or Redis
test_results_storage = {}

import secrets

continuation_tokens = {}

@app.route("/")
def home():
    """Health check endpoint"""
    return jsonify(
        {
            "status": "running",
            "service": "Schrool Diagnostic Tests API",
            "version": "1.3-CORS-FIXED",
            "email_service": "Brevo",
            "fixes": [
                "Explicit CORS allowlist for Schrool frontend domains",
                "OPTIONS preflight handling for /api/submit-test",
                "Clean route definition",
                "Combined results email logic preserved",
            ],
        }
    )


@app.route("/api/submit-test", methods=["POST", "OPTIONS"])
def submit_test():
    """
    Handle test submission and send results email.

    Expected JSON:
    {
        "parent_name": "John Doe",
        "parent_email": "john@example.com",
        "student_name": "Jane Doe",
        "school_grade": "6",
        "test_curriculum": "Australia",
        "test_grade": "5",
        "score": 18,
        "total": 25,
        "percentage": 72,
        "time_used": 1800
    }
    """
    # Explicit preflight handling
    if request.method == "OPTIONS":
        return ("", 204)

    try:
        data = request.get_json(silent=True) or {}

        # Validate required fields
        required_fields = [
            "parent_email",
            "student_name",
            "school_grade",
            "test_curriculum",
            "test_grade",
            "score",
            "total",
            "percentage",
        ]

        for field in required_fields:
            if field not in data or data[field] in (None, ""):
                return jsonify({"error": f"Missing required field: {field}"}), 400

        # Normalize values
        student_year = int(data["school_grade"])
        test_year = int(data["test_grade"])
        difference = student_year - test_year

        # Only year-1 and year-2 tests are valid
        if difference not in [1, 2]:
            return (
                jsonify(
                    {
                        "error": (
                            f"Invalid test year selected. Student year is {student_year}, "
                            f"test year is {test_year}. Expected {student_year - 1} "
                            f"or {student_year - 2}."
                        )
                    }
                ),
                400,
            )

        # Create unique key for this student
        student_key = f"{data['parent_email']}_{data['student_name']}".lower().replace(" ", "_")

        # Determine the other test automatically
        if difference == 1:
            # Student took Y-1 first, so remaining test is Y-2
            remaining_test_year = student_year - 2
        else:
            # Student took Y-2 first, so remaining test is Y-1
            remaining_test_year = student_year - 1

        # Check whether first test already exists in storage
        first_test_exists = student_key in test_results_storage

        if not first_test_exists:
            # FIRST TEST
            test_results_storage[student_key] = {
                "test1_name": f"{data['test_curriculum']} Year {data['test_grade']}",
                "test1_score": data["percentage"],
                "test1_raw": f"{data['score']}/{data['total']}",
                "test1_year": test_year,
                "remaining_test_year": remaining_test_year,
                "timestamp": datetime.now().isoformat(),
                "parent_name": data.get("parent_name", "Parent"),
                "student_name": data["student_name"],
            }

            # Add next test year into payload for email template
            data["next_test_grade"] = remaining_test_year

            result = send_first_test_email(data)

        else:
            # SECOND TEST
            first_test = test_results_storage.get(student_key, {})

            first_test_year = first_test.get('test1_year')
            expected_second_year = first_test.get('remaining_test_year')

            # Reject duplicate submission of the same first test
            if test_year == first_test_year:
                return jsonify({
                    'error': (
                        f"Duplicate test submission detected. "
                        f"The first completed test was Year {first_test_year}. "
                        f"The required second test is Year {expected_second_year}."
                    )
                }), 400

            # Reject any second submission that is not the required remaining year
            if test_year != expected_second_year:
                return jsonify({
                    'error': (
                        f"Incorrect second test submitted. "
                        f"Expected Year {expected_second_year}, but received Year {test_year}."
                    )
                }), 400

            data['test1_name'] = first_test.get('test1_name', 'First Test')
            data['test1_score'] = first_test.get('test1_score', 'N/A')
            data['test1_raw'] = first_test.get('test1_raw', 'N/A')

            data['test2_name'] = f"{data['test_curriculum']} Year {data['test_grade']}"
            data['test2_score'] = data['percentage']
            data['test2_raw'] = f"{data['score']}/{data['total']}"

            result = send_combined_results_email(data)

            # Clean up after combined email
            if student_key in test_results_storage:
                del test_results_storage[student_key]

        if result.get("success"):
            return jsonify(result), 200
        return jsonify(result), 500

    except Exception as e:
        return jsonify({"error": str(e)}), 500

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
                "expected_second_year": record["expected_second_year"]
            }), 200

        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

def send_brevo_email(to_email, to_name, subject, html_content):
    """
    Send email using Brevo API
    """
    try:
        if not BREVO_API_KEY:
            return {
                "success": False,
                "error": "BREVO_API_KEY is not set in environment variables",
            }

        headers = {
            "accept": "application/json",
            "api-key": BREVO_API_KEY,
            "content-type": "application/json",
        }

        payload = {
            "sender": {"name": SENDER_NAME, "email": SENDER_EMAIL},
            "to": [{"email": to_email, "name": to_name}],
            "subject": subject,
            "htmlContent": html_content,
        }

        response = requests.post(BREVO_API_URL, json=payload, headers=headers, timeout=20)

        if response.status_code in [200, 201]:
            return {
                "success": True,
                "message": "Email sent successfully",
                "email": to_email,
            }

        return {
            "success": False,
            "error": f"Brevo API error: {response.status_code} - {response.text}",
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to send email: {str(e)}",
        }


def send_first_test_email(data):
    """Send email with first test results and direct link to the exact second test"""
    try:
        # Extract first name only from student_name
        student_full_name = data["student_name"]
        student_first_name = student_full_name.split()[0] if student_full_name else "Student"

        # Calculate 48-hour deadline
        deadline = datetime.now() + timedelta(hours=48)
        deadline_str = deadline.strftime("%A, %B %d at %I:%M %p")

        # Build exact second-test link
        base_url = os.environ.get("FRONTEND_URL", "https://test.schrool.net").rstrip("/")

        # Generate secure continuation token
        token = secrets.token_urlsafe(24)

        # Store continuation data for the emailed second-test flow
        continuation_tokens[token] = {
            "student_key": f"{data['parent_email']}_{data['student_name']}".lower().replace(" ", "_"),
            "parent_email": data["parent_email"],
            "parent_name": data.get("parent_name", "Parent"),
            "student_name": data["student_name"],
            "test_curriculum": data["test_curriculum"],
            "first_test_year": int(data["test_grade"]),
            "expected_second_year": int(data["next_test_grade"]),
            "expires_at": (datetime.now() + timedelta(hours=48)).isoformat()
}

        curriculum_slug = data["test_curriculum"].strip().lower()
        next_test_grade = int(data["next_test_grade"])

        second_test_link = (
            f"{base_url}/schrool-fresher/"
            f"{curriculum_slug}-year{next_test_grade}-math-test.html"
            f"?token={token}"
        )

        # Email body
        interpretation = get_interpretation(data["percentage"])

        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #2563eb;">Test Results for {student_first_name}</h2>

                <p>Dear {data.get('parent_name', 'Parent')},</p>

                <p>Thank you for completing the first diagnostic test for {student_first_name}.</p>

                <div style="background: #f3f4f6; padding: 20px; border-radius: 8px; margin: 20px 0;">
                    <h3 style="margin-top: 0;">First Test Results</h3>
                    <p><strong>Completed test:</strong> {data['test_curriculum']} Year {data['test_grade']}</p>
                    <p><strong>Score:</strong> {data['score']} out of {data['total']} ({data['percentage']}%)</p>
                </div>

                <div style="background: #eff6ff; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #2563eb;">
                    <h3 style="margin-top: 0;">Performance Assessment</h3>
                    <p>{interpretation}</p>
                </div>

                <div style="background: #fef3c7; padding: 20px; border-radius: 8px; margin: 20px 0;">
                    <h3 style="margin-top: 0;">Next Test to Complete</h3>
                    <p><strong>{data['test_curriculum']} Year {next_test_grade}</strong></p>
                    <p>Please complete this second test within 48 hours so we can provide a full diagnosis of your child's math situation.</p>
                    <p style="margin-top: 15px;">
                        <a href="{second_test_link}"
                           style="background: #2563eb; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; display: inline-block;">
                            Take {data['test_curriculum']} Year {next_test_grade} Test Now
                        </a>
                    </p>
                    <p style="font-size: 16px; color: #dc2626; font-weight: bold; margin-top: 15px;">
                        ⏰ Complete the second test within 48 hours
                    </p>
                    <p style="font-size: 14px; color: #666; margin-top: 5px;">
                        Link expires: <strong>{deadline_str}</strong>
                    </p>
                </div>

                <p>If you have any questions, please don't hesitate to reach out.</p>

                <p>Best regards,<br>
                <strong>Richard & The Schrool Team</strong></p>

                <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 30px 0;">

                <p style="font-size: 12px; color: #9ca3af;">
                    This email was sent to {data['parent_email']} because you completed a diagnostic test at Schrool.
                </p>
            </div>
        </body>
        </html>
        """

        subject = f"⏰ {student_first_name}'s Results: Complete {data['test_curriculum']} Year {next_test_grade} Within 48 Hours"
        to_name = data.get("parent_name", "Parent")

        return send_brevo_email(data["parent_email"], to_name, subject, html_content)

    except Exception as e:
        return {"success": False, "error": str(e)}


def send_combined_results_email(data):
    """Send email with combined results from both tests"""
    try:
        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #10b981;">🎉 Congratulations!</h2>

                <p>Dear {data.get('parent_name', 'Parent')},</p>

                <p>{data['student_name']} has completed both diagnostic tests!</p>

                <div style="background: #f0fdf4; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #10b981;">
                    <h3 style="margin-top: 0;">Complete Results Summary</h3>
                    <p><strong>Test 1:</strong> {data.get('test1_name', 'First Test')} - <strong style="color: #059669; font-size: 18px;">{data.get('test1_score', 'N/A')}%</strong></p>
                    <p style="font-size: 14px; color: #666; margin-left: 20px;">Raw Score: {data.get('test1_raw', 'N/A')}</p>

                    <p style="margin-top: 15px;"><strong>Test 2:</strong> {data.get('test2_name', 'Second Test')} - <strong style="color: #059669; font-size: 18px;">{data.get('test2_score', 'N/A')}%</strong></p>
                    <p style="font-size: 14px; color: #666; margin-left: 20px;">Raw Score: {data.get('test2_raw', 'N/A')}</p>
                </div>

                <div style="background: #eff6ff; padding: 20px; border-radius: 8px; margin: 20px 0;">
                    <h3 style="margin-top: 0;">What's Next?</h3>
                    <p>Our team will analyze these results and send you personalized recommendations and strategies within the next <strong>72 hours</strong>.</p>
                    <p>You'll receive:</p>
                    <ul>
                        <li>Detailed analysis of strengths and areas for improvement</li>
                        <li>Personalized learning strategies</li>
                        <li>Recommended resources and activities</li>
                        <li>Tips for supporting your child's math development</li>
                    </ul>
                </div>

                <p>In the meantime, if you'd like to discuss your child's math learning journey, feel free to reply to this email.</p>

                <p>Best regards,<br>
                <strong>Richard & The Schrool Team</strong></p>

                <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 30px 0;">

                <p style="font-size: 12px; color: #9ca3af;">
                    This email was sent to {data['parent_email']} because you completed diagnostic tests at Schrool.
                </p>
            </div>
        </body>
        </html>
        """

        subject = f"Complete Diagnostic Results for {data['student_name']}"
        to_name = data.get("parent_name", "Parent")

        return send_brevo_email(data["parent_email"], to_name, subject, html_content)

    except Exception as e:
        return {"success": False, "error": str(e)}


def get_interpretation(percentage):
    """Get performance interpretation based on percentage"""
    if percentage >= 90:
        return "Excellent! Your child demonstrates strong mastery of the concepts at this grade level."
    if percentage >= 75:
        return "Good performance! Your child has a solid understanding with some areas for improvement."
    if percentage >= 60:
        return "Fair performance. Your child understands basic concepts but needs support in several areas."
    if percentage >= 40:
        return "Your child is struggling with many concepts at this level and would benefit from targeted support."
    return "Your child needs significant support. Consider working with a tutor to build foundational skills."


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
