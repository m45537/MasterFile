# Deployment Guide - Dataset Reconciliation System

## Quick Start (5 minutes)

### Prerequisites
- Python 3.8+ installed
- Command line/terminal access
- 2GB free RAM

### Installation Steps

1. **Download the files** to a folder on your computer

2. **Open terminal/command prompt** and navigate to the folder:
```bash
cd path/to/dataset-reconciliation
```

3. **Install requirements**:
```bash
pip install streamlit pandas openpyxl xlsxwriter pytz numpy plotly
```

4. **Run the application**:
```bash
streamlit run app_enhanced.py
```

5. **Open browser** to http://localhost:8501

## Production Deployment Options

### Option 1: Local Server Deployment

Perfect for: Small teams, internal networks

```bash
# Install as a service (Windows)
nssm install DatasetReconciliation "python" "streamlit run app_enhanced.py"

# Install as a service (Linux)
sudo nano /etc/systemd/system/dataset-reconciliation.service
```

Service file content:
```ini
[Unit]
Description=Dataset Reconciliation System
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/app
ExecStart=/usr/bin/python3 -m streamlit run app_enhanced.py --server.port 8080
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable dataset-reconciliation
sudo systemctl start dataset-reconciliation
```

### Option 2: Docker Deployment

Create `Dockerfile`:
```dockerfile
FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app_enhanced.py .
COPY test_app_enhanced.py .

EXPOSE 8501

CMD ["streamlit", "run", "app_enhanced.py", "--server.address=0.0.0.0"]
```

Build and run:
```bash
docker build -t dataset-reconciliation .
docker run -p 8501:8501 dataset-reconciliation
```

### Option 3: Cloud Deployment

#### Streamlit Cloud (Recommended for simplicity)

1. Push code to GitHub repository
2. Visit share.streamlit.io
3. Connect GitHub account
4. Deploy with one click

#### Heroku

Create `Procfile`:
```
web: sh setup.sh && streamlit run app_enhanced.py
```

Create `setup.sh`:
```bash
mkdir -p ~/.streamlit/

echo "\
[server]\n\
headless = true\n\
port = $PORT\n\
enableCORS = false\n\
\n\
" > ~/.streamlit/config.toml
```

Deploy:
```bash
heroku create dataset-reconciliation
git push heroku main
```

#### AWS EC2

1. Launch EC2 instance (t2.medium recommended)
2. SSH into instance
3. Install Python and dependencies
4. Run application with supervisor or systemd
5. Configure security group for port 8501

## Network Configuration

### Firewall Rules
Open port 8501 (or your chosen port) for web traffic:

```bash
# Linux (UFW)
sudo ufw allow 8501

# Windows
netsh advfirewall firewall add rule name="Dataset Reconciliation" dir=in action=allow protocol=TCP localport=8501
```

### Reverse Proxy (Nginx)

For production with custom domain:

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:8501;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

## Environment Configuration

### Memory Settings

For large datasets, increase Python memory:

```bash
# Linux/Mac
export PYTHONMAXMEM=4G
streamlit run app_enhanced.py

# Windows
set PYTHONMAXMEM=4G
streamlit run app_enhanced.py
```

### Streamlit Configuration

Create `.streamlit/config.toml`:

```toml
[server]
maxUploadSize = 200  # MB
maxMessageSize = 200

[browser]
serverAddress = "localhost"
gatherUsageStats = false
serverPort = 8501

[runner]
magicEnabled = true
installTracer = false

[client]
showErrorDetails = true
```

## Performance Tuning

### For Large Files (>50MB)

1. Increase upload limits in config.toml
2. Use SSD storage for temp files
3. Allocate more RAM (8GB+ recommended)
4. Consider batch processing

### Database Cache (Optional)

For frequently accessed data, add Redis caching:

```python
import redis
import pickle

r = redis.Redis(host='localhost', port=6379, db=0)

def cached_parse(file_hash):
    cached = r.get(f"parse:{file_hash}")
    if cached:
        return pickle.loads(cached)
    # Parse file
    result = parse_file(file)
    r.setex(f"parse:{file_hash}", 3600, pickle.dumps(result))
    return result
```

## Monitoring

### Basic Monitoring

Add to app_enhanced.py:

```python
import logging
from datetime import datetime

# Log usage
def log_usage(action, details=""):
    timestamp = datetime.now().isoformat()
    with open("usage.log", "a") as f:
        f.write(f"{timestamp},{action},{details}\n")
```

### Advanced Monitoring

Use Prometheus + Grafana:

```python
from prometheus_client import Counter, Histogram, generate_latest

# Metrics
process_counter = Counter('dataset_reconciliation_processed', 'Files processed')
process_time = Histogram('dataset_reconciliation_duration', 'Processing duration')

# In your processing function
@process_time.time()
def process_files():
    # ... processing ...
    process_counter.inc()
```

## Backup and Recovery

### Automated Backups

```bash
#!/bin/bash
# backup.sh - Run daily via cron

BACKUP_DIR="/backups/dataset-reconciliation"
DATE=$(date +%Y%m%d)

# Backup uploaded files
tar -czf "$BACKUP_DIR/uploads_$DATE.tar.gz" /path/to/uploads/

# Backup logs
tar -czf "$BACKUP_DIR/logs_$DATE.tar.gz" /path/to/logs/

# Keep only last 30 days
find "$BACKUP_DIR" -name "*.tar.gz" -mtime +30 -delete
```

Add to crontab:
```bash
0 2 * * * /path/to/backup.sh
```

## Security Hardening

### SSL/TLS Setup

For production, always use HTTPS:

```bash
# Generate certificate with Let's Encrypt
sudo certbot certonly --standalone -d your-domain.com

# Update Nginx config to use SSL
server {
    listen 443 ssl;
    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
    # ... rest of config
}
```

### Access Control

Add basic authentication:

```python
import streamlit as st
import hashlib

def check_password():
    """Returns `True` if the user had the correct password."""
    
    def password_entered():
        """Checks whether a password entered by the user is correct."""
        if hashlib.sha256(st.session_state["password"].encode()).hexdigest() == HASHED_PASSWORD:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("Password", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("Password", type="password", on_change=password_entered, key="password")
        st.error("😕 Password incorrect")
        return False
    else:
        return True

# Use in main app
if not check_password():
    st.stop()
```

## Troubleshooting Deployment

### Common Issues

1. **Port already in use**:
```bash
# Find process using port
lsof -i :8501  # Linux/Mac
netstat -ano | findstr :8501  # Windows

# Kill process or use different port
streamlit run app_enhanced.py --server.port 8502
```

2. **Module not found**:
```bash
# Ensure virtual environment is activated
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

3. **Permission denied**:
```bash
# Fix file permissions
chmod +x app_enhanced.py
chmod 755 /path/to/app/directory
```

4. **Out of memory**:
- Reduce max file size in Config
- Increase system swap space
- Use a larger server instance

## Support Resources

- **Documentation**: See README.md
- **Tests**: Run `pytest test_app_enhanced.py`
- **Logs**: Check `streamlit.log` and `usage.log`
- **Debug**: Enable debug mode in sidebar

---

*Deployment Guide v1.0 - Dataset Reconciliation System*