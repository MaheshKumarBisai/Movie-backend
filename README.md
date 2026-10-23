# ShowGo — Backend Setup & Architecture Guide

FastAPI-powered backend service for the **ShowGo** movie ticketing platform. Provides REST APIs for authentication, movie listings, seat layout & temporary locking, booking transactions, and merchant management.

---

## 💻 Part 1: Local Development Setup (Windows PowerShell)

Follow these step-by-step instructions to run the backend locally using **Windows PowerShell**.

### Prerequisites
- **Python 3.10+** installed ([python.org](https://www.python.org/downloads/))
- **PostgreSQL 14+** running locally (or access to an existing database instance)
- **Git**

---

### Step 1: Open PowerShell & Navigate to Backend
Open Windows PowerShell and navigate to the `backend` folder:
```powershell
cd C:\path\to\Movie-app\backend
```

---

### Step 2: Create a Virtual Environment
Create an isolated Python virtual environment:
```powershell
python -m venv venv
```

---

### Step 3: Enable Script Execution & Activate Environment
In Windows PowerShell, script execution is restricted by default. Enable execution for the current session and activate:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process
.\venv\Scripts\Activate.ps1
```
> *(You will see `(venv)` prepended to your PowerShell prompt once activated).*

---

### Step 4: Upgrade Pip & Install Dependencies
```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

---

### Step 5: Configure Environment Variables (`.env`)
Create a `.env` file in the `backend/` root directory:

```powershell
New-Item -ItemType File -Name .env -Force
```

Populate `.env` with your local configuration:
```env
# Application
APP_NAME="Movie Ticket Backend"
DEBUG=True

# Database Connection (PostgreSQL)
# Format: postgresql://<user>:<password>@<host>:<port>/<database_name>
DATABASE_URL="postgresql://postgres:yourpassword@localhost:5432/moviedb"

# Redis (Seat Locking Cache - Optional for basic dev)
REDIS_URL="redis://localhost:6379/0"

# JWT Authentication
JWT_SECRET_KEY="your-secure-random-jwt-secret-key"
JWT_EXPIRE_MINUTES=525600
OTP_EXPIRE_SECONDS=300
SEAT_LOCK_TTL=600

# AWS S3 (Media & Image Uploads)
AWS_ACCESS_KEY_ID="your-aws-access-key-id"
AWS_SECRET_ACCESS_KEY="your-aws-secret-access-key"
AWS_S3_BUCKET="your-s3-bucket-name"
AWS_REGION="us-east-2"

# SMTP Settings (Email OTP & Ticket Delivery)
SMTP_HOST="smtp.gmail.com"
SMTP_PORT=587
SMTP_USER="your-email@gmail.com"
SMTP_PASS="your-google-app-password"
SMTP_FROM="noreply@showgo.com"
```

---

### Step 6: Initialize Database Schema & Seed Core Accounts
Run the automated database setup script. This script automatically builds all database tables, performs column synchronizations, and seeds the initial default accounts:
- **Merchant Account**: `merchant@test.com` (Password: `password123`)
- **Admin Account**: `admin@test.com` (Password: `admin123`)

```powershell
python -m scripts.setup_complete_db
```

---

### Step 7: Start the FastAPI Server
Launch the development server with auto-reload enabled:
```powershell
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

---

### Step 8: Verify API & Interactive Documentation
Once started, test the backend in your browser:
- **Interactive Swagger UI**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **ReDoc Documentation**: [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)
- **Health Check**: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)

---

### 🛠️ Local Maintenance Scripts

Run these utility scripts from PowerShell as needed:

#### 1. Clear Sample Data (Preserves User Accounts)
Removes test movies, theatres, and bookings while keeping your user accounts intact:
```powershell
python -m scripts.clear_seeded_data
```

#### 2. Promote User to Merchant / Admin
Promotes an existing registered email to merchant or administrator status:
```powershell
python -m scripts.promote_user user@example.com
```

---

## ☁️ Part 2: AWS Cloud Architecture & Deployment Guide

This section covers the end-to-end production deployment of the **ShowGo Backend** on Amazon Web Services (AWS) using **Docker** and **GitHub Actions**.

---

### 🏛️ Infrastructure Architecture

<p align="center">
  <img src="docs/aws-architecture.png" alt="ShowGo AWS Cloud Architecture" width="100%">
</p>
---

### 📋 Step-by-Step AWS Setup (Order of Operations)

#### Step 1: Amazon RDS PostgreSQL (Private Subnet)
1. **Create Database**:
   - Engine: **PostgreSQL** (version 17 or 18 recommended).
   - DB instance identifier: e.g. `movie-backend`.
   - **Public Access**: Select **No** (places RDS securely in a private subnet).
2. **Configure RDS Security Group**:
   - In the RDS Security Group, add an **Inbound Rule**:
     - **Type**: `PostgreSQL` (Port `5432`)
     - **Source**: Select **Custom** → Enter your **EC2 Security Group ID** (`sg-xxxxxxxx`).
   > *This guarantees that only your EC2 application server can communicate with the database. The database is completely shielded from public internet traffic.*

---

#### Step 2: Amazon S3 (Media & Image Uploads)
1. **Create S3 Bucket**:
   - Bucket name: e.g. `movie-app-images-123`
   - Region: e.g. `us-east-2`
2. **Permissions (Allow Mobile App to Read Images)**:
   - Under **Block public access (bucket settings)**: Click **Edit** → **Uncheck** *"Block all public access"* → **Save**.
   - Under **Bucket Policy**: Click **Edit** → Paste the public read policy:
     ```json
     {
       "Version": "2012-10-17",
       "Statement": [
         {
           "Sid": "PublicReadGetObject",
           "Effect": "Allow",
           "Principal": "*",
           "Action": "s3:GetObject",
           "Resource": "arn:aws:s3:::movie-app-images-123/*"
         }
       ]
     }
     ```

---

#### Step 3: Amazon EC2 (Application Host)
1. **Launch EC2 Instance**:
   - AMI: **Ubuntu 24.04 LTS** (or 22.04 LTS).
   - Instance Type: `t3.micro` or `t3.small` (recommended for Docker).
   - Network: Same VPC as RDS, placed in a **Public Subnet** with Auto-assign Public IP **Enabled**.
2. **Configure EC2 Security Group**:
   - **Inbound Rules**:
     - `SSH (22)`: Your IP address (and GitHub Actions runner CIDRs if restricted).
     - `Custom TCP (8000)`: `0.0.0.0/0` (allows mobile apps to reach FastAPI).
   - **Outbound Rules**:
     - `All traffic (0.0.0.0/0)`: Default rule (allows EC2 to connect to RDS and S3).
3. **One-Time Server Setup on EC2**:
   SSH into your EC2 instance and install Docker and Git:
   ```bash
   sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
   sudo usermod -aG docker ubuntu
   newgrp docker
   ```

---

#### Step 4: Database Initialization on RDS
Once your backend container is deployed or running on EC2, initialize the schema, create all 18 tables, and populate initial admin/merchant seed data:

```bash
# Execute the setup script directly inside the running container
docker exec -it movie-backend python -m scripts.setup_complete_db
```

---

### 🚀 Step 5: Automated CI/CD Deployment (GitHub Actions)

The deployment workflow is defined in [`.github/workflows/deploy-backend.yml`](.github/workflows/deploy-backend.yml).

#### Security Architecture:
- **Zero `.env` file on EC2**: Environment variables are injected directly into the running Docker container in-memory via `-e` flags. No secret credentials are ever saved to the EC2 hard drive.
- **Multi-Stage Docker Image**: Compiled inside a builder stage; final image contains only pre-built wheels and runs under a non-root `appuser`.
- **Isolated Docker Network**: `movie-backend` and `movie-redis` communicate over an internal Docker bridge network (`movie-net`).

---

#### Required GitHub Settings

Go to your backend repository on GitHub → **Settings → Secrets and variables → Actions**:

##### 🔒 Secrets Tab (`secrets.*` — Confidential)
| Secret Name | Description | Example / Notes |
|---|---|---|
| `SSH_PRIVATE_KEY` | Contents of your EC2 `.pem` key | `-----BEGIN RSA PRIVATE KEY-----...` |
| `DATABASE_URL` | RDS PostgreSQL connection string | `postgresql://postgres:password@movie-backend.xxxx.us-east-2.rds.amazonaws.com:5432/postgres` |
| `JWT_SECRET_KEY` | Strong random secret for signing JWTs | `your-secure-jwt-secret-key` |
| `AWS_ACCESS_KEY_ID` | IAM User Access Key ID with S3 permissions | `AKIA...` |
| `AWS_SECRET_ACCESS_KEY` | IAM User Secret Access Key | `wJalrXUtnFEMI/K7MDENG/bPxRfiCY...` |
| `SMTP_USER` | Gmail address for sending booking & OTP emails | `your-email@gmail.com` |
| `SMTP_PASS` | Gmail 16-character App Password | `abcd efgh ijkl mnop` |

##### 🌐 Variables Tab (`vars.*` — Configuration)
| Variable Name | Description | Recommended Value |
|---|---|---|
| `EC2_HOST` | Public IP or DNS of your EC2 instance | `3.142.171.143` |
| `EC2_USER` | EC2 SSH username | `ubuntu` |
| `AWS_S3_BUCKET` | S3 Bucket Name for media uploads | `movie-app-images-123` |
| `AWS_REGION` | AWS Region of your S3 Bucket | `us-east-2` |
| `REDIS_URL` | Internal Redis URL on Docker network | `redis://movie-redis:6379/0` |
| `APP_NAME` | Application name | `Movie Ticket Backend` |
| `DEBUG` | FastAPI debug mode | `False` |
| `SMTP_HOST` | SMTP server host | `smtp.gmail.com` |
| `SMTP_PORT` | SMTP port | `587` |
| `SMTP_FROM` | Sender display email | `noreply@showgo.com` |
| `SEAT_LOCK_TTL` | Seat reservation lock duration (seconds) | `600` |
| `OTP_EXPIRE_SECONDS` | OTP expiration duration (seconds) | `300` |

---

### 🛠️ Useful EC2 Operational Commands

Once deployed on EC2, manage your backend using standard Docker commands:

```bash
# View running containers (movie-backend and movie-redis)
docker ps

# Stream live application logs
docker logs -f movie-backend

# Restart backend service
docker restart movie-backend

# Run complete database setup / table sync
docker exec -it movie-backend python -m scripts.setup_complete_db
```



