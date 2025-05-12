from fastapi import FastAPI
from app.db import models
from app.db.database import Base, engine
from app.routers import users, restaurants, restaurant_manager, admin, debug  # ✅ include debug
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="BookTable API",
    description="End-to-End Restaurant Reservation Backend",
    version="1.0.0"
)

# Create database tables
models.Base.metadata.create_all(bind=engine)

# Register routers
app.include_router(users.router)
app.include_router(restaurants.router)
app.include_router(restaurant_manager.router)
app.include_router(admin.router)
app.include_router(debug.router)  # ✅ test route enabled

@app.on_event("startup")
def startup_event():
    from app.db.seed_data import seed_restaurants_tables_reviews
    seed_restaurants_tables_reviews()

# Root endpoint
@app.get("/")
def read_root():
    return {"message": "Welcome to BookTable API 🎉"}

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)