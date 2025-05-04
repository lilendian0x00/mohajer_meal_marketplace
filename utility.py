import re

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