from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from rules import recommend_services

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://qfngb8kfc6-bot.github.io"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/recommend")
def recommend(data: RequestData):
    services = recommend_services(
        data.industry,
        data.company_size,
        data.goal
    )

    return {"recommended_services": services}
