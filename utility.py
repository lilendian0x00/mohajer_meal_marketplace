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