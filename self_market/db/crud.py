import logging
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal
from typing import Any, Coroutine
from sqlalchemy import func, and_
from sqlalchemy import or_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload, joinedload
from telegram import User as TelegramUser
from config import PENDING_TIMEOUT_MINUTES
from .. import models # Import the models.py file from the parent directory (self_market)

# Get logger instance
logger = logging.getLogger(__name__)


async def get_all_sold_listings(db: AsyncSession, page: int = 0, page_size: int = 5) -> tuple[list[models.Listing], int]:
    """
    Fetches all SOLD listings, paginated. Includes seller and buyer info.
    For admin use.
    Returns a list of Listing objects and the total count of sold listings.
    """
    logger.debug(f"Admin fetching all sold listings, page {page}, page_size {page_size}")
    offset = page * page_size

    # Query for total count of SOLD listings
    count_stmt = select(func.count(models.Listing.id)).where(
        models.Listing.status == models.ListingStatus.SOLD
    ).select_from(models.Listing)
    count_result = await db.execute(count_stmt)
    total_count = count_result.scalar_one_or_none() or 0

    if total_count == 0:
        return [], 0

    # Query for the page data
    stmt = select(models.Listing).where(
        models.Listing.status == models.ListingStatus.SOLD
    ).options(
        joinedload(models.Listing.meal),
        joinedload(models.Listing.seller).load_only(models.User.telegram_id, models.User.username,
                                                    models.User.first_name),
        joinedload(models.Listing.buyer).load_only(models.User.telegram_id, models.User.username,
                                                   models.User.first_name)
    ).order_by(
        models.Listing.sold_at.desc()
    ).offset(offset).limit(page_size).distinct()

    result = await db.execute(stmt)
    listings = result.scalars().all()
    logger.info(f"Admin fetched {len(listings)} sold listings for page {page}. Total sold: {total_count}")
    return listings, total_count

async def get_sold_listings_by_seller(db: AsyncSession, seller_telegram_id: int, page: int = 0, page_size: int = 5) -> tuple[list[models.Listing], int, models.User | None]:
    """
    Fetches SOLD listings for a specific seller, paginated. Includes buyer info.
    For admin use.
    Returns a list of Listing objects, the total count of their sold listings, and the seller User object.
    """
    logger.debug(f"Admin fetching sold listings for seller {seller_telegram_id}, page {page}, page_size {page_size}")

    # First, get the seller's DB User object
    seller_user = await get_user_by_telegram_id(db, seller_telegram_id)
    if not seller_user:
        logger.warning(f"Seller with Telegram ID {seller_telegram_id} not found.")
        return [], 0, None

    offset = page * page_size

    # Query for total count of SOLD listings for this seller
    count_stmt = select(func.count(models.Listing.id)).where(
        models.Listing.seller_id == seller_user.id,
        models.Listing.status == models.ListingStatus.SOLD
    ).select_from(models.Listing)
    count_result = await db.execute(count_stmt)
    total_count = count_result.scalar_one_or_none() or 0

    if total_count == 0:
        return [], 0, seller_user # Return seller user even if no sales

    # Query for the page data
    stmt = select(models.Listing).where(
        models.Listing.seller_id == seller_user.id,
        models.Listing.status == models.ListingStatus.SOLD
    ).options(
        joinedload(models.Listing.meal),
        joinedload(models.Listing.buyer).load_only(models.User.telegram_id, models.User.username,
                                                   models.User.first_name)
    ).order_by(
        models.Listing.sold_at.desc()
    ).offset(offset).limit(page_size).distinct()

    result = await db.execute(stmt)
    listings = result.scalars().all()
    logger.info(f"Admin fetched {len(listings)} sold listings for seller {seller_telegram_id} on page {page}. Total for seller: {total_count}")
    return listings, total_count, seller_user

async def get_user_by_telegram_id(db: AsyncSession, telegram_id: int, load_listings: bool = False) -> models.User | None:
    """Fetches a user by their Telegram ID."""
    # Access models like models.User, models.Listing, etc.
    stmt = select(models.User).filter(models.User.telegram_id == telegram_id)
    if load_listings: stmt = stmt.options(selectinload(models.User.listings), selectinload(models.User.purchases))
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_total_users_count(db: AsyncSession) -> int:
    """Returns the total number of users in the system."""
    stmt = select(func.count(models.User.id))
    result = await db.execute(stmt)
    return result.scalar_one_or_none() or 0

async def get_admin_users_count(db: AsyncSession) -> int:
    """Returns the total number of admin users."""
    stmt = select(func.count(models.User.id)).where(models.User.is_admin == True)
    result = await db.execute(stmt)
    return result.scalar_one_or_none() or 0

async def get_verified_users_count(db: AsyncSession) -> int:
    """Returns the total number of verified users."""
    stmt = select(func.count(models.User.id)).where(models.User.is_verified == True)
    result = await db.execute(stmt)
    return result.scalar_one_or_none() or 0

async def get_inactive_users_count(db: AsyncSession) -> int:
    """Returns the total number of inactive (disabled) users."""
    stmt = select(func.count(models.User.id)).where(models.User.is_active == False)
    result = await db.execute(stmt)
    return result.scalar_one_or_none() or 0

