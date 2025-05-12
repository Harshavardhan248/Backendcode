from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
import json

# Create router without any dependencies for testing
router = APIRouter(
    prefix="/api",
    tags=["confirmations"]
)

# Test endpoint to verify router registration
@router.get("/test")
async def test_endpoint():
    """Simple test endpoint to verify router is registered"""
    return {"message": "Confirmations router is working!"}

class EmailConfirmationRequest(BaseModel):
    reservation_id: int
    email: Optional[str] = None

class SMSConfirmationRequest(BaseModel):
    reservation_id: int
    phone_number: str

# Email endpoint that logs the incoming request
@router.post("/send-confirmation-email")
async def send_email_confirmation(request: Request):
    """Simplified email confirmation endpoint with full request debugging"""
    try:
        # Get the raw request body and log it
        body = await request.body()
        body_str = body.decode('utf-8')
        print(f"Raw request body: {body_str}")
        
        # Try to parse as JSON
        try:
            json_data = json.loads(body_str)
            print(f"Parsed JSON data: {json_data}")
            
            # Extract reservation_id
            reservation_id = json_data.get('reservation_id')
            email = json_data.get('email', 'user@example.com')
            
            if not reservation_id:
                return {"success": False, "error": "Missing reservation_id"}
                
            # Return success response
            return {
                "success": True,
                "message": f"Would send email confirmation for reservation {reservation_id} to {email}"
            }
        except json.JSONDecodeError:
            print("Failed to parse request body as JSON")
            return {"success": False, "error": "Invalid JSON in request body"}
    except Exception as e:
        print(f"Error in email confirmation: {str(e)}")
        return {"success": False, "error": str(e)}

# Simplified SMS endpoint
@router.post("/send-confirmation-sms")
async def send_sms_confirmation(request: Request):
    """Simplified SMS confirmation endpoint with request debugging"""
    try:
        # Get the raw request body and log it
        body = await request.body()
        body_str = body.decode('utf-8')
        print(f"Raw SMS request body: {body_str}")
        
        # Try to parse as JSON
        try:
            json_data = json.loads(body_str)
            print(f"Parsed SMS JSON data: {json_data}")
            
            # Extract fields
            reservation_id = json_data.get('reservation_id')
            phone_number = json_data.get('phone_number')
            
            if not reservation_id or not phone_number:
                return {"success": False, "error": "Missing reservation_id or phone_number"}
                
            # Return success response
            return {
                "success": True,
                "message": f"Would send SMS confirmation for reservation {reservation_id} to {phone_number}"
            }
        except json.JSONDecodeError:
            print("Failed to parse SMS request body as JSON")
            return {"success": False, "error": "Invalid JSON in request body"}
    except Exception as e:
        print(f"Error in SMS confirmation: {str(e)}")
        return {"success": False, "error": str(e)}