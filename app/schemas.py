from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LoginForm(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)


class ProjectCreate(BaseModel):
    title: str
    concept: str
    inspiration_sources: str = ""
    target_pages: int = 20
    target_words: int = 5000
    tone_preferences: str = "Longer, natural sentences with clean pacing."
    language: str = "pl"


class ProjectResponse(BaseModel):
    id: int
    title: str
    status: str
    target_pages: int
    target_words: int
    llm_provider_used: str

    model_config = ConfigDict(from_attributes=True)
