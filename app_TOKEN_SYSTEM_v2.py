 app_TOKEN_SYSTEM_v2.py
"""
Schrool Diagnostic Tests Backend - FIXED VERSION
Flask API for handling test submissions, token generation, and email notifications
Enhanced with proper error handling and Brevo email integration
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import uuid
import json
from datetime import datetime, timedelta
import requests
from functools import wraps

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# ============================================================================
# CONFIGURATION
# ============================================================================

# Brevo API Configuration
BREVO_API_KEY = os.environ.get('BREVO_API_KEY', '')
BREVO_API_URL = 'https://api.brevo.com/v3/smtp/email'

# Sender Configuration
SENDER_EMAIL = os.environ.get('SENDER_EMAIL', 'diagnostics@schrool.com' )
SENDER_NAME = os.environ.get('SENDER_NAME', 'Schrool Diagnostics')

# Base URL for token links
BASE_URL = os.environ.get('BASE_URL', 'https://test.schrool.net' )

# ============================================================================
# IN-MEMORY STORAGE
# ============================================================================

# Store test results: {student_key: {test_data}}
test_results_storage = {}

# Store tokens: {token: {student_email, student_name, test_curriculum, test_grade, created_at, expires_at, used}}
tokens_storage = {}

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def generate_token(student_email, student_name, test_curriculum, current_grade):
    """Generate a unique token for accessing the next test"""
    token = str(uuid.uuid4())
    
    tokens_storage[token] = {
        'student_email': student_email,
        'student_name': student_name,
        'test_curriculum': test_curriculum,
        'test_grade': current_grade,
        'created_at': datetime.now().isoformat(),
        'expires_at': (datetime.now() + timedelta(hours=48)).isoformat(),
        'used': False
    }
    
    return token

def validate_token(token):
    """Validate a token and return its data if valid"""
    if token not in tokens_storage:
        return {'valid': False, 'message': 'Invalid token'}
    
    token_data = tokens_storage[token]
    
    # Check if token has expired
    expires_at = datetime.fromisoformat(token_data['expires_at'])
    if datetime.now() > expires_at:
        return {'valid': False, 'message': 'Token has expired'}
    
    # Check if token has been used
    if token_data['used']:
        return {'valid': False, 'message': 'Token has already been used'}
    
    return {'valid': True, 'data': token_data}

def mark_token_used(token):
    """Mark a token as used (one-time use)"""
    if token in tokens_storage:
        tokens_storage[token]['used'] = True

def send_brevo_email(to_email, to_name, subject, html_content):
    """
    Send email using Brevo API
    Returns: {'success': True/False, 'message': '...', 'email': to_email}
    """
    if not BREVO_API_KEY:
        return {'success': False, 'message': 'Brevo API key not configured'}
    
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
    
    try:
        response = requests.post(BREVO_API_URL, json=payload, headers=headers, timeout=10)
        
        if response.status_code in [200, 201]:
            return {
                'success': True,
                'message': 'Email sent successfully',
                'email': to_email
            }
        else:
            return {
                'success': False,
                'message': f'Brevo API error: {response.status_code}',
                'email': to_email
            }
    except Exception as e:
        return {
            'success': False,
            'message': f'Email sending failed: {str(e)}',
            'email': to_email
        }

def get_performance_interpretation(percentage):
    """Get performance interpretation based on percentage"""
    if percentage >= 90:
        return 'Excellent! Your child demonstrates strong mastery of the concepts at this grade level.'
    elif percentage >= 75:
        return 'Good performance! Your child has a solid understanding with some areas for improvement.'
    elif percentage >= 60:
        return 'Fair performance. Your child understands basic concepts but needs support in several areas.'
    elif percentage >= 40:
        return 'Your child is struggling with many concepts at this level and would benefit from targeted support.'
    else:
        return 'Your child needs significant support. Consider working with a tutor to build foundational skills.'

def create_first_test_email(data, token_link):
    """Create HTML email for first test completion with token link"""
    student_name = data.get('student_name', 'Student')
    parent_name = data.get('parent_name', 'Parent')
    test_curriculum = data.get('test_curriculum', 'Ireland')
    test_grade = data.get('test_grade', '4')
    next_grade = int(test_grade) + 1
    score = data.get('score', 0)
    total = data.get('total', 0)
    percentage = data.get('percentage', 0)
    interpretation = data.get('interpretation', '')
    
    html_content = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #667eea;">Test Complete!</h2>
            
            <p>Dear {parent_name},</p>
            
            <p>{student_name} has completed the {test_curriculum} Grade {test_grade} diagnostic test. Here are the results:</p>
            
            <div style="background: #f0f4ff; padding: 20px; border-radius: 8px; margin: 20px 0;">
                <h3 style="color: #667eea; margin-top: 0;">Test Results</h3>
                <p><strong>Score:</strong> {score} out of {total} ({percentage}%)</p>
                <p><strong>Curriculum:</strong> {test_curriculum}</p>
                <p><strong>Grade Level:</strong> {test_grade}</p>
            </div>
            
            <div style="background: #e8f5e9; padding: 20px; border-radius: 8px; margin: 20px 0;">
                <h3 style="color: #2e7d32; margin-top: 0;">Performance Analysis</h3>
                <p>{interpretation}</p>
            </div>
            
            <div style="background: #fff3cd; padding: 20px; border-radius: 8px; margin: 20px 0;">
                <h3 style="color: #856404; margin-top: 0;">Next Step</h3>
                <p>{student_name} can now take the Grade {next_grade} test to continue the diagnostic assessment.</p>
                <p><strong>⏰ Important:</strong> This link expires in 48 hours.</p>
                <p style="text-align: center; margin-top: 20px;">
                    <a href="{token_link}" style="background: #667eea; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px; display: inline-block; font-weight: bold;">
                        Take Grade {next_grade} Test
                    </a>
                </p>
            </div>
            
            <hr style="border: none; border-top: 1px solid #ddd; margin: 30px 0;">
            
            <p style="font-size: 12px; color: #999;">
                This email was sent to {data.get('parent_email', '')} because you completed a diagnostic test at Schrool.
            </p>
            
            <p style="font-size: 12px; color: #999;">
                Best regards,  

                <strong>Richard & The Schrool Team</strong>
            </p>
        </div>
    </body>
    </html>
    """
    
    return html_content

