import io
import os
import qrcode
from PIL import Image, ImageDraw, ImageFont
import re
from datetime import date as GregorianDate
from datetime import datetime, timedelta
import jdatetime
import logging

logger = logging.getLogger(__name__)

def is_valid_iranian_national_id(national_id: str) -> bool:
    """
    Checks if the given Iranian National ID (کد ملی) is valid according to the standard algorithm.

    Args:
        national_id: The national ID as a string (should be 10 digits).

    Returns:
        True if the national ID is valid, False otherwise.
        Also returns False for inputs that are not 10 digits or contain non-digit characters.
    """
    # 1. Check if the input is a string, has exactly 10 digits, and contains only digits.
    if not isinstance(national_id, str) or not re.fullmatch(r'\d{10}', national_id):
        return False

    # 2. Check for the invalid case where all digits are the same (e.g., "1111111111")
    if len(set(national_id)) == 1:
        return False

    # 3. Calculate the check digit
    try:
        check_digit = int(national_id[9])
        s = 0
        for i in range(9):
            s += int(national_id[i]) * (10 - i)

        remainder = s % 11

        if remainder < 2:
            calculated_check_digit = remainder
        else:
            calculated_check_digit = 11 - remainder

        # 4. Compare the calculated check digit with the actual check digit
        return check_digit == calculated_check_digit

    except ValueError:
        # This should technically not be reached if the regex matched,
        # but it's good practice for robustness.
        return False

def mask_card_number(card_number: str | None) -> str:
    """Masks a card number, showing only the last 4 digits."""
    if not card_number:
        return " ثبت نشده" # "Not Set"

    # Remove potential spaces and non-digits for safety before masking
    digits_only = ''.join(filter(str.isdigit, card_number))

    if len(digits_only) < 4:
        # Handle cases where stored number is too short or invalid
        return " (فرمت نامعتبر)" # "(Invalid Format)"

    # Simple masking
    masked_part = "**** **** **** "
    last_four = digits_only[-4:]
    return f" `{masked_part}{last_four}`" # Return masked number within backticks for markdown


def escape_markdown_v2(text: str | None) -> str:
    """Escapes characters for Telegram MarkdownV2 parsing."""
    if text is None:
        return ""
    # Characters to escape: _ * [ ] ( ) ~ ` > # + - = | { } . !
    # Note: Escaping ` within code blocks is not needed if using single backticks.
    # We escape backticks outside code blocks if they might appear.
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    # Use re.sub to add a backslash before special characters
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)


def format_gregorian_date_to_shamsi(gregorian_date: GregorianDate | datetime | None) -> str:
    """Converts Gregorian date/datetime to Shamsi YYYY/MM/DD string."""
    if gregorian_date is None:
        return "نامشخص"
    # If it's a datetime object, get the date part
    if isinstance(gregorian_date, datetime):
        gregorian_date = gregorian_date.date()
    try:
        j_date = jdatetime.date.fromgregorian(date=gregorian_date)
        return j_date.strftime('%Y/%m/%d')
    except (ValueError, TypeError) as e:
        logger.error(f"Error converting Gregorian date {gregorian_date} to Shamsi: {e}")
        return "تاریخ نامعتبر"

def get_iran_week_start_dates():
    """
    Calculates the start date of the current and next Iranian weeks.
    The Iranian week starts on Saturday.
    """
    today = datetime.today()
    # Calculate days to subtract to get to the previous Saturday
    # datetime.weekday(): Monday is 0, ..., Saturday is 5, Sunday is 6
    # To make Saturday the start (index 0 for calculation ease): (today.weekday() + 2) % 7
    # If today is Monday (0), (0+2)%7 = 2. Monday - 2 days = Saturday.
    # If today is Saturday (5), (5+2)%7 = 0. Saturday - 0 days = Saturday.
    # If today is Sunday (6), (6+2)%7 = 1. Sunday - 1 day = Saturday.
    days_to_subtract = (today.weekday() + 2) % 7
    start_of_current_iran_week = today - timedelta(days=days_to_subtract)
    start_of_next_iran_week = start_of_current_iran_week + timedelta(days=7)
    return start_of_current_iran_week, start_of_next_iran_week


def generate_qr_code_image(data: str) -> bytes | None:
    """
    Generates a QR code image from the given data.

    Args:
        data: The string data to encode in the QR code.

    Returns:
        Bytes of the PNG image, or None if an error occurs.
    """
    try:
        # Generate QR code
        qr = qrcode.QRCode(
            version=1, # Can be adjusted or set to None for auto-sizing
            error_correction=qrcode.constants.ERROR_CORRECT_L, # L (Low, ~7%), M (Medium, ~15%), Q (Quartile, ~25%), H (High, ~30%)
            box_size=10, # Size of each "box" in the QR grid
            border=4,    # Thickness of the border (in boxes)
        )
        qr.add_data(data)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white") # Default Pillow image

        # Save to bytes
        img_byte_arr = io.BytesIO()
        qr_img.save(img_byte_arr, format='PNG')
        img_bytes = img_byte_arr.getvalue()
        logger.debug(f"Successfully generated QR code image for data: {data[:20]}...") # Log snippet of data
        return img_bytes

    except Exception as e:
        logger.error(f"Error generating QR code image for data '{data[:20]}...': {e}", exc_info=True)
        return None