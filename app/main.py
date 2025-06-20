from fastapi import FastAPI

app = FastAPI()


@app.get("/", status_code=200)
async def get_health_check():
    return {"status": "ok"}
