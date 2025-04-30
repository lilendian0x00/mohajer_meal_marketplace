# self_market/db/crud.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from telegram import User as TelegramUser


from .. import models # Import the models.py file from the parent directory (self_market)


async def get_user_by_telegram_id(db: AsyncSession, telegram_id: int) -> models.User | None:
    """Fetches a user by their Telegram ID."""
    # Access models like models.User, models.Listing, etc.
    result = await db.execute(
        select(models.User).filter(models.User.telegram_id == telegram_id)
    )
    return result.scalar_one_or_none()

async def get_or_create_user(db: AsyncSession, telegram_user: TelegramUser) -> models.User:
    """Gets an existing user or creates a new one if they don't exist."""
    db_user = await get_user_by_telegram_id(db, telegram_user.id)
    if db_user:
        needs_update = False
        if db_user.username != telegram_user.username:
            db_user.username = telegram_user.username
            needs_update = True
        if db_user.first_name != telegram_user.first_name:
            db_user.first_name = telegram_user.first_name
            needs_update = True
        if needs_update:
             await db.commit()
             await db.refresh(db_user)
        return db_user
    else:
        new_user = models.User( # Uses models.User correctly
            telegram_id=telegram_user.id,
            username=telegram_user.username,
            first_name=telegram_user.first_name,
            last_name=telegram_user.last_name,
            is_active=True,
        )
        db.add(new_user)
        await db.commit()
        await db.refresh(new_user)
        return new_user

# --- Placeholder functions ---

async def create_listing(db: AsyncSession, seller_id: int, reservation_id: int, price: float) -> models.Listing:
    """Creates a new listing."""
    new_listing = models.Listing( # Uses models.Listing
        seller_id=seller_id,
        reservation_id=reservation_id,
        price=price,
        status=models.ListingStatus.AVAILABLE # Uses models.ListingStatus
    )
    db.add(new_listing)
    await db.commit()
    await db.refresh(new_listing)
    return new_listing

async def get_available_listings(db: AsyncSession) -> list[models.Listing]:
    """Fetches all available listings."""
    result = await db.execute(
        select(models.Listing) # Uses models.Listing
        .where(models.Listing.status == models.ListingStatus.AVAILABLE) # Uses models.ListingStatus
        .options(selectinload(models.Listing.seller))
        # Need to adjust this if MealReservation is also in models.py
        .options(selectinload(models.Listing.reservation).selectinload(models.MealReservation.meal))
        .order_by(models.Listing.created_at.desc())
    )
    return result.scalars().all()

# ... rest of crud functions ...