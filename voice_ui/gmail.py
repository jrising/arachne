import email
import html
import imaplib
import os
import re, time
from datetime import datetime, timezone
from email.header import decode_header
from email.message import EmailMessage
from email.utils import getaddresses, parsedate_to_datetime
from bs4 import BeautifulSoup
from email import policy
from email.parser import BytesParser

from dotenv import load_dotenv

load_dotenv()

HOST = os.environ["GMAIL_IMAP_HOST"]
USER = os.environ["GMAIL_IMAP_USER"]
PASSWORD = os.environ["GMAIL_IMAP_PASSWORD"]
DRAFTS_FOLDER = os.getenv("GMAIL_DRAFTS_FOLDER", "[Gmail]/Drafts")

_inbox_cache = {"expires": 0, "value": None}

ARCHIVE_FOLDER = "aiarchive"

def connect():
    client = imaplib.IMAP4_SSL(HOST)
    client.login(USER, PASSWORD)
    client.select("INBOX")

    return client


def decode_text(value):
    if not value:
        return ""

    return "".join(
        value.decode(charset or "utf-8", errors="replace")
        if isinstance(value, bytes) else value
        for value, charset in decode_header(value)
    )


def message_body(message):
    """Extract readable text, preferring text/plain over text/html."""
    plain_parts = []
    html_parts = []

    parts = message.walk() if message.is_multipart() else [message]

    for part in parts:
        if part.get_content_maintype() == "multipart":
            continue

        # Skip genuine attachments, but do not discard HTML merely because
        # an email client assigned it a filename.
        if part.get_content_disposition() == "attachment":
            continue

        content_type = part.get_content_type()
        if content_type not in {"text/plain", "text/html"}:
            continue

        try:
            payload = part.get_payload(decode=True)

            # Malformed/simple messages sometimes have no transfer decoding.
            if payload is None:
                payload = part.get_payload()

            if isinstance(payload, bytes):
                charset = part.get_content_charset() or "utf-8"
                content = payload.decode(charset, errors="replace")
            elif isinstance(payload, str):
                content = payload
            else:
                continue

        except (LookupError, UnicodeDecodeError):
            # An invalid declared charset should not make the whole message
            # unreadable.
            raw = part.get_payload(decode=True) or b""
            content = raw.decode("utf-8", errors="replace")

        content = content.strip()
        if not content:
            continue

        if content_type == "text/plain":
            plain_parts.append(content)
        else:
            html_parts.append(content)

    if plain_parts:
        return "\n\n".join(plain_parts).strip()

    if html_parts:
        soup = BeautifulSoup("\n".join(html_parts), "html.parser")

        # Remove things that should never become reader text.
        for tag in soup(["script", "style", "noscript", "svg", "head"]):
            tag.decompose()

        # Preserve visible anchor text, but remove raw URLs from links.
        for anchor in soup.find_all("a"):
            if not anchor.get_text(" ", strip=True):
                anchor.decompose()

        return soup.get_text("\n", strip=True)

    return ""


def _thread_messages(client, thread_id):
    """Fetch Inbox messages in one Gmail thread, oldest first."""
    status, data = client.uid(
        "search",
        None,
        "X-GM-THRID",
        str(thread_id),
    )
    if status != "OK":
        raise RuntimeError(f"Could not retrieve Gmail conversation: {data!r}")

    messages = []

    for search_uid in data[0].split():
        status, rows = client.uid(
            "fetch",
            search_uid,
            "(UID FLAGS BODY.PEEK[])",
        )
        if status != "OK":
            continue

        fetched = next(
            (
                row for row in rows
                if (
                        isinstance(row, tuple)
                        and isinstance(row[0], bytes)
                        and isinstance(row[1], bytes)
                )
            ),
            None,
        )
        if not fetched:
            continue

        metadata = fetched[0].decode("utf-8", errors="replace")
        uid_match = re.search(r"\bUID\s+(\d+)\b", metadata)

        if not uid_match:
            raise RuntimeError(
                f"Gmail FETCH response omitted UID: {metadata!r}"
            )

        message_uid = uid_match.group(1)

        raw = fetched[1]
        msg = BytesParser(policy=policy.default).parsebytes(raw)

        try:
            date = parsedate_to_datetime(msg.get("Date"))
            if date is None:
                raise ValueError("Missing Date header")

            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)

        except (TypeError, ValueError, IndexError):
            date = datetime.min.replace(tzinfo=timezone.utc)

        messages.append({
            "uid": message_uid,
            "unread": r"\Seen" not in metadata,
            "from": decode_text(msg.get("From")),
            "to": decode_text(msg.get("To")),
            "cc": decode_text(msg.get("Cc")),
            "subject": decode_text(msg.get("Subject")) or "(no subject)",
            "date": date.isoformat(),
            "message_id": msg.get("Message-ID", ""),
            "references": msg.get("References", ""),
            "reply_to": decode_text(msg.get("Reply-To")),
            "body": speech_clean(message_body(msg)),
        })

    # Oldest to newest. ISO timestamps sort lexically in chronological order
    # because all are timezone-aware ISO-8601 strings.
    messages.sort(key=lambda message: message["date"])

    return messages


