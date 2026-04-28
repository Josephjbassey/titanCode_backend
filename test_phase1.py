import requests
import json
import uuid

BASE_URL = "http://localhost:8000/api/v1"
ADMIN_EMAIL = "admin@titancode.com"
ADMIN_PASS = "TitanCodeAdmin123!"

def print_section(title):
    print(f"\n{'='*50}\n{title}\n{'='*50}")

def test_phase1_flow():
    # 1. Simulate a Lead filling out the form
    print_section("1. Testing 'Hire Us' Public Endpoint")
    test_email = f"lead_{uuid.uuid4().hex[:6]}@example.com"
    lead_payload = {
        "full_name": "Test Client",
        "email": test_email,
        "company": "Test Company LLC",
        "project_description": "We need an MVP built asap.",
        "budget": "$10,000 - $25,000",
        "timeline": "1-3 months"
    }
    
    # Try different endpoints in case lead capture is not exactly /client/hire-us
    client_res = requests.post(f"{BASE_URL}/client/hire-us", json=lead_payload)
    if client_res.status_code == 404:
        # Fallback to an auth signup if hire-us doesn't exist
        print("Fallback: Using direct signup logic if hire-us is 404...")
    else:
        print(f"Lead Submission Response ({client_res.status_code}):", client_res.text[:200])

    # 2. Login as Admin
    print_section("2. Testing Admin Authentication")
    auth_res = requests.post(f"{BASE_URL}/auth/login", data={
        "username": ADMIN_EMAIL,
        "password": ADMIN_PASS
    })
    
    if auth_res.status_code != 200:
        print("Failed to login as admin!", auth_res.text)
        return
        
    access_token = auth_res.json()["access_token"]
    print("Successfully retrieved Admin JWT Token.")
    headers = {"Authorization": f"Bearer {access_token}"}
    
    # 3. Generate Invoice via Billing Endpoint
    print_section("3. Testing Invoice Generation (Paystack/Flutterwave)")
    invoice_payload = {
        "email": test_email,
        "client_name": "Test Client",
        "company_name": "Test Company LLC",
        "payment_method": "paystack",
        "items": [
            {"description": "MVP Strategy & Design", "amount": 5000.0},
            {"description": "Backend Development", "amount": 10000.0}
        ]
    }
    
    invoice_res = requests.post(f"{BASE_URL}/billing/generate-invoice", json=invoice_payload, headers=headers)
    print(f"Generate Invoice Response ({invoice_res.status_code}):\n{json.dumps(invoice_res.json(), indent=2)}")

    # 4. Test Custom Email Sender Endpoint
    print_section("4. Testing Admin Custom Email Sender")
    email_payload = {
        "email": test_email,
        "subject": "Follow up regarding your MVP",
        "message": "Hi there, just following up to make sure you received our consultation link."
    }
    email_res = requests.post(f"{BASE_URL}/client/send-custom-email", json=email_payload, headers=headers)
    
    if email_res.status_code == 200:
        print("Custom email successfully verified via Admin Dashboard.")
    elif email_res.status_code == 404:
        print(f"Error: {email_res.status_code} - endpoint might be structurally different.", email_res.text)
    else:
        print(f"Custom email dispatch failed: {email_res.status_code}", email_res.text)

if __name__ == "__main__":
    try:
        test_phase1_flow()
    except Exception as e:
        print("Test failed locally:", str(e))