def create_combined_results_email(data):
    """Create HTML email for combined results after second test"""
    student_name = data.get('student_name', 'Student')
    parent_name = data.get('parent_name', 'Parent')
    test_curriculum = data.get('test_curriculum', 'Ireland')
    
    test1_grade = data.get('test1_grade', '4')
    test1_score = data.get('test1_score', 0)
    test1_total = data.get('test1_total', 0)
    test1_percentage = data.get('test1_percentage', 0)
    
    test2_grade = data.get('test2_grade', '5')
    test2_score = data.get('test2_score', 0)
    test2_total = data.get('test2_total', 0)
    test2_percentage = data.get('test2_percentage', 0)
    
    html_content = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #667eea;">Complete Diagnostic Results</h2>
            
            <p>Dear {parent_name},</p>
            
            <p>{student_name} has completed both diagnostic tests. Here is a comprehensive summary:</p>
            
            <div style="background: #f0f4ff; padding: 20px; border-radius: 8px; margin: 20px 0;">
                <h3 style="color: #667eea; margin-top: 0;">Grade {test1_grade} Results</h3>
                <p><strong>Score:</strong> {test1_score} out of {test1_total} ({test1_percentage}%)</p>
                <p><strong>Curriculum:</strong> {test_curriculum}</p>
            </div>
            
            <div style="background: #e3f2fd; padding: 20px; border-radius: 8px; margin: 20px 0;">
                <h3 style="color: #1565c0; margin-top: 0;">Grade {test2_grade} Results</h3>
                <p><strong>Score:</strong> {test2_score} out of {test2_total} ({test2_percentage}%)</p>
                <p><strong>Curriculum:</strong> {test_curriculum}</p>
            </div>
            
            <div style="background: #e8f5e9; padding: 20px; border-radius: 8px; margin: 20px 0;">
                <h3 style="color: #2e7d32; margin-top: 0;">Overall Assessment</h3>
                <p>Your child has completed the diagnostic assessment across two grade levels. This comprehensive evaluation provides insights into their current academic level and readiness for advancement.</p>
                <p><strong>Average Score:</strong> {(test1_percentage + test2_percentage) / 2:.0f}%</p>
            </div>
            
            <div style="background: #fff3cd; padding: 20px; border-radius: 8px; margin: 20px 0;">
                <h3 style="color: #856404; margin-top: 0;">Tips for Success</h3>
                <ul>
                    <li>Take the test in a quiet environment</li>
                    <li>Have a pencil and paper available for working</li>
                    <li>Don't rush - you have 45 minutes</li>
                    <li>Do your best - this helps us understand your child's needs</li>
                </ul>
            </div>
            
            <hr style="border: none; border-top: 1px solid #ddd; margin: 30px 0;">
            
            <p style="font-size: 12px; color: #999;">
                This email was sent to {data.get('parent_email', '')} because you completed diagnostic tests at Schrool.
            </p>
            
            <p style="font-size: 12px; color: #999;">
                Best regards,  

                <strong>Richard & The Schrool Team</strong>
            </p>
        </div>
    </body>
    </html>
    """
    
    return html_content

# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.route('/', methods=['GET'])
def home():
    """Health check endpoint"""
    return jsonify({
        'status': 'running',
        'service': 'Schrool Diagnostic Tests API',
        'version': '2.0-FIXED',
        'features': [
            'Token generation for one-time links',
            '48-hour token expiration',
            'Combined results email',
            'Automatic form skipping with token',
            'Brevo email integration'
        ]
    }), 200

@app.route('/api/submit-test', methods=['POST'])
def submit_test():
    """
    Submit test results and generate token for next test
    
    Expected JSON:
    {
        'student_email': 'student@example.com',
        'student_name': 'John Doe',
        'parent_email': 'parent@example.com',
        'parent_name': 'Jane Doe',
        'test_curriculum': 'Ireland',
        'test_grade': '4',
        'score': 13,
        'total': 18,
        'percentage': 72
    }
    """
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['student_email', 'student_name', 'parent_email', 'parent_name', 
                          'test_curriculum', 'test_grade', 'score', 'total', 'percentage']
        
        missing_fields = [field for field in required_fields if field not in data]
        if missing_fields:
            return jsonify({
                'success': False,
                'message': f'Missing required fields: {", ".join(missing_fields)}'
            }), 400
        
        # Store test results
        student_key = f"{data['student_email']}_{data['test_curriculum']}_{data['test_grade']}"
        test_results_storage[student_key] = {
            'student_email': data['student_email'],
            'student_name': data['student_name'],
            'parent_email': data['parent_email'],
            'parent_name': data['parent_name'],
            'test_curriculum': data['test_curriculum'],
            'test_grade': data['test_grade'],
            'score': data['score'],
            'total': data['total'],
            'percentage': data['percentage'],
            'submitted_at': datetime.now().isoformat()
        }
        
        # Generate token for next test
        next_grade = int(data['test_grade']) + 1
        token = generate_token(
            data['student_email'],
            data['student_name'],
            data['test_curriculum'],
            data['test_grade']
        )
        
        # Create token link
        token_link = f"{BASE_URL}/index.html?token={token}&grade={next_grade}&curriculum={data['test_curriculum']}"
        
        # Get performance interpretation
        interpretation = get_performance_interpretation(data['percentage'])
        data['interpretation'] = interpretation
        
        # Create and send email
        html_content = create_first_test_email(data, token_link)
        email_result = send_brevo_email(
            data['parent_email'],
            data['parent_name'],
            f"Grade {data['test_grade']} Test Results - Complete Grade {next_grade} Test Within 48 Hours!",
            html_content
        )
        
        # Return response
        if email_result['success']:
            return jsonify({
                'success': True,
                'message': 'Test submitted successfully! Email sent with token link.',
                'token': token,
                'token_link': token_link,
                'next_grade': next_grade,
                'email_sent': True,
                'email': data['parent_email']
            }), 200
        else:
            # Email failed, but test was recorded
            return jsonify({
                'success': False,
                'message': f'Test recorded but email failed: {email_result["message"]}',
                'token': token,
                'token_link': token_link,
                'next_grade': next_grade,
                'email_sent': False,
                'email_error': email_result['message']
            }), 500
    
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error processing test submission: {str(e)}'
        }), 500

@app.route('/api/validate-token/<token>', methods=['GET'])
def validate_token_endpoint(token):
    """
    Validate a token and return test details
    
    Returns:
    {
        'valid': True/False,
        'message': '...',
        'test_details': {...} if valid
    }
    """
    try:
        validation = validate_token(token)
        
        if validation['valid']:
            token_data = validation['data']
            next_grade = int(token_data['test_grade']) + 1
            
            return jsonify({
                'valid': True,
                'message': 'Token is valid',
                'test_details': {
                    'student_email': token_data['student_email'],
                    'student_name': token_data['student_name'],
                    'test_curriculum': token_data['test_curriculum'],
                    'current_grade': token_data['test_grade'],
                    'next_grade': next_grade,
                    'expires_at': token_data['expires_at']
                }
            }), 200
        else:
            return jsonify({
                'valid': False,
                'message': validation['message']
            }), 400
    
    except Exception as e:
        return jsonify({
            'valid': False,
            'message': f'Error validating token: {str(e)}'
        }), 500

@app.route('/api/submit-second-test', methods=['POST'])
def submit_second_test():
    """
    Submit second test results and send combined results email
    
    Expected JSON:
    {
        'token': 'token-string',
        'score': 15,
        'total': 20,
        'percentage': 75,
        'test1_score': 13,
        'test1_total': 18,
        'test1_percentage': 72
    }
    """
    try:
        data = request.get_json()
        token = data.get('token')
        
        if not token:
            return jsonify({
                'success': False,
                'message': 'Token is required'
            }), 400
        
        # Validate token
        validation = validate_token(token)
        if not validation['valid']:
            return jsonify({
                'success': False,
                'message': validation['message']
            }), 400
        
        token_data = validation['data']
        
        # Mark token as used (one-time use)
        mark_token_used(token)
        
        # Prepare combined results data
        combined_data = {
            'student_email': token_data['student_email'],
            'student_name': token_data['student_name'],
            'parent_email': data.get('parent_email', token_data['student_email']),
            'parent_name': data.get('parent_name', 'Parent'),
            'test_curriculum': token_data['test_curriculum'],
            'test1_grade': token_data['test_grade'],
            'test1_score': data.get('test1_score', 0),
            'test1_total': data.get('test1_total', 0),
            'test1_percentage': data.get('test1_percentage', 0),
            'test2_grade': int(token_data['test_grade']) + 1,
            'test2_score': data.get('score', 0),
            'test2_total': data.get('total', 0),
            'test2_percentage': data.get('percentage', 0)
        }
        
        # Create and send combined results email
        html_content = create_combined_results_email(combined_data)
        email_result = send_brevo_email(
            combined_data['parent_email'],
            combined_data['parent_name'],
            f"Complete Diagnostic Results - {combined_data['test_curriculum']} Grades {combined_data['test1_grade']}-{combined_data['test2_grade']}",
            html_content
        )
        
        # Return response
        if email_result['success']:
            return jsonify({
                'success': True,
                'message': 'Second test submitted! Combined results email sent.',
                'email_sent': True,
                'email': combined_data['parent_email']
            }), 200
        else:
            return jsonify({
                'success': False,
                'message': f'Test recorded but email failed: {email_result["message"]}',
                'email_sent': False,
                'email_error': email_result['message']
            }), 500
    
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error processing second test: {str(e)}'
        }), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'tokens_active': len([t for t in tokens_storage.values() if not t['used']]),
        'results_stored': len(test_results_storage)
    }), 200

# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

# ============================================================================
# RUN APP
# ============================================================================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
