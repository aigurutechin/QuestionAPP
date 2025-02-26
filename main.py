import google.generativeai as genai
import psycopg2
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import asyncpg
from pydantic import BaseModel

# Configure Gemini API
GENAI_API_KEY = "AIzaSyD12Yk5ynGFAII5GV5nDFE80aVeoHoQ884"
genai.configure(api_key=GENAI_API_KEY)

# PostgreSQL Connection String
DB_URL = "postgresql://neondb_owner:npg_4UvmWT6kVgHI@ep-tight-tree-a8i4fds1-pooler.eastus2.azure.neon.tech/neondb?sslmode=require"

# Initialize FastAPI
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # Local development
        "https://questions-app-self.vercel.app"  # Deployed frontend
    ],
    allow_credentials=True,
    allow_methods=["*"],  # Allow all HTTP methods
    allow_headers=["*"],  # Allow all headers
)

async def get_db_connection():
    return await asyncpg.connect(DB_URL)

# Agent 1: Fetch Questions from Gemini AI
def fetch_questions(topic):
    model = genai.GenerativeModel("gemini-1.5-pro")
    prompt = f"Generate 500 unique interview questions for a software engineer with 7 years of experience in {topic}. Only provide questions, no numbering, no topics."

    response = model.generate_content(prompt)
    questions = response.text.split("\n") if hasattr(response, "text") else []
    return [q.strip() for q in questions if q.strip()]  # Remove empty lines

# Agent 2: Check for Duplicate Questions in NeonDB
def check_duplicates(questions):
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        cur.execute("SELECT question FROM questions")
        existing_questions = set(q[0] for q in cur.fetchall())
        cur.close()
        conn.close()

        unique_questions = [q for q in questions if q not in existing_questions]
        return unique_questions
    except Exception as e:
        print(f"Error checking duplicates: {e}")
        return []

# Agent 3: Bulk Insert Unique Questions into NeonDB
def bulk_insert_questions(questions, topic):
    if not questions:
        return []

    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        values = [(q, topic) for q in questions]
        cur.executemany("INSERT INTO questions (question, topic) VALUES (%s, %s) ON CONFLICT DO NOTHING", values)
        conn.commit()
        cur.close()
        conn.close()
        return questions
    except Exception as e:
        print(f"Error in bulk insert: {e}")
        return []

# Orchestrator: Fetch, Filter, and Store Questions
def process_questions(topic):
    questions = fetch_questions(topic)
    unique_questions = check_duplicates(questions)
    inserted_questions = bulk_insert_questions(unique_questions, topic)
    return inserted_questions

@app.get("/api/topics")
async def get_topics():
    """Fetch all topics from the database."""
    conn = await get_db_connection()
    try:
        topics = await conn.fetch("SELECT DISTINCT topic FROM questions")
        return [{"name": t["topic"]} for t in topics]
    finally:
        await conn.close()

@app.get("/api/questions")
async def get_questions(topic: str):
    """Fetch questions based on the selected topic."""
    conn = await get_db_connection()
    try:
        questions = await conn.fetch("SELECT id, question FROM questions WHERE topic = $1", topic)
        return [{"id": q["id"], "text": q["question"]} for q in questions]
    finally:
        await conn.close()

# Agent 4: Check if Answer Exists
def get_stored_answer(question_id):
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        cur.execute("SELECT answer FROM answers WHERE question_id = %s", (question_id,))
        result = cur.fetchone()
        cur.close()
        conn.close()
        return result[0] if result else None
    except Exception as e:
        print(f"Error fetching answer: {e}")
        return None

# Agent 5: Generate Answer from Gemini AI
def generate_answer(question_text):
    try:
        model = genai.GenerativeModel("gemini-1.5-pro")
        prompt = f"Answer this interview question precisely: {question_text}"
        response = model.generate_content(prompt)
        return response.text.strip() if hasattr(response, "text") else "No answer generated."
    except Exception as e:
        print(f"Error generating answer: {e}")
        return "Error generating answer."

# Agent 6: Store Answer in PostgreSQL
def store_answer(question_id, answer):
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        cur.execute("INSERT INTO answers (question_id, answer) VALUES (%s, %s)", (question_id, answer))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error storing answer: {e}")

class AnswerRequest(BaseModel):
    question_id: int
    question_text: str

@app.post("/api/get-answer/")
def fetch_answer(request: AnswerRequest):
    """Fetch an answer from DB or generate a new one."""
    stored_answer = get_stored_answer(request.question_id)

    if stored_answer:
        return {"answer": stored_answer}

    # If no answer exists, generate and store it
    new_answer = generate_answer(request.question_text)
    store_answer(request.question_id, new_answer)
    return {"answer": new_answer}

# API Endpoint to trigger the agent system with a topic
@app.get("/fetch-questions/{topic}")
def fetch_and_store_questions(topic: str):
    inserted_questions = process_questions(topic)

    if inserted_questions:
        return {
            "message": f"Inserted {len(inserted_questions)} new questions.",
            "questions": inserted_questions
        }
    else:
        return {
            "message": "No new questions inserted. They might already exist in the database."
        }
