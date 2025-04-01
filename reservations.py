import aiosqlite
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import List, Optional

DATABASE = "Library.db"

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------
# Pydantic Models
# -------------------------------

class BorrowRequest(BaseModel):
    user_id: int
    book_id: int

class ReturnRequest(BaseModel):
    user_id: int
    book_id: int

class RenewRequest(BaseModel):
    user_id: int
    book_id: int

class LoginRequest(BaseModel):
    username: str
    password: str
    
class AddBookRequest(BaseModel):
    book_name: str
    author: str
    genre: str
    year: int

class UserRequest(BaseModel):
    username: str
    password: str

class RegisterRequest(BaseModel):
    username: str
    password: str

class ReviewResponse(BaseModel):
    rating_id: int
    user_id: int
    username: str
    book_id: int
    rating: float

class AddReviewRequest(BaseModel):
    user_id: int
    book_id: int
    rating: float

class RecommendationRequest(BaseModel):
    user_id: int
    genre: Optional[str] = None
    limit: Optional[int] = 5

# -------------------------------
# API Endpoints
# -------------------------------

@app.post("/register/")
async def register(request: RegisterRequest):
    async with aiosqlite.connect(DATABASE) as db:
        # Check if the user already exists
        cursor = await db.execute("SELECT UserName FROM Users WHERE UserName = ?", (request.username,))
        existing_user = await cursor.fetchone()
        if existing_user:
            raise HTTPException(status_code=400, detail="Username already exists.")

        # Insert new user into the database
        await db.execute("""
            INSERT INTO Users (UserName, Password) 
            VALUES (?, ?)
        """, (request.username, request.password))
        await db.commit()

        return {"message": "User registered successfully", "success": True}
    
@app.get("/recommendations/{user_id}")
async def get_recommendations(user_id: int, genre: Optional[str] = None, limit: int = 5):
    """
    Get book recommendations based on user's borrowing history and optionally filtered by genre.
    If genre is provided, it will filter recommendations by that genre.
    Limit controls the maximum number of recommendations returned.
    """
    async with aiosqlite.connect(DATABASE) as db:
        # First check if user exists
        cursor = await db.execute("SELECT UserID FROM Users WHERE UserID = ?", (user_id,))
        user = await cursor.fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="User not found.")
        
        # Get genres the user has borrowed in the past
        cursor = await db.execute("""
            SELECT DISTINCT B.Genre
            FROM BorrowingHistory H
            JOIN Books B ON H.BookID = B.BookID
            WHERE H.UserID = ?
        """, (user_id,))
        preferred_genres = [row[0] for row in await cursor.fetchall()]
        
        # If user has no history, recommend popular books
        if not preferred_genres:
            query = """
                SELECT B.BookID, B.BookName, B.Author, B.Genre, B.Year, COUNT(*) as popularity
                FROM Books B
                JOIN BorrowingHistory H ON B.BookID = H.BookID
            """
            params = []
            
            if genre:
                query += " WHERE B.Genre = ?"
                params.append(genre)
                
            query += " GROUP BY B.BookID ORDER BY popularity DESC LIMIT ?"
            params.append(limit)
            
            cursor = await db.execute(query, params)
        else:
            # Get books in user's preferred genres that they haven't borrowed
            query = """
                SELECT B.BookID, B.BookName, B.Author, B.Genre, B.Year
                FROM Books B
                WHERE B.BookID NOT IN (
                    SELECT BookID FROM BorrowingHistory WHERE UserID = ?
                )
            """
            params = [user_id]
            
            if genre:
                query += " AND B.Genre = ?"
                params.append(genre)
            elif preferred_genres:
                placeholders = ','.join(['?' for _ in preferred_genres])
                query += f" AND B.Genre IN ({placeholders})"
                params.extend(preferred_genres)
                
            query += " LIMIT ?"
            params.append(limit)
            
            cursor = await db.execute(query, params)
            
        books = await cursor.fetchall()
        
        if not books:
            # Fallback to general recommendations if no matches
            query = "SELECT BookID, BookName, Author, Genre, Year FROM Books"
            params = []
            
            if genre:
                query += " WHERE Genre = ?"
                params.append(genre)
                
            query += " LIMIT ?"
            params.append(limit)
            
            cursor = await db.execute(query, params)
            books = await cursor.fetchall()
        
        return [{
            "book_id": row[0],
            "book_name": row[1],
            "author": row[2],
            "genre": row[3],
            "year": row[4]
        } for row in books]

