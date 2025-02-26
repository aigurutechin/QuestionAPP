import google.generativeai as genai
import psycopg2
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import asyncpg

# Configure Gemini API
GENAI_API_KEY = "AIzaSyD12Yk5ynGFAII5GV5nDFE80aVeoHoQ884"
genai.configure(api_key=GENAI_API_KEY)

# PostgreSQL Connection String
DB_URL = "postgresql://neondb_owner:npg_4UvmWT6kVgHI@ep-tight-tree-a8i4fds1-pooler.eastus2.azure.neon.tech/neondb?sslmode=require"

# Initialize FastAPI
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Update this with your frontend URL
    allow_credentials=True,
    allow_methods=["*"],  # Allow all HTTP methods
    allow_headers=["*"],  # Allow all headers
)

async def get_db_connection():
    return await asyncpg.connect(DB_URL)

# Agent 1: Fetch Questions from Gemini API
def fetch_questions(topic):
    model = genai.GenerativeModel("gemini-1.5-pro")
    prompt = f"Generate 500 unique interview questions for a software engineer with 7 years of experience in {topic}. Only provide questions, no numbering, no topics."

    response = model.generate_content(prompt)

    if hasattr(response, "text"):
        questions = response.text.split("\n")
    else:
        questions = []

    return [q.strip() for q in questions if q.strip()]  # Remove empty lines

# Agent 2: Check for Duplicate Questions in NeonDB
def check_duplicates(questions):
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        cur.execute("SELECT question FROM questions")
        existing_questions = set(q[0] for q in cur.fetchall())  # Fetch all existing questions in a set
        cur.close()
        conn.close()

        unique_questions = [q for q in questions if q not in existing_questions]  # Filter new questions
        print(f"Found {len(existing_questions)} existing questions. {len(unique_questions)} new questions to insert.")  # Debugging
        return unique_questions

    except Exception as e:
        print(f"Error checking duplicates: {e}")
        return []

# Agent 3: Bulk Insert Unique Questions into NeonDB
# Agent 3: Bulk Insert Unique Questions into NeonDB
def bulk_insert_questions(questions, topic):
    if not questions:
        print("No new questions to insert.")
        return []

    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()

        # Include topic in the insert query
        values = [(q, topic) for q in questions]
        cur.executemany("INSERT INTO questions (question, topic) VALUES (%s, %s) ON CONFLICT DO NOTHING", values)

        conn.commit()
        cur.close()
        conn.close()

        print(f"Inserted {len(questions)} questions for topic '{topic}' successfully.")
        return questions  # Return the inserted questions

    except Exception as e:
        print(f"Error in bulk insert: {e}")
        return []

# Orchestrator: Fetch, Filter, and Store Questions
def process_questions(topic):
    questions = fetch_questions(topic)
    unique_questions = check_duplicates(questions)  # Filter out duplicates
    inserted_questions = bulk_insert_questions(unique_questions, topic)  # Insert with topic
    return inserted_questions

@app.get("/api/topics")
async def get_topics():
    """Fetch all topics from the database."""
    conn = await get_db_connection()
    try:
        topics = await conn.fetch("SELECT DISTINCT topic FROM questions")  # Fetch unique topics
        return [{"name": t["topic"]} for t in topics]  # Returning only topic names
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
