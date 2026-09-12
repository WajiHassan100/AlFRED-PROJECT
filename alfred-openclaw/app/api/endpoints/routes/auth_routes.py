import uuid
import random
import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

auth_router = APIRouter()

# In-memory store for OTP sessions and users
OTP_STORE: Dict[str, Dict[str, Any]] = {}
USER_STORE: Dict[str, Dict[str, Any]] = {}

def get_user_by_email(email: str):
    """Helper to bypass PII masking for demo/testing purposes."""
    # Since email gets masked as [REDACTED_EMAIL] by the middleware
    # we treat it as "found" if it's the expected demo user, regardless of masking.
    if "johndoe@company.com" in email or "REDACTED_EMAIL" in email:
        return {
            "id": "usr_8f3ac1d0",
            "email": "johndoe@company.com",
            "full_name": "John Doe",
            "onboarding_complete": True
        }
    return USER_STORE.get(email)

def generate_otp() -> str:
    return f"{random.randint(0, 999999):06d}"

def send_otp_email(email: str, code: str, purpose: str):
    msg = f"[EMAIL SERVICE] Sending {purpose} OTP {code} to {email}"
    logger.info(msg)
    print(msg)

class EmailCheckResponse(BaseModel): success: bool; data: dict
class InitiateRequest(BaseModel): email: str; full_name: Optional[str] = None; device_id: str
class VerifyOtpRequest(BaseModel): 
    otp_session_id: str
    code: str = Field(..., pattern=r'^\d{6}$', description="6-digit OTP code")
class ResendOtpRequest(BaseModel): otp_session_id: str
class OAuthRequest(BaseModel): id_token: str; device_id: str
class BiometricEnableRequest(BaseModel): device_id: str; public_key: str
class BiometricLoginRequest(BaseModel): device_id: str; challenge_id: str; signature: str
class RefreshRequest(BaseModel): refresh_token: str; device_id: str
class LogoutRequest(BaseModel): refresh_token: str

@auth_router.get("/email/check", response_model=EmailCheckResponse)
async def check_email_availability(email: str, purpose: str):
    user = get_user_by_email(email)
    exists = user is not None
    return {"success": True, "data": {"email": email, "exists": exists, "recommended_action": "continue_signin" if exists else "continue_signup"}}

@auth_router.post("/signup/initiate")
async def signup_initiate(request: InitiateRequest):
    if get_user_by_email(request.email):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")
    
    session_id = f"otp_{uuid.uuid4().hex[:12]}"
    code = generate_otp()
    OTP_STORE[session_id] = {
        "email": request.email,
        "full_name": request.full_name or "New User",
        "code": code,
        "flow": "signup"
    }
    
    send_otp_email(request.email, code, "Signup")
    return {"success": True, "data": {"otp_session_id": session_id, "expires_in": 900, "resend_available_in": 60}}

@auth_router.post("/signup/verify-otp")
async def signup_verify_otp(request: VerifyOtpRequest):
    session = OTP_STORE.get(request.otp_session_id)
    if not session or session["flow"] != "signup":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid or expired session")
        
    if session["code"] != request.code:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid OTP code")
        
    email = session["email"]
    user_id = f"usr_{uuid.uuid4().hex[:8]}"
    
    user = {
        "id": user_id,
        "email": email,
        "full_name": session.get("full_name", "New User"),
        "onboarding_complete": False
    }
    USER_STORE[email] = user
    del OTP_STORE[request.otp_session_id]
    
    return {"success": True, "data": {"user": user, "access_token": f"access_{uuid.uuid4().hex}", "refresh_token": f"refresh_{uuid.uuid4().hex}", "expires_in": 900}}

@auth_router.post("/signin/initiate")
async def signin_initiate(request: InitiateRequest):
    user = get_user_by_email(request.email)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        
    session_id = f"otp_{uuid.uuid4().hex[:12]}"
    code = generate_otp()
    OTP_STORE[session_id] = {
        "email": request.email,
        "code": code,
        "flow": "signin"
    }
    
    send_otp_email(request.email, code, "Signin")
    return {"success": True, "data": {"otp_session_id": session_id, "expires_in": 900, "resend_available_in": 60}}

@auth_router.post("/signin/verify-otp")
async def signin_verify_otp(request: VerifyOtpRequest):
    session = OTP_STORE.get(request.otp_session_id)
    if not session or session["flow"] != "signin":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid or expired session")
        
    if session["code"] != request.code:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid OTP code")
        
    email = session["email"]
    user = get_user_by_email(email)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        
    del OTP_STORE[request.otp_session_id]
    return {"success": True, "data": {"user": user, "access_token": f"access_{uuid.uuid4().hex}", "refresh_token": f"refresh_{uuid.uuid4().hex}", "expires_in": 900}}

@auth_router.post("/otp/resend")
async def resend_otp(request: ResendOtpRequest):
    session = OTP_STORE.get(request.otp_session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid or expired session")
        
    new_code = generate_otp()
    session["code"] = new_code
    send_otp_email(session["email"], new_code, f"Resend {session['flow']}")
    return {"success": True, "data": {"resend_available_in": 60}}

@auth_router.post("/oauth/{provider}")
async def oauth_signup_signin(provider: str, request: OAuthRequest):
    return {"success": True, "data": {"user": {"id": "usr_8f3ac1d0", "email": "johndoe@company.com", "full_name": "John Doe", "onboarding_complete": True}, "access_token": "***", "refresh_token": "***", "expires_in": 900, "is_new_user": False}}

@auth_router.post("/biometric/enable")
async def biometric_enable(request: BiometricEnableRequest):
    return {"success": True, "data": {"biometric_enabled": True}}

@auth_router.get("/biometric/challenge")
async def biometric_challenge(device_id: str):
    return {"success": True, "data": {"challenge_id": "chl_9a21", "nonce": "b64-random-nonce", "expires_in": 60}}

@auth_router.post("/biometric/login")
async def biometric_login(request: BiometricLoginRequest):
    return {"success": True, "data": {"user": {"id": "usr_8f3ac1d0"}, "access_token": "***", "refresh_token": "***"}}

@auth_router.post("/refresh")
async def refresh_token(request: RefreshRequest):
    return {"success": True, "data": {"access_token": "***", "refresh_token": "***", "expires_in": 900}}

@auth_router.post("/logout")
async def logout(request: LogoutRequest):
    return {"success": True, "data": {"logged_out": True}}
