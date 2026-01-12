from fastapi import FastAPI
from pydantic import BaseModel
from rules import recommend_services

app = FastAPI()

class RequestData(BaseModel):
    company_name: str
    industry: str
    company_size: str
    goal: str

@app.post("/recommend")
def recommend(data: RequestData):
    services = recommend_services(
        data.industry,
        data.company_size,
        data.goal
    )

    return {"recommended_services": services}
