from fastapi import FastAPI
from app.database import engine
from app.models import Base
from app.routes import auth  # Importiamo i percorsi API
from app import models  # Importiamo i modelli prima di avviare l'app


app = FastAPI(title="CORE API", version="1.0")

# Inclusione delle rotte
app.include_router(auth.router, prefix="/auth", tags=["Authentication"])

@app.get("/")
def read_root():
    return {"message": "Welcome to CORE API"}


@app.get("/users")
def get_users():
    return [{"id": 1, "name": "User1"}, {"id": 2, "name": "User2"}]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=True)





