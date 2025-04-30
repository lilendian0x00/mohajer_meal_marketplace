import enum
import logging
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, Enum as SQLEnum,
    ForeignKey, Integer, Numeric, String, Date, Float,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

# Logger instance for this module
logger = logging.getLogger(__name__)


try:
    from .db.base import Base
except ImportError as e:
    # If Base cannot be imported, models can't be defined. Raise critical error.
    import logging
    logging.critical(f"Failed to import Base for models: {e}", exc_info=True)
    raise


# Listing Enum
class ListingStatus(enum.Enum):
    """Represents the status of a meal listing."""
    AVAILABLE = 'available'
    PENDING = 'pending'
    SOLD = 'sold'


# Models
class User(Base):
    """Represents a user interacting with the system via Telegram."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(Integer, unique=True, nullable=False, index=True)
    username = Column(String(64), nullable=True, index=True)

    first_name = Column(String(64), nullable=True)
    last_name = Column(String(64), nullable=True)

    education_number = Column(String(64), nullable=True)
    identity_number = Column(String(64), nullable=True)
    phone_number = Column(String(64), nullable=True)
    credit_card_number = Column(String(64), nullable=True)

    is_active = Column(Boolean, default=True, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


    # Relationships
    reservations = relationship(
        "MealReservation",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    listings = relationship(
        "Listing",
        foreign_keys="Listing.seller_id",
        back_populates="seller",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    purchases = relationship(
        "Listing",
        foreign_keys="Listing.buyer_id",
        back_populates="buyer",
        lazy="selectin",
    )

    def __repr__(self):
        return (
            f"<User(id={self.id}, telegram_id={self.telegram_id}, "
            f"username='{self.username}')>"
        )


class Meal(Base):
    """Represents a meal available for reservation."""
    __tablename__ = 'meals'

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False, index=True)
    meal_type = Column(String(20), nullable=False) # e.g., 'lunch', 'dinner'
    description = Column(String(255), nullable=True)
    price = Column(Float, nullable=True) # Original price from university

    # Relationships
    reservations = relationship(
        'MealReservation',
        back_populates='meal'
    )

    def __repr__(self):
         return f"<Meal(id={self.id}, date='{self.date}', type='{self.meal_type}')>"


class MealReservation(Base):
    """Represents a specific reservation of a meal by a user."""
    __tablename__ = 'meal_reservations'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    meal_id = Column(Integer, ForeignKey('meals.id'), nullable=False, index=True)
    university_reservation_code = Column(String(64), unique=True, nullable=False)
    reserved_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    user = relationship(
        'User',
        back_populates='reservations'
    )
    meal = relationship(
        'Meal',
        back_populates='reservations'
    )
    listing = relationship(
        'Listing',
        back_populates='reservation',
        uselist=False, # One-to-one: A reservation can only be listed once
        cascade="all, delete-orphan",
        lazy="joined",
    )

    def __repr__(self):
        return f"<MealReservation(id={self.id}, user_id={self.user_id}, meal_id={self.meal_id}, code='{self.university_reservation_code}')>"


class Listing(Base):
    """Represents a meal reservation put up for sale."""
    __tablename__ = 'listings'

    id = Column(Integer, primary_key=True, autoincrement=True)
    reservation_id = Column(Integer, ForeignKey('meal_reservations.id'), unique=True, nullable=False)
    seller_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    buyer_id = Column(Integer, ForeignKey('users.id'), nullable=True, index=True) # Null until sold
    price = Column(Numeric(10, 2), nullable=False) # Price for the listing
    status = Column(SQLEnum(ListingStatus, name="listing_status_enum"), default=ListingStatus.AVAILABLE, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
    sold_at = Column(DateTime(timezone=True), nullable=True) # When the sale was finalized

    # Relationships
    reservation = relationship(
        'MealReservation',
        back_populates='listing'
    )
    seller = relationship(
        'User',
        back_populates='listings',
        foreign_keys=[seller_id]
    )
    buyer = relationship(
        'User',
        back_populates='purchases',
        foreign_keys=[buyer_id]
    )

    def mark_as_sold(self, buyer_user: 'User') -> None:
        """Marks the listing as sold to the given buyer."""
        if self.status == ListingStatus.SOLD:
            logger.warning(f"Listing {self.id} is already marked as sold.")
            return
        self.buyer = buyer_user
        self.buyer_id = buyer_user.id
        self.status = ListingStatus.SOLD
        self.sold_at = datetime.now(timezone.utc)

    def __repr__(self):
        return f"<Listing(id={self.id}, seller_id={self.seller_id}, price={self.price}, status='{self.status.value}')>"