def inbox_threads():
    """Return thread summaries: unread first, then newest-first."""
    if _inbox_cache["value"] and time.time() < _inbox_cache["expires"]:
        return _inbox_cache["value"]
    
    client = connect()
    try:
        status, data = client.uid("search", None, "ALL")
        if status != "OK":
            raise RuntimeError("Could not search Inbox")

        threads = {}

        for uid_batch in batched(data[0].split(), 100):
            uid_set = b",".join(uid_batch)

            status, rows = client.uid(
                "fetch",
                uid_set,
                "(UID FLAGS X-GM-THRID INTERNALDATE "
                "BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])",
            )

            if status != "OK":
                raise RuntimeError(f"Could not fetch Inbox headers: {rows!r}")

            for row in rows:
                if not (
                        isinstance(row, tuple)
                        and isinstance(row[0], bytes)
                        and isinstance(row[1], bytes)
                ):
                    continue

                meta = row[0].decode("utf-8", errors="replace")
                msg = email.message_from_bytes(row[1])

                uid_match = re.search(r"UID\s+(\d+)", meta)
                thread_match = re.search(r"X-GM-THRID\s+(\d+)", meta)

                if not uid_match or not thread_match:
                    continue

                try:
                    date = parsedate_to_datetime(msg.get("Date"))
                    if date is None:
                        raise ValueError
                    if date.tzinfo is None:
                        date = date.replace(tzinfo=timezone.utc)
                except (TypeError, ValueError):
                    date = datetime.min.replace(tzinfo=timezone.utc)
            
                thread_id = thread_match.group(1)

                threads.setdefault(thread_id, []).append({
                    "uid": uid_match.group(1),
                    "unread": r"\Seen" not in meta,
                    "date": date,
                    "from": decode_text(msg.get("From")),
                    "subject": decode_text(msg.get("Subject")) or "(no subject)",
                })

        result = []
        for thread_id, messages in threads.items():
            messages.sort(key=lambda item: item["date"], reverse=True)
            latest = messages[0]
            result.append({
                "thread_id": thread_id,
                "unread": any(item["unread"] for item in messages),
                "message_count": len(messages),
                "latest": {
                    **latest,
                    "date": latest["date"].isoformat(),
                },
            })

        result.sort(
            key=lambda item: (
                not item["unread"],  # False (unread) sorts before True (read)
                -datetime.fromisoformat(
                    item["latest"]["date"]
                ).timestamp(),
            )
        )

        _inbox_cache["value"] = result
        _inbox_cache["expires"] = time.time() + 300
        return result
    finally:
        client.logout()


def get_thread(thread_id):
    client = connect()
    try:
        messages = _thread_messages(client, thread_id)
        if not messages:
            raise ValueError("Conversation was not found in Inbox")

        # IMAP search ordering is normally chronological, but do not depend on it.
        return {
            "thread_id": thread_id,
            "message_count": len(messages),
            "messages": messages,
            "latest": messages[-1],
        }
    finally:
        client.logout()


def mark_thread_read(thread_id):
    client = connect()
    try:
        for message in _thread_messages(client, thread_id):
            client.uid("store", message["uid"], "+FLAGS", r"(\Seen)")
    finally:
        client.logout()


def archive_thread(thread_id):
    """Label a Gmail thread aiarchive and remove it from Inbox."""
    client = connect()  # selects INBOX
    try:
        messages = _thread_messages(client, thread_id)
        if not messages:
            raise ValueError("Conversation was not found in Inbox")

        uid_set = ",".join(message["uid"] for message in messages)

        # Gmail custom labels are IMAP folders. Create it if necessary.
        status, response = client.create(ARCHIVE_FOLDER)
        if status not in {"OK", "NO"}:
            raise RuntimeError(
                f"Could not create archive label {ARCHIVE_FOLDER!r}: {response!r}"
            )

        # Retain a traceable system-specific label.
        status, response = client.uid(
            "store", uid_set, "+X-GM-LABELS.SILENT", f"({ARCHIVE_FOLDER})"
        )
        if status != "OK":
            raise RuntimeError(f"Could not apply archive label: {response!r}")

        # Gmail archive = remove Inbox label.
        status, response = client.uid(
            "store", uid_set, "-X-GM-LABELS.SILENT", r"(\Inbox)"
        )
        if status != "OK":
            raise RuntimeError(f"Could not remove Inbox label: {response!r}")

        _inbox_cache["value"] = None
        _inbox_cache["expires"] = 0

    finally:
        client.logout()

        
def create_reply_all_draft(thread_id, dictated_text):
    client = connect()
    try:
        conversation = get_thread(thread_id)
        original = conversation["latest"]

        recipient_headers = [
            original["reply_to"] or original["from"],
            original["to"],
            original["cc"],
        ]

        addresses = []
        seen = {USER.lower()}

        for _, address in getaddresses(recipient_headers):
            normalized = address.lower()
            if address and normalized not in seen:
                seen.add(normalized)
                addresses.append(address)

        if not addresses:
            raise ValueError("No reply recipients found")

        subject = original["subject"]
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        draft = EmailMessage()
        draft["From"] = USER
        draft["To"] = ", ".join(addresses)
        draft["Subject"] = subject
        draft["In-Reply-To"] = original["message_id"]

        references = f"{original['references']} {original['message_id']}".strip()
        if references:
            draft["References"] = references

        draft.set_content(dictated_text.strip())

        status, _ = client.append(
            DRAFTS_FOLDER,
            r"(\Draft)",
            None,
            draft.as_bytes(),
        )
        if status != "OK":
            raise RuntimeError("Could not save Gmail draft")

    finally:
        client.logout()

def batched(items, size=100):
    for start in range(0, len(items), size):
        yield items[start:start + size]

def speech_clean(text):
    text = re.sub(r"https?://\S+", "[link omitted]", text)
    text = re.sub(r"\bwww\.\S+", "[link omitted]", text)
    text = re.sub(r"\S+@\S+\.\S+", "[email address omitted]", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
