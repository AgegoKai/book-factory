from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LoginForm(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1)
    concept: str = Field(min_length=1)
    inspiration_sources: str = ""
    target_pages: int = 20
    target_chapters: int = 10
    target_words: int = 5000
    tone_preferences: str = "Dłuższe, naturalne zdania, ludzki styl."
    language: str = "pl"
    custom_system_prompt: str = ""
    writing_style: str = ""
    writing_styles: list[str] = Field(default_factory=list)
    target_market: str = "en-US"
    author_bio: str = ""
    emotions_to_convey: str = ""
    knowledge_to_share: str = ""
    target_audience: str = ""
    pdf_font_family: str = "Georgia"
    pdf_trim_size: str = "6x9"
    pdf_heading_size: int = 22
    pdf_body_size: int = 11
    pdf_book_title_size: int = 30
    pdf_chapter_title_size: int = 23
    pdf_subchapter_title_size: int = 17
    pdf_title_override: str = ""
    pdf_subtitle: str = ""
    pdf_author_name: str = ""
    pdf_include_toc: bool = True
    pdf_show_page_numbers: bool = True


class ProjectResponse(BaseModel):
    id: int
    title: str
    status: str
    target_chapters: int
    target_words: int
    llm_provider_used: str

    model_config = ConfigDict(from_attributes=True)


class UserSettingsUpdate(BaseModel):
    preferred_llm_provider: str = "auto"
    lm_studio_base_url: str = ""
    lm_studio_api_key: str = ""
    lm_studio_model: str = ""
    google_api_key: str = ""
    google_model: str = ""
    openrouter_api_key: str = ""
    openrouter_model: str = ""
    copyleaks_email: str = ""
    copyleaks_api_key: str = ""
