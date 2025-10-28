# Quick Deployment Commands

## After creating the Heroku app, run these commands:

### 1. Login to Heroku (if not already logged in)
```bash
heroku login
```

### 2. Add Heroku remote
```bash
cd /home/ubuntu/heroku_backend_template
heroku git:remote -a schrool-diagnostic-api
```

### 3. Add SendGrid add-on (free tier)
```bash
heroku addons:create sendgrid:starter -a schrool-diagnostic-api
```

### 4. Set environment variables
```bash
heroku config:set FRONTEND_URL=https://test.schrool.com -a schrool-diagnostic-api
```

### 5. Deploy to Heroku
```bash
git push heroku master
```

### 6. Open the app
```bash
heroku open -a schrool-diagnostic-api
```

### 7. Check logs
```bash
heroku logs --tail -a schrool-diagnostic-api
```

## Testing the API

### Health check
```bash
curl https://schrool-diagnostic-api.herokuapp.com/
```

Should return:
```json
{
  "status": "running",
  "service": "Schrool Diagnostic Tests API",
  "version": "1.0"
}
```

### Test email sending
```bash
curl -X POST https://schrool-diagnostic-api.herokuapp.com/api/submit-test \
  -H "Content-Type: application/json" \
  -d '{
    "parent_name": "Test Parent",
    "parent_email": "your-email@example.com",
    "student_name": "Test Student",
    "school_grade": "6",
    "test_curriculum": "Australia",
    "test_grade": "5",
    "score": 18,
    "total": 25,
    "percentage": 72,
    "is_first_test": true
  }'
```

## Troubleshooting

If deployment fails:
```bash
heroku logs --tail -a schrool-diagnostic-api
```

If emails not sending:
```bash
heroku config -a schrool-diagnostic-api
```
Check that SENDGRID_API_KEY is set.

