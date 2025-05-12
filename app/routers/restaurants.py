from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime, timedelta
import logging
from app.db import models, database
from app.auth.auth_dependency import get_current_user
from app.db.models import User
from app.models_api.restaurant import RestaurantCreate
from app.models_api.reservation import ReservationCreate
from app.utils.email_utils import send_booking_confirmation, BookingConfirmationDetails 

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/restaurants",
    tags=["Restaurants"]
)

# DB session dependency
def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Debug endpoint to test database
@router.get("/debug/test-db")
def test_database(db: Session = Depends(get_db)):
    """Test database connection and show recent reservations"""
    try:
        # Test reading from the reservations table
        reservations = db.query(models.Reservation).order_by(models.Reservation.id.desc()).limit(5).all()
        
        # Test writing a simple object and rolling back
        test_reservation = models.Reservation(
            user_id=19,  # Using the same user_id as your existing reservations
            restaurant_id=1,
            table_id=1,
            date=datetime.now().date(),
            time=datetime.now().time(),
            number_of_people=2
        )
        
        db.add(test_reservation)
        db.flush()  # Test that we can flush
        db.rollback()  # Roll back the test reservation
        
        # Return diagnostic info
        return {
            "database_type": str(db.bind.dialect.name),
            "database_path": str(db.bind.url),
            "recent_reservations": [
                {
                    "id": r.id,
                    "user_id": r.user_id,
                    "restaurant_id": r.restaurant_id,
                    "date": str(r.date),
                    "time": str(r.time),
                }
                for r in reservations
            ],
            "test_write": "successful"
        }
    except Exception as e:
        import traceback
        return {
            "error": str(e),
            "traceback": traceback.format_exc()
        }

#  Search restaurants - UPDATED to fix issues
@router.get("/search", response_model=List[dict])
def search_restaurants(
    date: Optional[str] = None,
    time: Optional[str] = None,
    people: Optional[int] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    zip_code: Optional[str] = None,
    cuisine: Optional[str] = None,
    db: Session = Depends(get_db)
):
    # Debug logging
    print(f"Search params: date={date}, time={time}, people={people}, city={city}, state={state}, zip_code={zip_code}")
    
    query = db.query(models.Restaurant)

    # Apply filters only if they are provided and not empty
    if city and city.strip():
        query = query.filter(models.Restaurant.city.ilike(f"%{city}%"))
    if state and state.strip():
        query = query.filter(models.Restaurant.state.ilike(f"%{state}%"))
    if zip_code and zip_code.strip():
        query = query.filter(models.Restaurant.zip_code == zip_code)
    if cuisine and cuisine.strip():
        query = query.filter(models.Restaurant.cuisine.ilike(f"%{cuisine}%"))

    restaurants = query.all()
    
    # Debug logging
    print(f"Found {len(restaurants)} restaurants")
    
    # Return empty list instead of raising 404 error
    if not restaurants:
        return []

    return [
        {
            "id": r.id,  # Include the restaurant ID
            "name": r.name,
            "cuisine": r.cuisine,
            "cost_rating": r.cost_rating,
            "city": r.city,
            "state": r.state,
            "zip_code": r.zip_code,  # Include zip_code
            "rating": r.rating,
            "total_bookings": r.total_bookings,
            "reviews": r.reviews,
            "maps_url": f"https://www.google.com/maps/search/?api=1&query={'+'.join(r.name.split())}+{r.zip_code}+{'+'.join(r.city.split())}+{r.state}"
        }
        for r in restaurants
    ]

