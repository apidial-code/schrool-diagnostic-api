"""
Schrool Diagnostic Tests Backend - Clean Production Version
Flask API for handling test submissions and email notifications using Brevo
DATABASE VERSION - Uses SQLite for persistent storage across server restarts

Version: 2.0-CLEAN
Date: February 2026
Status: Production Ready
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import os
from datetime import datetime, timedelta
import json
import requests
import sqlite3
from contextlib import contextmanager

# ============================================================================
# FLASK APP INITIALIZATION
# ============================================================================

app = Flask(__name__)

# Configure CORS for frontend requests
CORS(
    app,
    origins=[
        'http://schrool.net',
        'https://schrool.net',
        'http://test.schrool.net',
        'https://test.schrool.net'
    ],
    supports_credentials=True,
    methods=['GET', 'POST', 'OPTIONS'],
    allow_headers=['Content-Type']
)

# ============================================================================
# CONFIGURATION
# ============================================================================

# Brevo API Configuration
BREVO_API_KEY = os.environ.get('BREVO_API_KEY')
BREVO_API_URL = 'https://api.brevo.com/v3/smtp/email'

# Email Configuration
SENDER_EMAIL = os.environ.get('SENDER_EMAIL', 'diagnostics@schrool.com')
SENDER_NAME = os.environ.get('SENDER_NAME', 'Schrool Diagnostics')

# Database Configuration
DATABASE_PATH = os.environ.get('DATABASE_PATH', '/tmp/test_results.db')

# ============================================================================
# DATABASE MANAGEMENT
# ============================================================================

@contextmanager
def get_db():
    """Context manager for database connections"""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_database():
    """Initialize the database with required tables"""
    with get_db() as conn:
        # Create test_results table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS test_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_key TEXT UNIQUE NOT NULL,
                parent_email TEXT NOT NULL,
                parent_name TEXT,
                student_name TEXT NOT NULL,
                test1_name TEXT,
                test1_score INTEGER,
                test1_raw TEXT,
                test2_name TEXT,
                test2_score INTEGER,
                test2_raw TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        ''')
        
        # Create index for faster lookups
        conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_student_key 
            ON test_results(student_key)
        ''')
        
        # Clean up old entries (older than 7 days)
        seven_days_ago = (datetime.now() - timedelta(days=7)).isoformat()
        conn.execute('''
            DELETE FROM test_results 
            WHERE created_at < ?
        ''', (seven_days_ago,))


# Initialize database on startup
init_database()

# ============================================================================
# DATABASE OPERATIONS
# ============================================================================

def store_first_test(student_key, data):
    """Store first test results in database"""
    with get_db() as conn:
        now = datetime.now().isoformat()
        conn.execute('''
            INSERT OR REPLACE INTO test_results 
            (student_key, parent_email, parent_name, student_name, 
             test1_name, test1_score, test1_raw, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            student_key,
            data['parent_email'],
            data.get('parent_name', 'Parent'),
            data['student_name'],
            f"{data['test_curriculum']} Grade {data['test_grade']}",
            data['percentage'],
            f"{data['score']}/{data['total']}",
            now,
            now
        ))


def store_second_test(student_key, data):
    """Store second test results and retrieve first test data"""
    with get_db() as conn:
        # Retrieve first test data
        cursor = conn.execute('''
            SELECT test1_name, test1_score, test1_raw, parent_name
            FROM test_results
            WHERE student_key = ?
        ''', (student_key,))
        
        row = cursor.fetchone()
        
        if row:
            # Update with second test data
            now = datetime.now().isoformat()
            conn.execute('''
                UPDATE test_results
                SET test2_name = ?,
                    test2_score = ?,
                    test2_raw = ?,
                    updated_at = ?
                WHERE student_key = ?
            ''', (
                f"{data['test_curriculum']} Grade {data['test_grade']}",
                data['percentage'],
                f"{data['score']}/{data['total']}",
                now,
                student_key
            ))
            
            return {
                'test1_name': row['test1_name'],
                'test1_score': row['test1_score'],
                'test1_raw': row['test1_raw'],
                'parent_name': row['parent_name']
            }
        else:
            # First test data not found, return defaults
            return {
                'test1_name': 'First Test',
                'test1_score': None,
                'test1_raw': 'N/A',
                'parent_name': data.get('parent_name', 'Parent')
            }


def cleanup_test_data(student_key):
    """Remove test data after combined email is sent"""
    with get_db() as conn:
        conn.execute('''
            DELETE FROM test_results
            WHERE student_key = ?
        ''', (student_key,))

# ============================================================================
# HEALTH CHECK ENDPOINT
# ============================================================================

@app.route('/')
def home():
    """Health check endpoint"""
    return jsonify({
        'status': 'running',
        'service': 'Schrool Diagnostic Tests API',
        'version': '2.0-CLEAN',
        'email_service': 'Brevo',
        'storage': 'SQLite Database',
        'timestamp': datetime.now().isoformat()
    }), 200

# ============================================================================
# EMAIL HELPER FUNCTIONS
# ============================================================================

def get_performance_level(percentage):
    """Determine performance level and color based on percentage"""
    if percentage >= 75:
        return {
            'level': 'Strong',
            'color': '#059669',
            'description': 'Excellent performance'
        }
    elif percentage >= 60:
        return {
            'level': 'Satisfactory',
            'color': '#2563eb',
            'description': 'Good performance'
        }
    elif percentage >= 40:
        return {
            'level': 'Needs Improvement',
            'color': '#d97706',
            'description': 'Needs more practice'
        }
    else:
        return {
            'level': 'Requires Support',
            'color': '#dc2626',
            'description': 'Requires immediate support'
        }


def send_email_via_brevo(to_email, to_name, subject, html_content):
    """Send email via Brevo API"""
    try:
        payload = {
            'sender': {
                'name': SENDER_NAME,
                'email': SENDER_EMAIL
            },
            'to': [
                {
                    'email': to_email,
                    'name': to_name
                }
            ],
            'subject': subject,
            'htmlContent': html_content
        }
        
        headers = {
            'accept': 'application/json',
            'api-key': BREVO_API_KEY,
            'content-type': 'application/json'
        }
        
        response = requests.post(BREVO_API_URL, json=payload, headers=headers)
        
        if response.status_code == 201:
            return {'success': True}
        else:
            print(f"Brevo API error: {response.status_code} - {response.text}")
            return {'success': False, 'error': response.text}
            
    except Exception as e:
        print(f"Error sending email: {str(e)}")
        return {'success': False, 'error': str(e)}

# ============================================================================
# EMAIL TEMPLATE: FIRST TEST RESULTS
# ============================================================================

def send_first_test_email(data):
    """Send email after first test completion"""
    try:
        percentage = data['percentage']
        performance = get_performance_level(percentage)
        color = performance['color']
        
        # Use the pre-calculated next test grade from the endpoint
        # The formula has already been applied before this function is called
        if 'next_test_grade' in data:
            second_test_grade = str(data['next_test_grade'])
        else:
            # Fallback if not provided (shouldn't happen)
            second_test_grade = str(int(data['test_grade']) + 1)
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; border-radius: 10px 10px 0 0; text-align: center;">
                <h1 style="color: white; margin: 0; font-size: 28px;">⏰ Test 1 Complete!</h1>
            </div>
            
            <div style="background-color: #f9fafb; padding: 30px; border-radius: 0 0 10px 10px;">
                <p style="font-size: 16px; margin-bottom: 20px;">Dear {data.get('parent_name', 'Parent')},</p>
                
                <p style="font-size: 16px; margin-bottom: 25px;">
                    <strong>{data['student_name']}</strong> has completed the first diagnostic test!
                </p>
                
                <div style="background-color: white; padding: 25px; border-radius: 8px; border-left: 4px solid {color}; margin-bottom: 25px;">
                    <h2 style="color: #1f2937; margin-top: 0; font-size: 20px;">Test 1 Results</h2>
                    <p style="font-size: 18px; margin: 10px 0;">
                        <strong>Test:</strong> {data['test_curriculum']} Grade {data['test_grade']}
                    </p>
                    <p style="font-size: 24px; margin: 10px 0; color: {color};">
                        <strong>Score: {percentage}%</strong>
                    </p>
                    <p style="font-size: 14px; color: #666; margin: 10px 0;">
                        Raw Score: {data['score']}/{data['total']}
                    </p>
                    <p style="font-size: 16px; margin: 15px 0;">
                        <strong>Performance Level:</strong> {performance['level']}
                    </p>
                </div>
                
                <div style="background-color: #fef3c7; padding: 20px; border-radius: 8px; border-left: 4px solid #f59e0b; margin-bottom: 25px;">
                    <h3 style="color: #92400e; margin-top: 0; font-size: 18px;">⚠️ Important: Complete Test 2 Within 48 Hours</h3>
                    <p style="color: #78350f; margin-bottom: 15px;">
                        To receive your complete diagnostic report and personalized recommendations, 
                        please have {data['student_name']} complete the second test within the next <strong>48 hours</strong>.
                    </p>
                    <p style="color: #78350f; margin: 0;">
                        <strong>Test 2:</strong> {data['test_curriculum']} Grade {second_test_grade}
                    </p>
                </div>
                
                <div style="text-align: center; margin: 30px 0;">
                    <a href="https://test.schrool.net/schrool-fresher/{data['test_curriculum'].lower()}-year{second_test_grade}-math-test.html"
                    style="display: inline-block; background-color: #2563eb; color: white; padding: 15px 40px; text-decoration: none; border-radius: 8px; font-size: 18px; font-weight: bold;">
                        Take Test 2 Now
                    </a>
                </div>
                
                <div style="background-color: #e0f2fe; padding: 20px; border-radius: 8px; margin-top: 25px;">
                    <h3 style="color: #075985; margin-top: 0; font-size: 16px;">What Happens Next?</h3>
                    <p style="color: #0c4a6e; margin-bottom: 10px;">
                        After completing both tests, our team will analyze the results and send you:
                    </p>
                    <ul style="color: #0c4a6e; margin: 10px 0; padding-left: 20px;">
                        <li>Detailed analysis of strengths and areas for improvement</li>
                        <li>Personalized learning strategies</li>
                        <li>Recommended resources and activities</li>
                        <li>Tips for supporting your child's math development</li>
                    </ul>
                </div>
                
                <p style="font-size: 14px; color: #666; margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd;">
                    If you have any questions, feel free to reply to this email.
                </p>
                
                <p style="font-size: 14px; color: #666;">
                    Best regards,<br>
                    <strong>Richard & The Schrool Team</strong>
                </p>
            </div>
        </body>
        </html>
        """
        
        subject = f"⏰ {data['student_name']}'s Test Results - Complete Test 2 Within 48 Hours!"
        return send_email_via_brevo(data['parent_email'], data.get('parent_name', 'Parent'), subject, html_content)
        
    except Exception as e:
        print(f"Error in send_first_test_email: {str(e)}")
        return {'success': False, 'error': str(e)}