# Alternative endpoint that uses POST and the Pydantic model
@app.post("/recommendations/")
async def post_recommendations(request: RecommendationRequest):
    return await get_recommendations(
        user_id=request.user_id,
        genre=request.genre,
        limit=request.limit
    )
    
@app.get("/books/")
async def get_all_books():
    async with aiosqlite.connect(DATABASE) as db:
        cursor = await db.execute("""
            SELECT BookID, BookName, Author, Genre, Year FROM Books
        """)
        books = await cursor.fetchall()

        # Return books as a list of dictionaries
        return [{
            "book_id": row[0],
            "book_name": row[1],
            "author": row[2],
            "genre": row[3],
            "year": row[4],
        } for row in books]
    
@app.get("/available/{book_id}")
async def check_availability(book_id: int):
    async with aiosqlite.connect(DATABASE) as db:
        cursor = await db.execute("SELECT BookName FROM Books WHERE BookID = ?", (book_id,))
        book = await cursor.fetchone()
        if not book:
            raise HTTPException(status_code=404, detail="Book not found.")

        cursor = await db.execute("""
            SELECT COUNT(*) FROM BorrowingHistory 
            WHERE BookID = ? AND ReturnDate IS NULL
        """, (book_id,))
        borrowed_count = (await cursor.fetchone())[0]

        return {"available": borrowed_count == 0}


@app.post("/borrow/")
async def borrow_book(request: BorrowRequest):
    async with aiosqlite.connect(DATABASE) as db:
        # Check if book exists
        cursor = await db.execute("SELECT BookName FROM Books WHERE BookID = ?", (request.book_id,))
        book = await cursor.fetchone()
        if not book:
            raise HTTPException(status_code=404, detail="Book not found.")

        # Check if already borrowed
        cursor = await db.execute("""
            SELECT * FROM BorrowingHistory 
            WHERE UserID = ? AND BookID = ? AND ReturnDate IS NULL
        """, (request.user_id, request.book_id))
        active = await cursor.fetchone()
        if active:
            raise HTTPException(status_code=400, detail="You have already borrowed this book.")

        borrow_date = datetime.now().date()
        due_date = borrow_date + timedelta(days=14)

        await db.execute("""
            INSERT INTO BorrowingHistory (UserID, BookID, BorrowDate, DueDate, ReturnDate) 
            VALUES (?, ?, ?, ?, NULL)
        """, (request.user_id, request.book_id, borrow_date, due_date))
        await db.commit()

        return {"message": "Book borrowed successfully.", "due_date": due_date}


@app.post("/return/")
async def return_book(request: ReturnRequest):
    async with aiosqlite.connect(DATABASE) as db:
        cursor = await db.execute("""
            SELECT * FROM BorrowingHistory 
            WHERE UserID = ? AND BookID = ? AND ReturnDate IS NULL
        """, (request.user_id, request.book_id))
        record = await cursor.fetchone()
        if not record:
            raise HTTPException(status_code=400, detail="No active loan found for this book.")

        return_date = datetime.now().date()

        await db.execute("""
            UPDATE BorrowingHistory 
            SET ReturnDate = ? 
            WHERE HistoryID = ?
        """, (return_date, record[0]))
        await db.commit()

        return {"message": "Book returned successfully."}


