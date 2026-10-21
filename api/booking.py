from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import threading

from core.database import get_db, SessionLocal
from schemas.booking import BookingCreate, BookingResponse
from models.booking import Booking
from services.seat_lock import release_seats
from api import deps
from models.user import User

router = APIRouter(prefix="/booking", tags=["Booking"])


@router.post("", response_model=BookingResponse)
@router.post("/", response_model=BookingResponse, include_in_schema=False)
def create_booking(
    payload: BookingCreate,
    current_user: "User" = Depends(deps.get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a booking after seats are locked.
    """

    booking = Booking(
        show_id=payload.show_id,
        user_id=current_user.id,
        status="LOCKED",
        total_amount=0.0
    )

    db.add(booking)
    db.commit()
    db.refresh(booking)

    # Save the seats!
    from models.booking import BookingSeat
    for seat_id in payload.seat_ids:
        booking_seat = BookingSeat(
            booking_id=booking.id,
            seat_id=seat_id
        )
        db.add(booking_seat)
    
    db.commit()

    # Calculate Total Amount using dynamic logic (Show Base Price + Seat Category offset)
    from models.show import Show
    from models.seat import Seat
    
    show = db.query(Show).filter(Show.id == payload.show_id).first()
    seats = db.query(Seat).filter(Seat.id.in_(payload.seat_ids)).all()
    
    total_price = 0.0
    if show:
        base_price = float(show.price)
        for seat in seats:
            seat_price = base_price
            if seat.seat_type == "PREMIUM":
                seat_price += 100.0  # Must match the offset in seats.py
            elif seat.seat_type == "RECLINER":
                seat_price += 200.0  # Must match the offset in seats.py
            elif seat.seat_type == "REGULAR":
                seat_price += 1.0  # Must match the offset in seats.py! User changed this to 1.0 earlier
            total_price += seat_price
            
    booking.total_amount = total_price
    db.commit()

    return booking


from schemas.request import ConfirmBookingRequest, CancelBookingRequest

@router.post("/confirm")
def confirm_booking(
    payload: ConfirmBookingRequest,
    current_user: "User" = Depends(deps.get_current_user),
    db: Session = Depends(get_db)
):
    """
    Confirm booking after successful payment.
    """

    booking = db.query(Booking).filter(Booking.id == payload.booking_id).first()

    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    booking.status = "CONFIRMED"
    db.commit()

    # Release Redis locks
    release_seats(booking.show_id, payload.seat_ids)

    # Send Notification
    from services.notification_service import send_booking_confirmation
    from models.show import Show
    from models.movie import Movie
    
    show = db.query(Show).filter(Show.id == booking.show_id).first()
    movie_title = db.query(Movie.title).filter(Movie.id == show.movie_id).first()[0] if show else "Movie"
    
    send_booking_confirmation(db, booking.user_id, booking.id, movie_title)

    # Generate and Send PDF Ticket via Email (in background thread to not block response)
    try:
        if show:
            from services.ticket import generate_ticket_pdf
            from models.theatre import Theatre
            from models.screen import Screen
            
            theatre = db.query(Theatre.name).join(Screen).filter(Screen.id == show.screen_id).first()
            theatre_name = theatre[0] if theatre else "Cinema"
            
            # Get seat labels
            from models.booking import BookingSeat
            from models.seat import Seat
            booking_seats = db.query(Seat).join(BookingSeat, BookingSeat.seat_id == Seat.id).filter(BookingSeat.booking_id == booking.id).all()
            seat_labels = ", ".join([s.seat_number for s in booking_seats])
            
            pdf_path = generate_ticket_pdf(
                booking.id, 
                movie_title, 
                theatre_name, 
                show.show_time.strftime("%Y-%m-%d %H:%M"), 
                seat_labels, 
                booking.total_amount
            )
            
            user = db.query(User).filter(User.id == booking.user_id).first()
            if user and user.email:
                # Send email in background thread so it doesn't block the response
                def _send_email_bg(email: str, path: str, title: str):
                    try:
                        import smtplib
                        from email.mime.text import MIMEText
                        from email.mime.multipart import MIMEMultipart
                        from email.mime.application import MIMEApplication
                        import os
                        from core.config import settings
                        
                        if not settings.SMTP_USER or not settings.SMTP_PASS:
                            return
                        
                        msg = MIMEMultipart()
                        msg['From'] = settings.SMTP_FROM
                        msg['To'] = email
                        msg['Subject'] = f"Your Ticket for {title} - ShowGo"
                        body = f"<html><body><p>Your ticket for <b>{title}</b> is attached.</p></body></html>"
                        msg.attach(MIMEText(body, 'html'))
                        
                        with open(path, 'rb') as f:
                            part = MIMEApplication(f.read(), Name=os.path.basename(path))
                            part['Content-Disposition'] = f'attachment; filename="{os.path.basename(path)}"'
                            msg.attach(part)
                        
                        if settings.SMTP_PORT == 465:
                            server = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT)
                        else:
                            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10)
                            server.starttls()
                        server.login(settings.SMTP_USER, settings.SMTP_PASS)
                        server.send_message(msg)
                        server.quit()
                        print(f"Ticket email sent to {email}")
                    except Exception as ex:
                        print(f"Background email failed: {ex}")
                
                threading.Thread(target=_send_email_bg, args=(user.email, pdf_path, movie_title), daemon=True).start()
            
    except Exception as e:
        print(f"Failed to generate/send ticket: {e}")

    # Notify the merchant (theatre owner)
    from services.notification_service import send_merchant_booking_notification
    from models.screen import Screen
    from models.theatre import Theatre
    theatre_owner = (
        db.query(Theatre.owner_id)
        .join(Screen, Screen.theatre_id == Theatre.id)
        .join(Show, Show.screen_id == Screen.id)
        .filter(Show.id == booking.show_id)
        .first()
    )
    if theatre_owner:
        send_merchant_booking_notification(db, theatre_owner[0], booking.id, movie_title)

    return {
        "message": "Booking confirmed",
        "booking_id": booking.id
    }


from datetime import datetime, timedelta


@router.post("/cancel")
def cancel_booking(
    payload: CancelBookingRequest,
    current_user: "User" = Depends(deps.get_current_user),
    db: Session = Depends(get_db)
):
    """
    Cancel a booking if it's at least 1 hour before show time.
    """
    booking = db.query(Booking).filter(
        Booking.id == payload.booking_id,
        Booking.user_id == current_user.id
    ).first()

    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    if booking.status != "CONFIRMED":
        raise HTTPException(status_code=400, detail=f"Cannot cancel a booking with status: {booking.status}")

    # Check show time
    from models.show import Show
    show = db.query(Show).filter(Show.id == booking.show_id).first()

    if show:
        now = datetime.now()
        # Ensure comparison is naive to naive
        show_time_naive = show.show_time.replace(tzinfo=None)
        cutoff = show_time_naive - timedelta(hours=1)
        if now >= cutoff:
            raise HTTPException(
                status_code=400,
                detail="Sorry, cancellation window has passed. You can only cancel up to 1 hour before the show."
            )

    booking.status = "CANCELLED"
    db.commit()

    # Notify the merchant
    from services.notification_service import send_merchant_cancellation_notification
    from models.screen import Screen
    from models.theatre import Theatre
    from models.movie import Movie
    
    movie_title = db.query(Movie.title).join(Show, Show.movie_id == Movie.id).filter(Show.id == booking.show_id).first()
    theatre_owner = (
        db.query(Theatre.owner_id)
        .join(Screen, Screen.theatre_id == Theatre.id)
        .join(Show, Show.screen_id == Screen.id)
        .filter(Show.id == booking.show_id)
        .first()
    )
    if theatre_owner and movie_title:
        send_merchant_cancellation_notification(db, theatre_owner[0], booking.id, movie_title[0])

    # Release seats
    from models.booking import BookingSeat
    seat_ids = [bs.seat_id for bs in db.query(BookingSeat).filter(BookingSeat.booking_id == booking.id).all()]
    if seat_ids:
        release_seats(booking.show_id, seat_ids)

    return {
        "message": "Booking cancelled successfully",
        "booking_id": booking.id
    }


@router.get("/my-bookings", response_model=list[BookingResponse])
def get_my_bookings(
    current_user: "User" = Depends(deps.get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all bookings for the current user.
    """
    try:
        # Join Booking -> Show -> Movie, Screen
        from models.show import Show
        from models.movie import Movie
        from models.screen import Screen
        from models.theatre import Theatre
        
        from datetime import datetime, time
        now = datetime.now()
        today_start = datetime.combine(now.date(), time.min)
        
        results = db.query(Booking, Movie, Show, Screen, Theatre).outerjoin(
            Show, Booking.show_id == Show.id
        ).outerjoin(
            Movie, Show.movie_id == Movie.id
        ).outerjoin(
            Screen, Show.screen_id == Screen.id
        ).outerjoin(
            Theatre, Screen.theatre_id == Theatre.id
        ).filter(
            Booking.user_id == current_user.id,
            Show.id != None,
            Movie.id != None,
            Show.show_time >= today_start
        ).order_by(Show.show_time.asc()).all()
        
        response = []
        for booking, movie, show, screen, theatre in results:
            # Convert to Pydantic model and enrich
            booking_data = BookingResponse.from_orm(booking)
            booking_data.movie_id = movie.id if movie else None
            booking_data.movie_title = movie.title if movie else "Unknown Movie"
            booking_data.theater_name = theatre.name if theatre else (screen.name if screen else "Unknown Theater")
            booking_data.show_time = show.show_time.isoformat() if show else None
            booking_data.poster_url = movie.poster_url if movie else None
            booking_data.screen_name = screen.name if screen else "N/A"
            
            # Fetch seats for this booking
            from models.booking import BookingSeat
            from models.seat import Seat
            booking_seats = db.query(Seat).join(BookingSeat, BookingSeat.seat_id == Seat.id).filter(BookingSeat.booking_id == booking.id).all()
            booking_data.seat_label = ", ".join([s.seat_number for s in booking_seats])
            
            response.append(booking_data)
            
        return response
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