# ============================================================================
# EMAIL TEMPLATE: COMBINED TEST RESULTS
# ============================================================================

def send_combined_results_email(data):
    """Send email with both test results"""
    try:
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
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
                    
                    <p style="font-size: 16px; margin: 15px 0;">
                        <strong>Test 1:</strong> {data.get('test1_name', 'First Test')} - 
                        <strong style="color: #059669; font-size: 18px;">{data.get('test1_score', 'N/A')}%</strong>
                    </p>
                    <p style="font-size: 14px; color: #666; margin-left: 20px;">
                        Raw Score: {data.get('test1_raw', 'N/A')}
                    </p>
                    
                    <p style="font-size: 16px; margin: 15px 0; margin-top: 20px;">
                        <strong>Test 2:</strong> {data.get('test2_name', 'Second Test')} - 
                        <strong style="color: #059669; font-size: 18px;">{data.get('test2_score', 'N/A')}%</strong>
                    </p>
                    <p style="font-size: 14px; color: #666; margin-left: 20px;">
                        Raw Score: {data.get('test2_raw', 'N/A')}
                    </p>
                </div>
                
                <div style="background-color: #dbeafe; padding: 20px; border-radius: 8px; margin-bottom: 25px;">
                    <h3 style="color: #1e40af; margin-top: 0; font-size: 18px;">What's Next?</h3>
                    <p style="color: #1e3a8a; margin-bottom: 15px;">
                        Our team will analyze these results and send you personalized recommendations and strategies 
                        within the next <strong>72 hours</strong>.
                    </p>
                    <p style="color: #1e3a8a; margin-bottom: 10px;"><strong>You'll receive:</strong></p>
                    <ul style="color: #1e3a8a; margin: 10px 0; padding-left: 20px;">
                        <li>Detailed analysis of strengths and areas for improvement</li>
                        <li>Personalized learning strategies</li>
                        <li>Recommended resources and activities</li>
                        <li>Tips for supporting your child's math development</li>
                    </ul>
                </div>
                
                <p style="font-size: 14px; color: #666; margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd;">
                    In the meantime, if you'd like to discuss your child's math learning journey, 
                    feel free to reply to this email.
                </p>
                
                <p style="font-size: 14px; color: #666;">
                    Best regards,<br>
                    <strong>Richard & The Schrool Team</strong>
                </p>
            </div>
        </body>
        </html>
        """
        
        subject = f"🎉 Complete Diagnostic Results for {data['student_name']}"
        return send_email_via_brevo(data['parent_email'], data.get('parent_name', 'Parent'), subject, html_content)
        
    except Exception as e:
        print(f"Error in send_combined_results_email: {str(e)}")
        return {'success': False, 'error': str(e)}

# ============================================================================
# EMAIL TEMPLATE: 72-HOUR FOLLOW-UP
# ============================================================================

def send_followup_email(data):
    """Send 72-hour follow-up email with personalized recommendations"""
    try:
        # Calculate average score
        test1_score = data.get('test1_score', 0)
        test2_score = data.get('test2_score', 0)
        avg_score = (test1_score + test2_score) / 2 if test1_score and test2_score else 0
        
        # Determine recommendations based on average
        if avg_score >= 75:
            recommendation_title = "🌟 Excellent Progress!"
            recommendation_text = f"Your child is performing exceptionally well with an average score of {avg_score:.0f}%. Continue with challenging problems to maintain momentum."
            color = "#059669"
        elif avg_score >= 60:
            recommendation_title = "📈 Good Foundation"
            recommendation_text = f"Your child shows a solid foundation with an average score of {avg_score:.0f}%. Focus on strengthening weaker areas through targeted practice."
            color = "#2563eb"
        else:
            recommendation_title = "💪 Opportunity for Growth"
            recommendation_text = f"Your child is working with an average score of {avg_score:.0f}%. Consistent practice with our recommended strategies will help build confidence."
            color = "#d97706"
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; border-radius: 10px 10px 0 0; text-align: center;">
                <h1 style="color: white; margin: 0; font-size: 28px;">📊 Your Personalized Analysis</h1>
            </div>
            
            <div style="background-color: #f9fafb; padding: 30px; border-radius: 0 0 10px 10px;">
                <p style="font-size: 16px; margin-bottom: 20px;">Dear {data.get('parent_name', 'Parent')},</p>
                
                <p style="font-size: 16px; margin-bottom: 25px;">
                    Thank you for completing the diagnostic tests. Our team has analyzed {data['student_name']}'s performance and prepared personalized recommendations.
                </p>
                
                <div style="background-color: #f0f9ff; padding: 25px; border-radius: 8px; border-left: 4px solid {color}; margin-bottom: 25px;">
                    <h2 style="color: #1e40af; margin-top: 0; font-size: 20px;">{recommendation_title}</h2>
                    <p style="font-size: 16px; color: #1e3a8a; margin: 15px 0;">
                        {recommendation_text}
                    </p>
                </div>
                
                <div style="background-color: #f3f4f6; padding: 20px; border-radius: 8px; margin-bottom: 25px;">
                    <h3 style="color: #374151; margin-top: 0; font-size: 18px;">Recommended Next Steps</h3>
                    <ul style="color: #374151; margin: 10px 0; padding-left: 20px;">
                        <li><strong>Daily Practice:</strong> 15-20 minutes of focused math practice daily</li>
                        <li><strong>Problem-Solving:</strong> Work through problems step-by-step with explanations</li>
                        <li><strong>Concept Review:</strong> Revisit foundational concepts before moving forward</li>
                        <li><strong>Parent Support:</strong> Help your child explain their thinking process</li>
                    </ul>
                </div>
                
                <div style="background-color: #ecfdf5; padding: 20px; border-radius: 8px; margin-bottom: 25px;">
                    <h3 style="color: #065f46; margin-top: 0; font-size: 18px;">Resources Available</h3>
                    <p style="color: #047857; margin-bottom: 10px;">
                        We have curated resources specifically for your child's learning level:
                    </p>
                    <ul style="color: #047857; margin: 10px 0; padding-left: 20px;">
                        <li>Interactive practice problems with step-by-step solutions</li>
                        <li>Video tutorials explaining key concepts</li>
                        <li>Parent guides for supporting math learning at home</li>
                        <li>Progress tracking tools to monitor improvement</li>
                    </ul>
                </div>
                
                <div style="background-color: #fef3c7; padding: 20px; border-radius: 8px; margin-bottom: 25px;">
                    <h3 style="color: #92400e; margin-top: 0; font-size: 18px;">Need Help?</h3>
                    <p style="color: #78350f; margin: 0;">
                        Our team is here to support your child's learning journey. Reply to this email with any questions or concerns, 
                        and we'll be happy to provide additional guidance.
                    </p>
                </div>
                
                <p style="font-size: 14px; color: #666; margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd;">
                    Best regards,<br>
                    <strong>Richard & The Schrool Team</strong>
                </p>
            </div>
        </body>
        </html>
        """
        
        subject = f"📊 Personalized Analysis for {data['student_name']}"
        return send_email_via_brevo(data['parent_email'], data.get('parent_name', 'Parent'), subject, html_content)
        
    except Exception as e:
        print(f"Error in send_followup_email: {str(e)}")
        return {'success': False, 'error': str(e)}

