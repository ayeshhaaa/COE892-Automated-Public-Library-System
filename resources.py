from fastapi import APIRouter, HTTPException, status, Query
from pydantic import BaseModel
from enum import Enum
from datetime import datetime
import aiosqlite

DATABASE = "Library.db"

# -------------------------------
# Enum for Media Type
# -------------------------------
class MediaType(str, Enum):
    EBOOK = "e-book"
    AUDIOBOOK = "audiobook"
    PHYSICAL = "physical"

# -------------------------------
# Pydantic Model for Book
# -------------------------------
class Book(BaseModel):
    title: str
    author: str
    genre: str
    media_type: MediaType
    available_copies: int = None
    image: str = None

# Create the FastAPI router
router = APIRouter(
    prefix="/api/books",
    tags=["Books"],
    responses={404: {"description": "Resource not found"}}
)

# -------------------------------
# Helper Functions to Interact with SQLite
# -------------------------------
async def get_db_connection():
    db = await aiosqlite.connect(DATABASE)
    return db

# -------------------------------
# API Endpoints
# -------------------------------

@router.post("/", 
            status_code=status.HTTP_201_CREATED,
            summary="Add new resource",
            response_description="Details of added/updated resource")
async def add_book(book: Book):
    """
    Handles resource creation/updates with smart defaults:
    - Sets available_copies=1 for physical books if not provided
    - Sets available_copies=9999 for digital items if not provided
    - Properly handles optional image field
    - Updates existing physical books by adding copies
    """
    try:
        # Connect to database
        async with await get_db_connection() as db:
            cursor = await db.execute("SELECT * FROM Books WHERE title = ? AND author = ? AND media_type = ?", 
                                       (book.title, book.author, book.media_type))
            existing = await cursor.fetchone()
            
            if existing:
                # Resource exists: handle the existing resource logic
                if book.media_type in [MediaType.EBOOK, MediaType.AUDIOBOOK]:
                    return {
                        "id": existing[0],
                        "message": "Digital resource already exists",
                        "available_copies": existing[4],
                        "image": existing[5]  # assuming image is in column 5
                    }

                # Physical resource: increment available copies
                increment = book.available_copies if book.available_copies else 1
                await db.execute("UPDATE Books SET available_copies = available_copies + ? WHERE id = ?", 
                                 (increment, existing[0]))
                await db.commit()

                # Return updated resource details
                cursor = await db.execute("SELECT * FROM Books WHERE id = ?", (existing[0],))
                updated = await cursor.fetchone()
                return {
                    "id": updated[0],
                    "message": f"Added {increment} copies to existing resource",
                    "new_total": updated[4],
                    "image": updated[5]
                }

            # New resource: insert into database
            available_copies = book.available_copies if book.available_copies else (9999 if book.media_type in [MediaType.EBOOK, MediaType.AUDIOBOOK] else 1)
            await db.execute("""
                INSERT INTO Books (title, author, genre, media_type, available_copies, image) 
                VALUES (?, ?, ?, ?, ?, ?)
            """, (book.title, book.author, book.genre, book.media_type, available_copies, book.image))
            await db.commit()

            return {
                "id": cursor.lastrowid,
                "message": "New resource added successfully",
                "current_copies": available_copies,
                "image": book.image
            }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database operation failed: {str(e)}"
        )


@router.get("/",
           summary="Search resources",
           response_description="List of matching resources")
async def search_books(
    title: str = Query(None, description="Partial title match"),
    author: str = Query(None, description="Partial author match"),
    genre: str = Query(None, description="Exact genre match"),
    media_type: MediaType = Query(None, description="Filter by format"),
    sort_by: str = Query("title", enum=["title", "author", "published_year"]),
    sort_order: str = Query("asc", enum=["asc", "desc"])
):
    """Search endpoint with filters and sorting"""
    try:
        query = []
        params = []

        if title:
            query.append("title LIKE ?")
            params.append(f"%{title}%")
        if author:
            query.append("author LIKE ?")
            params.append(f"%{author}%")
        if genre:
            query.append("genre = ?")
            params.append(genre)
        if media_type:
            query.append("media_type = ?")
            params.append(media_type)

        where_clause = " AND ".join(query) if query else "1=1"
        order_by = f"ORDER BY {sort_by} {sort_order.upper()}"

        async with await get_db_connection() as db:
            cursor = await db.execute(f"SELECT * FROM Books WHERE {where_clause} {order_by}", tuple(params))
            resources = await cursor.fetchall()
            return [{
                "id": row[0], 
                "title": row[1],
                "author": row[2],
                "genre": row[3],
                "media_type": row[4],
                "available_copies": row[5],
                "image": row[6]
            } for row in resources]

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search failed: {str(e)}"
        )