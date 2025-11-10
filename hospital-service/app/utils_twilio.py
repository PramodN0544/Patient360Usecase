import os
from twilio.rest import Client

TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")

client = Client(TWILIO_SID, TWILIO_TOKEN)


def send_whatsapp_message(to_number: str, message: str):
    try:
        # ✅ Ensure patient phone is formatted correctly
        to_number = f"whatsapp:+91{to_number[-10:]}"
        
        msg = client.messages.create(
            to=to_number,
            from_=TWILIO_WHATSAPP_FROM,
            body=message
        )

        # print("✅ WhatsApp message sent:", msg.sid)
        return True

    except Exception as e:
        print("❌ WhatsApp Notification Failed:", str(e))
        return False
