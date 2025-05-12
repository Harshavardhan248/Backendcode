from pydantic import BaseModel
from datetime import date, time

class ReservationCreate(BaseModel):
    table_id: int
    date: date
    time: str
    number_of_people: int