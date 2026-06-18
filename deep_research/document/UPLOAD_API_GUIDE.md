# Document Upload API - Quick Start Guide

This guide shows you how to use the Document Upload API to programmatically upload documents to your deep research agent.

## 🚀 Quick Start

### 1. Configure Your API Key

First, generate a secure API key:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Copy the output and add it to your `.env` file:

```properties
UPLOAD_API_KEY=your_generated_key_here
UPLOAD_HOST=0.0.0.0
UPLOAD_PORT=2024
```

### 2. Start the Server

```bash
cd deep_research
uv run python webapp.py
```

You should see:
```
🚀 Starting Document Upload API on 0.0.0.0:2024
📁 Documents root: /path/to/deep_research/docs
🔑 API Key authentication: Enabled
```

### 3. Upload Documents

#### Using curl

Upload a single file:
```bash
curl -X POST http://localhost:2024/documents/upload \
  -H 'X-API-Key: your_generated_key_here' \
  -F 'folder=policy' \
  -F 'files=@document.pdf'
```

Upload multiple files:
```bash
curl -X POST http://localhost:2024/documents/upload \
  -H 'X-API-Key: your_generated_key_here' \
  -F 'folder=policy' \
  -F 'files=@doc1.pdf' \
  -F 'files=@doc2.pdf' \
  -F 'files=@doc3.pdf'
```

#### Using Python

```python
import requests

api_key = "your_generated_key_here"
url = "http://localhost:2024/documents/upload"

# Upload single file
with open('document.pdf', 'rb') as f:
    files = {'files': ('document.pdf', f, 'application/pdf')}
    data = {'folder': 'policy'}
    headers = {'X-API-Key': api_key}
    
    response = requests.post(url, files=files, data=data, headers=headers)
    print(response.json())

# Upload multiple files
files_to_upload = [
    ('files', ('doc1.pdf', open('doc1.pdf', 'rb'), 'application/pdf')),
    ('files', ('doc2.pdf', open('doc2.pdf', 'rb'), 'application/pdf')),
]
data = {'folder': 'policy'}
headers = {'X-API-Key': api_key}

response = requests.post(url, files=files_to_upload, data=data, headers=headers)
print(response.json())
```

### 4. List Files in Folder

Get a list of all files in a folder with their names and sizes:

```bash
curl -H 'X-API-Key: your_generated_key_here' \
  'http://localhost:2024/documents/list?folder=policy'
```

Response:
```json
{
  "folder": "policy",
  "count": 3,
  "files": [
    {
      "name": "document1.pdf",
      "size": 642000
    },
    {
      "name": "document2.pdf",
      "size": 523000
    },
    {
      "name": "document3.pdf",
      "size": 789000
    }
  ]
}
```

Using Python:
```python
import requests

api_key = "your_generated_key_here"
url = "http://localhost:2024/documents/list"
params = {'folder': 'policy'}
headers = {'X-API-Key': api_key}

response = requests.get(url, params=params, headers=headers)
print(response.json())
```

### 5. Download Files

Download a specific file from a folder:

```bash
curl -H 'X-API-Key: your_generated_key_here' \
  'http://localhost:2024/documents/download/document1.pdf?folder=policy' \
  -o downloaded_document.pdf
```

Using Python:
```python
import requests

api_key = "your_generated_key_here"
filename = "document1.pdf"
url = f"http://localhost:2024/documents/download/{filename}"
params = {'folder': 'policy'}
headers = {'X-API-Key': api_key}

response = requests.get(url, params=params, headers=headers)

if response.status_code == 200:
    with open(f'downloaded_{filename}', 'wb') as f:
        f.write(response.content)
    print(f"File downloaded successfully")
else:
    print(f"Error: {response.status_code} - {response.text}")
```

### 6. Check Storage Info

```bash
curl -H 'X-API-Key: your_generated_key_here' http://localhost:2024/storage/info
```

