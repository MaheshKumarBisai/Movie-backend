from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime, timedelta, date, timezone

# IST timezone offset (UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))

from core.database import get_db
from api import deps
from models.user import User
from models.theatre import Theatre
from models.screen import Screen
from models.seat import Seat
from models.movie import Movie
from models.booking import Booking, BookingSeat
from models.show import Show

router = APIRouter(prefix="/merchant", tags=["Merchant"])

class MovieCreate(BaseModel):
    title: str
    language: str
    duration_minutes: int
    description: Optional[str] = None
    cast_members: Optional[str] = None
    poster_url: Optional[str] = None
    status: Optional[str] = "ACTIVE"
    release_date: Optional[str] = None # Added release_date

class BatchShowCreate(BaseModel):
    movie_id: int
    screen_id: int
    dates: List[datetime]
    times: List[str]
    price: float
    language: Optional[str] = None

@router.get("/movies")
def get_merchant_movies(
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(get_db)
):
    """Return only movies created by the current merchant."""
    if not current_user.is_merchant:
        raise HTTPException(status_code=403, detail="You are a user, can't be merchant")
    movies = db.query(Movie).filter(Movie.created_by == current_user.id).all()
    return movies

@router.post("/movies")
def create_movie(
    payload: MovieCreate,
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(get_db)
):
    if not current_user.is_merchant:
         raise HTTPException(status_code=403, detail="You are a user, can't be merchant")

    # Validate release date if provided
    release_date_val = getattr(payload, "release_date", None)
    if payload.status == "COMING_SOON" and release_date_val:
        try:
            rd = datetime.strptime(release_date_val, "%Y-%m-%d").date()
            if rd < date.today():
                raise HTTPException(status_code=400, detail="Release date must be present or in the future, not past.")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    movie = Movie(
        title=payload.title,
        language=payload.language,
        duration_minutes=payload.duration_minutes,
        description=payload.description,
        cast_members=payload.cast_members,
        poster_url=payload.poster_url,
        status=payload.status,
        release_date=release_date_val,
        created_by=current_user.id
    )
    db.add(movie)
    db.commit()
    db.refresh(movie)
    return movie

@router.put("/movies/{movie_id}")
def update_movie(
    movie_id: int,
    payload: MovieCreate,
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(get_db)
):
    if not current_user.is_merchant:
         raise HTTPException(status_code=403, detail="You are a user, can't be merchant")

    movie = db.query(Movie).filter(Movie.id == movie_id, Movie.created_by == current_user.id).first()
    if not movie:
        raise HTTPException(status_code=404, detail="Movie not found or access denied")
        
    # Validate release date if provided
    release_date_val = getattr(payload, "release_date", None)
    if payload.status == "COMING_SOON" and release_date_val:
        try:
            rd = datetime.strptime(release_date_val, "%Y-%m-%d").date()
            if rd < date.today():
                raise HTTPException(status_code=400, detail="Release date must be present or in the future, not past.")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    movie.title = payload.title
    movie.language = payload.language
    movie.duration_minutes = payload.duration_minutes
    movie.description = payload.description
    movie.cast_members = payload.cast_members
    movie.poster_url = getattr(payload, "poster_url", None)
    movie.status = payload.status
    movie.release_date = release_date_val
    
    db.commit()
    db.refresh(movie)
    return movie

@router.delete("/movies/{movie_id}/shows")
def delete_movie_shows(
    movie_id: int,
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(get_db)
):
    if not current_user.is_merchant:
         raise HTTPException(status_code=403, detail="You are a user, can't be merchant")

    # Delete all shows for this movie that belong to merchant's screens
    merchant_screens = (
        db.query(Screen.id)
        .join(Theatre, Screen.theatre_id == Theatre.id)
        .filter(Theatre.owner_id == current_user.id)
        .subquery()
    )
    
    deleted = (
        db.query(Show)
        .filter(Show.movie_id == movie_id, Show.screen_id.in_(db.query(merchant_screens)))
        .delete(synchronize_session='fetch')
    )
    
    db.commit()
    return {"message": f"Deleted {deleted} shows for movie {movie_id}"}

