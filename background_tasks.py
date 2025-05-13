import asyncio
import json
import logging
from datetime import datetime, timezone, date, timedelta

import certifi
import httpx
from httpx import request
from sqlalchemy import delete
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from telegram.constants import ParseMode
from telegram.error import Forbidden, BadRequest # To handle blocked users or bad IDs
from telegram.ext import Application as PTBApplication # Specific type hint for Application

from config import MEALS_LIMIT, SAMAD_PROXY, DEFAULT_PRICE_LIMIT, SAMAD_API_USERNAME, SAMAD_API_PASSWORD
from self_market import models # Or wherever your models are
from self_market.db.session import get_db_session # Your session factory
from utility import get_iran_week_start_dates

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


# Constant days of the week
DAYS_ORDER = ["SATURDAY", "SUNDAY", "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"]

def process_meal_data(raw_data, current_week_start_date, is_current_week):
    """
    Processes the raw meal data from the API for a single week.
    Filters out past days for the current week.
    """
    logger.debug(f"Processing meal data for week starting {current_week_start_date}, is_current_week: {is_current_week}")
    processed_meals = {}
    if 'payload' in raw_data and 'selfWeekPrograms' in raw_data['payload']:
        for day_program_list in raw_data['payload']['selfWeekPrograms']:
            if day_program_list:
                meal_info = day_program_list[0] # Assuming the first meal object for the day

                day_translated = meal_info.get('dayTranslated')
                food_name = meal_info.get('foodName')
                food_price = meal_info.get('price')
                meal_date_str = meal_info.get('date')

                if day_translated and food_name is not None and food_price is not None and meal_date_str is not None:
                    day_key = day_translated.upper()
                    processed_meals[day_key] = {
                        "date": meal_date_str,
                        "foodName": food_name,
                        "foodPrice": food_price
                    }
                    logger.debug(f"Processed meal: {day_key} - {food_name}")
                else:
                    logger.warning(f"Missing data for a program entry ID: {meal_info.get('programId', 'Unknown ID')}. Meal_info: {meal_info}")
            else:
                logger.debug("Empty day_program_list encountered.")
    else:
        logger.warning("'payload' or 'selfWeekPrograms' not found in API response for a week. Raw data keys: %s", raw_data.keys() if isinstance(raw_data, dict) else "Not a dict")


    if is_current_week:
        today = date.today()
        # Ensure today_day_iran_upper is derived correctly as per your system's locale for day names
        # Python's strftime %A is locale-dependent. If it needs to be consistently Persian,
        # you might need a more robust way or ensure the locale is set.
        # For this example, assuming it aligns with DAYS_ORDER after .upper()
        today_day_iran_upper = today.strftime("%A").upper()

        if today_day_iran_upper not in DAYS_ORDER:
            logger.error(f"Error: Current day name '{today_day_iran_upper}' (from strftime) is not recognized in DAYS_ORDER: {DAYS_ORDER}.")
            return {}

        try:
            current_day_index = DAYS_ORDER.index(today_day_iran_upper)
        except ValueError:
            logger.critical(f"Critical Error: '{today_day_iran_upper}' not found in DAYS_ORDER despite prior check. This indicates a mismatch. DAYS_ORDER: {DAYS_ORDER}")
            return {}

        filtered_meals_current_week = {}
        for day_name_upper in DAYS_ORDER:
            if day_name_upper in processed_meals:
                day_index = DAYS_ORDER.index(day_name_upper)
                if day_index >= current_day_index:
                    filtered_meals_current_week[day_name_upper] = processed_meals[day_name_upper]
                    logger.debug(f"Included meal for current week (today or future): {day_name_upper}")
                else:
                    logger.debug(f"Filtered out past meal for current week: {day_name_upper}")
        logger.info(f"Finished processing for current week. {len(filtered_meals_current_week)} meals kept out of {len(processed_meals)}.")
        return filtered_meals_current_week
    else:
        logger.info(f"Finished processing for next week. {len(processed_meals)} meals kept.")
        return processed_meals

