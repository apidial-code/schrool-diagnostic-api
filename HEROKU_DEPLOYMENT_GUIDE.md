# Schrool Diagnostic Tests - Heroku Backend Deployment Guide

## What This Backend Does

This Flask backend handles:
- ✅ Receiving test submissions from diagnostic tests
- ✅ Sending result emails via SendGrid
- ✅ First test results + link to second test
- ✅ Combined results after both tests completed
- ✅ CORS enabled for frontend requests

## Prerequisites

1. Heroku account (free tier works)
2. SendGrid account (free tier: 100 emails/day)
3. Git installed on your computer

## Deployment Steps

### Step 1: Install Heroku CLI

**Mac:**
```bash
brew tap heroku/brew && brew install heroku
```

**Windows:**
Download from: https://devcenter.heroku.com/articles/heroku-cli

**Linux:**
```bash
curl https://cli-assets.heroku.com/install.sh | sh
```

### Step 2: Login to Heroku

```bash
heroku login
```

This will open a browser window for authentication.

### Step 3: Create Heroku App

```bash
# Navigate to the backend directory
cd /path/to/heroku_backend_template

# Create new Heroku app
heroku create schrool-diagnostic-api

# Or use existing app
heroku git:remote -a your-existing-app-name
```

### Step 4: Add SendGrid Add-on

```bash
# Add SendGrid free tier (100 emails/day)
heroku addons:create sendgrid:starter

# Get your SendGrid API key
heroku config:get SENDGRID_API_KEY
```

### Step 5: Set Environment Variables

```bash
# SendGrid API key (automatically set by add-on)
# But you can also set it manually if needed
heroku config:set SENDGRID_API_KEY=your_sendgrid_api_key

# Frontend URL
heroku config:set FRONTEND_URL=https://test.schrool.com

# Template IDs (if using SendGrid templates)
heroku config:set FIRST_TEST_TEMPLATE_ID=d-xxxxx
heroku config:set COMBINED_TEST_TEMPLATE_ID=d-yyyyy
```

### Step 6: Deploy to Heroku

```bash
# Initialize git repository (if not already)
git init
git add .
git commit -m "Initial commit - Schrool diagnostic backend"

# Deploy to Heroku
git push heroku main

# Or if your branch is named master
git push heroku master
```

### Step 7: Verify Deployment

```bash
# Open the app in browser
heroku open

# Check logs
heroku logs --tail

# Test the API
curl https://your-app-name.herokuapp.com/
```

## Testing the API

### Health Check

```bash
curl https://your-app-name.herokuapp.com/
```

Expected response:
```json
{
  "status": "running",
  "service": "Schrool Diagnostic Tests API",
  "version": "1.0"
}
```

### Submit Test (Example)

```bash
curl -X POST https://your-app-name.herokuapp.com/api/submit-test \
  -H "Content-Type: application/json" \
  -d '{
    "parent_name": "John Doe",
    "parent_email": "john@example.com",
    "student_name": "Jane Doe",
    "school_grade": "6",
    "test_curriculum": "Australia",
    "test_grade": "5",
    "score": 18,
    "total": 25,
    "percentage": 72,
    "is_first_test": true
  }'
```

## Updating the Frontend to Use Heroku Backend

In your diagnostic test files, replace the EmailJS code with:

```javascript
// Instead of EmailJS
function sendTestResultsEmail(curriculum, grade, score, total, percentage) {
    const userData = JSON.parse(localStorage.getItem('userData') || '{}');
    
    fetch('https://your-app-name.herokuapp.com/api/submit-test', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            parent_name: userData.parentName,
            parent_email: userData.parentEmail,
            student_name: userData.studentName,
            school_grade: userData.schoolGrade,
            test_curriculum: curriculum,
            test_grade: grade,
            score: score,
            total: total,
            percentage: percentage,
            is_first_test: true
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            alert('Email sent successfully!');
        } else {
            alert('Failed to send email: ' + data.error);
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('Failed to send email. Please try again.');
    });
}
```

## Monitoring and Maintenance

### View Logs
```bash
heroku logs --tail
```

### Check App Status
```bash
heroku ps
```

### Restart App
```bash
heroku restart
```

### Scale Dynos
```bash
# Scale up
heroku ps:scale web=1

# Scale down (stop)
heroku ps:scale web=0
```

## Cost Breakdown

### Free Tier (Eco Dynos - $5/month)
- 1,000 dyno hours/month
- Sleeps after 30 min inactivity
- Good for testing/low traffic

### SendGrid Free Tier
- 100 emails/day = 3,000/month
- FREE ✅

### Total Cost: $5/month

## Troubleshooting

### App Not Starting
```bash
heroku logs --tail
```
Check for Python errors or missing dependencies.

### Emails Not Sending
1. Verify SendGrid API key:
   ```bash
   heroku config:get SENDGRID_API_KEY
   ```
2. Check SendGrid dashboard for blocked emails
3. Verify sender email is verified in SendGrid

### CORS Errors
Make sure frontend URL is correct and CORS is enabled in app.py.

## Next Steps

1. ✅ Deploy backend to Heroku
2. ✅ Test API endpoints
3. ✅ Update frontend to use Heroku API
4. ✅ Upload updated frontend to Bunny.net
5. ✅ Test complete flow

## Support

For Heroku issues: https://devcenter.heroku.com/
For SendGrid issues: https://docs.sendgrid.com/

