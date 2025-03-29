import aiosqlite
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timedelta

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

# -------------------------------
# API Endpoints
# -------------------------------
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
            SELECT B.BookName, H.BorrowDate, H.DueDate 
            FROM BorrowingHistory H
            JOIN Books B ON H.BookID = B.BookID
            WHERE H.UserID = ? AND H.ReturnDate IS NULL
        """, (user_id,))
        books = await cursor.fetchall()
        return [{"book_name": row[0], "borrow_date": row[1], "due_date": row[2]} for row in books]

#User Login
@app.post("/login/")
async def login(request: LoginRequest):
    async with aiosqlite.connect(DATABASE) as db:
        cursor = await db.execute("SELECT UserID, UserName, Password FROM Users WHERE UserName = ?", (request.username,))
        user = await cursor.fetchone()

        if not user:
            raise HTTPException(status_code=401, detail="Invalid username or password.")

        actualPassword = user[2] #password from db
        #compare passwords
        if actualPassword != request.password:
            raise HTTPException(status_code=401, detail="Invalid username or password.")

        return {"message": "Login successful", "user_id": user[0]}
