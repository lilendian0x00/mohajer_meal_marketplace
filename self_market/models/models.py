import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum, # Group Enum with other SQLA types
    ForeignKey,
    Integer,
    Numeric,
    String,
    Date,
    Float,
    # Date, # Date was imported but not used, removed for cleanliness
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func # Alternative for server-side defaults like NOW()

# Assuming Base is defined in db.base as in the original script
from db.base import Base


# --- Enums ---
class ListingStatus(enum.Enum):
    """Represents the status of a meal listing."""
    AVAILABLE = 'available'
    PENDING = 'pending' # Example: Payment initiated but not confirmed
    SOLD = 'sold'


# --- Models ---

class User(Base):
    """Represents a user interacting with the system via Telegram."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Telegram-specific identifiers
    telegram_id = Column(Integer, unique=True, nullable=False, index=True)
    username = Column(String(64), nullable=True, index=True)
    first_name = Column(String(64), nullable=True)
    last_name = Column(String(64), nullable=True)

    # User specific information (using snake_case)
    education_number = Column(String(64), nullable=True)
    phone_number = Column(String(64), nullable=True)

    # !!! SECURITY WARNING !!!
    # Storing full credit card numbers directly in the database is highly insecure
    # and likely violates PCI DSS compliance. Consider using a third-party
    # payment processor and storing only tokens or non-sensitive identifiers.
    # If storing partial info (e.g., last 4 digits), ensure it's clearly named
    # and still handled securely.
    credit_card_info = Column(String(64), nullable=True) # Renamed for clarity/caution

    # System status
    is_active = Column(Boolean, default=True, nullable=False)

    # Timestamps (using timezone-aware UTC)
    created_at = Column(
        DateTime(timezone=True), # Explicitly set timezone=True
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True), # Explicitly set timezone=True
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    # Alternative using server-side defaults (often preferred):
    # created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


    # Relationships (using string references for safety)
    reservations = relationship(
        "MealReservation",
        back_populates="user",
        cascade="all, delete-orphan", # Deletes reservations if user is deleted
        lazy="selectin", # Example: Eagerly load reservations with the user
    )

    # Listings created by this user (seller)
    listings = relationship(
        "Listing",
        foreign_keys="Listing.seller_id", # Explicit FK
        back_populates="seller",
        cascade="all, delete-orphan", # Deletes listings if seller is deleted
        lazy="selectin",
    )

    # Listings purchased by this user (buyer)
    purchases = relationship(
        "Listing",
        foreign_keys="Listing.buyer_id", # Explicit FK
        back_populates="buyer",
        lazy="selectin",
        # Note: No cascade delete here typically, deleting a buyer
        # shouldn't delete the listing history (maybe set buyer_id to null instead)
    )

    def __repr__(self):
        return (
            f"<User(id={self.id}, telegram_id={self.telegram_id}, "
            f"username='{self.username}')>"
        )


class MealReservation(Base):
    """Represents a reservation of a specific meal by a user."""
    __tablename__ = 'meal_reservations'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    meal_id = Column(Integer, ForeignKey('meals.id'), nullable=False, index=True) # Assumes a 'meals' table exists
    university_reservation_code = Column(String(64), unique=True, nullable=False)

    # Timestamps (using timezone-aware UTC)
    reserved_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships (using string references)
    user = relationship(
        'User',
        back_populates='reservations'
    )
    meal = relationship(
        'Meal', # Assumes a Meal model exists
        back_populates='reservations'
    )
    # One-to-one relationship with Listing (a reservation can be listed once)
    listing = relationship(
        'Listing',
        back_populates='reservation',
        uselist=False, # Indicates one-to-one
        cascade="all, delete-orphan", # If reservation deleted, delete listing
        lazy="joined", # Example: Load listing along with reservation
    )

    def __repr__(self):
        return (
            f"<MealReservation(id={self.id}, user_id={self.user_id}, "
            f"meal_id={self.meal_id}, code='{self.university_reservation_code}')>"
        )


class Listing(Base):
    """Represents a meal reservation put up for sale."""
    __tablename__ = 'listings'

    id = Column(Integer, primary_key=True, autoincrement=True)
    # Link to the specific reservation being sold (unique constraint enforces 1-to-1)
    reservation_id = Column(
        Integer,
        ForeignKey('meal_reservations.id'),
        unique=True,
        nullable=False
    )
    seller_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    buyer_id = Column(Integer, ForeignKey('users.id'), nullable=True, index=True) # Nullable until sold

    price = Column(Numeric(10, 2), nullable=False) # Price in university currency (e.g., 12.34)
    status = Column(
        Enum(ListingStatus, name="listing_status_enum"), # Added name for enum type in DB
        default=ListingStatus.AVAILABLE,
        nullable=False,
        index=True
    )

    # Timestamps (using timezone-aware UTC)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    sold_at = Column(DateTime(timezone=True), nullable=True) # Records when the sale was finalized

    # Relationships (using string references)
    reservation = relationship(
        'MealReservation',
        back_populates='listing'
    )
    seller = relationship(
        'User',
        back_populates='listings',
        foreign_keys=[seller_id] # Specify FK for clarity
    )
    buyer = relationship(
        'User',
        back_populates='purchases', # Correctly link back to User.purchases
        foreign_keys=[buyer_id]    # Specify FK for clarity
    )

    def mark_as_sold(self, buyer: 'User') -> None:
        """
        Mark this listing as sold to the given buyer.
        Updates status, buyer, and sold_at timestamp.
        """
        if self.status == ListingStatus.SOLD:
            # Or raise an exception, depending on desired behavior
            print(f"Warning: Listing {self.id} is already marked as sold.")
            return

        self.buyer = buyer
        self.buyer_id = buyer.id # Explicitly set FK if needed before commit
        self.status = ListingStatus.SOLD
        self.sold_at = datetime.now(timezone.utc)

    def __repr__(self):
        return (
            f"<Listing(id={self.id}, seller_id={self.seller_id}, "
            f"price={self.price}, status='{self.status.value}')>"
        )

class Meal(Base):
    """Represents a meal for sale."""
    __tablename__ = 'meals'

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False, index=True)  # Date of the meal (e.g., 2025-05-01)
    meal_type = Column(String(20), nullable=False)   # e.g., 'breakfast', 'lunch', 'dinner'
    description = Column(String(255), nullable=True)
    price = Column(Float, nullable=True)

    # All reservations for this meal
    reservations = relationship('MealReservation', back_populates='meal')