@router.delete("/movies/{movie_id}")
def delete_movie(
    movie_id: int,
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(get_db)
):
    if not current_user.is_merchant:
         raise HTTPException(status_code=403, detail="You are a user, can't be merchant")

    movie = db.query(Movie).filter(Movie.id == movie_id, Movie.created_by == current_user.id).first()
    if not movie:
        raise HTTPException(status_code=404, detail="Movie not found or access denied")
        
    # Check for active shows to prevent breaking FKs (basic check)
    # Ideally we should check if there are Future shows.
    # For now, let's try delete and catch integrity error if needed, 
    # but a pre-check is better UX.
    
    active_shows = db.query(Show).filter(Show.movie_id == movie_id).count()
    if active_shows > 0:
         raise HTTPException(status_code=400, detail="Cannot delete movie with associated shows. Delete the shows first.")

    db.delete(movie)
    db.commit()
    return {"message": "Movie deleted successfully"}

@router.post("/shows/batch")
def batch_create_shows(
    payload: BatchShowCreate,
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(get_db)
):
    if not current_user.is_merchant:
         raise HTTPException(status_code=403, detail="You are a user, can't be merchant")

    # Verify screen ownership
    screen = db.query(Screen).join(Theatre).filter(
        Screen.id == payload.screen_id,
        Theatre.owner_id == current_user.id
    ).first()
    
    if not screen:
        raise HTTPException(status_code=404, detail="Screen not found or access denied")

    created_shows = []
    
    for date_obj in payload.dates:
        base_date = date_obj.date()
        
        # 1. Delete all existing shows for this movie + screen on this specific date
        # This ensures we don't pile up duplicates or hold onto old prices/times.
        db.query(Show).filter(
            Show.movie_id == payload.movie_id,
            Show.screen_id == payload.screen_id,
            func.date(Show.show_time) == base_date
        ).delete(synchronize_session=False)

        for time_str in payload.times:
            try:
                hours, minutes = map(int, time_str.split(':'))
                show_time = datetime.combine(base_date, datetime.min.time().replace(hour=hours, minute=minutes, tzinfo=IST))
                
                show = Show(
                    movie_id=payload.movie_id,
                    screen_id=payload.screen_id,
                    show_time=show_time,
                    price=payload.price,
                    language=payload.language
                )
                db.add(show)
                created_shows.append(show)     
            except ValueError:
                continue

    db.commit()
    return {"count": len(created_shows), "message": "Shows created successfully"}

# --- Schemas ---

class DashboardStats(BaseModel):
    revenue_today: float
    tickets_sold_today: int
    occupancy_percentage: float
    active_movies_count: int
    sales_trend: List[float] # Last 7 days

class TheatreCreate(BaseModel):
    name: str
    city: str
    image_url: Optional[str] = None

class ScreenCreate(BaseModel):
    theatre_id: int
    name: str
    technology: Optional[str] = None
    rows: int
    cols: int
    blocked_seats: List[str] = [] # List of seat numbers like "A1", "B2" to block

class ShowCreate(BaseModel):
    price: float

class CheckInRequest(BaseModel):
    booking_id: int

# --- Endpoints ---

