import locale

# Optional: Set locale for potential number formatting, though Toman usually doesn't use decimals heavily.
# try:
#     # Use a locale that supports comma separators if desired for display
#     locale.setlocale(locale.LC_ALL, 'en_US.UTF-8') # Or 'fa_IR.UTF-8' if available and needed
# except locale.Error:
#     print("Locale en_US.UTF-8 not found, using default.")

class Meal:
    """
    Base class representing a meal with a Persian name and price in Toman.
    """
    def __init__(self, name_persian: str, price_toman: float):
        if not isinstance(name_persian, str) or not name_persian:
            raise ValueError("Meal name must be a non-empty string.")
        if not isinstance(price_toman, (int, float)) or price_toman < 0:
            raise ValueError("Price must be a non-negative number.")

        self.name_persian = name_persian
        self.price_toman = float(price_toman) # Ensure price is float

    def get_price(self) -> float:
        """Returns the price of the meal in Toman."""
        return self.price_toman

    def set_price(self, new_price_toman: float):
        """Updates the price of the meal."""
        if not isinstance(new_price_toman, (int, float)) or new_price_toman < 0:
            raise ValueError("New price must be a non-negative number.")
        self.price_toman = float(new_price_toman)
        print(f"Price for {self.name_persian} updated to {self.price_toman:,.0f} Toman.")

    def __str__(self) -> str:
        """Returns a user-friendly string representation."""
        # Format price with commas, no decimal places for Toman typically
        formatted_price = f"{self.price_toman:,.0f}"
        return f"{self.name_persian}: {formatted_price} Toman"

    def __repr__(self) -> str:
        """Returns a developer-friendly string representation."""
        return f"{self.__class__.__name__}(price_toman={self.price_toman})"

# --- Specific Meal Classes ---

class AdasPoloBaGoosht(Meal):
    """Represents عدس پلو با گوشت."""
    def __init__(self, price_toman: float = 180000): # Default price example
        super().__init__(name_persian="عدس پلو با گوشت", price_toman=price_toman)

class CheloKababKoobideh(Meal):
    """Represents چلو کباب کوبیده."""
    def __init__(self, price_toman: float = 165000): # Default price example
        super().__init__(name_persian="چلو کباب کوبیده", price_toman=price_toman)

class CheloKhoreshtGhormehSabzi(Meal):
    """Represents چلو خورشت قورمه سبزی."""
    def __init__(self, price_toman: float = 175000): # Default price example
        super().__init__(name_persian="چلو خورشت قورمه سبزی", price_toman=price_toman)

class KalamPoloBaGoosht(Meal):
    """Represents کلم پلو با گوشت."""
    def __init__(self, price_toman: float = 190000): # Default price example
        super().__init__(name_persian="کلم پلو با گوشت", price_toman=price_toman)

class CheloJoojehKababBedoonOstokhan(Meal):
    """Represents چلو جوجه کباب بدون استخوان."""
    def __init__(self, price_toman: float = 195000): # Default price example
        super().__init__(name_persian="چلو جوجه کباب بدون استخوان", price_toman=price_toman)

# --- Example Usage for a "Trader Bot" Context ---

print("--- Initial Meal Prices ---")
# Create instances of the meals (using default or specified prices)
adas_polo = AdasPoloBaGoosht()
koobideh = CheloKababKoobideh(price_toman=170000) # Override default price
ghormeh_sabzi = CheloKhoreshtGhormehSabzi()
kalam_polo = KalamPoloBaGoosht()
joojeh = CheloJoojehKababBedoonOstokhan(price_toman=210000)

# Store meals, perhaps in a dictionary for easy lookup by name or type
meal_inventory = {
    "adas_polo": adas_polo,
    "koobideh": koobideh,
    "ghormeh_sabzi": ghormeh_sabzi,
    "kalam_polo": kalam_polo,
    "joojeh": joojeh
}

# Display current inventory/prices
print("Current Meal Inventory:")
for key, meal in meal_inventory.items():
    print(f"- {key}: {meal}") # Uses the __str__ method

print("\n--- Updating Prices ---")
# Simulate a price update
meal_inventory["koobideh"].set_price(175000)
meal_inventory["joojeh"].set_price(215000)

print("\n--- Final Meal Prices ---")
print("Updated Meal Inventory:")
for key, meal in meal_inventory.items():
    print(f"- {key}: {meal}")

# Example of accessing specific attributes
print(f"\nDetails for Ghormeh Sabzi:")
print(f"  Persian Name: {ghormeh_sabzi.name_persian}")
print(f"  Current Price: {ghormeh_sabzi.get_price():,.0f} Toman")

# Developer representation
print(f"\nDeveloper Representation of Joojeh: {repr(joojeh)}")