# ============================================================================
# MAIN API ENDPOINT: SUBMIT TEST
# ============================================================================

@app.route('/api/submit-test', methods=['POST', 'OPTIONS'])
def submit_test():
    """
    Handle test submission and send results email
    
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
        "time_used": 1800,
        "is_first_test": true
    }
    """
    # Handle preflight requests
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        data = request.json
        
        # Validate required fields
        required_fields = [
            'parent_email',
            'student_name',
            'test_curriculum',
            'test_grade',
            'score',
            'total',
            'percentage'
        ]
        
        for field in required_fields:
            if field not in data:
                return jsonify({
                    'success': False,
                    'error': f'Missing required field: {field}'
                }), 400
        
        # Create unique key for this student
        student_key = f"{data['parent_email']}_{data['student_name']}".lower().replace(' ', '_')
        
        # Determine if this is first or second test
        is_first_test = data.get('is_first_test', True)
        
        if is_first_test:
            # FIRST: Apply formula to determine next test grade
            # This is the "gauge" the email function needs
            if 'school_grade' in data and data['school_grade']:
                current_year = int(data['school_grade'])
                test1_grade = int(data['test_grade'])
                
                if test1_grade == current_year - 2:
                    next_test_grade = current_year - 1
                elif test1_grade == current_year - 1:
                    next_test_grade = current_year - 2
                else:
                    # Fallback
                    next_test_grade = current_year - 1
                
                # Add the calculated next test to data
                data['next_test_grade'] = next_test_grade
            
            # Store first test results in database
            store_first_test(student_key, data)
            
            # Send first test email with pre-calculated next test
            result = send_first_test_email(data)
            
            if result.get('success'):
                return jsonify({
                    'success': True,
                    'message': 'First test email sent successfully',
                    'email': data['parent_email'],
                    'test_number': 1
                }), 200
            else:
                return jsonify({
                    'success': False,
                    'error': result.get('error', 'Failed to send email')
                }), 500
        
        else:
            # Retrieve first test results from database
            first_test = store_second_test(student_key, data)
            
            # Add both test scores to data
            data['test1_name'] = first_test['test1_name']
            data['test1_score'] = first_test['test1_score'] if first_test['test1_score'] is not None else 'N/A'
            data['test1_raw'] = first_test['test1_raw']
            data['test2_name'] = f"{data['test_curriculum']} Grade {data['test_grade']}"
            data['test2_score'] = data['percentage']
            data['test2_raw'] = f"{data['score']}/{data['total']}"
            data['parent_name'] = first_test['parent_name']
            
            # Send combined results email
            result = send_combined_results_email(data)
            
            if result.get('success'):
                # Send 72-hour follow-up email with personalized analysis
                followup_result = send_followup_email(data)
                
                if not followup_result.get('success'):
                    print(f"Warning: Failed to send followup email: {followup_result.get('error')}")
                
                # Clean up stored results after sending combined email
                cleanup_test_data(student_key)
                
                return jsonify({
                    'success': True,
                    'message': 'Combined results email sent successfully',
                    'email': data['parent_email'],
                    'test_number': 2
                }), 200
            else:
                return jsonify({
                    'success': False,
                    'error': result.get('error', 'Failed to send email')
                }), 500
        
    except Exception as e:
        print(f"Error in submit_test: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors"""
    return jsonify({
        'success': False,
        'error': 'Endpoint not found'
    }), 404


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors"""
    return jsonify({
        'success': False,
        'error': 'Internal server error'
    }), 500

# ============================================================================
# APPLICATION ENTRY POINT
# ============================================================================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
