from fastapi import FastAPI

app = FastAPI(title="StockIt API", version="0.0.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
