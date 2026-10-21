from pydantic import BaseModel
from typing import List, Optional

class MovieIdRequest(BaseModel):
    movie_id: int

class ShowIdRequest(BaseModel):
    show_id: int

class BookingIdRequest(BaseModel):
    booking_id: int

class ConfirmBookingRequest(BaseModel):
    booking_id: int
    seat_ids: List[int]

class CancelBookingRequest(BaseModel):
    booking_id: int
    seat_ids: Optional[List[int]] = []

