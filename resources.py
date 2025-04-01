from fastapi import APIRouter, HTTPException, status, Query
from pydantic import BaseModel
from enum import Enum
from datetime import datetime
import aiosqlite

DATABASE = "Library.db"

# -------------------------------
# Pydantic Model for Book
# -------------------------------
class Book(BaseModel):
    title: str
    author: str
    genre: str
    year: int 

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
    Handles resource creation/updates:
    - Checks for existing book by title and author.
    - If the book already exists, it does nothing since only one copy per book.
    - Inserts new book record.
    """
    try:
        # Connect to database
        async with await get_db_connection() as db:
            cursor = await db.execute("SELECT * FROM Books WHERE BookName = ? AND Author = ?", 
                                       (book.title, book.author))
            existing = await cursor.fetchone()

            if existing:
                return {
                    "id": existing[0],
                    "message": "Book already exists with the same title and author",
                    "book_name": existing[1],
                    "author": existing[2],
                    "genre": existing[3],
                    "year": existing[4]
                }

            # New resource: insert into database
            await db.execute(""" 
                INSERT INTO Books (BookName, Author, Genre, Year) 
                VALUES (?, ?, ?, ?) 
            """, (book.title, book.author, book.genre, book.year))
            await db.commit()

            return {
                "id": cursor.lastrowid,
                "message": "New book added successfully",
                "book_name": book.title,
                "author": book.author,
                "genre": book.genre,
                "year": book.year
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
    sort_by: str = Query("title", enum=["title", "author", "year"]),
    sort_order: str = Query("asc", enum=["asc", "desc"])
):
    """Search endpoint with filters and sorting"""
    try:
        query = []
        params = []

        if title:
            query.append("BookName LIKE ?")
            params.append(f"%{title}%")
        if author:
            query.append("Author LIKE ?")
            params.append(f"%{author}%")
        if genre:
            query.append("Genre = ?")
            params.append(genre)

        where_clause = " AND ".join(query) if query else "1=1"
        order_by = f"ORDER BY {sort_by} {sort_order.upper()}"

        async with await get_db_connection() as db:
            cursor = await db.execute(f"SELECT * FROM Books WHERE {where_clause} {order_by}", tuple(params))
            resources = await cursor.fetchall()
            return [{
                "id": row[0], 
                "book_name": row[1],
                "author": row[2],
                "genre": row[3],
                "year": row[4]
            } for row in resources]

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search failed: {str(e)}"
        )