@app.post("/renew/")
async def renew_book(request: RenewRequest):
    async with aiosqlite.connect(DATABASE) as db:
        cursor = await db.execute("""
            SELECT DueDate FROM BorrowingHistory 
            WHERE UserID = ? AND BookID = ? AND ReturnDate IS NULL
        """, (request.user_id, request.book_id))
        record = await cursor.fetchone()
        if not record:
            raise HTTPException(status_code=400, detail="No active loan found for this book.")

        # Convert string to date
        due_date = datetime.strptime(record[0], "%Y-%m-%d").date()
        new_due_date = due_date + timedelta(days=7)

        await db.execute("""
            UPDATE BorrowingHistory 
            SET DueDate = ? 
            WHERE UserID = ? AND BookID = ? AND ReturnDate IS NULL
        """, (new_due_date, request.user_id, request.book_id))
        await db.commit()

        return {"message": "Book renewed successfully.", "new_due_date": new_due_date}


@app.get("/mybooks/{user_id}")
async def get_my_books(user_id: int):
    async with aiosqlite.connect(DATABASE) as db:
        cursor = await db.execute("""
            SELECT H.BookID, B.BookName, H.BorrowDate, H.DueDate 
            FROM BorrowingHistory H
            JOIN Books B ON H.BookID = B.BookID
            WHERE H.UserID = ? AND H.ReturnDate IS NULL
        """, (user_id,))
        books = await cursor.fetchall()
        return [{"book_id": row[0], "book_name": row[1], "borrow_date": row[2], "due_date": row[3]} for row in books]

#all users
@app.get("/users/")
async def get_all_users():
    async with aiosqlite.connect(DATABASE) as db:
        cursor = await db.execute("SELECT UserID, UserName, Password FROM Users")
        user = await cursor.fetchall()

        return [{
            "user_id": user[0],
            "username": user[1],
            "password": user[2]
        }]

#User Login
@app.post("/login/")
async def login(request: LoginRequest):
    async with aiosqlite.connect(DATABASE) as db:
        cursor = await db.execute("SELECT UserID, UserName, Password FROM Users WHERE UserName = ?", (request.username,))
        user = await cursor.fetchone()

        if not user:
            raise HTTPException(status_code=401, detail="Invalid username or password.")

        actualPassword = user[2]  # Password from database
        if actualPassword != request.password:
            raise HTTPException(status_code=401, detail="Invalid username or password.")

        # Check if the user is an admin
        is_admin = request.username == "admin" and request.password == "password"

        return {
            "message": "Login successful",
            "user_id": user[0],
            "isAdmin": is_admin
        }

#admin functions    
@app.post("/admin/add_book/")
async def add_book(request: AddBookRequest):
    async with aiosqlite.connect(DATABASE) as db:
        cursor = await db.execute("SELECT * FROM Books WHERE BookName = ?", (request.book_name,))
        book = await cursor.fetchone()
        if book:
            raise HTTPException(status_code=400, detail="Book already exists.")

        await db.execute("""
            INSERT INTO Books (BookName, Author, Genre, Year) 
            VALUES (?, ?, ?, ?)
        """, (request.book_name, request.author, request.genre, request.year))
        await db.commit()

# View all users
@app.get("/admin/users/")
async def get_all_users():
    async with aiosqlite.connect(DATABASE) as db:
        cursor = await db.execute("SELECT UserID, UserName FROM Users")
        users = await cursor.fetchall()
        return [{"user_id": user[0], "username": user[1]} for user in users]

# Add a new user
@app.post("/admin/add_user/")
async def add_user(request: UserRequest):
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("INSERT INTO Users (UserName, Password) VALUES (?, ?)", (request.username, request.password))
        await db.commit()
        return {"message": "User added successfully!"}

# Remove a user
@app.delete("/admin/remove_user/{user_id}")
async def remove_user(user_id: int):
    async with aiosqlite.connect(DATABASE) as db:
        cursor = await db.execute("SELECT * FROM Users WHERE UserID = ?", (user_id,))
        user = await cursor.fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="User not found.")

        await db.execute("DELETE FROM Users WHERE UserID = ?", (user_id,))
        await db.commit()
        return {"message": "User removed successfully!"}

