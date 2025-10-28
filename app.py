"""
Schrool Diagnostic Tests Backend
Flask API for handling test submissions and email notifications
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email, To, Content
import os
from datetime import datetime
import json

app = Flask(__name__)
CORS(app)  # Enable CORS for frontend requests

# SendGrid API Key (set in Heroku environment variables)
SENDGRID_API_KEY = os.environ.get('SENDGRID_API_KEY')

# Email templates
FIRST_TEST_TEMPLATE_ID = os.environ.get('FIRST_TEST_TEMPLATE_ID')
COMBINED_TEST_TEMPLATE_ID = os.environ.get('COMBINED_TEST_TEMPLATE_ID')

@app.route('/')
def home():
    """Health check endpoint"""
    return jsonify({
        'status': 'running',
        'service': 'Schrool Diagnostic Tests API',
        'version': '1.0'
    })

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
        "test_curriculum": "Australia",
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
        
        # Send appropriate email
        if data.get('is_first_test', True):
            result = send_first_test_email(data)
        else:
            result = send_combined_results_email(data)
        
        return jsonify(result), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def send_first_test_email(data):
    """Send email with first test results and link to second test"""
    
    try:
        # Get base URL from environment or request
        base_url = os.environ.get('FRONTEND_URL', 'https://test.schrool.com')
        second_test_link = f"{base_url}/schrool-fresher/index.html#grade-selection"
        
        # Prepare email content
        message = Mail(
            from_email=Email('diagnostics@schrool.com', 'Schrool Diagnostics'),
            to_emails=To(data['parent_email']),
            subject=f"{data['student_name']}'s Math Diagnostic Test Results"
        )
        
        # Email body
        interpretation = get_interpretation(data['percentage'])
        
        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #2563eb;">Test Results for {data['student_name']}</h2>
                
                <p>Dear {data.get('parent_name', 'Parent')},</p>
                
                <p>Thank you for completing the first diagnostic test for {data['student_name']}!</p>
                
                <div style="background: #f3f4f6; padding: 20px; border-radius: 8px; margin: 20px 0;">
                    <h3 style="margin-top: 0;">Test Results</h3>
                    <p><strong>Test:</strong> {data['test_curriculum']} Grade {data['test_grade']}</p>
                    <p><strong>Score:</strong> {data['score']} out of {data['total']} ({data['percentage']}%)</p>
                </div>
                
                <div style="background: #eff6ff; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #2563eb;">
                    <h3 style="margin-top: 0;">Performance Assessment</h3>
                    <p>{interpretation}</p>
                </div>
                
                <div style="background: #fef3c7; padding: 20px; border-radius: 8px; margin: 20px 0;">
                    <h3 style="margin-top: 0;">Next Steps</h3>
                    <p>We'll wait for the second test to be completed before providing a full diagnosis of your child's math situation.</p>
                    <p style="margin-top: 15px;">
                        <a href="{second_test_link}" 
                           style="background: #2563eb; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; display: inline-block;">
                            Take Second Test Now
                        </a>
                    </p>
                    <p style="font-size: 14px; color: #666; margin-top: 10px;">
                        We recommend completing the second test within 48 hours for the most accurate assessment.
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
        
        message.content = Content("text/html", html_content)
        
        # Send email via SendGrid
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        
        return {
            'success': True,
            'message': 'First test results email sent',
            'email': data['parent_email']
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }

def send_combined_results_email(data):
    """Send email with combined results from both tests"""
    
    try:
        # Prepare email content
        message = Mail(
            from_email=Email('diagnostics@schrool.com', 'Schrool Diagnostics'),
            to_emails=To(data['parent_email']),
            subject=f"Complete Diagnostic Results for {data['student_name']}"
        )
        
        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #10b981;">🎉 Congratulations!</h2>
                
                <p>Dear {data.get('parent_name', 'Parent')},</p>
                
                <p>{data['student_name']} has completed both diagnostic tests!</p>
                
                <div style="background: #f0fdf4; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #10b981;">
                    <h3 style="margin-top: 0;">Complete Results Summary</h3>
                    <p><strong>Test 1:</strong> {data.get('test1_name', 'First Test')} - {data.get('test1_score', 'N/A')}%</p>
                    <p><strong>Test 2:</strong> {data.get('test2_name', 'Second Test')} - {data.get('test2_score', 'N/A')}%</p>
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
        
        message.content = Content("text/html", html_content)
        
        # Send email via SendGrid
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        
        return {
            'success': True,
            'message': 'Combined results email sent',
            'email': data['parent_email']
        }
        
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