@router.get("/dashboard/stats", response_model=DashboardStats)
def get_dashboard_stats(
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(get_db)
):
    if not current_user.is_merchant:
        raise HTTPException(status_code=403, detail="You are a user, can't be merchant")

    # Get merchant's theatres
    theatres = db.query(Theatre).filter(Theatre.owner_id == current_user.id).all()
    theatre_ids = [t.id for t in theatres]
    
    if not theatre_ids:
        return DashboardStats(
            revenue_today=0.0,
            tickets_sold_today=0,
            occupancy_percentage=0.0,
            active_movies_count=0,
            sales_trend=[0.0]*7
        )

    # Filter shows for these theatres
    screens = db.query(Screen).filter(Screen.theatre_id.in_(theatre_ids)).all()
    screen_ids = [s.id for s in screens]
    
    # Today's Revenue & Tickets
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    
    # Find bookings for shows on these screens today
    # Join Booking -> Show -> Screen
    today_bookings = (
        db.query(Booking)
        .join(Show, Booking.show_id == Show.id)
        .filter(
            Show.screen_id.in_(screen_ids),
            Booking.created_at >= today_start,
            Booking.created_at < today_end,
            Booking.status.in_(["CONFIRMED", "CHECKED_IN"])
        )
        .all()
    )
    
    revenue_today = sum(b.total_amount for b in today_bookings)
    
    # Count tickets (BookingSeat)
    booking_ids = [b.id for b in today_bookings]
    tickets_sold_today = db.query(BookingSeat).filter(BookingSeat.booking_id.in_(booking_ids)).count() if booking_ids else 0

    # Active Movies Count
    # Count distinct movies showing today in merchant's screens
    active_movies_count = (
        db.query(Show.movie_id)
        .filter(
            Show.screen_id.in_(screen_ids),
            Show.show_time >= today_start,
            Show.show_time < today_end
        )
        .distinct()
        .count()
    )
    
    # Occupancy
    # Total seats in active shows
    # We need to sum the total_seats of the screen for each show
    active_shows = (
         db.query(Show)
        .filter(
            Show.screen_id.in_(screen_ids),
            Show.show_time >= today_start,
            Show.show_time < today_end
        )
        .all()
    )
    
    total_capacity = 0
    for show in active_shows:
        # Find screen capacity
        screen = next((s for s in screens if s.id == show.screen_id), None)
        if screen:
            total_capacity += screen.total_seats
            
    occupancy_percentage = (tickets_sold_today / total_capacity * 100) if total_capacity > 0 else 0.0

    # Sales Trend (Last 7 days)
    sales_trend = []
    for i in range(6, -1, -1):
        day_start = today_start - timedelta(days=i)
        day_end = day_start + timedelta(days=1)
        
        day_revenue = (
            db.query(func.sum(Booking.total_amount))
            .join(Show, Booking.show_id == Show.id)
            .filter(
                Show.screen_id.in_(screen_ids),
                Booking.created_at >= day_start,
                Booking.created_at < day_end,
                Booking.status.in_(["CONFIRMED", "CHECKED_IN"])
            )
            .scalar()
        )
        sales_trend.append(day_revenue or 0.0)

    return DashboardStats(
        revenue_today=revenue_today,
        tickets_sold_today=tickets_sold_today,
        occupancy_percentage=round(occupancy_percentage, 1),
        active_movies_count=active_movies_count,
        sales_trend=sales_trend
    )

class TheatreResponse(BaseModel):
    id: int
    name: str
    city: str
    image_url: Optional[str]

@router.get("/theatres", response_model=List[TheatreResponse])
def get_theatres(
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(get_db)
):
    if not current_user.is_merchant:
         raise HTTPException(status_code=403, detail="You are a user, can't be merchant")

    theatres = db.query(Theatre).filter(Theatre.owner_id == current_user.id).all()
    
    return [
        TheatreResponse(
            id=t.id,
            name=t.name,
            city=t.city,
            image_url=t.image_url
        ) for t in theatres
    ]

@router.post("/theatres")
def create_theatre(
    payload: TheatreCreate,
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(get_db)
):
    if not current_user.is_merchant:
         raise HTTPException(status_code=403, detail="You are a user, can't be merchant")

    theatre = Theatre(
        name=payload.name.strip(),
        city=payload.city.strip().title(),
        owner_id=current_user.id,
        image_url=payload.image_url
    )
    db.add(theatre)
    db.commit()
    db.refresh(theatre)
    return theatre

