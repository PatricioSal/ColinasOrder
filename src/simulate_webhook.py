import os
import base64
import requests
import time

WEBHOOK_URL = "http://localhost:5050/webhook"
PDF_DIR = "PDF_TEST"

for file in os.listdir(PDF_DIR):
    if file.lower().endswith(".pdf"):
        print(f"Sending {file} to webhook...")
        filepath = os.path.join(PDF_DIR, file)
        
        with open(filepath, "rb") as f:
            pdf_bytes = f.read()
            pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')
            
        payload = {
            "sender_phone": "+15551234567",
            "sender_name": "Test User",
            "body": "",
            "chat_id": "123456789@g.us",
            "is_group": True,
            "timestamp": "2026-06-17T12:00:00Z",
            "has_pdf": True,
            "pdf_data": pdf_base64,
            "pdf_name": file
        }
        
        try:
            response = requests.post(WEBHOOK_URL, json=payload)
            if response.status_code == 200:
                print(f"Response: {response.text.encode('ascii', 'ignore').decode()}")
            else:
                print(f"Failed to send {file}: {response.text.encode('ascii', 'ignore').decode()}")
        except Exception as e:
            print(f"Failed to send {file}: {e}")
        
        time.sleep(2) # brief pause between files
