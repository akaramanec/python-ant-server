from pydantic import BaseModel
from typing import Optional

class UserCreate(BaseModel):
    first_name: str
    last_name: str
    middle_name: Optional[str] = None
    age: int
    height: int
    weight: int
    sex: str

class UserUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    middle_name: Optional[str] = None
    age: Optional[int] = None
    height: Optional[int] = None
    weight: Optional[int] = None
    sex: Optional[str] = None

class RentalCreate(BaseModel):
    customer_id: int
    device_id: int