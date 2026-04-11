from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LoginForm(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1)
    concept: str = Field(min_length=1)
    inspiration_sources: str = ""
    target_pages: int = 20
    target_words: int = 5000
    tone_preferences: str = "Dłuższe, naturalne zdania, ludzki styl."
    language: str = "pl"
    custom_system_prompt: str = ""


class ProjectResponse(BaseModel):
    id: int
    title: str
    status: str
    target_pages: int
    target_words: int
    llm_provider_used: str

    model_config = ConfigDict(from_attributes=True)


class UserSettingsUpdate(BaseModel):
    lm_studio_base_url: str = ""
    lm_studio_api_key: str = ""
    lm_studio_model: str = ""
    google_api_key: str = ""
    google_model: str = ""
    openrouter_api_key: str = ""
    openrouter_model: str = ""
