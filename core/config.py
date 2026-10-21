from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App
    APP_NAME: str = "Movie Ticket Backend"
    DEBUG: bool = True

    # Database
    DATABASE_URL: str

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    SEAT_LOCK_TTL: int = 600  # seconds (10 minutes)

    # Auth
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 525600 # 1 year

    # OTP
    OTP_EXPIRE_SECONDS: int = 300

    # AWS S3
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_S3_BUCKET: str = ""
    AWS_REGION: str = ""

    # SMS via AWS SNS (reuses same AWS credentials above)


    # SMTP (Email OTP)
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASS: str = ""
    SMTP_FROM: str = "noreply@showgo.com"

    model_config = {
        "env_file": ".env",
        "extra": "ignore"
    }


settings = Settings()
