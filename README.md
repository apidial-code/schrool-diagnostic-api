# Schrool Diagnostic Tests API

Backend API for Schrool diagnostic math tests with email integration.

## Features

- ✅ Test submission endpoint
- ✅ SendGrid email integration
- ✅ Automatic email sending for test results
- ✅ Support for first and second test scenarios
- ✅ CORS enabled for frontend integration

## API Endpoints

### Health Check
```
GET /
```

### Submit Test Results
```
POST /api/submit-test
```

**Request Body:**
```json
{
  "parent_name": "John Doe",
  "parent_email": "parent@example.com",
  "student_name": "Jane Doe",
  "school_grade": "6",
  "test_curriculum": "Australia",
  "test_grade": "5",
  "score": 18,
  "total": 25,
  "percentage": 72,
  "is_first_test": true
}
```

## Deployment

This app is designed to be deployed on Heroku with SendGrid add-on.

### Environment Variables

- `SENDGRID_API_KEY` - Automatically set by SendGrid add-on
- `FRONTEND_URL` - URL of the frontend (e.g., https://test.schrool.com)

## Local Development

```bash
pip install -r requirements.txt
python app.py
```

## License

Proprietary - Schrool 2025
