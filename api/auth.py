from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from uuid import uuid4
import random
from pydantic import BaseModel
from typing import Optional
from core.database import get_db
from models.user import User
from api import deps
from schemas.user import UserResponse, UserUpdateRequest
from utils.jwt import create_access_token

from core.config import settings
from core.redis import redis_client

router = APIRouter(prefix="/auth", tags=["Auth"])




from schemas.auth import LoginRequest, VerifyOTPRequest, UserRole, OTPPurpose
from utils.password import get_password_hash, verify_password

@router.post("/request-otp")
async def request_otp(payload: LoginRequest, db: Session = Depends(get_db)):
    """
    Send OTP to email (primary) or mobile. Returns is_existing_user flag.
    If purpose is RESET, ensures user exists first.
    """
    email = payload.email
    mobile = payload.mobile
    purpose = payload.purpose
    
    if not email and not mobile:
        raise HTTPException(status_code=400, detail="Email address is required")
        
    identifier = email if email else mobile

    # Check existence
    if email:
        existing_user = db.query(User).filter(User.email == email).first()
    else:
        existing_user = db.query(User).filter(User.mobile == mobile).first()
        
    is_existing_user = existing_user is not None

    if purpose == OTPPurpose.RESET and not is_existing_user:
        raise HTTPException(status_code=404, detail="No account found with this email")

    otp = random.randint(100000, 999999)
    print(f" Your ShowGO OTP for {identifier} ({purpose}): {otp}")
    
    # Store in Redis with expiry
    redis_client.setex(f"otp:{identifier}", settings.OTP_EXPIRE_SECONDS, str(otp))

    sent_via = None
    if email:
        from services.email import send_otp_email
        success = await send_otp_email(email, otp)
        if success:
            sent_via = "email"
    
    if not sent_via and mobile:
        from services.sms import send_otp_sms
        success = await send_otp_sms(mobile, otp)
        if success:
            sent_via = "sms"

    return {
        "message": f"OTP sent to {identifier}" if sent_via else "Failed to send OTP",
        "sent_via": sent_via,
        "is_existing_user": is_existing_user
    }
    


@router.post("/verify-otp")
def verify_otp(
    payload: VerifyOTPRequest,
    db: Session = Depends(get_db)
):
    email = payload.email
    mobile = payload.mobile
    otp = str(payload.otp)
    role = payload.role
    password = payload.password
    
    if not email and not mobile:
        raise HTTPException(status_code=400, detail="Email address is required")
        
    identifier = email if email else mobile
    stored_otp = redis_client.get(f"otp:{identifier}")

    if not stored_otp or str(stored_otp) != otp:
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")

    # OTP verified, remove it
    redis_client.delete(f"otp:{identifier}")

    if email:
        user = db.query(User).filter(User.email == email).first()
    else:
        user = db.query(User).filter(User.mobile == mobile).first()

    is_new_user = False
    if not user:
        is_new_user = True
        # Create new user with appropriate role
        is_admin = (role == "ADMIN" or role == UserRole.ADMIN)
        is_merchant = (role == "MERCHANT" or role == UserRole.MERCHANT)
        
        # Hash password if provided
        hashed_pw = get_password_hash(password) if password else None
        
        user = User(
            email=email,
            mobile=mobile, 
            is_verified=True, 
            is_admin=is_admin, 
            is_merchant=is_merchant,
            password_hash=hashed_pw
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        # User exists, check privileges if creating admin session
        if (role == "ADMIN" or role == UserRole.ADMIN) and not user.is_admin:
             raise HTTPException(status_code=403, detail="User exists but is not an admin")
        
        if password:
             user.password_hash = get_password_hash(password)
             db.commit()

    access_token = create_access_token(subject=str(user.id))

    user_role = "USER"
    if user.is_admin:
        user_role = "ADMIN"
    elif user.is_merchant:
        user_role = "MERCHANT"

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_role": user_role,
        "is_new_user": is_new_user
    }



@router.post("/login-password")
def login_password(
    payload: LoginRequest,
    db: Session = Depends(get_db)
):
    email = payload.email
    mobile = payload.mobile
    password = payload.password
    role = payload.role

    if not password:
        raise HTTPException(status_code=400, detail="Password is required")

    if email:
        user = db.query(User).filter(User.email == email).first()
    else:
        user = db.query(User).filter(User.mobile == mobile).first()

    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    if not user.password_hash or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
        
    if (role == "ADMIN" or role == UserRole.ADMIN) and not user.is_admin:
         raise HTTPException(status_code=403, detail="User exists but is not an admin")

    if (role == "MERCHANT" or role == UserRole.MERCHANT) and not user.is_merchant:
         raise HTTPException(status_code=403, detail="You are a user, can't be merchant")

    access_token = create_access_token(subject=str(user.id))

    # Determine role for token response
    user_role = "USER"
    if user.is_admin:
        user_role = "ADMIN"
    elif user.is_merchant:
        user_role = "MERCHANT"

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_role": user_role
    }

from schemas.auth import SetPasswordRequest


@router.post("/set-password")
def set_password(
    payload: SetPasswordRequest,
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(get_db)
):
    """
    Set password for the current logged-in user.
    """
    if not payload.password:
        raise HTTPException(status_code=400, detail="Password is required")
    
    current_user.password_hash = get_password_hash(payload.password)
    db.commit()
    
    return {"message": "Password updated successfully"}


@router.get("/me", response_model=UserResponse)
def get_current_user_profile(
    current_user: User = Depends(deps.get_current_user)
):
    """
    Get current logged-in user details.
    """
    return current_user


@router.put("/me", response_model=UserResponse)
def update_current_user_profile(
    payload: UserUpdateRequest,
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(get_db)
):
    """
    Update current logged-in user details (name, email, avatar).
    """
    print(f"AUTH UPDATE /me: Payload keys={payload.dict(exclude_unset=True).keys()}")
    if payload.avatar_url:
        print(f"AUTH UPDATE /me: Avatar Length={len(payload.avatar_url)}")

    if payload.name is not None:
        current_user.name = payload.name
    
    if payload.email is not None and payload.email.strip():
        new_email = payload.email.strip()
        if new_email != current_user.email:
            existing_email_user = db.query(User).filter(User.email == new_email, User.id != current_user.id).first()
            if existing_email_user:
                raise HTTPException(status_code=400, detail="Email already in use by another account")
            current_user.email = new_email

    if payload.mobile is not None and payload.mobile.strip():
        new_mobile = payload.mobile.strip()
        if new_mobile != current_user.mobile:
            existing_mobile_user = db.query(User).filter(User.mobile == new_mobile, User.id != current_user.id).first()
            if existing_mobile_user:
                raise HTTPException(status_code=400, detail="Mobile number already in use by another account")
            current_user.mobile = new_mobile

    if payload.avatar_url is not None:
        print("AUTH UPDATE /me: Setting avatar_url")
        current_user.avatar_url = payload.avatar_url
        
    db.commit()
    db.refresh(current_user)
    return current_user


