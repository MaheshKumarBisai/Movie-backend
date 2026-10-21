from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from typing import List

from core.database import get_db
from models.review import Review
from schemas.review import ReviewCreate, ReviewResponse
from api import deps
from models.user import User

router = APIRouter(prefix="/movies/{movie_id}/reviews", tags=["Reviews"])

@router.get("", response_model=List[ReviewResponse])
def get_movie_reviews(
    movie_id: int,
    db: Session = Depends(get_db)
):
    """Get all public reviews for a movie."""
    reviews = db.query(Review).options(joinedload(Review.user)).filter(Review.movie_id == movie_id).all()
    
    # Map to schema manually to include user_name safely
    return [
        ReviewResponse(
            id=r.id,
            user_id=r.user_id,
            user_name=r.user.name if r.user and r.user.name else "Anonymous",
            movie_id=r.movie_id,
            rating=r.rating,
            comment=r.comment,
            created_at=r.created_at
        )
        for r in reviews
    ]

@router.post("", response_model=ReviewResponse)
def create_review(
    movie_id: int,
    payload: ReviewCreate,
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(get_db)
):
    """Submit a review for a movie."""
    if payload.movie_id != movie_id:
        raise HTTPException(status_code=400, detail="Movie ID mismatch")
    
    # Optional: Check if user already reviewed
    existing = db.query(Review).filter(
        Review.movie_id == movie_id, 
        Review.user_id == current_user.id
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="You have already reviewed this movie")
    
    review = Review(
        user_id=current_user.id,
        movie_id=movie_id,
        rating=payload.rating,
        comment=payload.comment
    )
    
    db.add(review)
    db.commit()
    db.refresh(review)
    
    # Calculate new average rating for the movie
    from sqlalchemy.sql import func
    from models.movie import Movie
    
    avg_rating = db.query(func.avg(Review.rating)).filter(Review.movie_id == movie_id).scalar()
    
    # Update movie global rating
    movie = db.query(Movie).filter(Movie.id == movie_id).first()
    if movie and avg_rating is not None:
        movie.rating = round(avg_rating, 1)
        db.commit()
    
    return ReviewResponse(
        id=review.id,
        user_id=review.user_id,
        user_name=current_user.name or "Anonymous",
        movie_id=review.movie_id,
        rating=review.rating,
        comment=review.comment,
        created_at=review.created_at
    )


# Separate router for user-scoped review endpoints
my_reviews_router = APIRouter(prefix="/reviews", tags=["Reviews"])

@my_reviews_router.get("/me")
def get_my_reviews(
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(get_db)
):
    """Get all reviews by the current user."""
    from models.movie import Movie

    reviews = (
        db.query(Review, Movie)
        .join(Movie, Review.movie_id == Movie.id)
        .filter(Review.user_id == current_user.id)
        .order_by(Review.created_at.desc())
        .all()
    )

    return [
        {
            "id": r.id,
            "movie_id": r.movie_id,
            "movie_title": m.title,
            "poster_url": m.poster_url,
            "rating": r.rating,
            "comment": r.comment,
            "created_at": r.created_at.isoformat() if r.created_at else None
        }
        for r, m in reviews
    ]