@router.put("/theatres/{theatre_id}")
def update_theatre(
    theatre_id: int,
    payload: TheatreCreate,
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(get_db)
):
    if not current_user.is_merchant:
        raise HTTPException(status_code=403, detail="You are a user, can't be merchant")

    theatre = db.query(Theatre).filter(
        Theatre.id == theatre_id,
        Theatre.owner_id == current_user.id
    ).first()
    if not theatre:
        raise HTTPException(status_code=404, detail="Theatre not found or access denied")

    theatre.name = payload.name.strip()
    theatre.city = payload.city.strip().title()
    if payload.image_url is not None:
        theatre.image_url = payload.image_url

    db.commit()
    db.refresh(theatre)
    return theatre

@router.delete("/theatres/{theatre_id}")
def delete_theatre(
    theatre_id: int,
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(get_db)
):
    if not current_user.is_merchant:
        raise HTTPException(status_code=403, detail="You are a user, can't be merchant")

    theatre = db.query(Theatre).filter(
        Theatre.id == theatre_id,
        Theatre.owner_id == current_user.id
    ).first()
    if not theatre:
        raise HTTPException(status_code=404, detail="Theatre not found or access denied")

    # Get all screens for this theatre
    screens = db.query(Screen).filter(Screen.theatre_id == theatre_id).all()
    screen_ids = [s.id for s in screens]

    if screen_ids:
        # Check for bookings on future shows in these screens
        now = datetime.now()
        future_shows_with_bookings = (
            db.query(Show)
            .join(Booking, Booking.show_id == Show.id)
            .filter(
                Show.screen_id.in_(screen_ids),
                Show.show_time >= now,
                Booking.status.in_(["CONFIRMED", "LOCKED", "CHECKED_IN"])
            )
            .count()
        )

        if future_shows_with_bookings > 0:
            raise HTTPException(
                status_code=400,
                detail="Cannot delete theatre with active bookings on upcoming shows. Cancel the bookings first."
            )

        # Delete seats for all screens
        db.query(Seat).filter(Seat.screen_id.in_(screen_ids)).delete(synchronize_session=False)

        # Delete booking_seats for shows in these screens
        show_ids = [s.id for s in db.query(Show).filter(Show.screen_id.in_(screen_ids)).all()]
        if show_ids:
            booking_ids = [b.id for b in db.query(Booking).filter(Booking.show_id.in_(show_ids)).all()]
            if booking_ids:
                db.query(BookingSeat).filter(BookingSeat.booking_id.in_(booking_ids)).delete(synchronize_session=False)
                db.query(Booking).filter(Booking.id.in_(booking_ids)).delete(synchronize_session=False)
            db.query(Show).filter(Show.id.in_(show_ids)).delete(synchronize_session=False)

        # Delete screens
        db.query(Screen).filter(Screen.theatre_id == theatre_id).delete(synchronize_session=False)

    db.delete(theatre)
    db.commit()
    return {"message": "Theatre deleted successfully"}

