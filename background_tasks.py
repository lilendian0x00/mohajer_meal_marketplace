import logging
from datetime import datetime, timezone
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from telegram.constants import ParseMode
from telegram.error import Forbidden, BadRequest # To handle blocked users or bad IDs
from telegram.ext import Application as PTBApplication # Specific type hint for Application
from self_market import models # Or wherever your models are
from self_market.db.session import get_db_session # Your session factory

logger = logging.getLogger(__name__)

async def check_pending_listings_timeout(app: PTBApplication):
    """
    Checks for listings stuck in AWAITING_CONFIRMATION past their timeout
    and reverts them to AVAILABLE, notifying relevant users.
    """
    logger.info("Running background task: check_pending_listings_timeout")
    now = datetime.now(timezone.utc)
    listings_reverted = []
    notification_tasks = []

    async with get_db_session() as session:
        try:
            # Find listings that are awaiting confirmation and whose pending_until time has passed
            stmt = select(models.Listing).where(
                models.Listing.status == models.ListingStatus.AWAITING_CONFIRMATION,
                models.Listing.pending_until != None,
                models.Listing.pending_until < now
            ).options(
                # Load seller for notification ID. Buyer ID is stored directly.
                selectinload(models.Listing.seller)
            )

            result = await session.execute(stmt)
            expired_listings = result.scalars().all()

            if not expired_listings:
                logger.info("No pending listings found past their timeout.")
                return

            logger.info(f"Found {len(expired_listings)} expired pending listings.")

            # Prepare listings for update and gather notification info
            for listing in expired_listings:
                seller_tg_id = listing.seller.telegram_id if listing.seller else None
                pending_buyer_id = listing.pending_buyer_id # This is the DB User ID

                if not seller_tg_id or not pending_buyer_id:
                    logger.warning(f"Skipping timeout for listing {listing.id} due to missing seller/buyer ID.")
                    continue

                # Store info needed for notifications after commit
                listings_reverted.append({
                    "listing_id": listing.id,
                    "seller_tg_id": seller_tg_id,
                    "pending_buyer_id": pending_buyer_id, # Store buyer's DB ID
                    "meal_desc": listing.meal.description if listing.meal else "Unknown Meal" # Get description if meal loaded or available
                })

                # Revert listing state
                listing.status = models.ListingStatus.AVAILABLE # Revert to AVAILABLE
                # Or use a new TIMED_OUT status if you prefer:
                # listing.status = models.ListingStatus.TIMED_OUT
                listing.pending_buyer_id = None
                listing.pending_until = None
                session.add(listing) # Add modified listing to session for commit

            # Commit all changes at once
            await session.commit()
            logger.info(f"Reverted {len(listings_reverted)} listings from AWAITING_CONFIRMATION due to timeout.")

            # Send Notifications AFTER successful commit
            for revert_info in listings_reverted:
                listing_id = revert_info["listing_id"]
                seller_tg_id = revert_info["seller_tg_id"]
                pending_buyer_db_id = revert_info["pending_buyer_id"]
                meal_desc = revert_info["meal_desc"]

                # Fetch the buyer user object to get their telegram_id
                pending_buyer_user = await session.get(models.User, pending_buyer_db_id)
                if not pending_buyer_user:
                    logger.warning(f"Could not find buyer user (DB ID: {pending_buyer_db_id}) for notification for timed-out listing {listing_id}.")
                    continue # Skip buyer notification if user not found

                buyer_tg_id = pending_buyer_user.telegram_id

                # Prepare notification messages
                seller_message = (
                    f"⏳ مهلت تایید برای آگهی شما (`{listing_id}` - {meal_desc}) به پایان رسید.\n"
                    f"این آگهی مجدداً در وضعیت **موجود** قرار گرفت."
                    # If using TIMED_OUT status:
                    # f"وضعیت این آگهی به 'منقضی شده' تغییر یافت."
                )
                buyer_message = (
                    f"⏳ متاسفانه فروشنده تایید پرداخت برای آگهی `{listing_id}` ({meal_desc}) را در زمان مقرر انجام نداد.\n"
                    f"درخواست خرید شما لغو شد. آگهی مجدداً **موجود** است و در صورت تمایل می‌توانید دوباره برای خرید اقدام کنید."
                    # If using TIMED_OUT status:
                    # f"درخواست خرید شما منقضی شد و آگهی دیگر فعال نیست."
                )

                # Send notification to seller (handle potential blocks)
                try:
                    notification_tasks.append(
                        await app.bot.send_message(chat_id=seller_tg_id, text=seller_message, parse_mode=ParseMode.MARKDOWN)
                    )
                    logger.debug(f"Scheduled timeout notification for seller {seller_tg_id} for listing {listing_id}")
                except (Forbidden, BadRequest) as e:
                    logger.warning(f"Failed to send timeout notification to seller {seller_tg_id} for listing {listing_id}: {e}")

                # Send notification to buyer (handle potential blocks)
                try:
                     notification_tasks.append(
                        await app.bot.send_message(chat_id=buyer_tg_id, text=buyer_message, parse_mode=ParseMode.MARKDOWN)
                    )
                     logger.debug(f"Scheduled timeout notification for buyer {buyer_tg_id} for listing {listing_id}")
                except (Forbidden, BadRequest) as e:
                    logger.warning(f"Failed to send timeout notification to buyer {buyer_tg_id} for listing {listing_id}: {e}")

        except Exception as e:
            logger.error(f"Error in check_pending_listings_timeout task: {e}", exc_info=True)
            await session.rollback() # Rollback on error during DB operations

    logger.info("Finished background task: check_pending_listings_timeout")