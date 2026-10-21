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

## ☁️ Part 2: AWS Cloud Architecture Outlook

This section provides an architectural overview of how the ShowGo backend and data layers are hosted on Amazon Web Services (AWS) in production.

### Infrastructure Topology

```mermaid
graph TB
    subgraph Clients ["Client Layer"]
        App["📱 Customer & Merchant Apps"]
        Web["💻 Admin Web Portal"]
    end

    subgraph AWS ["Amazon Web Services (AWS) VPC"]
        IGW["🌐 Internet Gateway"]
        
        subgraph PublicSubnet ["Public Subnet"]
            EC2["🖥️ Amazon EC2 Instance\n(FastAPI Application Server)"]
            SG_EC2["🔒 EC2 Security Group\n(Ports: 80, 443, 8000)"]
        end

        subgraph PrivateSubnet ["Private Subnet (Isolated)"]
            RDS[("🗄️ Amazon RDS PostgreSQL\n(Production Database)")]
            SG_RDS["🔒 RDS Security Group\n(Port 5432 from EC2 SG Only)"]
        end
    end

    subgraph AWS_Services ["Managed AWS Services"]
        S3[("🪣 Amazon S3 Bucket\n(Posters, Avatars & Tickets)")]
        IAM["🔑 AWS IAM Role\n(EC2 Instance Profile)"]
    end

    Clients -->|HTTPS Requests| IGW
    IGW --> EC2
    EC2 -->|SQL Queries (Port 5432)| RDS
    EC2 -.->|Assumes Role| IAM
    IAM -.->|Authorizes Access| S3
    EC2 -->|Direct Media Upload / Read| S3
```

---

### Core AWS Components

#### 1. Amazon EC2 (Public Subnet)
- **Role**: Hosts and executes the FastAPI application server.
- **Network Placement**: Resides in a **Public Subnet** with an assigned Public / Elastic IP connected to the AWS Internet Gateway.
- **Security Group Rules**:
  - `HTTP (80)` / `Custom TCP (8000)`: Inbound traffic for API communication from mobile clients.
  - `HTTPS (443)`: Secure encrypted API traffic.
  - `SSH (22)`: Administrative access restricted strictly to your trusted IP address.
- *Deployment Roadmap*: Production execution on EC2 will be containerized.

#### 2. Amazon RDS PostgreSQL (Private Subnet)
- **Role**: Managed relational database storing users, theatres, movies, shows, and bookings.
- **Network Placement**: Deployed in a dedicated **Private Subnet** with **Public Accessibility set to "No"**. It has no public IP address and cannot be accessed directly from the public internet.
- **Security Group Rules**:
  - `PostgreSQL (5432)`: Inbound traffic allowed **strictly from the EC2 Security Group**. No other inbound connections are permitted.

#### 3. Amazon S3 (Simple Storage Service)
- **Role**: Object storage for media assets including movie posters, theatre banner photos, merchant and user profile avatars, and generated ticket receipts.
- **Access Control**: Configured with CORS rules to permit image rendering on mobile applications, with write permissions restricted via IAM.

#### 4. AWS IAM Role (EC2 Instance Profile)
- **Role**: Grants the EC2 instance authenticated access to Amazon S3.
- **Security Advantage**: By attaching an IAM Role directly to the EC2 instance, the application automatically retrieves temporary credentials via the AWS Instance Metadata Service. This eliminates the need to hardcode `AWS_ACCESS_KEY_ID` or `AWS_SECRET_ACCESS_KEY` in the production `.env` file.