@router.post("/screens")
def create_screen(
    payload: ScreenCreate,
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(get_db)
):
    if not current_user.is_merchant:
         raise HTTPException(status_code=403, detail="You are a user, can't be merchant")
         
    # Verify theatre ownership
    theatre = db.query(Theatre).filter(Theatre.id == payload.theatre_id, Theatre.owner_id == current_user.id).first()
    if not theatre:
        raise HTTPException(status_code=404, detail="Theatre not found or access denied")

    total_seats = payload.rows * payload.cols
    
    screen = Screen(
        theatre_id=payload.theatre_id,
        name=payload.name,
        technology=payload.technology,
        total_seats=total_seats
    )
    db.add(screen)
    db.commit()
    db.refresh(screen)
    
    # Generate Seats
    seats = []
    import string
    alphabet = string.ascii_uppercase # A-Z
    
    for r in range(payload.rows):
        row_char = alphabet[r] if r < 26 else f"R{r+1}"
        for c in range(1, payload.cols + 1):
            seat_num = f"{row_char}{c}"
            
                
            # Determine Seat Type
            seat_type = "REGULAR"
            # Logic: Front 2 rows Regular, Middle Premium, Last 1-2 Recliner (if rows sufficient)
            
            if payload.rows <= 3:
                # Small screen
                if r == payload.rows - 1:
                    seat_type = "PREMIUM"
            else:
                # Larger screen
                if r == payload.rows - 1:
                    seat_type = "RECLINER"
                elif r >= 2 and r < payload.rows - 1:
                    seat_type = "PREMIUM"
            
            # blocked?
            is_blocked = seat_num in payload.blocked_seats
            
            seat = Seat(
                screen_id=screen.id,
                seat_number=seat_num,
                row=row_char,
                col=c,
                seat_type=seat_type, 
                is_blocked=is_blocked,
                price=0.0 # Price modifiers logic handled in booking/show
            )
            seats.append(seat)
            
    db.add_all(seats)
    db.commit()
    
    return screen

class ScreenResponse(BaseModel):
    id: int
    name: str
    theatre_name: str
    technology: Optional[str]

@router.get("/screens", response_model=List[ScreenResponse])
def get_screens(
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(get_db)
):
    if not current_user.is_merchant:
         raise HTTPException(status_code=403, detail="You are a user, can't be merchant")

    # Get merchant's ALL screens across all theatres
    screens = (
        db.query(Screen)
        .join(Theatre, Screen.theatre_id == Theatre.id)
        .filter(Theatre.owner_id == current_user.id)
        .all()
    )
    
    return [
        ScreenResponse(
            id=s.id,
            name=s.name,
            theatre_name=s.theatre.name, # Accessed via relationship? Need to check Theatre model
            technology=s.technology
        ) 
        for s in screens
    ]

@router.post("/shows")
def create_show(
    payload: ShowCreate,
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(get_db)
):
    if not current_user.is_merchant:
         raise HTTPException(status_code=403, detail="You are a user, can't be merchant")
         
    # Verify screen ownership logic... omitted for brevity but should limit to merchant's screens
    
    show = Show(
        movie_id=payload.movie_id,
        screen_id=payload.screen_id,
        show_time=payload.start_time,
        price=payload.price
    )
    db.add(show)
    db.commit()
    db.refresh(show)
    return show

@router.post("/bookings/check-in")
def check_in_booking(
    payload: CheckInRequest,
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(get_db)
):
    if not current_user.is_merchant:
         raise HTTPException(status_code=403, detail="You are a user, can't be merchant")

    booking = db.query(Booking).filter(Booking.id == payload.booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    if booking.status != "CONFIRMED":
        raise HTTPException(status_code=400, detail=f"Booking is in {booking.status} status")

    # Verify merchant ownership of the show/theatre
    # Join Booking -> Show -> Screen -> Theatre
    theatre = (
        db.query(Theatre)
        .join(Screen, Screen.theatre_id == Theatre.id)
        .join(Show, Show.screen_id == Screen.id)
        .filter(Show.id == booking.show_id, Theatre.owner_id == current_user.id)
        .first()
    )

    if not theatre:
        raise HTTPException(status_code=403, detail="Access denied: You do not own the theatre for this show")

    booking.status = "CHECKED_IN"
    db.commit()
    
    # Send Notification
    from services.notification_service import send_checkin_notification
    show_data = db.query(Movie.title).join(Show).filter(Show.id == booking.show_id).first()
    movie_title = show_data[0] if show_data else "Movie"

    send_checkin_notification(db, booking.user_id, booking.id, movie_title)

    return {"message": "Check-in successful", "booking_id": booking.id}