async def get_listings_count_by_status(db: AsyncSession, status: models.ListingStatus) -> int:
    """Returns the count of listings for a given status."""
    stmt = select(func.count(models.Listing.id)).where(models.Listing.status == status)
    result = await db.execute(stmt)
    return result.scalar_one_or_none() or 0

async def get_total_value_of_listings_by_status(db: AsyncSession, status: models.ListingStatus) -> Decimal:
    """Returns the total sum of prices for listings of a given status."""
    stmt = select(func.sum(models.Listing.price)).where(models.Listing.status == status)
    result = await db.execute(stmt)
    total_value = result.scalar_one_or_none()
    return total_value if total_value is not None else Decimal('0.00')


async def get_active_meals_count(db: AsyncSession) -> int:
    """Returns the count of meals that are for today or in the future."""
    today = datetime.now(timezone.utc).date()
    stmt = select(func.count(models.Meal.id)).where(models.Meal.date >= today)
    result = await db.execute(stmt)
    return result.scalar_one_or_none() or 0

async def get_total_meals_count(db: AsyncSession) -> int:
    """Returns the total number of meals in the system (including past)."""
    stmt = select(func.count(models.Meal.id))
    result = await db.execute(stmt)
    return result.scalar_one_or_none() or 0

async def get_all_db_admin_users(db: AsyncSession) -> list[models.User]:
    """Fetches all users currently marked as admin in the database."""
    stmt = select(models.User).filter(models.User.is_admin == True)
    result = await db.execute(stmt)
    users = result.scalars().all()
    logger.info(f"Fetched {len(users)} users currently marked as admin from DB.")
    return users

async def get_user_details_for_admin(db: AsyncSession, target_user_telegram_id: int) -> models.User | None:
    """
    Fetches a user by their Telegram ID for admin viewing, including their listings and purchases.
    """
    logger.debug(f"Admin fetching details for user {target_user_telegram_id}")
    # Using get_user_by_telegram_id with load_listings=True to get comprehensive details
    return await get_user_by_telegram_id(db, target_user_telegram_id, load_listings=True)