async def update_meals_from_samad(app: PTBApplication = None): # Added app parameter for consistency if needed by scheduler
    """
    Fetches meal data from Samad API, processes it, and updates the database.
    The `app` parameter is optional and not used in this function but included
    for consistency with how jobs might be scheduled in main.py.
    """
    logger.info("Starting scheduled task: update_meals_from_samad")


    # Check if credentials are set from config
    if not SAMAD_API_USERNAME or SAMAD_API_USERNAME == "YOUR_SAMAD_USERNAME" \
        or not SAMAD_API_PASSWORD or SAMAD_API_PASSWORD == "YOUR_SAMAD_PASSWORD":
            logger.error("Samad API username or password not configured. Skipping meal update.")

    return
    BASE_URL = "https://saba.nus.ac.ir"
    TOKEN_URL = f"{BASE_URL}/oauth/token"
    MEALS_URL_TEMPLATE = f"{BASE_URL}/rest/programs/v2?selfId=158&weekStartDate={{week_start_date}}"

    auth_form_fields = {
        "username": SAMAD_API_USERNAME,
        "password": SAMAD_API_PASSWORD,
        "grant_type": "password",
        "scope": "read+write",
    }
    auth_headers = {
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:137.0) Gecko/20100101 Firefox/137.0",
        "authorization": "Basic c2FtYWQtbW9iaWxlOnNhbWFkLW1vYmlsZS1zZWNyZXQ="
    }

    all_meal_results = {}
    processed_meals_for_db_objects = []
    access_token = None # Initialize access_token

    logger.info("Attempting to authenticate with Samad API.")
    try:
        logger.debug(f"Using proxy: {proxy_config}")
        async with httpx.AsyncClient(verify=False, timeout=20.0, proxy=SAMAD_PROXY) as client:
            auth_response = await client.post(TOKEN_URL, headers=auth_headers, data=auth_form_fields)
            auth_response.raise_for_status()
            logger.info(f"Authentication successful. Status: {auth_response.status_code}")

            tokens = auth_response.json()
            access_token = tokens.get("access_token")
            if not access_token:
                logger.error("Access token not found in authentication response.")
                return # Cannot proceed without token

            token_type = tokens.get("token_type", "bearer").capitalize()
            logger.debug(f"Access Token obtained. Type: {token_type}")

            client.headers.update({
                "Authorization": f"{token_type} {access_token}",
            })

            start_of_current_week, start_of_next_week = get_iran_week_start_dates()
            weeks_to_fetch = [
                {"date": start_of_current_week, "is_current": True, "label": "Current Week (Remaining)"},
                {"date": start_of_next_week, "is_current": False, "label": "Next Week"}
            ]

            for week_info in weeks_to_fetch:
                week_start_date_str = week_info["date"].strftime("%Y-%m-%d 00:00:00")
                current_meals_url = MEALS_URL_TEMPLATE.format(week_start_date=week_start_date_str)
                logger.info(f"Fetching meals for: {week_info['label']} (URL: {current_meals_url})")

                meals_response = await client.get(current_meals_url)
                try:
                    meals_response.raise_for_status()
                except httpx.HTTPStatusError:
                    continue
                raw_meal_data = meals_response.json()
                logger.debug(f"Successfully fetched raw meal data for {week_info['label']}. Status: {meals_response.status_code}")

                processed_data = process_meal_data(raw_meal_data, week_info["date"], week_info["is_current"])
                all_meal_results[week_info["label"]] = processed_data
                logger.info(f"Processed meal data for {week_info['label']}. Found {len(processed_data)} meals.")

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error during Samad API interaction: URL={e.request.url}, Status={e.response.status_code}, Response='{e.response.text}'", exc_info=True)
        return # Stop execution if API fails critically
    except httpx.RequestError as e:
        logger.error(f"Request error during Samad API interaction: URL={e.request.url}, Error={e}", exc_info=True)
        return
    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode JSON response from Samad API: {e.msg}", exc_info=True)
        # logger.debug(f"Problematic JSON text (first 500 chars): {e.doc[:500]}" if hasattr(e, 'doc') else "No document context") # Log part of the problematic JSON
        return
    except KeyError as e:
        logger.error(f"Missing expected key in API response from Samad: {e}", exc_info=True)
        return
    except Exception as e:
        logger.error(f"An unexpected error occurred during Samad API interaction: {e}", exc_info=True)
        return # Stop execution on unexpected error

    # Process meal data and prepare for DB ---
    logger.info("Processing all fetched meal data for database preparation.")
    if not all_meal_results:
        logger.warning("No meal results were fetched from the API. Nothing to process for DB.")
    else:
        for week_label, daily_meals_map in all_meal_results.items():
            logger.info(f"Processing meals for '{week_label}':")
            if daily_meals_map:
                # logger.debug(f"Data for {week_label}: {json.dumps(daily_meals_map, indent=2, ensure_ascii=False)}")
                for day_name, meal_item_data in daily_meals_map.items():
                    if not meal_item_data or not isinstance(meal_item_data, dict):
                        logger.warning(f"Skipping invalid meal data for {day_name} in {week_label}: {meal_item_data}")
                        continue

                    food_name = meal_item_data.get("foodName")
                    meal_date_str = meal_item_data.get("date")
                    food_price = meal_item_data.get("foodPrice")

                    if not food_name or not meal_date_str:
                        logger.warning(f"Skipping meal item due to missing foodName or date in {week_label} for day {day_name}. Data: {meal_item_data}")
                        continue

                    try:
                        meal_date_obj = datetime.strptime(meal_date_str, "%Y-%m-%d").date()
                    except ValueError:
                        logger.warning(f"Invalid date format for '{food_name}' on '{meal_date_str}' in {week_label}. Skipping.")
                        continue

                    price_limit_config = MEALS_LIMIT.get(food_name)
                    actual_price_limit = None
                    if price_limit_config:
                        actual_price_limit = price_limit_config.get("priceLimit")
                        logger.debug(f"Price limit for '{food_name}': {actual_price_limit}")
                    else:
                        actual_price_limit = DEFAULT_PRICE_LIMIT
                        logger.warning(f"Price limit configuration not found for '{food_name}'. Price limit will be set to {DEFAULT_PRICE_LIMIT}.")

                    new_meal_obj = models.Meal(
                        date=meal_date_obj,
                        meal_type="ناهار", # Assuming always "ناهار" (Lunch)
                        description=food_name,
                        price=food_price,
                        price_limit=actual_price_limit
                    )
                    processed_meals_for_db_objects.append(new_meal_obj)
                    logger.debug(f"Prepared DB object for meal: {food_name} on {meal_date_obj}")
            else:
                logger.info(f"No meals found or processed for {week_label}.")

    # Database Insertion
    if processed_meals_for_db_objects:
        logger.info(f"Attempting to save/update {len(processed_meals_for_db_objects)} meals in the database...")
        saved_count = 0
        updated_count = 0
        try:
            async with get_db_session() as session:
                for meal_to_add in processed_meals_for_db_objects:
                    # Check if meal already exists for this date and description
                    stmt = select(models.Meal).where(
                        models.Meal.date == meal_to_add.date,
                        models.Meal.description == meal_to_add.description
                    )
                    result = await session.execute(stmt)
                    existing_meal = result.scalars().first()

                    if existing_meal:
                        # Update existing meal if details have changed (e.g., price, price_limit)
                        logger.debug(f"Meal '{meal_to_add.description}' on {meal_to_add.date} already exists. Checking for updates.")
                        changed = False
                        if existing_meal.price != meal_to_add.price:
                            existing_meal.price = meal_to_add.price
                            changed = True
                        if existing_meal.price_limit != meal_to_add.price_limit:
                            existing_meal.price_limit = meal_to_add.price_limit
                            changed = True
                        # Add other fields if necessary

                        if changed:
                            session.add(existing_meal) # Add to session to mark as dirty
                            updated_count +=1
                            logger.info(f"Updating existing meal: {existing_meal.description} on {existing_meal.date}")
                        else:
                            logger.debug(f"No changes for existing meal: {existing_meal.description} on {existing_meal.date}")
                    else:
                        session.add(meal_to_add)
                        saved_count += 1
                        logger.info(f"Adding new meal: {meal_to_add.description} on {meal_to_add.date}")

                if saved_count > 0 or updated_count > 0:
                    await session.commit()
                    logger.info(f"Database update complete. New meals saved: {saved_count}. Existing meals updated: {updated_count}.")
                else:
                    logger.info("No new meals to save or existing meals to update in the database.")

        except Exception as e_db:
            logger.error(f"An error occurred during database operations for meals: {e_db}", exc_info=True)
            # Consider rollback if session is available and an error occurred mid-transaction
            # if 'session' in locals() and session.is_active:
            #     await session.rollback()
            #     logger.info("Database transaction rolled back due to error.")
    else:
        logger.info("No processed meals to add or update in the database.")

    # Clear the meals from the previous days and the listings related to them
    today_date = datetime.now(timezone.utc).date()
    logger.info(
        "Starting cleanup: Attempting to clear meals (and related listings) with a date before %s.",
        today_date.isoformat()
    )

    deleted_listings_count = 0
    deleted_meals_count = 0

    try:
        async with get_db_session() as session:
            # Listings are deleted first to prevent foreign key constraint violations
            listings_delete_stmt = delete(models.Listing).where(
                models.Listing.meal_id.in_(
                    select(models.Meal.id).where(models.Meal.date < today_date)
                )
            )
            # Execute the deletion of targeted listings
            listings_result = await session.execute(listings_delete_stmt)
            deleted_listings_count = listings_result.rowcount
            if deleted_listings_count > 0:
                logger.debug(f"Found and targeted {deleted_listings_count} old listings for deletion.")

            # This will delete meals whose date is before today_date.
            meals_delete_stmt = delete(models.Meal).where(
                models.Meal.date < today_date
            )
            # Execute the deletion of targeted meals
            meals_result = await session.execute(meals_delete_stmt)
            deleted_meals_count = meals_result.rowcount
            if deleted_meals_count > 0:
                logger.debug(f"Found and targeted {deleted_meals_count} old meals for deletion.")

            # Commit the transaction if any changes were made.
            if deleted_listings_count > 0 or deleted_meals_count > 0:
                await session.commit()
                logger.info(
                    "Cleanup transaction committed: Successfully deleted %d listings and %d meals dated before %s.",
                    deleted_listings_count,
                    deleted_meals_count,
                    today_date.isoformat()
                )
            else:
                # No need to commit if no rows were affected.
                logger.info(
                    "Cleanup: No meals or listings found with a date before %s. No cleanup changes committed to the database.",
                    today_date.isoformat()
                )

    except SQLAlchemyError as exc_alchemy:
        # The get_db_session context manager should handle rollback on exceptions.
        logger.error(
            "SQLAlchemyError during old meal/listing cleanup. Transaction likely rolled back. Error: %s",
            exc_alchemy,
            exc_info=True  # Logs the full traceback
        )
    except Exception as exc_general:
        # The get_db_session context manager should handle rollback.
        logger.error(
            "Unexpected error during old meal/listing cleanup. Transaction likely rolled back. Error: %s",
            exc_general,
            exc_info=True  # Logs the full traceback
        )

    logger.info("Finished scheduled task: update_meals_from_samad")



if __name__ == "__main__":
    asyncio.run(update_meals_from_samad())