# Route to remove a book
@app.delete("/admin/remove_book/{book_id}")
async def remove_book(book_id: int):
    async with aiosqlite.connect(DATABASE) as db:
        cursor = await db.execute("SELECT * FROM Books WHERE BookID = ?", (book_id,))
        book = await cursor.fetchone()
        if not book:
            raise HTTPException(status_code=404, detail="Book not found.")

        await db.execute("DELETE FROM Books WHERE BookID = ?", (book_id,))
        await db.commit()
        return {"message": "Book removed successfully!"}
    
#see all reviews
@app.get("/reviews/")
async def get_all_reviews():
    async with aiosqlite.connect(DATABASE) as db:
        cursor = await db.execute("""
            SELECT R.RatingID, R.UserID, U.UserName, R.BookID, R.Rating 
            FROM Ratings R
            JOIN Users U ON R.UserID = U.UserID
        """)
        reviews = await cursor.fetchall()
        
        return [{
            "rating_id": row[0],
            "user_id": row[1],
            "username": row[2],
            "book_id": row[3],
            "rating": row[4]
        } for row in reviews]

#see specific reviews
@app.get("/reviews/{book_id}")
async def get_book_reviews(book_id: int):
    async with aiosqlite.connect(DATABASE) as db:
        # First check if book exists
        cursor = await db.execute("SELECT BookID FROM Books WHERE BookID = ?", (book_id,))
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail="Book not found")
            
        cursor = await db.execute("""
            SELECT R.RatingID, R.UserID, U.UserName, R.BookID, R.Rating 
            FROM Ratings R
            JOIN Users U ON R.UserID = U.UserID
            WHERE R.BookID = ?
        """, (book_id,))
        reviews = await cursor.fetchall()
        
        return [{
            "rating_id": row[0],
            "user_id": row[1],
            "username": row[2],
            "book_id": row[3],
            "rating": row[4]
        } for row in reviews]
    
#add reviews
@app.post("/reviews/add/")
async def add_review(request: AddReviewRequest):
    # Validate rating is between 0 and 5 (or whatever your scale is)
    if not (0 <= request.rating <= 5):
        raise HTTPException(status_code=400, detail="Rating must be between 0 and 5")
    
    async with aiosqlite.connect(DATABASE) as db:
        # Check if user exists
        cursor = await db.execute("SELECT UserID FROM Users WHERE UserID = ?", (request.user_id,))
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail="User not found")
            
        # Check if book exists
        cursor = await db.execute("SELECT BookID FROM Books WHERE BookID = ?", (request.book_id,))
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail="Book not found")
            
        # Check if user already reviewed this book
        cursor = await db.execute("""
            SELECT RatingID FROM Ratings WHERE UserID = ? AND BookID = ?
        """, (request.user_id, request.book_id))
        if await cursor.fetchone():
            raise HTTPException(status_code=400, detail="You have already reviewed this book")
            
        await db.execute("""
            INSERT INTO Ratings (UserID, BookID, Rating)
            VALUES (?, ?, ?)
        """, (request.user_id, request.book_id, request.rating))
        await db.commit()
        
        return {"message": "Review added successfully"}
    
@app.delete("/reviews/{review_id}")
async def delete_review(review_id: int):
    async with aiosqlite.connect(DATABASE) as db:
        try:
            # First check if review exists
            cursor = await db.execute(
                "SELECT UserID FROM Ratings WHERE RatingID = ?",
                (review_id,)
            )
            review = await cursor.fetchone()
            
            if not review:
                raise HTTPException(status_code=404, detail="Review not found")
            
            # Delete the review
            await db.execute(
                "DELETE FROM Ratings WHERE RatingID = ?",
                (review_id,)
            )
            await db.commit()
            
            return {"message": "Review deleted successfully"}
        except Exception as e:
            await db.rollback()
            raise HTTPException(status_code=500, detail=str(e))