async def get_user_by_username_for_admin(db: AsyncSession, username: str) -> models.User | None:
    """
    Fetches a user by their username for admin viewing, including listings and purchases.
    Username search is case-insensitive.
    """
    logger.debug(f"Admin fetching details for user with username: @{username}")
    stmt = select(models.User).where(
        func.lower(models.User.username) == func.lower(username) # Case-insensitive search
    ).options(
        selectinload(models.User.listings),
        selectinload(models.User.purchases)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()

async def get_or_create_user_and_update_info(db: AsyncSession, telegram_user: TelegramUser) -> models.User:
    """
    Gets an existing user or creates a new one.
    Always checks and updates username, first_name, and last_name if they have changed.
    """
    db_user = await get_user_by_telegram_id(db, telegram_user.id)
    needs_commit = False

    if db_user:
        # User exists, check for info updates
        if db_user.username != telegram_user.username:
            logger.debug(f"Updating username for TG_ID {telegram_user.id}: '{db_user.username}' -> '{telegram_user.username}'")
            db_user.username = telegram_user.username
            needs_commit = True
        if db_user.first_name != telegram_user.first_name:
            logger.debug(f"Updating first_name for TG_ID {telegram_user.id}: '{db_user.first_name}' -> '{telegram_user.first_name}'")
            db_user.first_name = telegram_user.first_name
            needs_commit = True
        if db_user.last_name != telegram_user.last_name: # Also check last_name
            logger.debug(f"Updating last_name for TG_ID {telegram_user.id}: '{db_user.last_name}' -> '{telegram_user.last_name}'")
            db_user.last_name = telegram_user.last_name
            needs_commit = True

        if needs_commit:
            try:
                db.add(db_user) # Ensure it's in the session if it became detached or for good measure
                await db.commit()
                await db.refresh(db_user)
                logger.info(f"User info updated in DB for TG_ID: {telegram_user.id}")
            except Exception as e:
                await db.rollback()
                logger.error(f"Error committing user info update for TG_ID {telegram_user.id}: {e}", exc_info=True)
                # db_user object might be stale here, but it's better than raising and potentially losing original user object
        return db_user
    else:
        # User does not exist, create them
        logger.info(f"Creating new user for TG_ID: {telegram_user.id}, Username: {telegram_user.username}")
        new_user = models.User(
            telegram_id=telegram_user.id,
            username=telegram_user.username,
            first_name=telegram_user.first_name,
            last_name=telegram_user.last_name,
            is_verified=False, # Default, will be set by verification flow
            is_active=True,    # Default new users to active
        )
        try:
            db.add(new_user)
            await db.commit()
            await db.refresh(new_user)
            logger.info(f"Created new user in DB: TG_ID: {new_user.telegram_id}")
            return new_user
        except Exception as e:
            await db.rollback()
            logger.error(f"Error creating new user for TG_ID {telegram_user.id}: {e}", exc_info=True)
            # If creation fails, we can't return a user object.
            # This is a more critical error, consider how to handle.
            # For now, re-raise or return None based on desired behavior.
            # Returning None might be problematic for callers expecting a User object.
            # Perhaps raise a specific custom exception.
            raise  # Re-raising for now to make it visible.


async def set_user_admin_state(db: AsyncSession, user_telegram_id: int, is_admin: bool) -> models.User | None:
    """Sets the admin status for a user."""
    user = await get_user_by_telegram_id(db, telegram_id=user_telegram_id)
    if user:
        user.is_admin = is_admin
        db.add(user)
        await db.commit()
        await db.refresh(user)
        logger.info(f"Set admin status for user {user_telegram_id} to {is_admin}")
        return user
    logger.warning(f"User {user_telegram_id} not found to set admin status.")
    return None


async def admin_get_all_users(db: AsyncSession, page: int = 0, page_size: int = 10) -> tuple[list[models.User], int]:
    """
    Fetches all users, paginated. For admin use.
    Returns a list of user objects and the total count of users.
    """
    logger.debug(f"Admin fetching all users, page {page}, page_size {page_size}")
    offset = page * page_size

    # Query for total count
    count_stmt = select(func.count(models.User.id)).select_from(models.User)
    count_result = await db.execute(count_stmt)
    total_count = count_result.scalar_one_or_none() or 0

    if total_count == 0:
        return [], 0

    # Query for the page data, ordering by ID for consistent pagination
    stmt = select(models.User).order_by(models.User.id).offset(offset).limit(page_size)
    result = await db.execute(stmt)
    users = result.scalars().all()
    logger.info(f"Admin fetched {len(users)} users for page {page}. Total users: {total_count}")
    return users, total_count


async def admin_delete_listing(db: AsyncSession, listing_id: int) -> bool:
    """
    Deletes a listing by its ID. For admin use.
    This is a hard delete.
    Returns True if deleted, False otherwise.
    """
    logger.info(f"Admin attempting to delete listing {listing_id}")
    listing = await db.get(models.Listing, listing_id) # Efficient way to get by PK

    if not listing:
        logger.warning(f"Admin delete failed: Listing {listing_id} not found.")
        return False

    try:
        await db.delete(listing)
        await db.commit()
        logger.info(f"Admin successfully deleted listing {listing_id}.")
        return True
    except Exception as e:
        await db.rollback()
        logger.error(f"DB error during admin deletion of listing {listing_id}: {e}", exc_info=True)
        return False

async def set_user_active_status(db: AsyncSession, user_telegram_id: int, is_active: bool) -> models.User | None:
    """Sets the active status for a user (enable/disable)."""
    user = await get_user_by_telegram_id(db, telegram_id=user_telegram_id)
    if user:
        if user.is_active == is_active: # No change needed
            logger.info(f"Active status for user {user_telegram_id} is already {is_active}. No action taken.")
            return user
        user.is_active = is_active
        db.add(user)
        await db.commit()
        await db.refresh(user)
        logger.info(f"Set active status for user {user_telegram_id} to {is_active}")
        return user
    logger.warning(f"User {user_telegram_id} not found to set active status.")
    return None


async def create_meal(db: AsyncSession,
    description: str,
    meal_type: str,
    meal_date: datetime.date,
    price: Decimal,
    price_limit: Decimal | None,
    is_active: bool = True) -> models.Meal | None:
    """Creates a new meal."""
    new_meal = models.Meal(
        description=description,
        meal_type=meal_type,
        date=meal_date,
        price=price,
        price_limit=price_limit
    )
    db.add(new_meal)
    await db.commit()
    await db.refresh(new_meal)
    logger.info(f"Created new meal: {new_meal.description} for {new_meal.date}")
    return new_meal


async def get_meal_by_id(db: AsyncSession, meal_id: int) -> models.Meal | None:
    """Fetches a meal by its ID."""
    stmt = select(models.Meal).where(models.Meal.id == meal_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()

async def get_all_meals(db: AsyncSession) -> list[models.Meal]:
    """
    Fetches all meals.
    Note: The provided Meal model does not have an `is_active` field.
    If it were added, `only_active=True` logic could be re-inserted here.
    """
    stmt = select(models.Meal).order_by(models.Meal.date.desc(), models.Meal.description)
    result = await db.execute(stmt)
    return result.scalars().all()


async def delete_meal(db: AsyncSession, meal_id: int) -> bool:
    """
    Deletes a meal by its ID.
    Prevents deletion if the meal is referenced by any existing listings.
    Returns True if deleted, False otherwise.
    """
    meal = await get_meal_by_id(db, meal_id)
    if not meal:
        logger.warning(f"Meal {meal_id} not found for deletion.")
        return False

    # Check if the meal is used in any listings
    stmt_listings = select(models.Listing.id).filter(models.Listing.meal_id == meal_id).limit(1)
    result_listings = await db.execute(stmt_listings)
    if result_listings.scalar_one_or_none():
        logger.warning(f"Cannot delete meal {meal_id} as it is referenced by existing listings. Consider deactivating listings first or marking meal as inactive (if model supported).")
        return False

    try:
        await db.delete(meal)
        await db.commit()
        logger.info(f"Deleted meal {meal_id}")
        return True
    except Exception as e:
        await db.rollback()
        logger.error(f"Error deleting meal {meal_id}: {e}", exc_info=True)
        return False

async def update_user_verification(
    db: AsyncSession,
    telegram_id: int,
    # edu_num: str,
    # id_num: str,
    phone_num: str
) -> models.User | None:
    """Updates user details from verification and sets is_verified to True."""
    db_user = await get_user_by_telegram_id(db, telegram_id)
    if not db_user:
        # This shouldn't happen if called after get_or_create_user
        return None

    # db_user.education_number = edu_num
    # db_user.identity_number = id_num
    db_user.phone_number = phone_num
    db_user.is_verified = True

    try:
        await db.commit()
        await db.refresh(db_user)
        return db_user
    except Exception as e:
        await db.rollback() # Rollback on error
        # Consider logging the error here
        # logger.error(f"Failed to update verification for user {telegram_id}: {e}")
        raise # Re-raise the exception to be handled by the caller


# async def get_reservation_by_code(db: AsyncSession, code: str) -> models.MealReservation | None:
#     """Fetches a MealReservation by its unique university_reservation_code."""
#     logger.debug(f"Fetching reservation by code: {code}")
#     stmt = select(models.MealReservation).where(
#         models.MealReservation.university_reservation_code == code
#     ).options(
#         # Load data needed for checks and confirmation messages
#         joinedload(models.MealReservation.user),    # Need user to check ownership
#         joinedload(models.MealReservation.meal),    # Need meal for price_limit & description
#         selectinload(models.MealReservation.listing) # Need listing to check if already listed
#     )
#     result = await db.execute(stmt)
#     return result.scalar_one_or_none()

# Get meals for selection
async def get_meals_for_selling(db: AsyncSession, specific_date: date | None = None) -> list[models.Meal]:
    """Fetches meals (e.g., for today/future) that can be listed."""
    today = datetime.now(timezone.utc).date()
    stmt = select(models.Meal).where(
        models.Meal.date >= today,
    ).order_by(models.Meal.date, models.Meal.description)
    result = await db.execute(stmt)
    return result.scalars().all()

async def check_listing_exists_by_code(db: AsyncSession, code: str) -> bool:
    """
    Checks if a listing with the given university_reservation_code already exists
    AND IS NOT CANCELLED OR EXPIRED.
    Returns True if an active (non-cancelled) listing with this code exists, False otherwise.
    """
    logger.debug(f"Checking for existing, non-cancelled listing with code: {code}")
    stmt = select(models.Listing.id).where(
        and_(
            models.Listing.university_reservation_code == code,
            models.Listing.status != models.ListingStatus.CANCELLED,
            models.Listing.status != models.ListingStatus.EXPIRED
        )
    ).limit(1)
    result = await db.execute(stmt)
    exists = result.scalar_one_or_none() is not None
    if exists:
        logger.info(f"An active (non-cancelled) listing with code '{code}' already exists.")
    else:
        logger.info(f"No active (non-cancelled) listing found with code '{code}'. Safe to create a new one.")
    return exists

async def create_listing(
    db: AsyncSession,
    seller_db_id: int, # Use the DB User ID
    university_reservation_code: str,
    meal_id: int,  # Foreign key to the selected Meal
    price: Decimal  # Consider using Decimal or Numeric if passed from handler
) -> models.Listing | None:
    """Creates a new listing, ensuring the code is unique."""
    # Check uniqueness of the code first
    code_exists = await check_listing_exists_by_code(db, university_reservation_code)
    if code_exists:
        logger.warning(
            f"Attempted to create listing for code {university_reservation_code}, "
            "but an active (non-cancelled) listing with this code already exists."
        )
        return None # Indicate failure: duplicate code

    logger.info(f"Creating new listing for code {university_reservation_code} by seller {seller_db_id} for meal {meal_id} at price {price}")

    # Check if the referenced meal_id exists (optional but good practice)
    meal_check = await db.get(models.Meal, meal_id)
    if not meal_check:
        logger.error(f"Meal with id {meal_id} not found when creating listing for code {university_reservation_code}.")
        return None # Indicate failure: invalid meal_id

    new_listing = models.Listing(
        seller_id=seller_db_id,
        university_reservation_code=university_reservation_code,
        meal_id=meal_id,
        price=price,  # Store as Numeric/Decimal
        status=models.ListingStatus.AVAILABLE
    )
    db.add(new_listing)
    try:
        await db.commit()
        await db.refresh(new_listing)
        logger.info(f"Successfully created listing {new_listing.id}")
        return new_listing
    except Exception as e:
        await db.rollback()
        logger.error(f"DB error creating listing for code {university_reservation_code}: {e}", exc_info=True)
        return None


async def get_available_listings(db: AsyncSession) -> list[models.Listing]:
    """Fetches all available listings."""
    result = await db.execute(
        select(models.Listing)
        .where(models.Listing.status == models.ListingStatus.AVAILABLE)
        .options(
            joinedload(models.Listing.seller),  # Eager load seller
            joinedload(models.Listing.meal)  # Eager load meal directly
        )
        .order_by(models.Listing.created_at.desc())  # Example order
    )
    return result.scalars().all()

async def get_listing_by_id(db: AsyncSession, listing_id: int) -> models.Listing | None:
    """Fetches a specific listing by its ID, loading related meal and seller."""
    result = await db.execute(
        select(models.Listing)
        .where(models.Listing.id == listing_id)
        .options(
            joinedload(models.Listing.seller), # Need seller for card number & notification
            joinedload(models.Listing.meal)    # Need meal details
        )
    )
    return result.scalar_one_or_none()


async def set_listing_awaiting_confirmation(
    db: AsyncSession, listing_id: int, buyer_telegram_id: int
) -> models.Listing | None:
    """Updates listing status to AWAITING_CONFIRMATION and sets pending_buyer_id."""
    logger.info(f"Setting listing {listing_id} to awaiting confirmation for buyer {buyer_telegram_id}")
    listing = await get_listing_by_id(db, listing_id) # Gets listing with seller+meal loaded
    if not listing:
        logger.warning(f"Listing {listing_id} not found.")
        return None

    if listing.status != models.ListingStatus.AVAILABLE:
        logger.warning(f"Listing {listing_id} is not available (status: {listing.status}). Cannot set to awaiting confirmation.")
        return None # Already processed or not available

    buyer_user = await get_user_by_telegram_id(db, buyer_telegram_id)
    if not buyer_user:
        logger.error(f"Buyer user {buyer_telegram_id} not found.")
        return None # Should not happen if buyer used /start

    if listing.seller_id == buyer_user.id:
         logger.warning(f"User {buyer_telegram_id} attempted to initiate purchase on own listing {listing_id}.")
         return None # Or handle as specific error case

    listing.status = models.ListingStatus.AWAITING_CONFIRMATION
    listing.pending_buyer_id = buyer_user.id # Store the intended buyer's *DB ID*
    listing.buyer_id = None # Ensure final buyer_id is null at this stage
    timeout_duration = timedelta(minutes=PENDING_TIMEOUT_MINUTES)
    listing.pending_until = datetime.now(timezone.utc) + timeout_duration
    listing.sold_at = None  # Ensure sold_at is None

    try:
        db.add(listing) # Ensure tracked by session
        await db.commit()
        await db.refresh(listing)
        # Ensure relationships needed by handler are refreshed
        await db.refresh(listing, attribute_names=['seller', 'meal'])
        logger.info(f"Listing {listing_id} status updated to AWAITING_CONFIRMATION.")
        return listing
    except Exception as e:
        await db.rollback()
        logger.error(f"DB error setting listing {listing_id} to awaiting: {e}", exc_info=True)
        return None


async def cancel_pending_purchase_by_buyer(
    db: AsyncSession, listing_id: int, buyer_telegram_id: int
) -> tuple[models.Listing | None, int | None]:
    """
    Allows the pending buyer to cancel their purchase request.
    Reverts the listing to AVAILABLE.
    Returns (updated_listing, seller_telegram_id) or (None, None).
    """
    logger.info(f"Buyer {buyer_telegram_id} attempting to cancel pending purchase for listing {listing_id}")
    try:
        # Fetch listing with seller and pending buyer info
        stmt = select(models.Listing).where(models.Listing.id == listing_id).options(
            joinedload(models.Listing.seller),
            joinedload(models.Listing.pending_buyer_relation).load_only(models.User.telegram_id) # Load only TG ID of pending buyer
        )
        result = await db.execute(stmt)
        listing = result.scalar_one_or_none()

        if not listing:
            logger.warning(f"Buyer cancellation failed: Listing {listing_id} not found.")
            return None, None

        # Verify status is AWAITING_CONFIRMATION
        if listing.status != models.ListingStatus.AWAITING_CONFIRMATION:
            logger.warning(f"Buyer cancellation failed: Listing {listing_id} is not AWAITING_CONFIRMATION (Status: {listing.status}).")
            return None, None

        # Verify the user cancelling is the pending buyer
        if not listing.pending_buyer_relation or listing.pending_buyer_relation.telegram_id != buyer_telegram_id:
            logger.warning(f"Buyer cancellation failed: User {buyer_telegram_id} is not the pending buyer for listing {listing_id}.")
            return None, None

        # Get seller TG ID for notification before potential detachment
        seller_tg_id = listing.seller.telegram_id if listing.seller else None

        # Perform cancellation
        listing.status = models.ListingStatus.AVAILABLE # Revert to available
        listing.pending_buyer_id = None
        listing.pending_buyer_relation = None # Detach relation in memory
        listing.pending_until = None
        listing.cancelled_by_buyer_at = datetime.now(timezone.utc) # Mark cancellation time

        db.add(listing)
        await db.commit()
        await db.refresh(listing) # Refresh the listing state
        logger.info(f"Successfully cancelled pending purchase for listing {listing_id} by buyer {buyer_telegram_id}.")
        return listing, seller_tg_id

    except Exception as e:
        await db.rollback()
        logger.error(f"DB error cancelling pending purchase by buyer for listing {listing_id}: {e}", exc_info=True)
        return None, None


async def reject_pending_purchase_by_seller(
    db: AsyncSession, listing_id: int, seller_telegram_id: int
) -> tuple[models.Listing | None, int | None]:
    """
    Allows the seller to reject/cancel a pending purchase request.
    Reverts the listing to AVAILABLE.
    Returns (updated_listing, buyer_telegram_id) or (None, None).
    """
    logger.info(f"Seller {seller_telegram_id} attempting to reject/cancel pending purchase for listing {listing_id}")
    try:
        # Fetch listing with seller and pending buyer info
        stmt = select(models.Listing).where(models.Listing.id == listing_id).options(
            joinedload(models.Listing.seller).load_only(models.User.telegram_id), # Load only TG ID of seller
            joinedload(models.Listing.pending_buyer_relation) # Load pending buyer for notification
        )
        result = await db.execute(stmt)
        listing = result.scalar_one_or_none()

        if not listing:
            logger.warning(f"Seller rejection failed: Listing {listing_id} not found.")
            return None, None

        # Verify ownership
        if not listing.seller or listing.seller.telegram_id != seller_telegram_id:
            logger.warning(f"Seller rejection failed: User {seller_telegram_id} is not the seller of listing {listing_id}.")
            return None, None

        # Verify status is AWAITING_CONFIRMATION
        if listing.status != models.ListingStatus.AWAITING_CONFIRMATION:
            logger.warning(f"Seller rejection failed: Listing {listing_id} is not AWAITING_CONFIRMATION (Status: {listing.status}).")
            return None, None

        # Get pending buyer TG ID for notification before potential detachment
        buyer_tg_id = listing.pending_buyer_relation.telegram_id if listing.pending_buyer_relation else None

        # Perform rejection (similar to buyer cancellation)
        listing.status = models.ListingStatus.AVAILABLE # Revert to available
        listing.pending_buyer_id = None
        listing.pending_buyer_relation = None # Detach relation in memory
        listing.pending_until = None
        listing.rejected_by_seller_at = datetime.now(timezone.utc) # Mark rejection time

        db.add(listing)
        await db.commit()
        await db.refresh(listing) # Refresh the listing state
        logger.info(f"Successfully rejected pending purchase for listing {listing_id} by seller {seller_telegram_id}.")
        return listing, buyer_tg_id

    except Exception as e:
        await db.rollback()
        logger.error(f"DB error rejecting pending purchase by seller for listing {listing_id}: {e}", exc_info=True)
        return None, None


async def finalize_listing_sale(
    db: AsyncSession, listing_id: int, confirming_seller_telegram_id: int
) -> tuple[models.Listing | None, str | None]: # Use tuple for clearer return type hint
    """
    Finalizes the sale after seller confirmation.
    Checks status, seller identity, sets buyer_id, status=SOLD, sold_at.
    Returns (updated_listing, reservation_code) or (None, None).
    """
    logger.info(f"Seller {confirming_seller_telegram_id} confirming payment for listing {listing_id}")

    # Fetch the listing, ensuring seller and meal details are loaded upfront
    stmt = select(models.Listing).where(models.Listing.id == listing_id).options(
        joinedload(models.Listing.seller),  # Load seller for checks
        joinedload(models.Listing.meal),            # Load meal for potential notifications later
        joinedload(models.Listing.pending_buyer_relation)  # Load pending buyer relation
    )
    result = await db.execute(stmt)
    listing = result.scalar_one_or_none()

    # --- Perform Checks ---
    if not listing:
        logger.warning(f"Listing {listing_id} not found.")
        return None, None
    # Use seller loaded via joinedload
    if not listing.seller or listing.seller.telegram_id != confirming_seller_telegram_id:
        # Added more specific log message
        logger.error(f"User {confirming_seller_telegram_id} is not the seller of listing {listing_id} or seller info failed to load.")
        return None, None
    if listing.status != models.ListingStatus.AWAITING_CONFIRMATION:
        # Added status value to log message
        logger.warning(f"Listing {listing_id} is not awaiting confirmation (Status: {listing.status}). Cannot finalize.")
        return None, None
    if not listing.pending_buyer_id: # This check is important
        logger.error(f"Listing {listing_id} is awaiting confirmation but has no pending_buyer_id!")
        # This indicates a potential issue in the previous step (handle_confirm_purchase)
        return None, None

    # --- Fetch the Pending Buyer User Separately ---
    # This is the correct way to get the user based on the pending_buyer_id
    pending_buyer_user = await db.get(models.User, listing.pending_buyer_id)
    if not pending_buyer_user:
        logger.error(f"Pending buyer user ID {listing.pending_buyer_id} not found in DB for listing {listing_id}.")
        # Decide how to handle this - maybe revert listing status? For now, fail finalization.
        return None, None # Cannot finalize without the buyer user object

    # --- Prepare for Update ---
    reservation_code = listing.university_reservation_code # Get code before potential state changes
    pending_buyer_user = listing.pending_buyer_relation  # Get buyer from the loaded relationship

    # --- Finalize the Sale Attributes ---
    listing.status = models.ListingStatus.SOLD
    listing.buyer_id = listing.pending_buyer_id     # Set final buyer FK from pending FK
    listing.buyer = pending_buyer_user              # Associate the fetched buyer object in memory
    listing.pending_buyer_id = None                 # Clear pending buyer ID
    listing.pending_buyer_relation = None           # Clear pending buyer relationship in memory
    listing.sold_at = datetime.now(timezone.utc)
    listing.pending_until = None  # Clear timeout

    # --- Commit and Refresh ---
    try:
        db.add(listing) # Ensure the modified listing object is tracked by the session
        await db.commit()
        # Refresh the listing object AND the relationships modified/needed by the caller.
        # Refreshing 'buyer' ensures the relationship uses the now-committed buyer_id.
        # Refreshing 'meal' ensures it's up-to-date if accessed after returning.
        await db.refresh(listing, attribute_names=['buyer', 'meal'])
        logger.info(f"Listing {listing_id} finalized as SOLD to buyer ID {listing.buyer_id}.")
        return listing, reservation_code # Return the updated listing object and the code
    except Exception as e:
        await db.rollback()
        logger.error(f"DB error during commit/refresh finalizing sale for listing {listing_id}: {e}", exc_info=True)
        return None, None


async def update_user_credit_card(db: AsyncSession, telegram_id: int, new_card_number: str) -> bool:
    """Updates only the credit_card_number for a given user."""
    logger.info(f"Attempting to update credit card for telegram_id {telegram_id}")
    try:
        # Fetch the user first
        stmt = select(models.User).filter(models.User.telegram_id == telegram_id)
        result = await db.execute(stmt)
        db_user = result.scalar_one_or_none()

        if not db_user:
            logger.warning(f"User with telegram_id {telegram_id} not found for card update.")
            return False

        # Update the card number
        db_user.credit_card_number = new_card_number
        # The updated_at field should update automatically due to onupdate

        await db.commit()
        logger.info(f"Successfully updated credit card for telegram_id {telegram_id}")
        return True

    except Exception as e:
        await db.rollback()
        logger.error(f"DB error updating credit card for telegram_id {telegram_id}: {e}", exc_info=True)
        return False # Indicate failure

async def get_user_active_listings(db: AsyncSession, user_telegram_id: int) -> list[models.Listing]:
    """
    Fetches listings for a user that are either AVAILABLE or AWAITING_CONFIRMATION.
    """
    logger.debug(f"Fetching active listings for user {user_telegram_id}")
    user = await get_user_by_telegram_id(db, user_telegram_id)
    if not user:
        logger.warning(f"User {user_telegram_id} not found when fetching active listings.")
        return []

    stmt = select(models.Listing).where(
        models.Listing.seller_id == user.id,
        or_( # Check for multiple statuses
            models.Listing.status == models.ListingStatus.AVAILABLE,
            models.Listing.status == models.ListingStatus.AWAITING_CONFIRMATION
        )
    ).options(
        # Load meal details for display
        joinedload(models.Listing.meal)
        # joinedload(models.Listing.pending_buyer) # Optional: Load if displaying buyer info
    ).order_by(
        # Order by status first (e.g., awaiting first), then by date
        models.Listing.status.desc(), # 'sold', 'awaiting...', 'available', 'cancelled'
        models.Listing.created_at.desc() # Or by meal date: models.Listing.meal.date
    )

    result = await db.execute(stmt)
    listings = result.scalars().all()
    logger.debug(f"Found {len(listings)} active listings for user {user_telegram_id}")
    return listings

async def cancel_available_listing_by_seller(db: AsyncSession, listing_id: int, seller_telegram_id: int) -> bool:
    """
    Cancels an AVAILABLE listing if the user is the seller.
    Returns True on success, False otherwise.
    """
    logger.info(f"User {seller_telegram_id} attempting to cancel available listing {listing_id}")
    try:
        # Fetch the listing and seller in one go
        stmt = select(models.Listing).where(models.Listing.id == listing_id).options(joinedload(models.Listing.seller))
        result = await db.execute(stmt)
        listing = result.scalar_one_or_none()

        if not listing:
            logger.warning(f"Cancellation failed: Listing {listing_id} not found.")
            return False

        # Verify ownership
        if not listing.seller or listing.seller.telegram_id != seller_telegram_id:
            logger.warning(f"Cancellation failed: User {seller_telegram_id} is not the seller of listing {listing_id}.")
            return False

        # Verify status
        if listing.status != models.ListingStatus.AVAILABLE:
            logger.warning(f"Cancellation failed: Listing {listing_id} is not AVAILABLE (Status: {listing.status}).")
            return False

        # Perform cancellation
        listing.status = models.ListingStatus.CANCELLED
        listing.cancelled_at = datetime.now(timezone.utc)
        # Keep other fields like pending_buyer_id (should be null anyway)

        db.add(listing)
        await db.commit()
        logger.info(f"Successfully cancelled listing {listing_id} by seller {seller_telegram_id}.")
        return True

    except Exception as e:
        await db.rollback()
        logger.error(f"DB error cancelling listing {listing_id}: {e}", exc_info=True)
        return False


async def get_user_purchase_history(
        db: AsyncSession,
        user_telegram_id: int,
        page: int = 0,
        page_size: int = 5
) -> tuple[list[models.Listing], int]:
    """Fetches paginated purchase history (SOLD listings) for a user."""
    logger.debug(f"Fetching purchase history for user {user_telegram_id}, page {page}")
    # Ensure the target user exists and get their DB ID
    user = await get_user_by_telegram_id(db, user_telegram_id)
    if not user:
        return [], 0

    offset = page * page_size

    # Query for total count
    count_stmt = select(func.count(models.Listing.id)).where(
        models.Listing.buyer_id == user.id,
        models.Listing.status == models.ListingStatus.SOLD # Only show successful purchases
    ).select_from(models.Listing) # Specify the FROM clause for count
    count_result = await db.execute(count_stmt)
    total_count = count_result.scalar_one_or_none() or 0

    if total_count == 0:
        return [], 0

    # Query for the page data
    stmt = select(models.Listing).where(
        models.Listing.buyer_id == user.id,
        models.Listing.status == models.ListingStatus.SOLD
    ).options(
        # Load data needed for display
        joinedload(models.Listing.meal),
        joinedload(models.Listing.seller) # Load seller info
    ).order_by(
        models.Listing.sold_at.desc() # Newest purchases first
    ).offset(offset).limit(page_size)

    result = await db.execute(stmt)
    listings = result.scalars().all()
    logger.debug(f"Found {len(listings)} purchases on page {page} for user {user_telegram_id} (Total: {total_count})")
    return listings, total_count

async def get_user_sale_history(db: AsyncSession, user_telegram_id: int, page: int = 0, page_size: int = 5) -> tuple[list[models.Listing], int]:
    """Fetches paginated sale history (SOLD listings) for a user."""
    logger.debug(f"Fetching sale history for user {user_telegram_id}, page {page}")
    user = await get_user_by_telegram_id(db, user_telegram_id)
    if not user:
        return [], 0

    offset = page * page_size

    # Query for total count
    count_stmt = select(func.count(models.Listing.id)).where(
        models.Listing.seller_id == user.id,
        models.Listing.status == models.ListingStatus.SOLD # Only show successful sales
    ).select_from(models.Listing)
    count_result = await db.execute(count_stmt)
    total_count = count_result.scalar_one_or_none() or 0

    if total_count == 0:
        return [], 0

    # Query for the page data
    stmt = select(models.Listing).where(
        models.Listing.seller_id == user.id,
        models.Listing.status == models.ListingStatus.SOLD
    ).options(
        # Load data needed for display
        joinedload(models.Listing.meal),
        joinedload(models.Listing.buyer) # Load buyer info
    ).order_by(
        models.Listing.sold_at.desc() # Newest sales first
    ).offset(offset).limit(page_size)

    result = await db.execute(stmt)
    listings = result.scalars().all()
    logger.debug(f"Found {len(listings)} sales on page {page} for user {user_telegram_id} (Total: {total_count})")
    return listings, total_count

# async def mark_listing_as_sold(db: AsyncSession, listing_id: int, buyer_telegram_id: int) -> models.Listing | None:
#     """Marks a listing as sold to a specific buyer."""
#     logger.info(f"Attempting to mark listing {listing_id} as sold to user {buyer_telegram_id}")
#     listing = await get_listing_by_id(db, listing_id)
#     if not listing:
#         logger.warning(f"Listing {listing_id} not found for purchase attempt.")
#         return None # Listing doesn't exist
#
#     if listing.status != models.ListingStatus.AVAILABLE:
#         logger.warning(f"Listing {listing_id} is not available for purchase (status: {listing.status}).")
#         return None # Listing not available (already sold or pending)
#
#     buyer_user = await get_user_by_telegram_id(db, buyer_telegram_id)
#     if not buyer_user:
#         logger.error(f"Buyer user with Telegram ID {buyer_telegram_id} not found in DB.")
#         # Or should we create the buyer if they somehow don't exist? Unlikely after /start.
#         return None # Buyer doesn't exist
#
#     if listing.seller_id == buyer_user.id:
#         logger.warning(f"User {buyer_telegram_id} attempted to buy their own listing {listing_id}.")
#         # Depending on rules, you might disallow this
#         return None # Prevent buying own listing
#
#     # Use the model's method to update state
#     listing.mark_as_sold(buyer_user=buyer_user)
#     logger.info(f"Listing {listing_id} marked as sold in object. Committing...")
#
#     try:
#         # Add the listing to the session if it wasn't already tracked or became detached
#         db.add(listing)
#         await db.commit()
#         await db.refresh(listing) # Refresh to get updated timestamps etc.
#         logger.info(f"Successfully committed listing {listing_id} as SOLD to buyer {buyer_user.id}.")
#         return listing
#     except Exception as e:
#         await db.rollback()
#         logger.error(f"Database error marking listing {listing_id} as sold: {e}", exc_info=True)
#         return None # Indicate failure