Response:
```json
{
  "total_space_bytes": 500000000000,
  "used_space_bytes": 401234567900,
  "free_space_bytes": 98765432100,
  "total_space_human": "465.66 GB",
  "used_space_human": "373.66 GB",
  "free_space_human": "92.00 GB",
  "usage_percentage": 80.25
}
```

### 7. Health Check (No Auth Required)

```bash
curl http://localhost:2024/health
```

## 📋 API Endpoints Summary

| Endpoint | Method | Auth Required | Description |
|----------|--------|---------------|-------------|
| `/documents/upload` | POST | ✅ Yes | Upload documents to a folder |
| `/documents/list` | GET | ✅ Yes | List files in a folder with name and size |
| `/documents/download/{filename}` | GET | ✅ Yes | Download a specific file |
| `/storage/info` | GET | ✅ Yes | Get detailed storage information |
| `/health` | GET | ❌ No | Health check endpoint |

## 🔐 Security Best Practices

1. **Use Strong API Keys**: Always use randomly generated keys (32+ characters)
2. **Enable HTTPS**: Use SSL/TLS in production with a reverse proxy (nginx, Apache)
3. **Rate Limiting**: Implement rate limiting for public deployments
4. **Monitor Logs**: Regularly check access logs for suspicious activity
5. **Rotate Keys**: Periodically rotate your API keys

## 🌐 Public Access Setup

To expose the API publicly:

### Option 1: Direct Exposure (Development Only)

```bash
export UPLOAD_HOST=0.0.0.0
export UPLOAD_PORT=2024
uv run python webapp.py
```

Then configure your firewall/router to forward port 2024.

### Option 2: Behind Nginx (Production Recommended)

Create `/etc/nginx/sites-available/upload-api`:

```nginx
server {
    listen 443 ssl;
    server_name uploads.yourdomain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://localhost:2024;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable the site:
```bash
sudo ln -s /etc/nginx/sites-available/upload-api /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

## 🧪 Testing

Run the included test suite:

```bash
uv run python test_upload_api.py
```

This will verify:
- ✅ Health endpoint works
- ✅ Authentication is enforced
- ✅ File uploads work correctly
- ✅ Storage info returns accurate data
- ✅ Free space is calculated after uploads

## 📁 Folder Structure

Uploaded files are stored in:
```
deep_research/
└── docs/
    ├── policy/          # Default folder
    ├── resume/
    ├── interview_prep/
    └── ...              # Any custom folder you specify
```

## 💡 Tips

1. **Organize by Project**: Use different folders for different projects
   ```bash
   curl -X POST http://localhost:2024/documents/upload \
     -H 'X-API-Key: your_key' \
     -F 'folder=project-alpha/policies' \
     -F 'files=@policy.pdf'
   ```

2. **Batch Uploads**: Upload multiple related documents at once
   ```bash
   curl -X POST http://localhost:2024/documents/upload \
     -H 'X-API-Key: your_key' \
     -F 'folder=research/sources' \
     -F 'files=@source1.pdf' \
     -F 'files=@source2.pdf' \
     -F 'files=@source3.pdf'
   ```

3. **Check Before Upload**: Use the health endpoint to verify available space
   ```bash
   curl http://localhost:2024/health
   ```

## ❓ Troubleshooting

### "Invalid or missing API key"
- Ensure you're sending the `X-API-Key` header
- Verify the key matches what's in your `.env` file
- Restart the server after changing the `.env` file

### "folder must be a relative path inside docs"
- Don't use absolute paths (e.g., `/home/user/docs`)
- Don't use `..` to traverse directories
- Use simple relative paths like `policy`, `research/sources`, etc.

### Server won't start
- Check if port 2024 is already in use: `lsof -i :2024`
- Change the port: `export UPLOAD_PORT=8001`
- Ensure you have write permissions to the `docs` directory

## 🔗 Next Steps

After uploading documents, you can use them with the deep research agent:

```bash
uv run python research_agent_cli.py "Research topic" --doc-folder ./docs/policy
```

Or via LangGraph Studio:
```
langgraph dev
```

Then reference the uploaded documents in your queries!
