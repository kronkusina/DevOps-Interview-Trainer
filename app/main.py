import json, os, random, sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR=Path(__file__).parent
DB_PATH=Path(os.environ.get("DB_PATH",BASE_DIR/"data"/"trainer.db"))
SEED_PATH=BASE_DIR/"questions_seed.json"
GROQ_API_KEY=os.environ.get("GROQ_API_KEY","")
GROQ_MODEL=os.environ.get("GROQ_MODEL","qwen/qwen3.6-27b")
GROQ_URL="https://api.groq.com/openai/v1/chat/completions"
app=FastAPI(title="DevOps Interview Trainer")
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_methods=["*"],allow_headers=["*"])

@contextmanager
def get_db():
    DB_PATH.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(DB_PATH); c.row_factory=sqlite3.Row
    try: yield c; c.commit()
    finally: c.close()

def init_db():
    with get_db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS questions (id INTEGER PRIMARY KEY AUTOINCREMENT,topic TEXT NOT NULL,grade TEXT NOT NULL,question TEXT NOT NULL,reference_answer TEXT NOT NULL,question_type TEXT NOT NULL DEFAULT 'theory',source TEXT NOT NULL DEFAULT 'База тренажёра')")
        c.execute("CREATE TABLE IF NOT EXISTS attempts (id INTEGER PRIMARY KEY AUTOINCREMENT,question_id INTEGER NOT NULL,answer_text TEXT NOT NULL,score INTEGER,feedback TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        columns={row["name"] for row in c.execute("PRAGMA table_info(questions)").fetchall()}
        if "question_type" not in columns: c.execute("ALTER TABLE questions ADD COLUMN question_type TEXT NOT NULL DEFAULT 'theory'")
        if "source" not in columns: c.execute("ALTER TABLE questions ADD COLUMN source TEXT NOT NULL DEFAULT 'База тренажёра'")
        seed=json.loads(SEED_PATH.read_text(encoding="utf-8"))
        # Синхронизируем seed при каждом старте: старые попытки и id сохраняются,
        # а новые/обновлённые вопросы немедленно становятся доступны.
        for item in seed:
            item.setdefault("question_type","theory"); item.setdefault("source","База тренажёра")
            existing=c.execute("SELECT id FROM questions WHERE question=?",(item["question"],)).fetchone()
            if existing:
                c.execute("UPDATE questions SET topic=:topic,grade=:grade,reference_answer=:reference_answer,question_type=:question_type,source=:source WHERE id=:id",{**item,"id":existing["id"]})
            else:
                c.execute("INSERT INTO questions(topic,grade,question,reference_answer,question_type,source) VALUES(:topic,:grade,:question,:reference_answer,:question_type,:source)",item)

@app.on_event("startup")
def startup(): init_db()

class AnswerIn(BaseModel):
    question_id:int
    answer_text:str
class FollowupIn(BaseModel):
    question_id:int
    original_answer:str
    followup_text:str
    conversation:list[dict]=[]
class GenerateQuestionIn(BaseModel):
    topic:Optional[str]=None
    grade:Optional[str]=None
    question_type:Optional[str]=None
class AnswerOut(BaseModel):
    score:int
    feedback:str
    strengths:list[str]
    gaps:list[str]
    reference_answer:str
    followup_question:str
class FollowupOut(BaseModel):
    reply:str
    next_followup:str
class SessionSummaryOut(BaseModel):
    total_attempts:int
    average_score:Optional[float]
    by_topic:list

@app.get("/api/topics")
def topics():
    with get_db() as c:
        rows=c.execute("SELECT topic,grade,COUNT(*) cnt FROM questions GROUP BY topic,grade").fetchall()
    d={}
    for r in rows:
        x=d.setdefault(r["topic"],{"topic":r["topic"],"middle":0,"senior":0}); x[r["grade"]]=r["cnt"]
    return {"topics":list(d.values())}

@app.get("/api/question")
def question(topic:Optional[str]=None,grade:Optional[str]=None,question_type:Optional[str]=None):
    q="SELECT * FROM questions WHERE 1=1"; p=[]
    if topic:
        selected=[value for value in topic.split(",") if value]
        q+=f" AND topic IN ({','.join('?' for _ in selected)})"; p.extend(selected)
    if grade: q+=" AND grade=?"; p.append(grade)
    if question_type: q+=" AND question_type=?"; p.append(question_type)
    with get_db() as c: rows=c.execute(q,p).fetchall()
    if not rows: raise HTTPException(404,"Нет вопросов под заданный фильтр")
    x=dict(random.choice(rows)); x.pop("reference_answer",None); return x

@app.get("/api/questions/count")
def question_count(topic:Optional[str]=None,grade:Optional[str]=None,question_type:Optional[str]=None):
    q="SELECT COUNT(*) AS count FROM questions WHERE 1=1"; p=[]
    if topic:
        selected=[value for value in topic.split(",") if value]
        q+=f" AND topic IN ({','.join('?' for _ in selected)})"; p.extend(selected)
    if grade: q+=" AND grade=?"; p.append(grade)
    if question_type: q+=" AND question_type=?"; p.append(question_type)
    with get_db() as c: count=c.execute(q,p).fetchone()["count"]
    return {"count":count}

def groq_json(messages):
    if not GROQ_API_KEY: raise HTTPException(500,"GROQ_API_KEY не задан. Добавь ключ в .env и перезапусти контейнер.")
    try:
        r=httpx.post(GROQ_URL,json={"model":GROQ_MODEL,"messages":messages,"temperature":0.25,"response_format":{"type":"json_object"}},headers={"Authorization":f"Bearer {GROQ_API_KEY}"},timeout=45)
        r.raise_for_status()
        return json.loads(r.json()["choices"][0]["message"]["content"])
    except httpx.HTTPStatusError as e: raise HTTPException(502,f"Groq API вернул ошибку: {e.response.text}")
    except (httpx.RequestError,KeyError,IndexError,json.JSONDecodeError) as e: raise HTTPException(502,f"Ошибка ответа Groq: {e}")

EVAL="""Ты опытный DevOps-интервьюер и ведёшь живое собеседование. Оцени ответ 1-5, но не ограничивайся баллом: объясни, что верно, что упущено и как рассуждать лучше. Эталон — ориентир, допустимы корректные альтернативы. Верни строго JSON: {"score":1,"feedback":"3-5 предложений живого технического разбора","strengths":["конкретный плюс"],"gaps":["конкретный пробел"],"followup_question":"один уточняющий вопрос интервьюера"}"""
FOLLOW="""Ты продолжаешь живое DevOps-собеседование после основного ответа. Не ставь новую оценку. Разбери последний ответ кандидата, подтверди правильное, исправь ошибки, дай практическую деталь/пример и задай следующий уточняющий вопрос. Верни строго JSON: {"reply":"3-6 предложений естественного ответа интервьюера","next_followup":"следующий вопрос или пустая строка"}"""
GENERATE="""Составь ОДИН короткий DevOps-вопрос на РУССКОМ языке для mock-интервью: максимум два коротких предложения и до 55 слов. Не используй английский, кроме названий технологий и команд. Не добавляй длинный сценарий, вводную, список команд или Markdown. Эталонный ответ — на русском, максимум два коротких предложения, до 70 слов. Верни ТОЛЬКО JSON с ключами question и reference_answer без переносов строк и code fence."""

def groq_generated_question(messages):
    if not GROQ_API_KEY: raise HTTPException(500,"GROQ_API_KEY не задан. Добавь ключ в .env и перезапусти контейнер.")
    try:
        r=httpx.post(GROQ_URL,json={"model":GROQ_MODEL,"messages":messages,"temperature":0.4},headers={"Authorization":f"Bearer {GROQ_API_KEY}"},timeout=45)
        r.raise_for_status()
        content=r.json()["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content=content.split("\n",1)[-1].rsplit("```",1)[0].strip()
        if not content.startswith("{"):
            start,end=content.find("{"),content.rfind("}")
            if start>=0 and end>start: content=content[start:end+1]
        return json.loads(content)
    except httpx.HTTPStatusError as e: raise HTTPException(502,f"Groq API вернул ошибку: {e.response.text}")
    except (httpx.RequestError,KeyError,IndexError,json.JSONDecodeError) as e: raise HTTPException(502,f"Не удалось разобрать AI-вопрос. Попробуй ещё раз: {e}")

@app.post("/api/answer",response_model=AnswerOut)
def answer(x:AnswerIn):
    with get_db() as c: row=c.execute("SELECT * FROM questions WHERE id=?",(x.question_id,)).fetchone()
    if not row: raise HTTPException(404,"Вопрос не найден")
    r=groq_json([{"role":"system","content":EVAL},{"role":"user","content":f"Вопрос: {row['question']}\nЭталон: {row['reference_answer']}\nОтвет кандидата: {x.answer_text}"}])
    score=max(1,min(5,int(r.get("score",1))))
    feedback=str(r.get("feedback","")); strengths=[str(v) for v in r.get("strengths",[])][:5]; gaps=[str(v) for v in r.get("gaps",[])][:5]
    fq=str(r.get("followup_question","Расскажи, как бы ты проверил это на реальной системе?"))
    with get_db() as c: c.execute("INSERT INTO attempts(question_id,answer_text,score,feedback) VALUES(?,?,?,?)",(x.question_id,x.answer_text,score,feedback))
    return AnswerOut(score=score,feedback=feedback,strengths=strengths,gaps=gaps,reference_answer=row["reference_answer"],followup_question=fq)

@app.post("/api/followup",response_model=FollowupOut)
def followup(x:FollowupIn):
    with get_db() as c: row=c.execute("SELECT * FROM questions WHERE id=?",(x.question_id,)).fetchone()
    if not row: raise HTTPException(404,"Вопрос не найден")
    hist="\n".join(f"{m.get('role')}: {m.get('content')}" for m in x.conversation[-8:])
    r=groq_json([{"role":"system","content":FOLLOW},{"role":"user","content":f"Основной вопрос: {row['question']}\nЭталон: {row['reference_answer']}\nПервоначальный ответ: {x.original_answer}\nИстория:\n{hist}\nПоследний ответ: {x.followup_text}"}])
    return FollowupOut(reply=str(r.get("reply","Хорошо, разберём это подробнее.")),next_followup=str(r.get("next_followup","")))

@app.post("/api/generate-question")
def generate_question(x:GenerateQuestionIn):
    with get_db() as c:
        available=[r["topic"] for r in c.execute("SELECT DISTINCT topic FROM questions").fetchall()]
    topic=x.topic if x.topic in available else random.choice(available)
    grade=x.grade if x.grade in {"middle","senior"} else random.choice(["middle","senior"])
    question_type=x.question_type if x.question_type in {"theory","practical","real_interview"} else "practical"
    r=groq_generated_question([{"role":"system","content":GENERATE},{"role":"user","content":f"Сгенерируй вопрос по теме: {topic}. Уровень: {grade}. Тип: {question_type}."}])
    question=str(r.get("question","")).strip(); reference=str(r.get("reference_answer","")).strip()
    if not question or not reference: raise HTTPException(502,"AI вернул неполный вопрос. Попробуй ещё раз.")
    with get_db() as c:
        cursor=c.execute("INSERT INTO questions(topic,grade,question,reference_answer,question_type,source) VALUES(?,?,?,?,?,?)",(topic,grade,question,reference,question_type,"Сгенерировано AI для этой тренировки"))
        row=dict(c.execute("SELECT * FROM questions WHERE id=?",(cursor.lastrowid,)).fetchone())
    row.pop("reference_answer",None)
    return row

@app.get("/api/session/summary",response_model=SessionSummaryOut)
def summary():
    with get_db() as c:
        total=c.execute("SELECT COUNT(*) c FROM attempts").fetchone()["c"]; avg=c.execute("SELECT AVG(score) a FROM attempts").fetchone()["a"]
        rows=c.execute("SELECT q.topic topic,AVG(a.score) avg_score,COUNT(*) cnt FROM attempts a JOIN questions q ON a.question_id=q.id GROUP BY q.topic ORDER BY avg_score ASC").fetchall()
    return SessionSummaryOut(total_attempts=total,average_score=round(avg,2) if avg is not None else None,by_topic=[dict(r) for r in rows])

@app.post("/api/session/reset")
def reset():
    with get_db() as c: c.execute("DELETE FROM attempts")
    return {"status":"ok"}

app.mount("/static",StaticFiles(directory=BASE_DIR/"static"),name="static")
@app.get("/")
def index(): return FileResponse(BASE_DIR/"static"/"index.html")
