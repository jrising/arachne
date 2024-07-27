import os, re
import urllib.parse
import google.auth
import google_auth_oauthlib.flow
import google.auth.transport.requests
import ssl
import imaplib
import json
import email
from email.header import decode_header
from bs4 import BeautifulSoup
import html2text

imaplib.Debug = 0

CLIENT_SECRET_FILE = 'memory/client_secret_971430942627-45mdl5bgtn17ga95q1jfon3ikjcpvs09.apps.googleusercontent.com.json'
SCOPES = ['https://mail.google.com/']

def get_credentials():
    """Gets valid user credentials from storage or OAuth 2.0 flow."""
    creds = None
    token_file = 'token.json'
    
    if os.path.exists(token_file):
        creds = google.oauth2.credentials.Credentials.from_authorized_user_file(token_file, SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(google.auth.transport.requests.Request())
            except:
                creds = None
        if not creds or not creds.valid:
            flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
                CLIENT_SECRET_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
            
        with open(token_file, 'w') as token:
            token.write(creds.to_json())
    
    return creds

def connect_to_gmail(creds):
    auth_string = 'user=%s\1auth=Bearer %s\1\1' % ("jarising.managed@gmail.com", creds.token)
    
    mail = imaplib.IMAP4_SSL('imap.gmail.com', ssl_context=ssl.create_default_context())
    # mail.debug = 4
    mail.authenticate('XOAUTH2', lambda x: auth_string)
    mail.select('INBOX')
    print('Successfully authenticated and connected to Gmail')
    return mail

def parse_google_alerts(body):
    soup = BeautifulSoup(body, 'html.parser')
    entries = soup.find_all('h3', attrs={'style': 'font-weight:normal;margin:0;font-size:17px;line-height:20px;'})

    for entry in entries:
        title = entry.find('a').text
        link = entry.find('a')['href']
        authors_journal_year = entry.find_next('div').text
        parts = re.split(r'\s-\s', authors_journal_year)
        if len(parts) == 2:
            authors, journal_year = re.split(r'\s-\s', authors_journal_year)
            parts2 = journal_year.split(',') if ', ' in journal_year else ['', journal_year]
            journal = ', '.join(parts2[:-1])
            year = parts2[-1]
        else:
            authors = authors_journal_year
            journal = ''
            year = "NA"
            
        content = entry.find_next('div').find_next('div').text.strip()

        longtitle = f"{title} ({authors}, {journal} {year})"

        yield longtitle, link, content

def get_emails(mail, num_emails=10):
    # Fetch emails
    status, messages = mail.search(None, "ALL")
    email_ids = messages[0].split()[-num_emails:]

    # Process emails
    for email_id in email_ids:
        status, msg_data = mail.fetch(email_id, "(RFC822)")
        for response_part in msg_data:
            if isinstance(response_part, tuple):
                msg = email.message_from_bytes(response_part[1])

                # Decode email subject
                subject, encoding = decode_header(msg["Subject"])[0]
                if isinstance(subject, bytes):
                    subject = subject.decode(encoding if encoding else "utf-8")

                # Decode email sender
                from_, encoding = decode_header(msg.get("From"))[0]
                if isinstance(from_, bytes):
                    from_ = from_.decode(encoding if encoding else "utf-8")

                # Parse email date
                date_header = msg.get("Date")

                # Process email content
                if msg.is_multipart():
                    for part in msg.walk():
                        content_type = part.get_content_type()
                        content_disposition = str(part.get("Content-Disposition"))

                        if "attachment" not in content_disposition:
                            body = part.get_payload(decode=True)
                            if body is not None:
                                yield subject, from_, date_header, body.decode('utf-8', errors='ignore')
                else:
                    body = msg.get_payload(decode=True)
                    if body is not None:
                        yield subject, from_, date_header, body.decode('utf-8', errors='ignore')

def iter_feed_items():
    creds = get_credentials()
    mail = connect_to_gmail(creds)
    try:
        h = html2text.HTML2Text()
        h.ignore_links = False

        for subject, _from, date, body in get_emails(mail, 50):
            if _from == 'Google Scholar Alerts <scholaralerts-noreply@google.com>':
                for longtitle, link, content in parse_google_alerts(body):
                    yield "Google Scholar Alert", longtitle, date, link, content
            else:
                # Remove unnecessary HTML
                soup = BeautifulSoup(body, 'html.parser')
                markdowndesc = h.handle(soup.prettify())

                yield "Managed Email", subject, date, "https://mail.google.com/mail/u/3/#advanced-search/subset=all&has=" + urllib.parse.quote_plus(subject) + "&within=1d&sizeoperator=s_sl&sizeunit=s_smb&date=" + date, markdowndesc
    finally:
        mail.close()
        mail.logout()
