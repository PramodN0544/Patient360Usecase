# from email.message import EmailMessage
# import aiosmtplib

# SMTP_HOST = "smtp.gmail.com"
# SMTP_PORT = 587
# SMTP_USER = "your_email@gmail.com"
# SMTP_PASS = "your_email_app_password"  # ⚠ Use app password if using Gmail

# async def send_email(to_email: str, subject: str, body: str):
#     message = EmailMessage()
#     message["From"] = SMTP_USER
#     message["To"] = to_email
#     message["Subject"] = subject
#     message.set_content(body)

#     await aiosmtplib.send(
#         message,
#         hostname=SMTP_HOST,
#         port=SMTP_PORT,
#         start_tls=True,
#         username=SMTP_USER,
#         password=SMTP_PASS,
#     )