# ➕ Add new restaurant
@router.post("/add")
def add_restaurant(
    restaurant: RestaurantCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "RestaurantManager":
        raise HTTPException(status_code=403, detail="Only RestaurantManagers can add restaurants.")

    new_restaurant = models.Restaurant(
        name=restaurant.name,
        cuisine=restaurant.cuisine,
        cost_rating=restaurant.cost_rating,
        city=restaurant.city,
        state=restaurant.state,
        zip_code=restaurant.zip_code,
        rating=restaurant.rating,
        total_bookings=0
    )

    db.add(new_restaurant)
    db.commit()
    db.refresh(new_restaurant)

    return {"message": "Restaurant added successfully", "restaurant_id": new_restaurant.id}

#  Search availability
@router.get("/availability")
def search_availability(
    date: str,
    time: str,
    people: int,
    city: Optional[str] = None,
    state: Optional[str] = None,
    zip_code: Optional[str] = None,
    db: Session = Depends(get_db)
):
    try:
        target_time = datetime.strptime(time, "%H:%M").time()
        date_obj = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date/time format")

    start_time = (datetime.combine(date_obj, target_time) - timedelta(minutes=30)).time()
    end_time = (datetime.combine(date_obj, target_time) + timedelta(minutes=30)).time()

    restaurant_query = db.query(models.Restaurant)
    if city:
        restaurant_query = restaurant_query.filter(models.Restaurant.city.ilike(f"%{city}%"))
    if state:
        restaurant_query = restaurant_query.filter(models.Restaurant.state.ilike(f"%{state}%"))
    if zip_code:
        restaurant_query = restaurant_query.filter(models.Restaurant.zip_code == zip_code)

    matching_restaurants = []

    for restaurant in restaurant_query.all():
        bookings_count = db.query(models.Reservation).filter(
        models.Reservation.restaurant_id == restaurant.id,
        models.Reservation.date == date
        ).count()
        reviews = db.query(models.Review).filter(models.Review.restaurant_id == restaurant.id).all()

        for table in restaurant.tables:
            if table.size >= people:
                available_times = [t.strip() for t in table.available_times.split(",")]
                for t in available_times:
                    try:
                        t_obj = datetime.strptime(t, "%H:%M").time()
                        if start_time <= t_obj <= end_time:
                            matching_restaurants.append({
                                "restaurant_id": restaurant.id,
                                "reviews": reviews,
                                "restaurant_name": restaurant.name,
                                "table_id": table.id,
                                "available_time": t,
                                "city": restaurant.city,
                                "cuisine": restaurant.cuisine,
                                "cost_rating": restaurant.cost_rating,
                                "rating": restaurant.rating,
                                "total_bookings": bookings_count
                            })
                            break
                    except ValueError:
                        continue

    if not matching_restaurants:
        raise HTTPException(status_code=404, detail="No available restaurants found.")

    return matching_restaurants

# View reviews
@router.get("/{restaurant_id}/reviews")
def get_reviews(
    restaurant_id: int,
    db: Session = Depends(get_db)
):
    restaurant = db.query(models.Restaurant).filter(models.Restaurant.id == restaurant_id).first()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurant not found.")

    reviews = db.query(models.Review).filter(models.Review.restaurant_id == restaurant_id).all()

    return [
        {
            "review_id": r.id,
            "user_name": r.user.full_name,
            "rating": r.rating,
            "comment": r.comment,
            "date": r.created_at.strftime("%Y-%m-%d") if hasattr(r, 'created_at') else None
        }
        for r in reviews
    ]

#  View current user's reservations
@router.get("/my-reservations")
def get_my_reservations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    reservations = db.query(models.Reservation).filter(models.Reservation.user_id == current_user.id).all()
    return [
        {
            "reservation_id": r.id,
            "restaurant": r.restaurant.name,
            "date": r.date,
            "time": r.time.strftime("%H:%M"),
            "table_id": r.table_id,
            "number_of_people": r.number_of_people
        } for r in reservations
    ]

# Send confirmation email endpoint
@router.post("/api/send-confirmation-email")
async def email_confirmation(
    background_tasks: BackgroundTasks,
    reservation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Send booking confirmation email to user."""
    
    # Verify the reservation exists and belongs to the user
    reservation = db.query(models.Reservation).filter(
        models.Reservation.id == reservation_id,
        models.Reservation.user_id == current_user.id
    ).join(models.Restaurant).first()
    
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found or doesn't belong to you")
    
    # Get restaurant details
    restaurant = reservation.restaurant
    
    # Create booking details object
    booking_details = BookingConfirmationDetails(
        id=str(reservation.id),
        restaurant_name=restaurant.name,
        date=reservation.date.strftime("%A, %B %d, %Y"),
        time=reservation.time.strftime("%H:%M"),
        people=reservation.number_of_people,
        table_type=f"Table #{reservation.table_id}" if reservation.table_id else "Standard",
        address=f"{restaurant.city}, {restaurant.state} {restaurant.zip_code}",
        contact=restaurant.contact if hasattr(restaurant, 'contact') else None
    )
    
    # Send email in the background
    background_tasks.add_task(
        send_booking_confirmation, 
        current_user.email, 
        booking_details
    )
    
    return {"message": "Confirmation email will be sent shortly"}

#  Get today's bookings count for a restaurant
@router.get("/{restaurant_id}/bookings/today")
def get_today_bookings_count(
    restaurant_id: int,
    db: Session = Depends(get_db)
):
    # Get today's date
    today = datetime.now().date()
    
    # Query the database for bookings made today for this restaurant
    bookings_count = db.query(models.Reservation).filter(
        models.Reservation.restaurant_id == restaurant_id,
        models.Reservation.date == today
    ).count()
    
    return {"count": bookings_count}

#  Book table + prevent overlaps + send email - COMPLETELY REWRITTEN FOR DEBUGGING
@router.post("/{restaurant_id}/book")
def book_table(
    restaurant_id: int,
    reservation: ReservationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    print("\n==== BOOKING REQUEST ====")
    print(f"User: {current_user.id} - {current_user.email}")
    print(f"Restaurant: {restaurant_id}")
    print(f"Table: {reservation.table_id}")
    print(f"Date: {reservation.date} (type: {type(reservation.date).__name__})")
    print(f"Time: {reservation.time} (type: {type(reservation.time).__name__})")
    print(f"People: {reservation.number_of_people}")
    
    try:
        if current_user.role != "Customer":
            print(f"User role is {current_user.role}, not Customer")
            raise HTTPException(status_code=403, detail="Only customers can book tables.")

        # Check if restaurant exists
        restaurant = db.query(models.Restaurant).filter(models.Restaurant.id == restaurant_id).first()
        if not restaurant:
            print(f"Restaurant with ID {restaurant_id} not found")
            raise HTTPException(status_code=404, detail="Restaurant not found.")

        # Check if table exists and belongs to the restaurant
        table = db.query(models.Table).filter(
            models.Table.id == reservation.table_id,
            models.Table.restaurant_id == restaurant_id
        ).first()
        if not table:
            print(f"Table with ID {reservation.table_id} not found for restaurant {restaurant_id}")
            raise HTTPException(status_code=404, detail="Table not found for this restaurant.")

        # Convert time to proper format if it's a string
        reservation_time = None
        if isinstance(reservation.time, str):
            try:
                # Try parsing in HH:MM format
                hour, minute = map(int, reservation.time.split(':'))
                reservation_time = datetime.time(hour, minute)
                print(f"Successfully parsed time string to time object: {reservation_time}")
            except ValueError as e:
                print(f"Error parsing time: {str(e)}")
                # Try other common formats
                try:
                    reservation_time = datetime.strptime(reservation.time, "%H:%M:%S").time()
                    print(f"Successfully parsed time using H:M:S format: {reservation_time}")
                except ValueError:
                    try:
                        # Try AM/PM format - FIX: Use the imported datetime module
                        time_parts = reservation.time.split(' ')
                        if len(time_parts) == 2:
                            time_str, period = time_parts
                            hour, minute = map(int, time_str.split(':'))
                            if period.upper() == 'PM' and hour < 12:
                                hour += 12
                            elif period.upper() == 'AM' and hour == 12:
                                hour = 0
                            reservation_time = datetime.time(hour, minute)
                            print(f"Successfully parsed AM/PM time: {reservation_time}")
                        else:
                            raise ValueError("Could not parse time format")
                    except Exception:
                        print(f"Could not parse time in any format: {reservation.time}")
                        raise HTTPException(status_code=400, detail=f"Invalid time format: {reservation.time}")
        else:
            reservation_time = reservation.time

        # Check if selected time is in table's available_times
        available_times = [t.strip() for t in table.available_times.split(",")]
        reservation_time_str = reservation_time.strftime("%H:%M") if hasattr(reservation_time, "strftime") else reservation_time
        print(f"Checking availability for time {reservation_time_str} in available times: {available_times}")
        
        if reservation_time_str not in available_times:
            print(f"Time {reservation_time_str} not available for table {table.id}")
            raise HTTPException(status_code=400, detail="Selected time not available for this table.")

        #  Prevent overlapping reservations (1 hour block)
        if isinstance(reservation.date, str):
            try:
                reservation_date = datetime.strptime(reservation.date, "%Y-%m-%d").date()
                print(f"Parsed date string to date object: {reservation_date}")
            except ValueError:
                print(f"Invalid date format: {reservation.date}")
                raise HTTPException(status_code=400, detail=f"Invalid date format: {reservation.date}")
        else:
            reservation_date = reservation.date
            
        start_time = datetime.combine(reservation_date, reservation_time)
        end_time = start_time + timedelta(hours=1)

        print(f"Checking for conflicts between {start_time.time()} and {end_time.time()}")
        conflict = db.query(models.Reservation).filter(
            models.Reservation.table_id == reservation.table_id,
            models.Reservation.date == reservation_date,
            models.Reservation.time.between(
                start_time.time(),
                (end_time - timedelta(minutes=1)).time()
            )
        ).first()

        if conflict:
            print(f"Reservation conflict detected for table {table.id} at {reservation_time_str}")
            raise HTTPException(
                status_code=400,
                detail="This table is already reserved within the selected time window. Please choose another time."
            )

        # All good – proceed with booking
        try:
            new_reservation = models.Reservation(
                user_id=current_user.id,
                restaurant_id=restaurant_id,
                table_id=reservation.table_id,
                date=reservation_date,
                time=start_time.time(),  # Use the properly formatted time
                number_of_people=reservation.number_of_people
            )
            
            print(f"Creating new reservation: {vars(new_reservation)}")
            
            # Add the reservation to the session
            db.add(new_reservation)
            print("Added to session")
            
            # Explicitly flush to detect any database errors before commit
            db.flush()
            print("Flush successful")
            
            # Commit the transaction to persist the reservation
            db.commit()
            print("Commit successful")
            
            # Refresh to get the ID
            db.refresh(new_reservation)
            print(f"New reservation created with ID: {new_reservation.id}")
            
            # Verify the reservation is now in the database
            check_reservation = db.query(models.Reservation).get(new_reservation.id)
            print(f"Verified reservation in DB: {check_reservation is not None}")
            
            # Increment the total_bookings count for the restaurant
            restaurant.total_bookings += 1
            db.commit()
            print("Restaurant total_bookings incremented")

            # Send confirmation email with new structure
            try:
                booking_details = BookingConfirmationDetails(
                    id=str(new_reservation.id),
                    restaurant_name=restaurant.name,
                    date=reservation_date.strftime("%A, %B %d, %Y"),
                    time=reservation_time_str,
                    people=reservation.number_of_people,
                    table_type=f"Table #{reservation.table_id}",
                    address=f"{restaurant.city}, {restaurant.state} {restaurant.zip_code}",
                    contact=restaurant.contact if hasattr(restaurant, 'contact') else None
                )
                
                # Send confirmation email
                send_booking_confirmation(
                    to_email=current_user.email,
                    booking_details=booking_details
                )
                print(f"Confirmation email sent to {current_user.email}")
            except Exception as email_error:
                # Log the error but don't fail the reservation if email sending fails
                print(f"Failed to send confirmation email: {str(email_error)}")

            print("==== BOOKING COMPLETED SUCCESSFULLY ====")
            return {"message": "Table booked successfully!", "reservation_id": new_reservation.id}
        
        except Exception as db_error:
            print(f"DATABASE ERROR during reservation creation: {str(db_error)}")
            import traceback
            traceback.print_exc()
            db.rollback()
            raise HTTPException(status_code=500, detail=f"Database error: {str(db_error)}")
    
    except Exception as e:
        print(f"OVERALL ERROR in book_table: {str(e)}")
        import traceback
        traceback.print_exc()
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create reservation: {str(e)}")

# Cancel a booking (only by the user who made it)
@router.delete("/cancel/{reservation_id}")
def cancel_booking(
    reservation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "Customer":
        raise HTTPException(status_code=403, detail="Only customers can cancel bookings.")

    reservation = db.query(models.Reservation).filter(models.Reservation.id == reservation_id).first()

    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found.")

    if reservation.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only cancel your own reservations.")

    # Decrement the restaurant's total_bookings count if the reservation is for today or in the future
    today = datetime.now().date()
    if reservation.date >= today:
        restaurant = db.query(models.Restaurant).filter(models.Restaurant.id == reservation.restaurant_id).first()
        if restaurant and restaurant.total_bookings > 0:
            restaurant.total_bookings -= 1

    db.delete(reservation)
    db.commit()

    return {"message": "Reservation cancelled successfully."}

# Add review endpoint
@router.post("/{restaurant_id}/reviews")
def add_review(
    restaurant_id: int,
    rating: int,
    comment: str = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if current_user.role != "Customer":
        raise HTTPException(status_code=403, detail="Only customers can add reviews.")
    
    restaurant = db.query(models.Restaurant).filter(models.Restaurant.id == restaurant_id).first()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurant not found.")
    
    # Check if user has already reviewed this restaurant
    existing_review = db.query(models.Review).filter(
        models.Review.user_id == current_user.id,
        models.Review.restaurant_id == restaurant_id
    ).first()
    
    if existing_review:
        raise HTTPException(status_code=400, detail="You have already reviewed this restaurant.")
    
    # Create new review
    new_review = models.Review(
        user_id=current_user.id,
        restaurant_id=restaurant_id,
        rating=rating,
        comment=comment,
        created_at=datetime.now()
    )
    
    db.add(new_review)
    db.commit()
    db.refresh(new_review)
    
    # Update restaurant rating
    all_reviews = db.query(models.Review).filter(
        models.Review.restaurant_id == restaurant_id
    ).all()
    
    total_rating = sum(review.rating for review in all_reviews)
    avg_rating = total_rating / len(all_reviews)
    
    restaurant.rating = round(avg_rating, 1)
    db.commit()
    
    return {"message": "Review added successfully"}

@router.get("/{restaurant_id}")
def get_restaurant_details(
    restaurant_id: int,
    db: Session = Depends(get_db)
):
    restaurant = db.query(models.Restaurant).filter(models.Restaurant.id == restaurant_id).first()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurant not found.")

    return {
        "id": restaurant.id,
        "name": restaurant.name,
        "cuisine": restaurant.cuisine,
        "cost_rating": restaurant.cost_rating,
        "city": restaurant.city,
        "state": restaurant.state,
        "zip_code": restaurant.zip_code,
        "rating": restaurant.rating,
        "contact": restaurant.contact if hasattr(restaurant, 'contact') else None,
        "address": f"{restaurant.city}, {restaurant.state} {restaurant.zip_code}"
    }