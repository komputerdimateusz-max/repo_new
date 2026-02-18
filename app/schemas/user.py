"""Customer/company/location schemas."""

from pydantic import BaseModel, ConfigDict


class LocationCreate(BaseModel):
    name: str
    address: str
    postal_code: str | None = None


class LocationRead(LocationCreate):
    id: int

    model_config = ConfigDict(from_attributes=True)


class CompanyCreate(BaseModel):
    name: str
    location_id: int


class CompanyRead(CompanyCreate):
    id: int

    model_config = ConfigDict(from_attributes=True)


class CustomerCreate(BaseModel):
    name: str
    email: str
    company_id: int
    postal_code: str | None = None
    is_active: bool = True


class CustomerRead(CustomerCreate):
    id: int

    model_config = ConfigDict(from_attributes=True)
