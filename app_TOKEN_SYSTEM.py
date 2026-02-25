"""
Schrool Diagnostic Tests Backend
Flask API for handling test submissions and email notifications using Brevo
ENHANCED VERSION - With token generation, validation, and 48-hour expiration
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import os
from datetime import datetime, timedelta
import json
import requests
import uuid

app = Flask(__name__)
CORS(app)  # Enable CORS for frontend requests

# Brevo API Key (set in Heroku environment variables)
BREVO_API_KEY = os.environ.get('BREVO_API_KEY')
BREVO_API_URL = 'https://api.brevo.com/v3/smtp/email'

# Sender email (must be verified in Brevo )
SENDER_EMAIL = os.environ.get('SENDER_EMAIL', 'diagnostics@schrool.com')
SENDER_NAME = os.environ.get('SENDER_NAME', 'Schrool Diagnostics')

# In-memory storage for test results and tokens
test_results_storage = {}
tokens_storage = {}  # NEW: Store tokens with expiration and usage tracking

# Get base URL from environment or use default
BASE_URL = os.environ.get('BASE_URL', 'https://test.schrool.net/schrool-fresher' )

@app.route('/')
def home():
    """Health check endpoint"""
    return jsonify({
        'status': 'running',
        'service': 'Schrool Diagnostic Tests API',
        'version': '1.3-TOKEN-SYSTEM',
        'email_service': 'Brevo',
        'features': [
            'Token generation for one-time links',
            '48-hour token expiration',
            'Combined results email',
            'Automatic form skipping with token'
        ]
    })


@app.route('/api/validate-token/<token>', methods=['GET'])
def validate_token(token):
    """
    Validate a token and return test details
    
    Returns:
    {
        "valid": true/false,
        "message": "...",
        "test_details": {
            "parent_email": "...",
            "student_name": "...",
            "test_grade": "5"
        }
    }
    """
    try:
        if token not in tokens_storage:
            return jsonify({
                'valid': False,
                'message': 'Invalid token'
            }), 400
        
        token_data = tokens_storage[token]
        
        # Check if token has expired
        expires_at = datetime.fromisoformat(token_data['expires_at'])
        if datetime.now() > expires_at:
            return jsonify({
                'valid': False,
                'message': 'Token has expired. Please request a new link.'
            }), 400
        
        # Check if token has already been used
        if token_data['used']:
            return jsonify({
                'valid': False,
                'message': 'This link has already been used. Please request a new one.'
            }), 400
        
        # Mark token as used
        token_data['used'] = True
        tokens_storage[token] = token_data
        
        return jsonify({
            'valid': True,
            'message': 'Token is valid',
            'test_details': {
                'parent_email': token_data['student_email'],
                'student_name': token_data['student_name'],
                'test_grade': token_data['test_grade'],
                'test_curriculum': token_data['test_curriculum']
            }
        }), 200
        
    except Exception as e:
        return jsonify({
            'valid': False,
            'message': f'Error validating token: {str(e)}'
        }), 500


@app.route('/api/submit-test', methods=['POST'])
def submit_test():
    """
    Handle test submission and send results email
    
    Expected JSON:
    {
        "parent_name": "John Doe",
        "parent_email": "john@example.com",
        "student_name": "Jane Doe",
        "school_grade": "6",
        "test_curriculum": "Ireland",
        "test_grade": "5",
        "score": 18,
        "total": 25,
        "percentage": 72,
        "time_used": 1800,
        "is_first_test": true
    }
    """
    try:
        data = request.json
        
        # Validate required fields
        required_fields = ['parent_email', 'student_name', 'test_curriculum', 
                          'test_grade', 'score', 'total', 'percentage']
        
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        # Create unique key for this student (email + student name)
        student_key = f"{data['parent_email']}_{data['student_name']}".lower().replace(' ', '_')
        
        # Send appropriate email
        if data.get('is_first_test', True):
            # Store first test results
            test_results_storage[student_key] = {
                'test1_name': f"{data['test_curriculum']} Grade {data['test_grade']}",
                'test1_score': data['percentage'],
                'test1_raw': f"{data['score']}/{data['total']}",
                'timestamp': datetime.now().isoformat(),
                'parent_name': data.get('parent_name', 'Parent'),
                'student_name': data['student_name'],
                'test_curriculum': data['test_curriculum'],
                'test_grade': data['test_grade']
            }
            result = send_first_test_email(data)
        else:
            # Retrieve first test results and combine with second test
            first_test = test_results_storage.get(student_key, {})
            
            # Add both test scores to data
            data['test1_name'] = first_test.get('test1_name', 'First Test')
            data['test1_score'] = first_test.get('test1_score', 'N/A')
            data['test1_raw'] = first_test.get('test1_raw', 'N/A')
            data['test2_name'] = f"{data['test_curriculum']} Grade {data['test_grade']}"
            data['test2_score'] = data['percentage']
            data['test2_raw'] = f"{data['score']}/{data['total']}"
            
            result = send_combined_results_email(data)
            
            # Clean up stored results after sending combined email
            if student_key in test_results_storage:
                del test_results_storage[student_key]
        
        if result.get('success'):
            return jsonify(result), 200
        else:
            return jsonify(result), 500
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def generate_token(student_email, student_name, test_curriculum, current_grade):
    """
    Generate a unique token for the next test
    
    Args:
        student_email: Parent's email
        student_name: Student's name
        test_curriculum: Country curriculum (e.g., 'Ireland')
        current_grade: Current test grade (e.g., '4')
    
    Returns:
        str: Generated token UUID
    """
    token = str(uuid.uuid4())
    next_grade = str(int(current_grade) + 1)
    
    # Store token with expiration (48 hours from now)
    tokens_storage[token] = {
        'student_email': student_email,
        'student_name': student_name,
        'test_curriculum': test_curriculum,
        'test_grade': next_grade,
        'created_at': datetime.now().isoformat(),
        'expires_at': (datetime.now() + timedelta(hours=48)).isoformat(),
        'used': False
    }
    
    return token


def send_brevo_email(to_email, to_name, subject, html_content):
    """
    Send email using Brevo API
    
    Args:
        to_email: Recipient email address
        to_name: Recipient name
        subject: Email subject
        html_content: HTML email content
    
    Returns:
        dict: Response with success status and message
    """
    try:
        headers = {
            'accept': 'application/json',
            'api-key': BREVO_API_KEY,
            'content-type': 'application/json'
        }
        
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
        
        response = requests.post(BREVO_API_URL, json=payload, headers=headers)
        
        if response.status_code in [200, 201]:
            return {
                'success': True,
                'message': 'Email sent successfully',
                'email': to_email
            }
        else:
            return {
                'success': False,
                'error': f'Brevo API error: {response.status_code}'
            }
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


def send_first_test_email(data):
    """
    Send email after first test with token link to second test
    
    NEW: Includes token generation and link to next grade test
    """
    try:
        # Generate token for second test
        token = generate_token(
            data['parent_email'],
            data['student_name'],
            data['test_curriculum'],
            data['test_grade']
        )
        
        # Determine next grade
        next_grade = int(data['test_grade']) + 1
        
        # Create token link
        token_link = f"{BASE_URL}/index.html?token={token}&grade={next_grade}"
        
        # Get performance interpretation
        interpretation = get_interpretation(data['percentage'])
        
        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #667eea;">🎓 {data['student_name']}'s Test Results</h2>
                
                <p>Dear {data.get('parent_name', 'Parent')},</p>
                
                <p>Thank you for completing the diagnostic test! Here are the results:</p>
                
                <div style="background: #f0f4ff; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #667eea;">
                    <h3 style="margin-top: 0; color: #667eea;">Test Results</h3>
                    <p><strong>Test:</strong> {data['test_curriculum']} Grade {data['test_grade']}</p>
                    <p><strong>Score:</strong> <span style="font-size: 24px; color: #667eea; font-weight: bold;">{data['percentage']}%</span></p>
                    <p style="font-size: 14px; color: #666;">Raw Score: {data['score']}/{data['total']}</p>
                    <p style="margin-top: 15px;"><strong>Performance:</strong> {interpretation}</p>
                </div>
                
                <div style="background: #fff3cd; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #ffc107;">
                    <h3 style="margin-top: 0; color: #856404;">⏰ Next Step: Complete the Second Test</h3>
                    <p>{data['student_name']} needs to complete the Grade {next_grade} test to continue the diagnostic assessment.</p>
                    <p style="color: #d32f2f; font-weight: bold;">⚠️ IMPORTANT: This link expires in 48 hours</p>
                    <p style="margin-top: 15px;">
                        <a href="{token_link}" style="display: inline-block; background: #667eea; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold;">
                            📝 Take Grade {next_grade} Test
                        </a>
                    </p>
                    <p style="font-size: 12px; color: #666; margin-top: 10px;">
                        Or copy this link: <code style="background: #f5f5f5; padding: 4px 8px; border-radius: 4px;">{token_link}</code>
                    </p>
                </div>
                
                <div style="background: #e8f5e9; padding: 20px; border-radius: 8px; margin: 20px 0;">
                    <h3 style="margin-top: 0; color: #2e7d32;">📚 Tips for Success</h3>
                    <ul style="color: #2e7d32;">
                        <li>Take the test in a quiet environment</li>
                        <li>Have a pencil and paper available for working</li>
                        <li>Don't rush - you have 45 minutes</li>
                        <li>Do your best - this helps us understand your child's needs</li>
                    </ul>
                </div>
                
                <p>If you have any questions, feel free to reply to this email.</p>
                
                <p>Best regards,  

                <strong>Richard & The Schrool Team</strong></p>
                
                <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 30px 0;">
                
                <p style="font-size: 12px; color: #9ca3af;">
                    This email was sent to {data['parent_email']} because you completed a diagnostic test at Schrool.
                </p>
            </div>
        </body>
        </html>
        """
        
        subject = f"Grade {data['test_grade']} Test Results - Complete Grade {next_grade} Test Within 48 Hours!"
        to_name = data.get('parent_name', 'Parent')
        
        return send_brevo_email(data['parent_email'], to_name, subject, html_content)
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


def send_combined_results_email(data):
    """
    Send email after second test with both test results
    """
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
                
                <p>Best regards,  

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
        to_name = data.get('parent_name', 'Parent')
        
        return send_brevo_email(data['parent_email'], to_name, subject, html_content)
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


def get_interpretation(percentage):
    """Get performance interpretation based on percentage"""
    if percentage >= 90:
        return "Excellent! Your child demonstrates strong mastery of the concepts at this grade level."
    elif percentage >= 75:
        return "Good performance! Your child has a solid understanding with some areas for improvement."
    elif percentage >= 60:
        return "Fair performance. Your child understands basic concepts but needs support in several areas."
    elif percentage >= 40:
        return "Your child is struggling with many concepts at this level and would benefit from targeted support."
    else:
        return "Your child needs significant support. Consider working with a tutor to build foundational skills."


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
