from pydantic import BaseModel, Field, field_validator


class GastoCreateIn(BaseModel):
    categoria: str = Field(..., min_length=1, max_length=50)
    descripcion: str = Field(..., min_length=1, max_length=500)
    monto: int = Field(..., gt=0, strict=True)

    @field_validator("categoria", "descripcion")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Field must not be blank")
        return value
